"""Trusted validation manifest and immediate, append-only execution receipts.

Only application-owned ContainerValidator executions enter this path. Builder output,
operator JSON and the generic ledger event API cannot create these records.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from .discovery import git
from .evidence import source_hash
from .policy import safe_relative
from .store import digest

VERSION = "development-validation-3"
GATES = ("focused_tests", "full_suite", "release_baseline", "cc_contract", "agent_contract", "todo_consistency", "development_governance")


def manifest(focused, base):
    if not focused or not isinstance(focused, list):
        raise ValueError("approved focused test paths required")
    for path in focused:
        safe_relative(path.split('::')[0])
        if not path.startswith("tests/") or not path.split('::')[0].endswith('.py'):
            raise ValueError("focused tests must be explicit repository test paths")
    return [
        ("focused_tests", ["python", "-m", "pytest", *focused, "-v", "--tb=short"]),
        ("full_suite", ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]),
        ("release_baseline", ["python", "scripts/check_release_baseline.py", "test-results.xml"]),
        ("cc_contract", ["python", "scripts/check_cc_contract.py", "--trusted-prior-file", "/authority/prior-cc-baseline.json"]),
        ("agent_contract", ["python", "scripts/check_agent_contract.py"]),
        ("todo_consistency", ["python", "scripts/check_todo_status.py"]),
        ("development_governance", ["python", "scripts/check_development_agent.py"]),
    ]


def execute(root, store, cid, validator, *, fixture=False):
    from .runner import ContainerValidator
    if type(validator) is not ContainerValidator:
        raise ValueError("trusted ContainerValidator required")
    candidate = store.get(cid)
    plan = [e['payload'] for e in candidate['events'] if e['kind'] == 'PLAN'][-1]
    ctx = plan['context']
    if git(root, 'status', '--porcelain'):
        raise ValueError("commit candidate before mandatory validation")
    binding = dict(candidate=cid, todo=ctx['todo'], base=ctx['head'], head=git(root, 'rev-parse', 'HEAD'), source_hash=source_hash(root), mode=ctx.get('mode', 'SUPERVISED'))
    from .test_oracle import files, tree_hash
    binding.update(trusted_test_tree_hash=tree_hash(files(root,binding['base'])), candidate_source_tree_hash=binding['source_hash'])
    if ctx.get('validation_hash')!=digest(plan.get('focused_tests',['tests/test_development_agent.py'])): raise ValueError('approved validation scope changed')
    if binding['head'] == binding['base']:
        raise ValueError('committed implementation required')
    focused = plan.get('focused_tests', ['tests/test_development_agent.py'])
    commands = manifest(focused, binding['base'])
    batch = str(uuid.uuid4())
    records = []
    deadline=time.monotonic()+2400
    for name, command in commands:
        start = time.time()
        if time.monotonic()>=deadline:
            result=dict(status='NOT_RUN',exit_code=None,reason='validation batch budget exhausted')
        elif source_hash(root) != binding['source_hash'] or git(root, 'rev-parse', 'HEAD') != binding['head']:
            result = dict(status='FAIL', exit_code=None, reason='source changed during validation')
        else:
            try:
                validator.timeout=min(1800,max(1,deadline-time.monotonic()))
                validator.prior_base=binding['base']
                result = validator.run(root, name, command)
            except Exception as exc:
                result = dict(status='UNAVAILABLE', exit_code=None, reason=type(exc).__name__)
        status = result.get('status', 'UNAVAILABLE')
        if status not in {'PASS', 'FAIL', 'PARTIAL', 'NOT_RUN', 'UNAVAILABLE'}: status = 'FAIL'
        if result.get('exit_code') != 0 and status == 'PASS': status = 'FAIL'
        if name in {'focused_tests', 'full_suite'}:
            inv = result.get('inventory', {})
            if inv.get('total', 0) <= 0 or inv.get('failures') or not isinstance(inv.get('skipped'), list):
                status = 'FAIL' if inv.get('failures') else 'PARTIAL'
        record = dict(binding, name=name, command=result.get('command', command), command_contract=VERSION, manifest_hash=digest(commands), sandbox_image_digest=validator.image, started_at=start, ended_at=time.time(), exit_code=result.get('exit_code'), status=status, batch=batch, fixture_only=fixture)
        for key in ('inventory', 'artifact_hash', 'reason'):
            if key in result: record[key] = result[key]
        # Write each result immediately, even if a subsequent gate crashes.
        with store.connect(True) as db:
            store._append(db, cid, 'VALIDATION', record, f'validation:{batch}:{name}')
        records.append(record)
    complete = dict(binding, batch=batch, command_contract=VERSION, manifest_hash=digest(commands), records=[digest(r) for r in records], fixture_only=fixture)
    with store.connect(True) as db:
        store._append(db, cid, 'VALIDATION_BATCH', complete, 'validation-batch:'+batch)
    # Candidate-written tests never replace an oracle test or contribute to the
    # mandatory seven-gate result. They run in a separate container/artifact namespace.
    try:
        supplemental=validator.run(root,'supplemental_tests',['python','-m','pytest','tests/','-v','--tb=short'])
    except Exception as exc:
        supplemental=dict(status='UNAVAILABLE',reason=type(exc).__name__)
    with store.connect(True) as db:
        store._append(db,cid,'SUPPLEMENTAL_VALIDATION',dict(binding,batch=batch,result=supplemental), 'supplemental:'+batch)
    return records


def reconstruct(root, store, cid):
    candidate = store.get(cid)
    plans = [e['payload'] for e in candidate['events'] if e['kind'] == 'PLAN']
    batches = [e['payload'] for e in candidate['events'] if e['kind'] == 'VALIDATION_BATCH']
    if not plans or not batches: raise ValueError('trusted validation batch missing')
    ctx = plans[-1]['context']; batch = batches[-1]
    expected = dict(candidate=cid, todo=ctx['todo'], base=ctx['head'], head=git(root, 'rev-parse', 'HEAD'), source_hash=source_hash(root), mode=ctx.get('mode', 'SUPERVISED'))
    from .test_oracle import files, tree_hash
    expected.update(trusted_test_tree_hash=tree_hash(files(root,ctx['head'])),candidate_source_tree_hash=expected['source_hash'])
    if any(batch.get(k) != v for k,v in expected.items()) or batch.get('fixture_only'):
        raise ValueError('stale, mixed or fixture validation evidence')
    commands = manifest(plans[-1].get('focused_tests', ['tests/test_development_agent.py']), ctx['head'])
    records = [e['payload'] for e in candidate['events'] if e['kind']=='VALIDATION' and e['payload'].get('batch')==batch['batch']]
    if len(records)!=len(GATES) or {r['name'] for r in records}!=set(GATES):
        raise ValueError('missing or duplicate mandatory validation')
    if batch.get('records') != [digest(r) for r in records]: raise ValueError('validation batch altered')
    supplemental=[e['payload'] for e in candidate['events'] if e['kind']=='SUPPLEMENTAL_VALIDATION' and e['payload'].get('batch')==batch['batch']]
    if len(supplemental)!=1 or any(supplemental[0].get(k)!=v for k,v in expected.items()) or supplemental[0]['result'].get('status')!='PASS' or supplemental[0]['result'].get('exit_code')!=0:
        raise ValueError('supplemental test evidence missing, failed or stale')
    for record, (name, command) in zip(records, commands):
        actual = record.get('command', [])
        if actual != command and actual != command+['--junitxml=/artifacts/results.xml']:
            raise ValueError('validation command changed')
        if record['name']!=name or record.get('command_contract')!=VERSION or record.get('manifest_hash')!=digest(commands) or any(record.get(k)!=v for k,v in expected.items()) or record.get('fixture_only'):
            raise ValueError('validation binding changed')
    return records


def validate_and_review(root,store,cid,validator,reviewer):
    """Run mandatory gates, then an independent exact-head review in trusted code."""
    from .runner import review
    records=execute(root,store,cid,validator)
    candidate=store.get(cid)
    plan=[e['payload'] for e in candidate['events'] if e['kind']=='PLAN'][-1]
    context=plan['context'];old={}
    for name in candidate['files']:
        try: old[name]=git(root,'show',context['head']+':'+name)
        except Exception: old[name]=''
    prior=[e['payload'] for e in candidate['events'] if e['kind']=='ITERATION']
    supplemental=[e['payload']['result'] for e in candidate['events'] if e['kind']=='SUPPLEMENTAL_VALIDATION'][-1]
    result=review(root,(Path(root)/plan['path']).read_text(),old,reviewer,records+[supplemental],context['risk'],prior_findings=prior[-1].get('review',{}).get('findings',[]) if prior else [])
    store.run_event(cid,str(uuid.uuid4()),'reviewer','PASS' if result['disposition']=='PASS' else 'NEEDS_HUMAN',dict(head=git(root,'rev-parse','HEAD'),source_hash=source_hash(root),mode=context.get('mode','SUPERVISED'),provider=result.get('provider'),independent_context=result.get('independent_context')))
    store.event(cid,'ITERATION',dict(iteration=len(prior)+1,source_hash=source_hash(root),review=result,mode=context.get('mode','SUPERVISED'),fixture_only=False,provider=prior[-1].get('provider',{}) if prior else {}))
    return result
