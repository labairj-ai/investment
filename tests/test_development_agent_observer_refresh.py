"""Isolated pin-transition regression tests; never host acceptance evidence."""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ops.discovery import pin_refresh as r


@pytest.fixture
def host(monkeypatch):
    # Private home fixture: production checks reject writable /tmp ancestry.
    with tempfile.TemporaryDirectory(prefix='.rf-',dir=Path.home()) as d:
        h=SimpleNamespace(base=Path(d),calls=[],starts=0,stops=0,pid=100,active=True,fail=None)
        for name,rel in dict(ROOT='repo',SOURCE='opt/observer.py',CONFIG='etc/config.json',UNIT='units/observer.service',SOCKET='run/observer.sock',STATE='state',CONTROL='control',USER_UNITS='user',RUNTIME='bin/python3',PROC='proc').items():
            p=h.base/rel;setattr(h,name,p);monkeypatch.setattr(r,name,p)
            p.mkdir(parents=True) if name in {'ROOT','STATE','CONTROL','USER_UNITS','PROC'} else p.parent.mkdir(parents=True,exist_ok=True)
        monkeypatch.setattr(r,'ROOT_UID',os.getuid());monkeypatch.setattr(r.sys,'platform','linux')
        monkeypatch.setattr(r.pwd,'getpwnam',lambda _:SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid()))
        def git(*args):
            return subprocess.check_output(['git','-C',str(h.ROOT),*args],stderr=subprocess.DEVNULL).decode().strip()
        h.git=git;git('init','-q');git('config','user.email','test@invalid');git('config','user.name','fixture')
        files={n:('fixed '+n+'\n').encode() for n in r.IDENTITIES}
        for name in ('static_oracle.py','investment-static-oracle.service','live_acceptance.py','investment-static-oracle-acceptance.service'):files['ops/validator/'+name]=b'fixed validator\n'
        files['config/development_agent.json']=r.encoded(dict(autonomous_implementation=False,supervised_loop_enabled=False,supervised_publish_pr=False,auto_merge=False,autonomy_stage='SHADOW',autonomous_max_risk='L2',required_human_merge=True,emergency_stop=False))
        files['docs/help.md']=b'old docs\n'
        for name,data in files.items():
            p=h.ROOT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        git('add','.');git('commit','-qm','old');h.old=git('rev-parse','HEAD')
        h.old_config=r.configuration(h.old,r.source_manifest(h.ROOT,h.old))
        h.raw=json.dumps(h.old_config,indent=2).encode()+b'\n';h.CONFIG.write_bytes(h.raw)
        h.SOURCE.write_bytes(files[r.IDENTITIES[0]]);h.UNIT.write_bytes(files[r.IDENTITIES[1]])
        h.RUNTIME.write_bytes(b'root Python fixture');h.RUNTIME.chmod(0o755)
        (h.ROOT/'docs/help.md').write_text('new docs\n');git('add','.');git('commit','-qm','new');h.head=git('rev-parse','HEAD')
        git('remote','add','origin','https://github.com/labairj-ai/investment.git');git('update-ref','refs/remotes/origin/main',h.head)
        h.listener=None
        real_socket=socket.socket
        def process():
            p=h.PROC/str(h.pid);p.mkdir(exist_ok=True)
            (p/'cmdline').write_bytes(b'\0'.join([str(h.RUNTIME).encode(),b'-I',b'-S',str(h.SOURCE).encode(),b'serve',b'']))
            (p/'status').write_text('Uid:\t'+'\t'.join([str(os.getuid())]*4)+'\nGid:\t'+'\t'.join([str(os.getgid())]*4)+'\n')
            (p/'exe').symlink_to(h.RUNTIME)
            h.listener=real_socket(socket.AF_UNIX,socket.SOCK_STREAM);h.listener.bind(str(h.SOCKET));h.SOCKET.chmod(0o660)
        process()
        class Channel:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,n):assert n==5
            def connect(self,path):assert path==str(h.SOCKET)
            def getsockopt(self,*args):return struct.pack('3i',h.pid,os.getuid(),os.getgid())
            def sendall(self,data):assert data==b'{}\n'
            def shutdown(self,how):assert how==socket.SHUT_WR
            def recv(self,n):return b'FAILED\n'
        monkeypatch.setattr(r.socket,'SO_PEERCRED',17,raising=False)
        monkeypatch.setattr(r.socket,'socket',lambda *args:Channel())
        h.Channel=Channel
        def invoke(args,**kw):
            h.calls.append(args)
            if args[:3]==['/usr/bin/systemctl','--user','show']:
                assert args[3] in r.DISCOVERY and kw['user']==os.getuid() and kw['extra_groups']==[]
                return SimpleNamespace(returncode=1,stdout='LoadState=not-found\nActiveState=inactive\nUnitFileState=\n')
            assert args[:1]==['/bin/systemctl'] and args[2]==r.SERVICE
            if args[1] in {'start','stop'}:
                if args[1]=='stop':
                    h.stops+=1;h.active=False
                    if h.listener:h.listener.close();h.listener=None
                    h.SOCKET.unlink(missing_ok=True)
                else:
                    h.starts+=1
                    if h.fail=='restart' and h.starts==1:raise subprocess.CalledProcessError(1,args)
                    if h.fail=='rollback' :raise subprocess.CalledProcessError(1,args)
                    h.active=True;h.pid+=1;process()
                    if h.starts==1:
                        if h.fail=='socket':h.SOCKET.chmod(0o666)
                        if h.fail=='config':h.CONFIG.write_text('{}')
                        if h.fail=='digest':h.SOURCE.write_text('tampered')
                        if h.fail=='runtime':h.RUNTIME.write_bytes(b'changed runtime')
                return SimpleNamespace(returncode=0,stdout='')
            assert args[1]=='show'
            values=dict(User='root',Group='optiplex',FragmentPath=str(h.UNIT),DropInPaths='',NeedDaemonReload='no',ActiveState='active' if h.active else 'inactive',SubState='running' if h.active else 'dead',PrivateNetwork='yes',PrivateTmp='yes',PrivateDevices='yes',ProtectSystem='strict',ProtectHome='read-only',NoNewPrivileges='yes',ProtectKernelTunables='yes',ProtectKernelModules='yes',ProtectControlGroups='yes',RestrictSUIDSGID='yes',RestrictAddressFamilies='AF_UNIX',ReadWritePaths=str(h.STATE)+' '+str(h.SOCKET.parent),InaccessiblePaths='-/home/optiplex/.ssh -/home/optiplex/.aws -/home/optiplex/.config/gh -/home/optiplex/investment/.env',MainPID=str(h.pid),InvocationID=f'{h.pid:032x}',CapabilityBoundingSet='cap_dac_read_search cap_setgid cap_setuid',EnvironmentFiles='')
            return SimpleNamespace(returncode=0,stdout='\n'.join(k+'='+values[k] for k in args[3].split('=',1)[1].split(','))+'\n')
        h.invoke=invoke
        h.run=lambda **kwargs:r.refresh(h.ROOT,h.head,h.old,invoke=invoke,**kwargs)
        h.snapshot=lambda:{str(p.relative_to(h.ROOT)):p.read_bytes() for p in h.ROOT.rglob('*') if p.is_file() and '.git' not in p.parts}
        try:yield h
        finally:
            if h.listener:h.listener.close()


