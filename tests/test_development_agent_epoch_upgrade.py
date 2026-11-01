"""Isolated transaction crash/fault fixtures. No production services or accounts."""
import copy
import json
import os
from pathlib import Path
import pytest
from ops.discovery import epoch_upgrade as e

@pytest.fixture
def host(tmp_path,monkeypatch):
    config=tmp_path/'etc';config.mkdir();state=tmp_path/'state';state.mkdir()
    monkeypatch.setattr(e.r,'CONFIG',config/'config.json');monkeypatch.setattr(e.r,'STATE',state);monkeypatch.setattr(e.o,'STATE',state);monkeypatch.setattr(e.o,'protected',lambda p:None)
    # Ownership trust is a fixture boundary; real byte replacement/fsync/archives
    # and lock/nonce behavior remain active. Never monkeypatch the engine itself.
    monkeypatch.setattr(e.r,'protected',lambda *a,**k:None)
    monkeypatch.setattr(e.os,'getgid',lambda:os.getgid()) if False else None
    original_write=e.u.write
    def write(path,data,mode,uid,gid):return original_write(path,data,mode,os.getuid(),os.getgid())
    monkeypatch.setattr(e.u,'write',write)
    class Fake:
        old=e.OLD;head='b'*40
        def __init__(self):
            self.calls=[];self.active=True;self.source=self.old;self.config=self.old;self.fail=None;self.stop_fail=False;self.verify_fail=False
            self.plan=dict(old=self.old,head=self.head,receipt=e.r.encoded(dict(source_head=self.old,runs=[dict(slot='scout:2026-10-29',invocation='8608a7c10e9b4c23b96cf91bcc8fa51f')])),fires=b'["old-genuine-fire"]',failure=b'[{"code":"TIMER_TRIGGER_INVALID"},{"code":"BOOKEND_INVALID"}]',ledger_history=b'[]',candidates=b'[]',before=dict(candidate_count=5,candidates_sha256='d'*64,protected={},ledger={}),source=b'old-observer',config=b'old-config',new_source=b'new-observer',new_config=b'new-epoch-config')
            self.nonce='fresh-owner-authorization-20261030'
            self.financial=b'live protected synthetic financial fixture';self.ledger=b'append-only synthetic ledger'
        def inspect(self):self.calls.append('inspect');return copy.deepcopy(self.plan)
        def authorize(self):
            self.calls.append('authorize')
            if self.fail=='authorize':raise ValueError('unauthorized')
            return dict(nonce=self.nonce,historical_receipt_sha256=e.r.sha(self.plan['receipt']),historical_runs=len(e.r.loads(self.plan['receipt'])['runs']))
        def guard(self,p):
            self.calls.append('guard')
            if self.fail=='guard' and not self.active:raise ValueError('timer or receipt changed')
        def stop(self):
            self.calls.append('stop')
            if self.stop_fail:raise ValueError('active Scout race')
            self.active=False
        def install(self,p):
            assert not self.active;self.calls.append('install');self.source=self.head
            if self.fail=='checkout':raise RuntimeError('fault after checkout')
            self.config=self.head
            if self.fail=='install':raise RuntimeError('fault after selector commit')
        def verify(self,p,new):
            self.calls.append('verify-new' if new else 'verify-old')
            assert self.source==self.config==(self.head if new else self.old)
            if self.verify_fail or new and self.fail=='verify':raise ValueError('financial/ledger/source proof failed')
        def start(self,p,new):
            self.calls.append('start-new' if new else 'start-old');self.active=True
            if new and self.fail=='start':raise ValueError('new observer boundary unavailable')
        def restore(self,p):
            assert not self.active;self.calls.append('restore');self.source=self.config=self.old
            if self.fail=='restore':raise ValueError('restore failed')
        def recovery_guard(self,p):self.calls.append('recovery-guard')
    value=Fake()
    yield value
    for directory in state.rglob('*'):
        if directory.is_dir():directory.chmod(0o700)


def test_plan_only_is_read_only_and_does_not_consume_go(host,tmp_path):
    before=list(tmp_path.rglob('*'));result=e.transaction(host)
    assert result['status']=='PLAN_ONLY' and not result['changes_applied']
    assert host.calls==['inspect'] and list(tmp_path.rglob('*'))==before


def test_success_archives_history_and_starts_zero_new_epoch(host):
    result=e.transaction(host,apply=True)
    assert result['status']=='NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS' and result['historical_runs']==1 and result['current_epoch_runs']==0
    archive=next(p for p in (e.r.STATE/'history').iterdir() if not p.name.startswith('.'))
    assert (archive/'discovery.json').read_bytes()==host.plan['receipt']
    assert (archive/'october30-failure.json').read_bytes()==host.plan['failure']
    assert [p.name for p in (e.r.STATE/'epochs'/host.head).iterdir()]==['transition.json']
    assert e.r.loads((e.r.STATE/'epochs'/host.head/'transition.json').read_bytes())['status']=='COMMITTED'
    assert host.financial==b'live protected synthetic financial fixture' and host.ledger==b'append-only synthetic ledger'
    assert host.calls.index('stop')<host.calls.index('install')<host.calls.index('verify-new')<host.calls.index('start-new')
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)
    assert host.calls.count('install')==1


@pytest.mark.parametrize('fault',['guard','checkout','install','verify','start'])
def test_every_install_failure_restores_old_boundary_without_retry(host,fault):
    host.fail=fault;result=e.transaction(host,apply=True)
    assert result['status']=='ROLLED_BACK_NOT_READY' and host.source==host.config==host.old and host.active
    assert host.calls.count('install')<=1 and host.calls.count('restore')==1
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)


