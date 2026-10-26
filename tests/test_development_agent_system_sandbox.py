"""Adversarial SYSTEM sandbox/control tests. Synthetic only, no host acceptance."""
import json,os
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.discovery import observer as o,sandbox_certify as c
from test_development_agent_scout_failure import system

@pytest.mark.parametrize('key,value,reason',[
 ('ControlPID','999','SCOUT_CONTROL_PID_MISMATCH'),('FragmentPath','/untrusted','SCOUT_FRAGMENT_MISMATCH'),
 ('DropInPaths','/untrusted','SCOUT_DROP_IN_UNEXPECTED'),('NeedDaemonReload','yes','SCOUT_RELOAD_REQUIRED')])
def test_distinct_sanitized_control_diagnostics(system,key,value,reason):
 system.values[key]=value
 with pytest.raises(o.TrustFailure,match=reason):system.run()

def test_unit_digest_diagnostic(system,monkeypatch):
 monkeypatch.setattr(o,'file_hash',lambda p:'wrong')
 with pytest.raises(o.TrustFailure,match='SCOUT_UNIT_DIGEST_MISMATCH'):system.run()

@pytest.mark.parametrize('phase',['begin','end'])
@pytest.mark.parametrize('attack',['pid','argv','binary','finished','old_invocation','old_timestamp','missing','duplicate'])
def test_per_command_record_attacks_fail(phase,attack,monkeypatch):
 now=1000.0;mono=100.0;inv='a'*32;pid=123
 row=['/usr/bin/python3',['/usr/bin/python3','-I','-S',str(o.SOURCE),phase],False,999000000,99000000,0,0,pid,0,0]
 if attack=='pid':row[7]=999
 if attack=='argv':row[1][-1]='scout'
 if attack=='binary':row[0]='/untrusted'
 if attack=='finished':row[5]=999000001
 if attack=='old_timestamp':row[4]=1000
 data=[] if attack=='missing' else [row,row] if attack=='duplicate' else [row]
 def output(cmd,**kw):
  assert '--system' in cmd and '--user' not in cmd
  if cmd[0]=='/usr/bin/systemctl':return ('InvocationID='+('b'*32 if attack=='old_invocation' else inv)+'\nControlPID=0\nActiveState='+('activating' if phase=='begin' else 'deactivating')+'\nSubState='+('start-pre' if phase=='begin' else 'stop-post')+'\n').encode()
  return json.dumps(dict(type='t',data=99000028) if 'InactiveExitTimestampMonotonic' in cmd else dict(type='a(sasbttttuii)',data=data)).encode()
 monkeypatch.setattr(o.subprocess,'check_output',output);monkeypatch.setattr(o.time,'time',lambda:now);monkeypatch.setattr(o.time,'monotonic',lambda:mono)
 with pytest.raises(o.TrustFailure):o.command_record({},pid,inv,phase)

@pytest.mark.parametrize('phase',['begin','end'])
def test_active_per_command_pid_is_authority_when_aggregate_is_zero(phase,monkeypatch):
 inv='a'*32;row=['/usr/bin/python3',['/usr/bin/python3','-I','-S',str(o.SOURCE),phase],False,999000000,99000000,0,0,123,0,0]
 def output(cmd,**kw):
  if cmd[0]=='/usr/bin/systemctl':return ('InvocationID='+inv+'\nControlPID=0\nActiveState='+('activating' if phase=='begin' else 'deactivating')+'\nSubState='+('start-pre' if phase=='begin' else 'stop-post')+'\n').encode()
  return json.dumps(dict(type='t',data=99000028) if 'InactiveExitTimestampMonotonic' in cmd else dict(type='a(sasbttttuii)',data=[row])).encode()
 monkeypatch.setattr(o.subprocess,'check_output',output);monkeypatch.setattr(o.time,'time',lambda:1000);monkeypatch.setattr(o.time,'monotonic',lambda:100)
 o.command_record({},123,inv,phase)

@pytest.fixture
def certified(monkeypatch):
 h=SimpleNamespace(route=False,uid=123,accessible=None,interfaces=['lo'])
 monkeypatch.setattr(Path,'read_text',lambda p:'header\nroute\n' if str(p)=='/proc/net/route' and h.route else 'header\n' if str(p)=='/proc/net/route' else '')
 monkeypatch.setattr(c.os,'listdir',lambda p:h.interfaces);monkeypatch.setattr(c.os,'getuid',lambda:h.uid)
 monkeypatch.setattr(c.pwd,'getpwnam',lambda n:SimpleNamespace(pw_uid=123));monkeypatch.setattr(c.os,'statvfs',lambda p:SimpleNamespace(f_flag=os.ST_RDONLY))
 monkeypatch.setattr(c,'denied',lambda p:str(p)!=h.accessible)
 monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**kw:b'{"type":"u","data":0}')
 monkeypatch.setattr(c,'active_record',lambda:True)
 return h

