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
    monkeypatch.setattr(e.r,'CONFIG',config/'config.json');monkeypatch.setattr(e.r,'STATE',state)
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
            self.plan=dict(old=self.old,head=self.head,receipt=e.r.encoded(dict(runs=[dict(slot='scout:2026-10-29',invocation='8608a7c10e9b4c23b96cf91bcc8fa51f')])),fires=b'["old-genuine-fire"]',failure=b'[{"code":"TIMER_TRIGGER_INVALID"},{"code":"BOOKEND_INVALID"}]',source=b'old-observer',config=b'old-config',new_source=b'new-observer',new_config=b'new-epoch-config')
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
    return Fake()


def test_plan_only_is_read_only_and_does_not_consume_go(host,tmp_path):
    before=list(tmp_path.rglob('*'));result=e.transaction(host)
    assert result['status']=='PLAN_ONLY' and not result['changes_applied']
    assert host.calls==['inspect'] and list(tmp_path.rglob('*'))==before


def test_success_archives_history_and_starts_zero_new_epoch(host):
    result=e.transaction(host,apply=True)
    assert result['status']=='NEW_EPOCH_AWAITING_GENUINE_SYSTEM_TIMER_RUNS' and result['historical_runs']==1 and result['current_epoch_runs']==0
    archive=e.r.STATE/'history'/(host.old+'-'+e.r.sha(host.plan['receipt']))
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
    assert 'o.snapshot(' not in source and 'sqlite3.connect' not in source
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
    archived=e.r.STATE/'history'/(old+'-'+e.r.sha(host.plan['receipt']))
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