@pytest.mark.parametrize('fault',['restore','verification','stop'])
def test_unverifiable_rollback_stays_failed_closed(host,fault):
    host.fail='install'
    if fault=='restore':host.fail='restore';host.verify_fail=True
    if fault=='verification':host.verify_fail=True
    if fault=='stop':host.stop_fail=True
    result=e.transaction(host,apply=True)
    assert result['status']=='FAILED_CLOSED_REQUIRES_INTERVENTION'
    if fault!='stop':assert not host.active
    assert 'start-new' not in host.calls and 'start-old' not in host.calls


def test_authorization_failure_has_no_mutations(host):
    host.fail='authorize'
    with pytest.raises(ValueError):e.transaction(host,apply=True)
    assert host.calls==['inspect','authorize'] and not (e.r.CONFIG.parent/'epoch-transitions').exists()


def test_explicit_interrupted_rollback_never_rolls_forward(host):
    # A process crash is BaseException, so engine cannot perform in-process rollback.
    original=host.install
    def crash(p):original(p);raise SystemExit('synthetic process crash')
    host.install=crash
    with pytest.raises(SystemExit):e.transaction(host,apply=True)
    assert not host.active
    assert e.rollback(host,host.nonce)['status']=='ROLLED_BACK_NOT_READY'
    assert host.source==host.config==host.old and host.calls.count('install')==1
    with pytest.raises(ValueError):e.rollback(host,host.nonce)


@pytest.mark.parametrize('stage',['stop','checkout','selector','verified','start'])
def test_process_crash_at_each_stage_has_durable_backup_and_explicit_rollback(host,stage):
    method={'stop':'stop','checkout':'install','selector':'install','verified':'verify','start':'start'}[stage];original=getattr(host,method)
    def crash(*args):
        value=original(*args)
        if method not in {'verify','start'} or args[-1] is True:raise SystemExit('synthetic crash')
        return value
    setattr(host,method,crash)
    with pytest.raises(SystemExit):e.transaction(host,apply=True)
    setattr(host,method,original)
    assert e.rollback(host,host.nonce)['status']=='ROLLED_BACK_NOT_READY'
    assert host.source==host.config==host.old


@pytest.fixture
def approved(tmp_path,monkeypatch):
    p=tmp_path/'authorization.json';monkeypatch.setattr(e.r,'protected',lambda *a,**k:None)
    data=dict(version='scout-epoch-authorization-1',repository='labairj-ai/investment',scope=e.SCOPE,old_head=e.OLD,target_head='b'*40,reviewed_head='c'*40,merge_sha='b'*40,risk='L5',decision='APPROVE',nonce='new-deliberate-owner-nonce-123',created=e.time.time(),financial_ack=True,execution_ack=True,authentication_source='solo-owner-1',owner_object='https://github.com/labairj-ai/investment/pull/34#issuecomment-123',owner_verified=True,ci_head='b'*40,ci_status='PASS',historical_receipt_sha256='d'*64,historical_runs=1)
    return p,data


@pytest.mark.parametrize('field,value',[('scope','old-migration'),('old_head','a'*40),('target_head','c'*40),('reviewed_head','bad'),('merge_sha','c'*40),('risk','L2'),('decision','DEFER'),('nonce','short'),('created',1),('financial_ack',False),('execution_ack',False),('owner_verified',False),('authentication_source','model'),('owner_object','https://evil.invalid'),('ci_head','c'*40),('ci_status','FAIL'),('historical_receipt_sha256','bad'),('historical_runs',0)])
def test_untrusted_or_stale_authority_rejected(approved,field,value):
    p,data=approved;data[field]=value;p.write_bytes(e.r.encoded(data))
    with pytest.raises(ValueError):e.authorization(p,e.OLD,'b'*40)


def test_fresh_exact_head_protected_controller_receipt(approved):
    p,data=approved;p.write_bytes(e.r.encoded(data))
    assert e.authorization(p,e.OLD,'b'*40)==data


def test_no_scout_or_timer_control_commands_in_release_adapter():
    source=Path(e.__file__).read_text()
    assert "['/bin/systemctl','start',r.SERVICE]" in source
    assert all(token not in source for token in ('systemd-run','reset-failed','daemon-reload',"'disable'","'enable'","'restart'"))


def test_quiet_gate_requires_no_job_even_with_zero_pids(monkeypatch):
    monkeypatch.setattr(e,'no_scout_processes',lambda *a:None)
    monkeypatch.setattr(e.m,'quiescent',lambda *a:None);monkeypatch.setattr(e.m,'timer_state',lambda *a:None);monkeypatch.setattr(e.m,'next_timer',lambda *a:123)
    from types import SimpleNamespace
    for data in ([0,'/'],[77,'/org/freedesktop/systemd1/job/77']):
        h=e.Host('b'*40,invoke=lambda *a,**k:SimpleNamespace(stdout=json.dumps(dict(type='(uo)',data=data))))
        if data[0]:
            with pytest.raises(ValueError):h.quiet()
        else:assert h.quiet()==123


def test_release_adapter_never_opens_financial_sqlite_database():
    source=Path(e.__file__).read_text()
    assert 'o.snapshot(' not in source
    assert source.count('sqlite3.connect(')==1
    assert "sqlite3.connect(':memory:')" in source
    assert 'u.protected_state()' in source


def test_recovery_ci_keeps_all_eight_release_gates_and_adds_influence_audit():
    workflow=Path('.github/workflows/test.yml').read_text()
    assert 'python -I -S "$AUDIT_ROOT/ops/discovery/influence.py"' in workflow
    assert 'git clone --no-hardlinks --no-checkout' in workflow
    assert workflow.index('Exact-head Scout source influence audit')<workflow.index('Aggregate independent repository diagnostics')
    from scripts.aggregate_release_validation import GATES
    assert GATES==('todo_consistency','agent_contract','development_governance','focused_agent_tests','full_suite','release_baseline','cc_contract','summary_integrity')