def test_certification_passes_only_fixed_booleans_without_acceptance(certified,capsys):
 assert c.main()==0;value=json.loads(capsys.readouterr().out);assert all(type(v) is bool for v in value.values()) and value['test_evidence_only'] and not value['accepted_scout_run']

@pytest.mark.parametrize('attack',['route','wrong_uid','holdings','out','credential','interface','manager'])
def test_configured_private_network_is_not_runtime_proof(certified,monkeypatch,attack,capsys):
 if attack=='route':certified.route=True
 if attack=='wrong_uid':certified.uid=0
 if attack in {'holdings','out','credential'}:certified.accessible=str(c.ROOT/({'holdings':'holdings.csv','out':'out','credential':'.env'}[attack]))
 if attack=='interface':certified.interfaces=['lo','eth0']
 if attack=='manager':monkeypatch.setattr(c.subprocess,'check_output',lambda *a,**k:b'{"type":"u","data":42}')
 assert c.main()==1;assert json.loads(capsys.readouterr().out)['accepted_scout_run'] is False

def test_namespace_setup_error_is_sanitized_not_acceptance(monkeypatch,capsys):
 monkeypatch.setattr(c,'checks',lambda:(_ for _ in ()).throw(PermissionError('/secret credential SQL holdings')))
 assert c.main()==1;out=capsys.readouterr().out;assert 'secret' not in out and 'SQL' not in out and not json.loads(out)['accepted_scout_run']

def test_system_units_have_only_daily_calendar_and_cert_is_not_scout():
 scout=Path('systemd/development-scout.service').read_text();timer=Path('systemd/development-scout.timer').read_text();cert=Path('ops/discovery/development-scout-sandbox-certification.service').read_text()
 for line in ['User=optiplex','Group=optiplex','PrivateNetwork=true','PrivateTmp=true','ProtectSystem=strict','ProtectHome=read-only','NoNewPrivileges=true','WorkingDirectory=/home/optiplex/investment']:
  assert line in scout and line in cert
 assert [l for l in timer.splitlines() if l.startswith('OnCalendar=')]==['OnCalendar=*-*-* 16:00:00 America/New_York']
 assert 'observer.py' not in cert and 'sandbox_certify.py' in cert and 'development-control.sqlite3' in cert
 assert '--user' not in Path('ops/discovery/observer.py').read_text() and 'XDG_RUNTIME_DIR' not in Path('ops/discovery/observer.py').read_text()


def test_certification_requires_live_command_record(monkeypatch):
 monkeypatch.setenv('INVOCATION_ID','a'*32);monkeypatch.setattr(c.os,'getpid',lambda:123)
 row=['/usr/bin/python3',['/usr/bin/python3','-I','-S','/opt/investment-discovery-observer/sandbox_certify.py'],False,1,int(c.time.monotonic()*1e6),0,0,123,0,0]
 def output(cmd,**kw):return ('InvocationID='+('a'*32)).encode() if cmd[0]=='/usr/bin/systemctl' else json.dumps(dict(type='a(sasbttttuii)',data=[row])).encode()
 monkeypatch.setattr(c.subprocess,'check_output',output);assert c.active_record()
 row[7]=999;assert not c.active_record()


def test_legacy_user_bootstrap_refuses_system_scout_template():
 from ops.install_discovery import legacy_user_units_only
 with pytest.raises(ValueError,match='root migration'):
  legacy_user_units_only({'development-scout.service':Path('systemd/development-scout.service').read_bytes()})

def test_scheduler_manager_environment_cannot_redirect_system_bus(monkeypatch):
 from dev_agent import scheduler
 monkeypatch.setenv('INVOCATION_ID','a'*32);monkeypatch.setenv('DBUS_SYSTEM_BUS_ADDRESS','unix:path=/untrusted');monkeypatch.setenv('XDG_RUNTIME_DIR','/untrusted')
 calls=[]
 def run(cmd,**kw):
  calls.append(kw);assert kw['env']=={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'};raise OSError('unavailable')
 monkeypatch.setattr(scheduler.subprocess,'run',run)
 assert scheduler.trigger()=={'source':'operator','invocation':None} and calls


def test_cert_manager_exception_stays_sanitized(monkeypatch,capsys):
 from ops.discovery import sandbox_certify as c
 def broken():raise RuntimeError("secret SQL private path")
 monkeypatch.setattr(c,"checks",broken);monkeypatch.setattr(c,"active_record",broken)
 assert c.main()==1
 out=capsys.readouterr().out
 assert "secret" not in out and "SQL" not in out and json.loads(out)["execution_record_current"] is False