def test_plan_default_has_no_mutation(host):
    before=host.snapshot();config=host.CONFIG.read_bytes();names=set(host.CONFIG.parent.iterdir())
    result=host.run()
    assert result['status']=='PLAN_ONLY' and not result['changes_applied']
    assert host.snapshot()==before and host.CONFIG.read_bytes()==config and set(host.CONFIG.parent.iterdir())==names
    assert host.starts==host.stops==0 and not list(host.STATE.iterdir())


def test_success_unchanged_binary_no_discovery_or_investment_mutation(host):
    (host.ROOT/'holdings.csv').write_text('synthetic protected state')
    (host.ROOT/'out').mkdir();(host.ROOT/'out/investment.db').write_bytes(b'fixture db')
    (host.ROOT/'out/buffett.db').write_bytes(b'fixture aux db')
    before=host.snapshot();source=host.SOURCE.read_bytes();unit=host.UNIT.read_bytes()
    result=host.run(apply=True)
    assert result['status']=='PIN_REFRESHED' and result['accepted_runs_carried']==0 and result['grants_implementation'] is False
    assert json.loads(host.CONFIG.read_bytes())==r.configuration(host.head,r.source_manifest(host.ROOT,host.head))
    assert Path(result['backup']).read_bytes()==host.raw
    assert host.snapshot()==before and host.SOURCE.read_bytes()==source and host.UNIT.read_bytes()==unit
    assert not list(host.STATE.iterdir()) and not list(host.USER_UNITS.iterdir()) and not list(host.CONTROL.iterdir())
    assert host.starts==host.stops==1
    assert all(c[1] in {'show','start','stop','--user'} for c in host.calls)