@pytest.mark.parametrize('fail_selector',[False,True])
def test_real_git_and_file_commit_restore_preserve_financial_and_history(host,tmp_path,monkeypatch,fail_selector):
    import subprocess
    from types import SimpleNamespace
    root=tmp_path/'checkout';root.mkdir();(root/'safe.py').write_text('OLD=True\n')
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL).decode().strip()
    git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@invalid');git('add','safe.py');git('commit','-qm','old')
    old=git('rev-parse','HEAD');(root/'safe.py').write_text('NEW=True\n');git('commit','-qam','new');new=git('rev-parse','HEAD');git('checkout','--detach',old)
    financial=root/'holdings.csv';financial.write_bytes(b'private synthetic holdings; never checkout or restore')
    ledger=tmp_path/'ledger.sqlite3';ledger.write_bytes(b'synthetic authoritative ledger remains unchanged')
    host.old=old;host.head=new;host.plan.update(old=old,head=new,config=e.r.encoded(dict(head=old)),new_config=e.r.encoded(dict(head=new,acceptance_epoch=new)))
    data=e.r.loads(host.plan['receipt']);data['source_head']=old;host.plan['receipt']=e.r.encoded(data)
    host.source=host.config=old
    source=tmp_path/'installed-observer.py';source.write_bytes(host.plan['source']);e.r.CONFIG.write_bytes(host.plan['config'])
    monkeypatch.setattr(e.r,'ROOT',root);monkeypatch.setattr(e.r,'SOURCE',source)
    monkeypatch.setattr(e.r.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid()))
    def invoke(args,**kw):
        for key in ('user','group','extra_groups'):kw.pop(key,None)
        return subprocess.run(args,**kw)
    host.invoke=invoke
    def checkout(head):e.Host.checkout(host,head);host.source=head
    host.checkout=checkout
    def install(plan):e.Host.install(host,plan);host.config=new
    def restore(plan):e.Host.restore(host,plan);host.config=old
    host.install=install;host.restore=restore
    def verify(plan,is_new):
        expected=new if is_new else old
        assert git('rev-parse','HEAD')==expected
        assert source.read_bytes()==plan['new_source' if is_new else 'source']
        assert e.r.CONFIG.read_bytes()==plan['new_config' if is_new else 'config']
        assert financial.read_bytes()==b'private synthetic holdings; never checkout or restore'
        assert ledger.read_bytes()==b'synthetic authoritative ledger remains unchanged'
    host.verify=verify
    original=e.u.replace
    def replace(path,data,*args):
        if fail_selector and path==e.r.CONFIG and data==host.plan['new_config']:raise OSError('synthetic selector failure')
        return original(path,data,*args)
    monkeypatch.setattr(e.u,'replace',replace)
    result=e.transaction(host,apply=True)
    assert result['status']==('ROLLED_BACK_NOT_READY' if fail_selector else 'NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS')
    assert git('rev-parse','HEAD')==(old if fail_selector else new)
    archived=next(p for p in (e.r.STATE/'history').iterdir() if not p.name.startswith('.'))
    assert (archived/'discovery.json').read_bytes()==host.plan['receipt']


def test_owner_capability_cannot_apply_after_historical_acceptance_changes(host):
    approved=host.authorize()
    host.authorize=lambda:approved
    host.plan['receipt']=e.r.encoded(dict(runs=[dict(slot='scout:2026-10-29'),dict(slot='scout:2026-10-31')]))
    with pytest.raises(ValueError,match='historical state changed'):e.transaction(host,apply=True)
    assert 'stop' not in host.calls and 'install' not in host.calls


@pytest.mark.parametrize('argv',[
    [b'/usr/bin/python3',b'-I',b'-S',str(e.r.SOURCE).encode(),b'begin'],
    [b'/usr/bin/python3',b'-I',b'-S',str(e.r.SOURCE).encode(),b'scout'],
    [b'/usr/bin/python3',b'-I',b'-S',str(e.r.SOURCE).encode(),b'end'],
    [b'python',b'-m',b'dev_agent.cli',b'scout'],
    [b'python',b'-mdev_agent.cli',b'scout'],
    [b'python',b'/home/optiplex/investment/dev_agent/cli.py',b'scout']])
def test_stray_scout_process_blocks_transition_even_if_manager_pids_zero(tmp_path,argv):
    proc=tmp_path/'123';proc.mkdir();(proc/'cmdline').write_bytes(b'\0'.join(argv)+b'\0')
    with pytest.raises(ValueError,match='no Scout process'):e.no_scout_processes(tmp_path)


def test_observer_and_other_processes_are_not_scout(tmp_path):
    for number,argv in enumerate(([b'python',str(e.r.SOURCE).encode(),b'serve'],[b'python',b'serve.py']),1):
        proc=tmp_path/str(number);proc.mkdir();(proc/'cmdline').write_bytes(b'\0'.join(argv)+b'\0')
    e.no_scout_processes(tmp_path)


@pytest.mark.parametrize('field',['observer_digest','unit_digest','timer_digest','head','files','scout_manager','acceptance_epoch'])
def test_legacy_boundary_is_bound_to_git_objects_not_only_config_claims(field):
    manifest={name:chr(97+i)*64 for i,name in enumerate(e.r.IDENTITIES)}
    current=e.r.configuration(e.OLD,manifest);current['scout_manager']='system'
    e.legacy_configuration(current,manifest)
    current[field]='unexpected'
    with pytest.raises(ValueError,match='exact reviewed legacy'):e.legacy_configuration(current,manifest)

