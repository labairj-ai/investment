"""Immutable receipts bound to committed SHA and complete worktree contents."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .discovery import git
from .store import bounded, digest

STATUSES = {"PASS", "FAIL", "PARTIAL", "NOT_RUN", "UNAVAILABLE"}
REQUIRED = {"focused_tests", "full_suite", "release_baseline", "cc_contract", "agent_contract", "todo_consistency", "development_governance"}


def source_hash(root):
    root = Path(root).resolve()
    names = git_output(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    sha = hashlib.sha256()
    for name in sorted(set(filter(None, names))):
        path = root / name
        sha.update(name.encode() + b"\0")
        if path.is_symlink():
            sha.update(b"symlink:" + str(path.readlink()).encode())
        elif path.is_file():
            sha.update(str(path.stat().st_mode & 0o777).encode() + b"\0" + path.read_bytes())
        else:
            sha.update(b"<deleted>")
    return sha.hexdigest()


def junit(path):
    tree = ET.parse(path)
    if tree.getroot().tag not in {'testsuite','testsuites'}: raise ValueError('invalid JUnit document')
    tests = list(tree.iter("testcase"))
    failures, skipped = [], []
    for test in tests:
        identity = test.get("classname", "") + "::" + test.get("name", "")
        if test.find("failure") is not None or test.find("error") is not None:
            failures.append(identity)
        if test.find("skipped") is not None:
            skipped.append(identity)
    for suite in tree.iter('testsuite'):
        for error in list(suite.findall('error'))+list(suite.findall('failure')):
            failures.append('suite::'+suite.get('name','unknown'))
        declared=int(suite.get('failures','0'))+int(suite.get('errors','0'))
        contained=sum(1 for case in suite.iter('testcase') if case.find('failure') is not None or case.find('error') is not None)
        if declared>contained: failures.append('suite::unaccounted-failures')
    if len({c.get('classname','')+'::'+c.get('name','') for c in tests})!=len(tests):
        raise ValueError('duplicate JUnit test identity')
    return dict(total=len(tests), passed=sum(1 for case in tests if case.find('failure') is None and case.find('error') is None and case.find('skipped') is None), failures=failures, skipped=skipped)


def receipt(root, candidate, todo, base, iteration, validations, review, risk, provider, contracts, *, trusted=False):
    if not validations or any(v.get("status") not in STATUSES or not isinstance(v.get("command"), list) or "exit_code" not in v for v in validations):
        raise ValueError("exact validation records required")
    labels = {v["name"] for v in validations}
    if len(labels) != len(validations): raise ValueError("duplicate validation labels")
    inventories = all(v.get("inventory", {}).get("total", 0) > 0 and not v["inventory"].get("failures") and "skipped" in v["inventory"] for v in validations if v["name"] in {"focused_tests", "full_suite"})
    passed = trusted and REQUIRED <= labels and inventories and all(v["status"] == "PASS" and v["exit_code"] == 0 for v in validations) and review.get("disposition") == "PASS"
    data = dict(version="dev-evidence-2", trusted_validation=trusted, candidate=candidate, todo=todo, base=base, head=git(root, "rev-parse", "HEAD"), iteration=iteration,
                source_hash=source_hash(root), validations=validations, review=review, risk=risk, provider=provider, contracts=contracts,
                status="PASS" if passed else "PARTIAL")
    data["id"] = digest(data)
    return data


def verify(root, data):
    payload = {k: v for k, v in data.items() if k != "id"}
    return data.get("id") == digest(payload) and data.get("head") == git(root, "rev-parse", "HEAD") and data.get("source_hash") == source_hash(root)


def persist(directory, data):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (data["id"] + ".json")
    encoded = bounded(data) + "\n"
    try:
        with path.open("x") as stream: stream.write(encoded)
    except FileExistsError:
        if path.read_text() != encoded: raise ValueError("receipt collision/tamper")
    return path


def seal(root, store, cid):
    from .validation import reconstruct
    candidate = store.get(cid)
    plans = [e['payload'] for e in candidate['events'] if e['kind']=='PLAN']
    iterations = [e['payload'] for e in candidate['events'] if e['kind']=='ITERATION']
    if not plans or not iterations: raise ValueError('independent review missing')
    context = plans[-1]['context']; iteration = iterations[-1]
    if iteration.get('fixture_only'): raise ValueError('fixture review cannot seal operational evidence')
    if iteration['source_hash'] != source_hash(root): raise ValueError('source changed since review')
    records = reconstruct(root, store, cid)
    data = receipt(root, cid, context['todo'], context['head'], iteration['iteration'], records, iteration['review'], iteration['review']['risk'], iteration.get('provider', {}), {'validation': records[0]['command_contract']}, trusted=True)
    if data['source_hash']!=records[0]['source_hash'] or data['head']!=records[0]['head']: raise ValueError('source changed during sealing')
    data['mode'] = context.get('mode', 'SUPERVISED')
    data['batch'] = records[0]['batch']
    data['id'] = digest({k:v for k,v in data.items() if k!='id'})
    path = persist(store.path.parent/'receipts', data)
    with store.connect(True) as db:
        store._append(db, cid, 'RECEIPT', dict(path=str(path), receipt=data), 'receipt:'+data['id'])
    return data


def trusted_receipt(root, store, cid, data):
    if not verify(root, data) or not data.get('trusted_validation'): return False
    try:
        from .validation import reconstruct
        records = reconstruct(root, store, cid)
        return records == data['validations'] and any(e['kind']=='RECEIPT' and e['payload']['receipt']==data for e in store.get(cid)['events'])
    except (ValueError, KeyError, IndexError):
        return False