@pytest.mark.parametrize('case',['old','dirty','head','origin','config','source','unit','writable','symlink','parent-writable','manifest','flags','spool','worktree','evidence','user-unit','ledger'])
def test_preflight_refuses_before_mutation(host,monkeypatch,case):
    if case=='old':host.old='0'*40
    elif case=='dirty':(host.ROOT/'docs/help.md').write_text('dirty')
    elif case=='head':host.head='1'*40
    elif case=='origin':host.git('update-ref','refs/remotes/origin/main',host.old)
    elif case=='config':host.CONFIG.write_text('{}')
    elif case=='source':host.SOURCE.write_text('tamper')
    elif case=='unit':host.UNIT.write_text('tamper')
    elif case=='writable':host.CONFIG.chmod(0o666)
    elif case=='symlink':host.CONFIG.rename(host.CONFIG.with_suffix('.real'));host.CONFIG.symlink_to(host.CONFIG.with_suffix('.real'))
    elif case=='parent-writable':host.CONFIG.parent.chmod(0o777)
    elif case=='manifest':monkeypatch.setattr(r,'manifest_matches',Mock(side_effect=ValueError('target manifest mismatch')))
    elif case=='flags':monkeypatch.setattr(r,'flags_disabled',Mock(side_effect=ValueError('enabled')))
    elif case=='spool':(host.CONTROL/'operational-signals.json').write_text('{}')
    elif case=='worktree':(host.CONTROL/'worktrees').mkdir()
    elif case=='evidence':(host.STATE/'discovery.json').write_text('{}')
    elif case=='user-unit':(host.USER_UNITS/'development-scout.timer').write_text('fixture')
    elif case=='ledger':
        import sqlite3
        with sqlite3.connect(host.CONTROL/'development-control.sqlite3') as db:
            db.execute('CREATE TABLE dev_events(kind TEXT)');db.execute("INSERT INTO dev_events VALUES ('SCHEDULE')")
    before=host.CONFIG.read_bytes()
    with pytest.raises((ValueError,subprocess.CalledProcessError)):host.run(apply=True)
    assert host.starts==host.stops==0 and host.CONFIG.read_bytes()==before
    assert not (host.CONFIG.parent/'pin-refresh.lock').exists()


@pytest.mark.parametrize('name',r.IDENTITIES)
def test_changed_executable_or_unit_requires_separate_upgrade(host,name):
    (host.ROOT/name).write_text('changed boundary')
    host.git('add','.');host.git('commit','-qm','boundary change');host.head=host.git('rev-parse','HEAD');host.git('update-ref','refs/remotes/origin/main',host.head)
    with pytest.raises(ValueError,match='separately reviewed full upgrade'):host.run(apply=True)
    assert host.CONFIG.read_bytes()==host.raw and host.starts==host.stops==0