@pytest.mark.parametrize('member',['discovery.json','timer-fires.json','october30-failure.json','ledger-history.json','candidates.json','manifest.json'])
def test_archived_member_corruption_is_detected_and_never_repaired(host,member):
    meta=e.archive_history(host.plan,host.nonce)
    directory=e.o.verify_history(meta)
    assert directory.stat().st_mode&0o777==0o500
    path=directory/member;assert path.stat().st_mode&0o777==0o400
    path.chmod(0o600);path.write_bytes(b'corrupted synthetic fixture');path.chmod(0o400)
    with pytest.raises(ValueError):e.o.verify_history(meta)
    assert path.read_bytes()==b'corrupted synthetic fixture'
    assert host.calls==[]


@pytest.mark.parametrize('failure',['create','member','manifest','verify'])
def test_archive_failures_roll_back_without_installing_or_losing_history(host,monkeypatch,failure):
    write=e.u.write;verify=e.o.verify_history;receipt=host.plan['receipt']
    def injected(path,*args,**kwargs):
        if (failure=='member' and path.name=='timer-fires.json' or failure=='manifest' and path.name=='manifest.json'):
            raise OSError('archive write fault')
        return write(path,*args,**kwargs)
    monkeypatch.setattr(e.u,'write',injected)
    if failure=='create':
        directory=e.r.STATE/'history';directory.mkdir();(directory/('.staging-'+host.nonce)).mkdir()
    if failure=='verify':monkeypatch.setattr(e.o,'verify_history',lambda *a:(_ for _ in ()).throw(ValueError('hash mismatch')))
    result=e.transaction(host,apply=True)
    assert result['status']=='ROLLED_BACK_NOT_READY'
    assert host.plan['receipt']==receipt and host.source==host.old and host.active
    assert 'install' not in host.calls
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)


def test_archive_has_no_overwrite_or_unlisted_member_authority(host):
    meta=e.archive_history(host.plan,host.nonce);directory=e.o.verify_history(meta)
    with pytest.raises(ValueError):e.archive_history(host.plan,'different-nonce-no-overwrite')
    assert e.o.verify_history(meta)==directory
    directory.chmod(0o700);(directory/'unreviewed.json').write_text('{}');directory.chmod(0o500)
    with pytest.raises(ValueError):e.o.verify_history(meta)


def test_plan_reports_epoch_and_protected_preservation(host):
    result=e.transaction(host)
    assert result['production_head']==e.OLD and result['proposed_target_head']==host.head
    assert result['historical_slots']==['scout:2026-10-29'] and result['existing_candidate_count']==5
    assert result['epoch_transition']['new_accepted_runs']==0
    assert result['epoch_transition']['historical_credit_transferred'] is False
    assert result['readiness_failures']==[] and not result['changes_applied']
    assert result['archive_requirements'] and result['rollback_requirements'] and result['protected_state_fingerprints']

@pytest.fixture
def live_go(approved,monkeypatch):
    from dev_agent import github_owner
    _,a=approved
    data=dict(pr=34,head=a['reviewed_head'],decision='APPROVE',risk='L5',financial_ack=True,execution_ack=True,nonce=a['nonce'],rationale=e.SCOPE+':'+a['old_head']+':'+a['target_head'])
    origin=dict(url=a['owner_object'],created_at='2026-10-30T20:00:00Z')
    monkeypatch.setattr(github_owner,'verified_object',lambda *args:(data,dict(head=a['reviewed_head']),origin))
    monkeypatch.setattr(github_owner,'latest_object',lambda *args:123)
    class Client:
        def __init__(self):
            self.identity=dict(state='MERGED',mergeCommit=dict(oid=a['target_head']))
            self.runs=dict(total_count=1,workflow_runs=[dict(id=7,path='.github/workflows/test.yml',head_branch='main',head_sha=a['target_head'],event='push',status='completed',conclusion='success')])
            self.jobs=dict(total_count=2,jobs=[dict(name=n,conclusion='success') for n in ('native-systemd255','test')])
        def pr_identity(self,n):return self.identity
        def read(self,endpoint):return self.jobs if '/jobs?' in endpoint else self.runs
    return a,data,Client(),github_owner


def test_apply_independently_verifies_live_owner_and_merged_main_gates(live_go):
    a,_,client,_=live_go
    assert e.live_authorization(a,client)==dict(owner_object_id=123,ci_run_id=7,head=a['target_head'])


@pytest.mark.parametrize('failure',['scope','nonce','risk','ack','decision','revoked','notmerged','wrongmerge','wrongci','failedci','missingnative','failedgate','incompletejobs'])
def test_live_owner_and_ci_fail_closed(live_go,monkeypatch,failure):
    a,data,client,owner=live_go
    if failure=='scope':data['rationale']='generic deployment approval'
    if failure=='nonce':data['nonce']='old-consumed-authorization'
    if failure=='risk':data['risk']='L4'
    if failure=='ack':data['execution_ack']=False
    if failure=='decision':data['decision']='DEFER'
    if failure=='revoked':monkeypatch.setattr(owner,'latest_object',lambda *a:124)
    if failure=='notmerged':client.identity['state']='OPEN'
    if failure=='wrongmerge':client.identity['mergeCommit']['oid']='c'*40
    if failure=='wrongci':client.runs['workflow_runs'][0]['head_sha']='c'*40
    if failure=='failedci':client.runs['workflow_runs'][0]['conclusion']='failure'
    if failure=='missingnative':client.jobs['jobs'][0]['name']='other'
    if failure=='failedgate':client.jobs['jobs'][1]['conclusion']='failure'
    if failure=='incompletejobs':client.jobs['total_count']=3
    with pytest.raises(ValueError):e.live_authorization(a,client)


