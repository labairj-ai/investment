"""Versioned deterministic authority attacks; fixture success is never operational success."""
from __future__ import annotations

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

VERSION='authority-adversarial-2'
COMPONENTS={'forged_validation','stale_validation','mixed_candidate','mixed_commit','arbitrary_snapshot','forged_provenance','stale_backup','synthetic_supervision','replayed_supervision','autonomy_disabled','mode_confusion','remote_sha_mismatch','stale_remote_head','ruleset_bypass','incomplete_protection_visibility','stale_certification'}


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
        from .identity import dashboard_identity
        repo=temp/'repo';repo.mkdir()
        subprocess.run(['git','init','-b','fixture',str(repo)],check=True,capture_output=True)
        (repo/'note.md').write_text('before')
        subprocess.run(['git','-C',str(repo),'add','.'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture'],check=True,capture_output=True)
        head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        commands=manifest(['tests/test_fixture.py'],'a'*40)
        for attack in ('stale_validation','mixed_candidate','mixed_commit'):
            candidate=store.discover(dict(source='user',title='Fixture '+attack,problem=attack,evidence=['fixture'],outcome='Deny forged evidence',files=['docs/note.md'],category='TEST'))
            ctx=dict(todo='0001',head='a'*40,mode='SUPERVISED')
            store.event(candidate,'PLAN',dict(context=ctx,focused_tests=['tests/test_fixture.py']))
            binding=dict(candidate=candidate,todo='0001',base='a'*40,head=head,mode='SUPERVISED',source_hash=source_hash(repo))
            records=[dict(binding,name=name,command=cmd,batch=attack,command_contract=COMMAND_VERSION,manifest_hash=digest(commands),fixture_only=False,status='PASS',exit_code=0) for name,cmd in commands]
            if attack=='mixed_candidate':records[0]['candidate']='another-candidate'
            if attack=='mixed_commit':records[0]['head']='b'*40
            with store.connect(True) as db:
                for r in records:store._append(db,candidate,'VALIDATION',r,attack+':'+r['name'])
                store._append(db,candidate,'VALIDATION_BATCH',dict(binding,batch=attack,records=[digest(r) for r in records]),attack+':batch')
            if attack=='stale_validation':(repo/'note.md').write_text('changed')
            try: reconstruct(repo,store,candidate);results[attack]='FAIL'
            except ValueError:results[attack]='PASS'
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
        store.transition(auto,'PLANNED');store.decide(auto,'approve','fixture',context,'fixture-mode',identity=dashboard_identity())
        proof=dict(proof,harness_hash=harness_hash(root));proof['id']=digest({k:v for k,v in proof.items() if k!='id'})
        for name,mode in [('autonomy_disabled','AUTONOMOUS'),('mode_confusion','SUPERVISED')]:
            try:
                authorize_start(root,store,auto,mode,[proof],dict(status='PASS',created=time.time()),human=dashboard_identity())
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