@pytest.mark.parametrize('failure',['restart','socket','config'])
def test_failure_restores_exact_configuration_and_old_boundary(host,failure):
    host.fail=failure
    result=host.run(apply=True)
    assert result['status']=='ROLLED_BACK_NOT_READY' and result['prior_exact_configuration_restored']
    assert host.CONFIG.read_bytes()==host.raw and host.active
    assert not list(host.STATE.iterdir()) and not list(host.USER_UNITS.iterdir())


@pytest.mark.parametrize('failure',['digest','rollback','runtime'])
def test_unverifiable_rollback_stops_observer_not_ready(host,failure):
    host.fail=failure
    result=host.run(apply=True)
    assert result['status']=='FAILED_STOPPED' and not host.active
    assert host.CONFIG.read_bytes()==host.raw and result['prior_exact_configuration_restored']
    assert not result['rollback_boundary_verified']


def test_atomic_config_replacement_and_fsync(host,monkeypatch):
    events=[];replace=r.os.replace;fsync=r.os.fsync
    def record_replace(src,dst):
        assert Path(src).read_bytes()==r.encoded(r.configuration(host.head,r.source_manifest(host.ROOT,host.head)))
        assert host.CONFIG.read_bytes()==host.raw and not host.active
        events.append('replace');return replace(src,dst)
    monkeypatch.setattr(r.os,'replace',record_replace)
    monkeypatch.setattr(r.os,'fsync',lambda fd:(events.append('fsync'),fsync(fd))[1])
    assert host.run(apply=True)['status']=='PIN_REFRESHED'
    i=events.index('replace');assert i>=4 and events[i-1]=='fsync' and events[i+1]=='fsync'


def test_replace_failure_rolls_back(host,monkeypatch):
    original=r.replace_config
    def fail_once(path):
        if path.name=='config.json.refreshing':raise OSError('storage error')
        return original(path)
    monkeypatch.setattr(r,'replace_config',fail_once)
    assert host.run(apply=True)['status']=='ROLLED_BACK_NOT_READY'
    assert host.CONFIG.read_bytes()==host.raw


def test_unrestorable_config_removed_from_authoritative_path(host,monkeypatch):
    host.fail='restart';original=r.replace_config
    def failed_rollback(path):
        if path.name.startswith('pin-refresh-backup'):raise OSError('restore failed')
        return original(path)
    monkeypatch.setattr(r,'replace_config',failed_rollback)
    result=host.run(apply=True)
    assert result['status']=='FAILED_STOPPED' and not host.active and not host.CONFIG.exists()
    assert (host.CONFIG.parent/('config.failed-refresh-'+host.head+'.json')).exists()


@pytest.mark.parametrize('case',['process','runtime','peer','reply','socket-mode','loaded-unit'])
def test_real_boundary_checks_fail_closed(host,monkeypatch,case):
    if case=='process':(host.PROC/str(host.pid)/'cmdline').write_bytes(b'other\0')
    elif case=='runtime':(host.PROC/str(host.pid)/'exe').unlink();(host.PROC/str(host.pid)/'exe').symlink_to(host.SOURCE)
    elif case=='peer':monkeypatch.setattr(host.Channel,'getsockopt',lambda *a:struct.pack('3i',999,999,999))
    elif case=='reply':monkeypatch.setattr(host.Channel,'recv',lambda *a:b'PASS\n')
    elif case=='socket-mode':host.SOCKET.chmod(0o666)
    elif case=='loaded-unit':
        original=host.invoke
        host.invoke=lambda args,**kw:SimpleNamespace(returncode=0,stdout=original(args,**kw).stdout.replace('PrivateNetwork=yes','PrivateNetwork=no'))
    with pytest.raises(ValueError):r.boundary(host.old_config,host.invoke)
    assert host.starts==host.stops==0