def test_plan_failure_reports_readiness_and_never_authorizes(host):
    host.inspect=lambda:(_ for _ in ()).throw(ValueError('source identity mismatch'))
    result=e.transaction(host)
    assert result['status']=='PLAN_ONLY_BLOCKED' and result['changes_applied'] is False
    assert result['readiness_failures']==['source identity mismatch'] and host.calls==[]
    with pytest.raises(ValueError):e.transaction(host,apply=True)


def test_authorization_issuer_requires_live_scoped_owner_and_never_overwrites(host,live_go,monkeypatch):
    a,data,client,owner=live_go
    host.head=a['target_head'];host.plan['head']=host.head
    monkeypatch.setattr(e,'AUTH',e.r.CONFIG.parent/'authorization.json')
    result=e.issue_authorization(host,123,client)
    assert result['status']=='AUTHORIZATION_RECORDED' and not result['changes_applied']
    assert e.authorization(e.AUTH,host.old,host.head)['nonce']==data['nonce']
    with pytest.raises(FileExistsError):e.issue_authorization(host,123,client)
    assert 'install' not in host.calls and 'stop' not in host.calls

@pytest.fixture
def public_evidence(approved,monkeypatch):
    """Real owner/parser/policy/CI stack; only HTTPS responses are disposable."""
    import io
    from email.message import Message
    from datetime import datetime, timezone
    _,a=approved
    a['owner_object']='https://github.com/labairj-ai/investment/pull/36#issuecomment-123'
    bindings=dict(repository='labairj-ai/investment',owner_login='labairj-ai',owner_id=260142791,
                  operators={},allowed_github_apps=[dict(id=1144995,slug='chatgpt-codex-connector')])
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(bindings))
    # Ambient CLI/token/proxy settings must never be consulted by this transport.
    monkeypatch.setenv('DEV_AGENT_GITHUB_READ_TOKEN_FILE','/must/not/be/read')
    monkeypatch.setenv('GH_TOKEN','disposable-unusable-ambient-value')
    monkeypatch.setenv('HTTPS_PROXY','http://invalid.invalid:1')
    repo=dict(full_name=a['repository'],name='investment',owner=dict(type='User',id=260142791,login='labairj-ai'))
    pr=dict(number=36,html_url='https://github.com/'+a['repository']+'/pull/36',state='closed',merged=True,draft=False,
            merge_commit_sha=a['target_head'],head=dict(sha=a['reviewed_head'],ref='correction',repo=repo),base=dict(ref='main',repo=repo))
    payload=dict(repository=a['repository'],pr=36,head=a['reviewed_head'],risk='L5',decision='APPROVE',nonce=a['nonce'],
                 rationale=e.SCOPE+':'+a['old_head']+':'+a['target_head'],financial_ack=True,execution_ack=True)
    now=datetime.now(timezone.utc).isoformat()
    comment=dict(id=123,user=repo['owner'].copy(),performed_via_github_app=bindings['allowed_github_apps'][0].copy(),
                 html_url=a['owner_object'],issue_url='https://api.github.com/repos/'+a['repository']+'/issues/36',
                 created_at=now,updated_at=now)
    runs=dict(total_count=1,workflow_runs=[dict(id=7,path='.github/workflows/test.yml',head_branch='main',head_sha=a['target_head'],event='push',status='completed',conclusion='success')])
    jobs=dict(total_count=2,jobs=[dict(name=n,conclusion='success') for n in ('native-systemd255','test')])
    state=dict(a=a,repo=repo,pr=pr,payload=payload,comment=comment,runs=runs,jobs=jobs,calls=[],headers=[],superseded=False,error=None)
    class Response(io.BytesIO):
        status=200
        headers=Message()
        headers['Content-Type']='application/json; charset=utf-8'
        def geturl(self):return self.url
    def open_request(request,timeout):
        assert timeout==30 and request.method=='GET'
        state['headers'].append(dict(request.header_items()))
        assert not request.has_header('Authorization')
        if state['error']:raise state['error']
        endpoint=request.full_url.removeprefix('https://api.github.com/')
        state['calls'].append(endpoint)
        prefix='repos/'+a['repository']
        comment['body']='OWNER-REVIEW solo-owner-2\n'+json.dumps(payload)
        if endpoint==prefix:value=repo
        elif endpoint==prefix+'/pulls/36':value=pr
        elif '/files?' in endpoint:value=[dict(filename='ops/discovery/epoch_upgrade.py',patch='public GET transport')]
        elif endpoint==prefix+'/issues/comments/123':value=comment
        elif '/comments?' in endpoint:
            value=[comment]
            if state['superseded']:value.append(dict(comment,id=124))
        elif '/actions/runs?' in endpoint:value=runs
        elif '/jobs?' in endpoint:value=jobs
        else:raise AssertionError(endpoint)
        response=Response(json.dumps(value).encode());response.url=request.full_url
        return response
    def build(*handlers):
        from types import SimpleNamespace
        assert any(isinstance(h,e.urllib.request.ProxyHandler) and h.proxies=={} for h in handlers)
        state['handlers']=handlers
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(e.urllib.request,'build_opener',build)
    return state


def test_anonymous_transport_preserves_real_owner_app_scope_and_ci_verification(public_evidence):
    s=public_evidence
    assert e.live_authorization(s['a'])==dict(owner_object_id=123,ci_run_id=7,head=s['a']['target_head'])
    assert s['calls'] and all('Authorization' not in h for h in s['headers'])


