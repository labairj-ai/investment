"""Versioned deterministic authority attacks; fixture success is never operational success."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

import sqlite3
import tempfile
import json
import subprocess
import time
import copy
from pathlib import Path

from .github import verify_remote_pr, effective_protections
from .snapshot import check_snapshot
from .store import Store

VERSION='authority-adversarial-3'
COMPONENTS={'trusted_oracle_isolation','runner_configuration_risk','active_content_risk','git_hook_isolation','unique_dashboard_identity','stale_lifecycle_protection','forged_supplemental','forged_validation','stale_validation','mixed_candidate','mixed_commit','arbitrary_snapshot','forged_provenance','stale_backup','synthetic_supervision','replayed_supervision','autonomy_disabled','mode_confusion','remote_sha_mismatch','stale_remote_head','ruleset_bypass','incomplete_protection_visibility','stale_certification'}


def probe(root):
    results={}
    with tempfile.TemporaryDirectory(prefix='authority-canary-') as directory:
        temp=Path(directory);store=Store(temp/'development-control.sqlite3');store.migrate()
        cid=store.discover(dict(source='user',title='Fixture authority probe',problem='Check authority boundaries',evidence=['fixture'],outcome='Reject forged authority',files=['docs/note.md'],category='TEST'))
        for name,kind,payload in [('forged_validation','VALIDATION',{'full_suite':'PASS'}),('synthetic_supervision','OPERATIONAL_SUCCESS',{'actor':'RJ','status':'PASS'})]:
            try:store.event(cid,kind,payload);results[name]='FAIL'
            except ValueError:results[name]='PASS'
        snapshot=temp/'arbitrary.db'
        with sqlite3.connect(snapshot) as db:db.execute('CREATE TABLE unrelated(x)')
        results['arbitrary_snapshot']='PASS' if check_snapshot(snapshot,temp)['status']!='PASS' else 'FAIL'
        results['forged_provenance']='PASS' if check_snapshot(snapshot,temp,{'production':True,'signature':'forged'},key=b'fixture-only-key-not-operational-0000')['status']!='PASS' else 'FAIL'
        try:
            verify_remote_pr(dict(number=1,headRefName='agent/fixture',headRefOid='a'*40,baseRefName='main',headRepository={'nameWithOwner':'fixture/repo'},isDraft=False),repository='fixture/repo',branch='agent/fixture',head='b'*40)
            results['remote_sha_mismatch']='FAIL'
        except ValueError:results['remote_sha_mismatch']='PASS'
        # Exercise receipt reconstruction against real temporary Git and ledger state.
        from .validation import manifest, reconstruct, VERSION as COMMAND_VERSION
        from .evidence import source_hash
        from .store import digest
        from .snapshot import REQUIRED_TABLES, sign_backup
        from .certification import harness_hash, technical_current, TECHNICAL_COMPONENTS
        from .operations import authorize_start
        from .identity import HumanIdentity, _PROOF
        fixture_human = lambda: HumanIdentity('fixture-human', 'fixture-only', _PROOF)
        repo=temp/'repo';repo.mkdir()
        git_run(repo,'init','-b','fixture')
        (repo/'note.md').write_text('before')
        (repo/'tests').mkdir();(repo/'tests/test_fixture.py').write_text('def test_fixture(): assert True\n')
        git_run(repo,'add','.')
        git_run(repo,'commit','-m','fixture')
        base=git_output(repo,'rev-parse','HEAD').strip()
        (repo/'note.md').write_text('after');git_run(repo,'add','.');git_run(repo,'commit','-m','candidate')
        head=git_output(repo,'rev-parse','HEAD').strip()
        from .test_oracle import files,tree_hash
        oracle_hash=tree_hash(files(repo,base))
        commands=manifest(['tests/test_fixture.py'],base)
        for attack in ('stale_validation','mixed_candidate','mixed_commit'):
            candidate=store.discover(dict(source='user',title='Fixture '+attack,problem=attack,evidence=['fixture'],outcome='Deny forged evidence',files=['docs/note.md'],category='TEST'))
            ctx=dict(todo='0001',head=base,mode='SUPERVISED')
            store.event(candidate,'PLAN',dict(context=ctx,focused_tests=['tests/test_fixture.py']))
            binding=dict(candidate=candidate,todo='0001',base=base,head=head,mode='SUPERVISED',source_hash=source_hash(repo),trusted_test_tree_hash=oracle_hash,candidate_source_tree_hash=source_hash(repo))
            records=[dict(binding,name=name,command=cmd,batch=attack,command_contract=COMMAND_VERSION,manifest_hash=digest(commands),fixture_only=False,status='PASS',exit_code=0,artifact_integrity=dict(status='PASS',fixture_only=True)) for name,cmd in commands]
            with store.connect(True) as db:
                for r in records:store._append(db,candidate,'VALIDATION',r,attack+':'+r['name'])
                store._append(db,candidate,'VALIDATION_BATCH',dict(binding,batch=attack,records=[digest(r) for r in records]),attack+':batch')
                store._append(db,candidate,'SUPPLEMENTAL_VALIDATION',dict(binding,batch=attack,result=dict(status='PASS',exit_code=0)),attack+':supplemental')
            reconstruct(repo,store,candidate)
            if attack in {'mixed_candidate','mixed_commit'}:
                bad_batch=attack+'-corrupt'
                corrupt=[dict(r,batch=bad_batch) for r in records]
                corrupt[0].update(candidate='another-candidate') if attack=='mixed_candidate' else corrupt[0].update(head='b'*40)
                with store.connect(True) as db:
                    for r in corrupt:store._append(db,candidate,'VALIDATION',r,bad_batch+':'+r['name'])
                    store._append(db,candidate,'VALIDATION_BATCH',dict(binding,batch=bad_batch,records=[digest(r) for r in corrupt]),bad_batch+':batch')
                    store._append(db,candidate,'SUPPLEMENTAL_VALIDATION',dict(binding,batch=bad_batch,result=dict(status='PASS',exit_code=0)),bad_batch+':supplemental')
            if attack=='stale_validation':(repo/'note.md').write_text('changed')
            try: reconstruct(repo,store,candidate);results[attack]='FAIL'
            except ValueError:results[attack]='PASS'
            (repo/'note.md').write_text('after')
        # New boundaries exercise the production adapters on disposable state.
        from .policy import classify
        from .identity import dashboard_identity
        from types import SimpleNamespace
        from .protection import require
        before=files(repo,base)
        (repo/'tests/conftest.py').write_text('raise RuntimeError("untrusted plugin")\n')
        results['trusted_oracle_isolation']='PASS' if files(repo,base)==before else 'FAIL'
        results['runner_configuration_risk']='PASS' if int(classify(['tests/conftest.py'])['risk'][1:])>=3 else 'FAIL'
        results['active_content_risk']='PASS' if int(classify(['static/view.svg'],content={'static/view.svg':('', '<svg><script/></svg>')})['risk'][1:])>=3 else 'FAIL'
        hooks=repo/'.git/hooks';hooks.mkdir(exist_ok=True);marker=temp/'hook-executed'
        hook=hooks/'pre-commit';hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\nexit 1\n');hook.chmod(0o755)
        git_run(repo,'add','.');git_run(repo,'commit','-m','hook isolation')
        results['git_hook_isolation']='PASS' if not marker.exists() else 'FAIL'
        try:dashboard_identity(SimpleNamespace(client_address=('192.0.2.1',1),server=SimpleNamespace(server_address=('0.0.0.0',5001)),headers={}));results['unique_dashboard_identity']='FAIL'
        except ValueError:results['unique_dashboard_identity']='PASS'
        raw={'fixture_only':True,'identity':{'login':'fixture-agent','id':1},'repository':{'full_name':'fixture/repo','id':2}}
        stale=dict(status='PASS',created=time.time()-301,identity='fixture-agent',repository='fixture/repo',evidence=raw,evidence_hash=digest(raw),effective={k:True for k in ('pr','checks','review','stale','last_push','conversation','no_force','no_delete','admin')},agent_capabilities={k:False for k in ('direct_push','bypass_review','bypass_checks','force_push','delete_ref','bypass_conversations','self_approve')})
        try:require(store,cid,SimpleNamespace(repository='fixture/repo'),'start',root=root,observation=stale);results['stale_lifecycle_protection']='FAIL'
        except ValueError:results['stale_lifecycle_protection']='PASS'
        try:store.event(cid,'SUPPLEMENTAL_VALIDATION',{'status':'PASS'});results['forged_supplemental']='FAIL'
        except ValueError:results['forged_supplemental']='PASS'
        valid=temp/'closed.db'
        with sqlite3.connect(valid) as db:
            for name in REQUIRED_TABLES:db.execute('CREATE TABLE '+name+'(x)')
        key=b'fixture-only-key-not-operational-0000'
        expired=sign_backup(valid,key=key,source_sha=head,now=time.time()-86401)
        results['stale_backup']='PASS' if check_snapshot(valid,temp,expired,key=key)['status']=='FAIL' else 'FAIL'
        proof=dict(version='harness-canary-2',kind='TECHNICAL',status='PASS',harness_hash='stale-config',created=time.time(),components={k:'PASS' for k in TECHNICAL_COMPONENTS});proof['id']=digest(proof)
        results['stale_certification']='PASS' if not technical_current(root,[proof]) else 'FAIL'
        try:
            with store.connect(True) as db:
                store._append(db,cid,'OPERATIONAL_SUCCESS',{'run':'same'},'fixture-replay')
                store._append(db,cid,'OPERATIONAL_SUCCESS',{'run':'different'},'fixture-replay')
            results['replayed_supervision']='FAIL'
        except ValueError:results['replayed_supervision']='PASS'
        auto=store.discover(dict(source='user',title='Fixture autonomous denial',problem='autonomy disabled',evidence=['fixture'],outcome='Deny automatic start',files=['docs/note.md'],category='TEST'))
        context=dict(todo='0001',head=head,scope_hash=digest(['docs/note.md']),risk='L0',acceptance_hash='fixture',mode='AUTONOMOUS',validation_hash=digest(['tests/test_fixture.py']))
        store.event(auto,'PLAN',dict(context=context,focused_tests=['tests/test_fixture.py']))
        store.transition(auto,'PLANNED');store.decide(auto,'approve','fixture',context,'fixture-mode',identity=fixture_human())
        proof=dict(proof,harness_hash=harness_hash(root));proof['id']=digest({k:v for k,v in proof.items() if k!='id'})
        for name,mode in [('autonomy_disabled','AUTONOMOUS'),('mode_confusion','SUPERVISED')]:
            try:
                valid=dict(stale,status='PASS',created=time.time())
                authorize_start(root,store,auto,mode,[proof],valid,human=fixture_human())
                results[name]='FAIL'
            except ValueError:results[name]='PASS'
        try:
            verify_remote_pr(dict(number=1,headRefName='agent/fixture',headRefOid='c'*40,baseRefName='main',headRepository={'nameWithOwner':'fixture/repo'},isDraft=False),repository='fixture/repo',branch='agent/fixture',head='a'*40)
            results['stale_remote_head']='FAIL'
        except ValueError:results['stale_remote_head']='PASS'
        rules=[dict(type='pull_request',ruleset_id=1,parameters=dict(required_approving_review_count=1,dismiss_stale_reviews_on_push=True,require_last_push_approval=True,required_review_thread_resolution=True)),dict(type='required_status_checks',ruleset_id=1,parameters=dict(strict_required_status_checks_policy=True,required_status_checks=[{'context':'test'}])),dict(type='non_fast_forward',ruleset_id=1),dict(type='deletion',ruleset_id=1)]
        details=[dict(id=1,enforcement='active',bypass_actors=[{'actor_type':'User','actor_id':1}])]
        args=(None,rules,details,{'login':'fixture-agent'},{'permissions':{'push':True,'admin':False}})
        results['ruleset_bypass']='PASS' if effective_protections(*args,visibility=True)['status']=='FAIL' else 'FAIL'
        results['incomplete_protection_visibility']='PASS' if effective_protections(*args,visibility=False)['status']=='UNAVAILABLE' else 'FAIL'
    return dict(version=VERSION,components=results,status='PASS' if COMPONENTS==results.keys() and all(v=='PASS' for v in results.values()) else 'FAIL',fixture_only=True)