def test_actual_manifest_rejects_mutation_and_symlink(host):
    manifest=r.source_manifest(host.ROOT,host.head)
    (host.ROOT/'docs/help.md').write_text('bad')
    with pytest.raises(ValueError,match='manifest mismatch'):r.manifest_matches(host.ROOT,manifest)
    (host.ROOT/'docs/help.md').unlink();(host.ROOT/'docs/help.md').symlink_to(host.SOURCE)
    with pytest.raises(ValueError,match='symlink'):r.manifest_matches(host.ROOT,manifest)


def test_fixed_root_linux_and_layout_required(host,monkeypatch):
    monkeypatch.setattr(r.sys,'platform','darwin')
    with pytest.raises(ValueError,match='Linux root'):host.run(apply=True)
    assert host.starts==host.stops==0

@pytest.mark.parametrize('suffix',['-wal','-journal'])
def test_pending_ledger_refused_without_sqlite_side_files(host,suffix):
    import sqlite3
    ledger=host.CONTROL/'development-control.sqlite3'
    with sqlite3.connect(ledger) as db:db.execute('CREATE TABLE dev_events(kind TEXT)')
    ledger.with_name(ledger.name+suffix).write_bytes(b'pending')
    before={p.name:p.read_bytes() for p in host.CONTROL.iterdir()}
    with pytest.raises(ValueError,match='pending ledger'):host.run(apply=True)
    assert {p.name:p.read_bytes() for p in host.CONTROL.iterdir()}==before and host.stops==0


def test_empty_existing_ledger_read_without_mutation(host):
    import sqlite3
    ledger=host.CONTROL/'development-control.sqlite3'
    with sqlite3.connect(ledger) as db:db.execute('CREATE TABLE dev_events(kind TEXT)')
    before=ledger.read_bytes()
    assert host.run()['status']=='PLAN_ONLY'
    assert ledger.read_bytes()==before and list(host.CONTROL.iterdir())==[ledger]


@pytest.mark.parametrize('path',['SOURCE','UNIT','CONFIG'])
def test_symlinked_or_writable_protected_files(host,path):
    p=getattr(host,path);p.chmod(0o662)
    with pytest.raises(ValueError,match='protected'):host.run(apply=True)
    assert host.starts==host.stops==0


def test_wrong_layout_and_nonroot_rejected(host,monkeypatch):
    with pytest.raises(ValueError,match='Linux root'):r.refresh(host.base,host.head,host.old,apply=True,invoke=host.invoke)
    monkeypatch.setattr(r.os,'geteuid',lambda:os.getuid()+1)
    with pytest.raises(ValueError,match='Linux root'):host.run(apply=True)
    assert host.starts==host.stops==0


def test_service_stop_must_be_verified(host):
    original=host.invoke
    def unconfirmed(args,**kw):
        if args[1]=='show' and args[3]=='--property=ActiveState,SubState':return SimpleNamespace(returncode=0,stdout='ActiveState=active\nSubState=running\n')
        return original(args,**kw)
    result=r.refresh(host.ROOT,host.head,host.old,apply=True,invoke=unconfirmed)
    assert result['status']=='FAILED_STOP_UNCONFIRMED' and not result['rollback_boundary_verified']
    assert host.starts==0 and host.CONFIG.read_bytes()==host.raw


def test_post_restart_manifest_change_rolls_back(host,monkeypatch):
    original=r.manifest_matches;calls=[]
    def fail_after_restart(root,manifest):
        calls.append(1)
        if host.starts:raise ValueError('target source manifest mismatch')
        return original(root,manifest)
    monkeypatch.setattr(r,'manifest_matches',fail_after_restart)
    assert host.run(apply=True)['status']=='ROLLED_BACK_NOT_READY'
    assert host.CONFIG.read_bytes()==host.raw


def test_actual_activation_flags_fail_closed(host):
    path=host.ROOT/'config/development_agent.json';cfg=json.loads(path.read_bytes());cfg['supervised_loop_enabled']=True;path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='disabled SHADOW'):r.flags_disabled(host.ROOT)