@pytest.mark.parametrize('failure',['owner','app','appslug','pr','head','merge','scope','nonce','edited','superseded','missing','api','rate_limit','ci','native','merge_only'])
def test_public_evidence_security_rejections(public_evidence,failure):
    import urllib.error
    s=public_evidence
    if failure=='owner':s['comment']['user']['id']=1234
    if failure=='app':s['comment']['performed_via_github_app']['id']=1
    if failure=='appslug':s['comment']['performed_via_github_app']['slug']='wrong'
    if failure=='pr':s['payload']['pr']=35
    if failure=='head':s['payload']['head']='d'*40
    if failure=='merge':s['pr']['merge_commit_sha']='d'*40
    if failure=='scope':s['payload']['rationale']='MERGE_ONLY'
    if failure=='nonce':s['payload']['nonce']='a-different-owner-nonce'
    if failure=='edited':s['comment']['updated_at']='2026-01-01T00:00:00Z'
    if failure=='superseded':s['superseded']=True
    if failure=='missing':s['error']=urllib.error.HTTPError('https://api.github.com',404,'missing',{},None)
    if failure=='api':s['error']=urllib.error.URLError('unavailable')
    if failure=='rate_limit':s['error']=urllib.error.HTTPError('https://api.github.com',403,'rate limited',{},None)
    if failure=='ci':s['runs']['workflow_runs'][0]['conclusion']='failure'
    if failure=='native':s['jobs']['jobs'][0]['conclusion']='failure'
    if failure=='merge_only':s['payload']['action']='MERGE_ONLY'
    with pytest.raises((ValueError,urllib.error.URLError)):e.live_authorization(s['a'])


@pytest.mark.parametrize('endpoint',[
    'https://evil.invalid/repos/labairj-ai/investment','//evil.invalid/path',
    'repos/other/project','repos/labairj-ai/investment/deployments',
    'repos/labairj-ai/investment/actions/workflows/1/dispatches',
    'repos/labairj-ai/investment/../other','repos/labairj-ai/investment#fragment',
    'repos/labairj-ai/investment?x=1','repos/labairj-ai/investment/pulls/34?token=x',
    'repos/labairj-ai/investment/actions/runs?head_sha=x&event=push&per_page=10',
    'repos/labairj-ai/investment/actions/runs/7/jobs?per_page=100&per_page=100'])
def test_public_transport_rejects_noncontract_endpoints(public_evidence,endpoint):
    with pytest.raises(ValueError):e.PublicGitHub('labairj-ai/investment').read(endpoint)
    assert public_evidence['calls']==[]


def test_public_transport_rejects_redirects_and_never_uses_shared_cli(public_evidence,monkeypatch):
    from dev_agent.github import GitHub
    monkeypatch.setattr(GitHub,'read',lambda *a,**kw:pytest.fail('shared credential/CLI fallback'))
    e.live_authorization(public_evidence['a'])
    handler=next(h for h in public_evidence['handlers'] if isinstance(h,e.urllib.request.HTTPRedirectHandler))
    with pytest.raises(ValueError):handler.redirect_request(None,None,302,'redirect',{},'https://api.github.com/elsewhere')


@pytest.mark.parametrize('raw',[b'not json',b'{"id":1,"id":2}',b'null',b'NaN',b'"scalar"',b'['+b' '*20_000_001+b']'])
def test_public_transport_rejects_malformed_or_oversized_responses(monkeypatch,raw):
    import io
    from email.message import Message
    from types import SimpleNamespace
    class Response(io.BytesIO):
        status=200;headers=Message();headers['Content-Type']='application/json'
        def geturl(self):return 'https://api.github.com/repos/labairj-ai/investment'
    monkeypatch.setattr(e.urllib.request,'build_opener',lambda *h:SimpleNamespace(open=lambda *a,**kw:Response(raw)))
    with pytest.raises((ValueError,UnicodeError)):e.PublicGitHub('labairj-ai/investment').read('repos/labairj-ai/investment')


def test_issuer_uses_public_evidence_without_dedicated_credentials(host,public_evidence,monkeypatch):
    s=public_evidence;host.head=s['a']['target_head'];host.plan['head']=host.head
    monkeypatch.setattr(e,'AUTH',e.r.CONFIG.parent/'authorization.json')
    result=e.issue_authorization(host,123)
    assert result['status']=='AUTHORIZATION_RECORDED' and result['changes_applied'] is False
    assert e.authorization(e.AUTH,host.old,host.head)['reviewed_head']==s['a']['reviewed_head']
    assert 'install' not in host.calls and 'stop' not in host.calls


@pytest.mark.parametrize('status,content_type,url',[(403,'application/json','https://api.github.com/repos/labairj-ai/investment'),(200,'text/html','https://api.github.com/repos/labairj-ai/investment'),(200,'application/json','https://evil.invalid/')])
def test_public_transport_rejects_unsuccessful_or_noncanonical_response(monkeypatch,status,content_type,url):
    import io
    from email.message import Message
    from types import SimpleNamespace
    class Response(io.BytesIO):
        def geturl(self):return url
    response=Response(b'{}');response.status=status;response.headers=Message();response.headers['Content-Type']=content_type
    monkeypatch.setattr(e.urllib.request,'build_opener',lambda *h:SimpleNamespace(open=lambda *a,**kw:response))
    with pytest.raises(ValueError):e.PublicGitHub('labairj-ai/investment').read('repos/labairj-ai/investment')

# Preserve the real implementation before the older synthetic host fixture swaps
# it. Only the fixture owner's UID changes; mode/type/ancestry checks stay real.
from ops.discovery.pin_refresh import protected as REAL_PROTECTED

@pytest.fixture
def real_protection_host(host,monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='scout-protection-fixture-',dir=Path.home()) as directory:
        root=Path(directory).resolve();root.chmod(0o700)
        config=root/'etc';config.mkdir(mode=0o700);state=root/'state';state.mkdir(mode=0o700)
        monkeypatch.setattr(e.r,'CONFIG',config/'config.json');monkeypatch.setattr(e.r,'STATE',state);monkeypatch.setattr(e.o,'STATE',state)
        monkeypatch.setattr(e.r,'ROOT_UID',os.getuid())
        monkeypatch.setattr(e.r,'protected',REAL_PROTECTED)
        try:yield host,root
        finally:
            for p in root.rglob('*'):
                if p.is_dir() and not p.is_symlink():p.chmod(0o700)


def test_real_protection_accepts_protected_directory_and_rejects_file_default(real_protection_host):
    _,root=real_protection_host
    assert REAL_PROTECTED(root,directory=True).st_uid==os.getuid()
    with pytest.raises(ValueError,match='protected'):REAL_PROTECTED(root)


@pytest.mark.parametrize('mode',[0o770,0o777,0o702])
def test_real_protection_rejects_writable_directories(real_protection_host,mode):
    _,root=real_protection_host;p=root/'writable';p.mkdir(mode=mode);p.chmod(mode)
    with pytest.raises(ValueError,match='protected'):REAL_PROTECTED(p,directory=True)


def test_real_protection_rejects_directory_symlinks_and_writable_ancestry(real_protection_host):
    _,root=real_protection_host;target=root/'target';target.mkdir(mode=0o700);link=root/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError,match='protected'):REAL_PROTECTED(link,directory=True)
    parent=root/'unsafe';parent.mkdir(mode=0o700);child=parent/'safe';child.mkdir(mode=0o700);parent.chmod(0o777)
    with pytest.raises(ValueError,match='ancestry'):REAL_PROTECTED(child,directory=True)


def test_apply_initialization_uses_real_directory_protection_and_preserves_nonce(real_protection_host):
    host,_=real_protection_host
    result=e.transaction(host,apply=True)
    assert result['status']=='NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'
    base=e.r.CONFIG.parent/'epoch-transitions'
    REAL_PROTECTED(base,directory=True);REAL_PROTECTED(base/'lock')
    REAL_PROTECTED(base/host.nonce,directory=True)
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)
    assert host.calls.count('install')==1


def test_apply_real_protection_rejects_bad_parent_before_attempt_or_stop(real_protection_host):
    host,_=real_protection_host;e.r.CONFIG.parent.chmod(0o777)
    with pytest.raises(ValueError,match='protected'):e.transaction(host,apply=True)
    assert not (e.r.CONFIG.parent/'epoch-transitions').exists()
    assert 'stop' not in host.calls and 'install' not in host.calls


def test_rollback_real_directory_and_file_protection_is_not_mocked(real_protection_host):
    host,_=real_protection_host;host.fail='install'
    result=e.transaction(host,apply=True)
    assert result['status']=='ROLLED_BACK_NOT_READY'
    assert host.source==host.config==host.old and host.active
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)

@pytest.fixture
def unused_receipt(real_protection_host,approved,monkeypatch):
    host,root=real_protection_host;_,original=approved;a=copy.deepcopy(original)
    monkeypatch.setattr(e.r,'protected',REAL_PROTECTED)
    monkeypatch.setattr(e,'AUTH',e.r.CONFIG.parent/'scout-epoch-authorization.json')
    a.update(target_head='c'*40,merge_sha='c'*40,ci_head='c'*40,nonce='previous-unused-receipt-nonce-123',historical_receipt_sha256=e.r.sha(host.plan['receipt']),historical_runs=1)
    raw=e.r.encoded(a);e.AUTH.write_bytes(raw);e.AUTH.chmod(0o600)
    return host,a,raw,e.r.sha(raw)


def test_retire_unused_receipt_preserves_bytes_and_permanently_reserves_nonce(unused_receipt):
    import stat
    host,a,raw,digest=unused_receipt;before=copy.deepcopy(host.plan)
    result=e.retire_unused_authorization(host,digest);archive=Path(result['archive'])
    assert result['status']=='UNUSED_AUTHORIZATION_RETIRED' and not result['changes_applied']
    assert not e.AUTH.exists() and (archive/'retired-authorization.json').read_bytes()==raw
    assert stat.S_IMODE(archive.stat().st_mode)==0o500
    for p in archive.iterdir():
        assert stat.S_IMODE(p.stat().st_mode)==0o400;REAL_PROTECTED(p)
    metadata=e.r.loads((archive/'retirement.json').read_bytes())
    assert metadata['status']=='RETIRED_UNUSED' and metadata['receipt_sha256']==digest
    assert metadata['nonce']==a['nonce'] and metadata['grants_implementation'] is False
    assert host.plan==before and 'stop' not in host.calls and 'install' not in host.calls
    # Existing O_EXCL nonce protection rejects reuse even after retirement.
    host.nonce=a['nonce']
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)
    assert 'stop' not in host.calls


def test_retirement_allows_expired_receipt_without_reviving_authority(unused_receipt):
    host,a,_,_=unused_receipt;a['created']=1;raw=e.r.encoded(a);e.AUTH.write_bytes(raw)
    with pytest.raises(ValueError,match='fresh'):e.authorization(e.AUTH,host.old,a['target_head'])
    result=e.retire_unused_authorization(host,e.r.sha(raw))
    assert (Path(result['archive'])/'retired-authorization.json').read_bytes()==raw
    assert result['grants_implementation'] is False


@pytest.mark.parametrize('failure',['wronghash','currenttarget','history','scope','nonce','writable','symlink','consumed','previousepoch','changedpreflight','locked'])
def test_retirement_rejects_unsafe_or_used_receipts(unused_receipt,monkeypatch,failure):
    import fcntl
    host,a,raw,digest=unused_receipt;lock=None
    if failure=='wronghash':digest='0'*64
    if failure=='currenttarget':a.update(target_head=host.head,merge_sha=host.head,ci_head=host.head)
    if failure=='history':a['historical_receipt_sha256']='0'*64
    if failure=='scope':a['scope']='MERGE_ONLY'
    if failure=='nonce':a['nonce']='../bad'
    if failure in {'currenttarget','history','scope','nonce'}:
        raw=e.r.encoded(a);e.AUTH.write_bytes(raw);digest=e.r.sha(raw)
    if failure=='writable':e.AUTH.chmod(0o666)
    if failure=='symlink':
        target=e.AUTH.with_name('actual-receipt');e.AUTH.rename(target);e.AUTH.symlink_to(target)
    if failure in {'consumed','locked'}:
        base=e.r.CONFIG.parent/'epoch-transitions';base.mkdir(mode=0o700)
        if failure=='consumed':(base/a['nonce']).mkdir(mode=0o700)
        else:
            lock=(base/'lock').open('w');(base/'lock').chmod(0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if failure=='previousepoch':(e.r.STATE/'epochs'/a['target_head']).mkdir(mode=0o700,parents=True)
    if failure=='changedpreflight':
        original=host.inspect;calls=[]
        def changed():
            p=original();calls.append(1)
            if len(calls)>1:p['before']['protected']['synthetic']='changed'
            return p
        host.inspect=changed
    try:
        with pytest.raises((ValueError,OSError)):e.retire_unused_authorization(host,digest)
        assert e.AUTH.read_bytes()==raw and 'stop' not in host.calls and 'install' not in host.calls
    finally:
        if lock:lock.close()


@pytest.mark.parametrize('failure',['mkdir','rename','sync','metadata','statechange'])
def test_retirement_faults_never_lose_old_evidence_or_grant_new_authority(unused_receipt,monkeypatch,failure):
    host,a,raw,digest=unused_receipt;archive=e.r.CONFIG.parent/'epoch-transitions'/a['nonce']
    if failure=='mkdir':
        original=Path.mkdir
        def mkdir(p,*args,**kwargs):
            if p==archive:raise OSError('archive creation failure')
            return original(p,*args,**kwargs)
        monkeypatch.setattr(Path,'mkdir',mkdir)
    if failure=='rename':monkeypatch.setattr(e.os,'rename',lambda *args:(_ for _ in ()).throw(OSError('rename failure')))
    if failure=='sync':
        original=e.u.sync
        def sync(p):
            if (archive/'retired-authorization.json').exists():raise OSError('fsync interrupted after rename')
            return original(p)
        monkeypatch.setattr(e.u,'sync',sync)
    if failure=='metadata':monkeypatch.setattr(e.u,'write',lambda *args:(_ for _ in ()).throw(OSError('retirement audit write failed')))
    if failure=='statechange':
        original=host.inspect
        def inspect():
            p=original()
            if not e.AUTH.exists():p['before']['protected']['synthetic']='changed'
            return p
        host.inspect=inspect
    with pytest.raises((ValueError,OSError)):e.retire_unused_authorization(host,digest)
    evidence=e.AUTH if e.AUTH.exists() else archive/'retired-authorization.json'
    assert evidence.read_bytes()==raw
    assert 'stop' not in host.calls and 'install' not in host.calls
    assert not (archive/'retirement.json').exists()


def test_retired_receipt_cannot_reauthorize_but_fresh_new_source_approval_can(unused_receipt,public_evidence,monkeypatch):
    host,a,raw,digest=unused_receipt;e.retire_unused_authorization(host,digest)
    with pytest.raises(FileNotFoundError):e.authorization(e.AUTH,host.old,host.head)
    s=public_evidence;host.head=s['a']['target_head'];host.plan['head']=host.head
    result=e.issue_authorization(host,123)
    assert result['status']=='AUTHORIZATION_RECORDED' and result['nonce']==s['a']['nonce']!=a['nonce']
    assert e.authorization(e.AUTH,host.old,host.head)['target_head']==host.head
    host.authorize=lambda:e.authorization(e.AUTH,host.old,host.head)
    assert e.transaction(host,apply=True)['status']=='NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'
    with pytest.raises(FileExistsError):e.transaction(host,apply=True)
    assert (e.r.CONFIG.parent/'epoch-transitions'/a['nonce']/'retired-authorization.json').read_bytes()==raw
    with pytest.raises(ValueError):e.retire_unused_authorization(host,digest)
    assert e.authorization(e.AUTH,host.old,host.head)['nonce']==s['a']['nonce']


def test_retirement_archive_hash_mismatch_stops_without_discarding_original_bytes(unused_receipt,monkeypatch):
    host,a,raw,digest=unused_receipt;original=Path.read_bytes
    def read(p):
        if p.name=='retired-authorization.json':return b'unexpected read corruption'
        return original(p)
    monkeypatch.setattr(Path,'read_bytes',read)
    with pytest.raises(ValueError,match='archived receipt hash mismatch'):e.retire_unused_authorization(host,digest)
    archive=e.r.CONFIG.parent/'epoch-transitions'/a['nonce']
    assert original(archive/'retired-authorization.json')==raw
    assert not (archive/'retirement.json').exists() and 'stop' not in host.calls


def test_retirement_record_is_never_interpreted_as_interrupted_apply(unused_receipt):
    host,a,_,digest=unused_receipt;e.retire_unused_authorization(host,digest)
    with pytest.raises(FileNotFoundError):e.rollback(host,a['nonce'])
    assert 'stop' not in host.calls and 'restore' not in host.calls
