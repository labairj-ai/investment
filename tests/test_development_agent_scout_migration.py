"""Synthetic migration transaction. No host systemd, Scout or financial writes."""
import json,sqlite3,time,subprocess,shutil
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import pytest
from ops.discovery import migrate as m,pin_refresh as r,observer as o
from test_development_agent_observer_refresh import host

@pytest.fixture
def migration(host,monkeypatch):
 monkeypatch.setattr(m.time,'time',lambda:eastern('07:00:00'))
 h=host;h.CONFIG.write_bytes(r.encoded(h.old_config));h.git('branch','-M','main');h.user_active=h.user_enabled=True;h.system_active=h.system_enabled=False;h.cert_started=False;h.failure=None;h.timeline=[];h.next_offset=0
 system=h.base/'system';system.mkdir();monkeypatch.setattr(m,'SYSTEM',system);monkeypatch.setattr(m,'STAMP',h.base/'system-stamp');monkeypatch.setattr(m,'CERT_SOURCE',h.SOURCE.parent/'sandbox_certify.py')
 monkeypatch.setattr(m,'OLD_HEAD',h.old)
 for name,key in [('OLD_OBSERVER','observer_digest'),('OLD_SERVICE','unit_digest'),('OLD_TIMER','timer_digest')]:monkeypatch.setattr(m,name,h.old_config[key])
 monkeypatch.setattr(m,'OLD_UNIT',h.old_config['files'][r.IDENTITIES[1]])
 monkeypatch.setattr(m,'isolated',lambda:True);monkeypatch.setattr(m,'audit',lambda *a,**k:dict(untracked_source_influence='PASS'))
 for name in r.IDENTITIES[2:]:(h.USER_UNITS/Path(name).name).write_bytes(r.git(h.ROOT,'show',h.old+':'+name))
 for name in [r.IDENTITIES[0],r.IDENTITIES[2]]:(h.ROOT/name).write_text('new reviewed '+name)
 (h.ROOT/r.IDENTITIES[3]).write_text('OnCalendar=*-*-* 16:00:00 America/New_York\nPersistent=true\nRandomizedDelaySec=120\nUnit=development-scout.service\n')
 for name in m.CERT_FILES:
  p=h.ROOT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('new fixed certification '+name)
 (h.ROOT/'holdings.csv').write_text('synthetic holdings');(h.ROOT/'out').mkdir()
 for name in ['investment.db','buffett.db']:(h.ROOT/'out'/name).write_bytes(b'synthetic financial fixture')
 (h.CONTROL/'operational-signals.json').write_text('{}')
 ledger=h.CONTROL/'development-control.sqlite3';monkeypatch.setattr(o,'LEDGER',ledger)
 with sqlite3.connect(ledger) as db:db.execute('CREATE TABLE dev_events(seq INTEGER PRIMARY KEY,event_id TEXT,candidate TEXT,kind TEXT,created REAL,payload TEXT)');db.execute("INSERT INTO dev_events VALUES(1,'observation',NULL,'SCHEDULER_OBSERVATION',1,'{}')")
 h.git('add','.');h.git('commit','-qm','reviewed system migration');h.head=h.git('rev-parse','HEAD');h.git('update-ref','refs/remotes/origin/main',h.head)
 original=h.invoke
 def invoke(args,**kw):
  if args[:2]==['/bin/systemctl','stop']:
   result=original(args,**kw);shutil.rmtree(h.PROC/str(h.pid),ignore_errors=True);return result
  if args[:2]==['/bin/systemctl','show'] and not h.active:
   result=original(args,**kw);result.stdout='\n'.join(('MainPID=0' if line.startswith('MainPID=') else 'InvocationID=' if line.startswith('InvocationID=') else line) for line in result.stdout.splitlines());return result
  if args[0]=='/usr/bin/journalctl':
   keys=['network_namespace_isolated','repository_read_only','protected_state_inaccessible','credentials_inaccessible','process_uid_expected','system_manager_readable','execution_record_current','test_evidence_only'];report={k:True for k in keys};report['accepted_scout_run']=False
   if h.failure=='runtime_route':report['network_namespace_isolated']=False
   return SimpleNamespace(returncode=0,stdout='\n'.join(json.dumps(dict(MESSAGE=json.dumps(report))) for _ in range(3)))
  if args[0]=='/usr/bin/busctl':return SimpleNamespace(returncode=0,stdout='t '+str(int(((time.time()+86400) if '--user' in args else (m.first_activation_slot()+h.next_offset))*1e6))+'\n')
  if args[:2] in [['/usr/bin/systemctl','--system'],['/usr/bin/systemctl','--user']]:
   h.calls.append(args);user=args[1]=='--user';action=args[2];name=args[3] if len(args)>3 else ''
   if action=='daemon-reload':return SimpleNamespace(returncode=0,stdout='')
   if action=='show':
    is_timer=name.endswith('.timer');cert=name==m.CERT_UNIT;loaded=user or (system/name).exists()
    active=(h.user_active if user else h.system_active) if is_timer else False
    enabled=(h.user_enabled if user else h.system_enabled) if is_timer else False
    data=dict(LoadState='loaded' if loaded else 'not-found',FragmentPath=str((h.USER_UNITS if user else system)/name) if loaded else '',DropInPaths='/bad' if (h.failure=='dropin' and user or h.failure=='system_dropin' and not user and loaded) else '',NeedDaemonReload='no',ActiveState='active' if active else 'inactive',SubState='waiting' if active else 'dead',UnitFileState='enabled' if enabled else 'disabled',MainPID='0',ControlPID='0',InvocationID='c'*32 if cert and h.cert_started else '0'*32,Result='success',ExecMainStatus='0',User='optiplex',Group='optiplex',RefuseManualStart='yes',PrivateNetwork='yes',PrivateTmp='yes',ProtectSystem='strict',ProtectHome='read-only',NoNewPrivileges='yes',WorkingDirectory=str(h.ROOT))
    return SimpleNamespace(returncode=0,stdout='\n'.join(k+'='+v for k,v in data.items()))
   if name==m.CERT_UNIT and action=='start':
    h.cert_started=True
    if h.failure=='namespace':raise subprocess.CalledProcessError(1,args)
   elif 'development-scout.timer' in args:
    if action=='disable':
     if user:h.user_active=h.user_enabled=h.failure=='old_timer_stuck'
     else:h.system_active=h.system_enabled=False
    elif action=='enable':
     assert not user and not h.user_active,'both timers active forbidden';h.system_active=h.system_enabled=True
     if h.failure=='both_active':h.user_active=h.user_enabled=True
    else:pytest.fail('unexpected timer mutation '+str(args))
    h.timeline.append((h.user_active,h.system_active))
   else:pytest.fail('must never invoke Scout service '+str(args))
   return SimpleNamespace(returncode=0,stdout='')
  return original(args,**kw)
 h.invoke=invoke;h.migrate=lambda **kw:m.migrate(h.ROOT,h.head,h.old,invoke=invoke,**kw)
 return h

def test_migration_plan_only_preserves_existing_installed_discovery(migration):
 h=migration;before=h.snapshot();config=h.CONFIG.read_bytes();names=set(h.CONFIG.parent.iterdir());result=h.migrate()
 assert result['status']=='PLAN_ONLY' and not result['changes_applied'] and result['accepted_runs']==0 and not result['grants_implementation']
 assert h.snapshot()==before and h.CONFIG.read_bytes()==config and set(h.CONFIG.parent.iterdir())==names and h.user_active and not h.system_active and h.stops==h.starts==0

def test_transaction_installs_only_system_scout_and_certifies_before_timer(migration):
 h=migration;ledger=h.CONTROL.joinpath('development-control.sqlite3').read_bytes();result=h.migrate(apply=True)
 assert result['status']=='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS' and result['accepted_runs']==0 and not result['grants_implementation']
 assert h.system_active and not h.user_active and not h.user_enabled and h.cert_started
 assert h.CONTROL.joinpath('development-control.sqlite3').read_bytes()==ledger and not list(h.STATE.iterdir())
 assert json.loads(h.CONFIG.read_text())['scout_manager']=='system' and json.loads(h.CONFIG.read_text())['head']==h.head
 assert Path(result['backup'],'manifest.json').is_file() and not any(a[2:]==['start','development-scout.service'] for a in h.calls)
 assert all(not (old and new) for old,new in h.timeline)
 cert=h.calls.index(['/usr/bin/systemctl','--system','start',m.CERT_UNIT]);enable=h.calls.index(['/usr/bin/systemctl','--system','enable','--now','development-scout.timer']);assert cert<enable
 assert result['certification']['test_evidence_only'] and result['certification']['accepted_scout_run'] is False

@pytest.mark.parametrize('failure',['namespace','runtime_route','both_active','old_timer_stuck','system_dropin'])
def test_migration_failure_stops_not_ready_without_credit(migration,failure):
 h=migration;source=h.SOURCE.read_bytes();config=h.CONFIG.read_bytes();h.failure=failure;result=h.migrate(apply=True)
 assert 'NOT_READY' in result['status'] and not result['changes_applied'] and not h.active and not list(h.STATE.iterdir())
 if failure!='old_timer_stuck':assert not h.user_active and not h.system_active and h.SOURCE.read_bytes()==source and h.CONFIG.read_bytes()==config

@pytest.mark.parametrize('attack',['old_head','old_digest','dropin','system_collision','stamp','history'])
def test_migration_preconditions_fail_closed(migration,attack):
 h=migration
 if attack=='old_head':h.old='b'*40
 elif attack=='old_digest':h.SOURCE.write_text('wrong old observer')
 elif attack=='dropin':h.failure='dropin'
 elif attack=='system_collision':(m.SYSTEM/'development-scout.service').write_text('unexpected')
 elif attack=='stamp':m.STAMP.write_text('do not reset this')
 elif attack=='history':(h.STATE/'discovery.json').write_text('{"runs":[]}')
 result=h.migrate();assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and result['failure_stage']=='PREFLIGHT_VERIFIED'
 assert h.user_active and not h.system_active

@pytest.mark.parametrize('entry',['16:30:00','18:30:00','21:00:00'])
def test_elapsed_calendar_is_never_installable(entry):
 raw=Path('systemd/development-scout.timer').read_bytes()+('OnCalendar=2026-10-25 '+entry+' America/New_York\n').encode()
 with pytest.raises(ValueError):m.daily_only(raw)


def test_failed_observer_restart_restores_old_bytes_and_stops(migration):
 h=migration;old=h.SOURCE.read_bytes();config=h.CONFIG.read_bytes();h.fail='restart'
 result=h.migrate(apply=True)
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and not h.active and not h.user_active and not h.system_active
 assert h.SOURCE.read_bytes()==old and h.CONFIG.read_bytes()==config

def test_wrong_backup_prevents_claiming_successful_rollback(migration,monkeypatch):
 h=migration;original=m.certify
 def corrupt(invoke,start):
  backup=next(h.CONFIG.parent.glob('scout-system-migration-backup-*'));(backup/'0').write_text('corrupt')
  raise ValueError('fixture certificate failure')
 monkeypatch.setattr(m,'certify',corrupt);result=h.migrate(apply=True)
 assert result['status']=='FAILED_STOPPED_NOT_READY' and result['observer_stopped'] and not result['old_files_restored']

def test_new_file_atomic_install_refuses_collision_without_overwrite(tmp_path):
 target=tmp_path/'unit';target.write_bytes(b'foreign');created=[]
 with pytest.raises(FileExistsError):m.install_new(target,b'reviewed',0o644,created)
 assert target.read_bytes()==b'foreign' and not created and not list(tmp_path.glob('*.scout-migrating'))


def eastern(clock):
 return datetime.fromisoformat('2026-10-26T'+clock).replace(tzinfo=ZoneInfo('America/New_York')).timestamp()

@pytest.mark.parametrize('clock',['13:00:00','14:00:00','15:30:00','15:49:59'])
def test_first_activation_window_valid(clock):
 assert m.first_activation_slot(eastern(clock))==eastern('16:00:00')

@pytest.mark.parametrize('clock',['15:50:00','15:55:00','16:00:00','17:00:00','23:00:00'])
def test_first_activation_window_never_rolls_to_tomorrow(clock):
 with pytest.raises(ValueError,match='before 15:50'):m.first_activation_slot(eastern(clock))

@pytest.mark.parametrize('offset',[0,60,120])
def test_enabled_next_elapse_is_today_in_reviewed_interval(migration,offset):
 h=migration;h.next_offset=offset
 assert h.migrate(apply=True)['status']=='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'

@pytest.mark.parametrize('offset',[-1,-7200,-14400,-86400,121,86400])
def test_wrong_next_elapse_rolls_back_without_scout(migration,offset):
 h=migration;h.next_offset=offset
 result=h.migrate(apply=True)
 assert 'NOT_READY' in result['status'] and not h.system_active and not h.user_active
 assert not any(a[2:]==['start','development-scout.service'] for a in h.calls)

def test_plan_before_cutoff_apply_at_cutoff_refuses_without_mutation(migration,monkeypatch):
 h=migration;monkeypatch.setattr(m.time,'time',lambda:eastern('15:49:00'))
 assert h.migrate()['status']=='PLAN_ONLY'
 before=h.snapshot();names=set(h.CONFIG.parent.iterdir());calls=list(h.calls)
 monkeypatch.setattr(m.time,'time',lambda:eastern('15:50:00'))
 result=h.migrate(apply=True);assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and result['failure_code']=='ACTIVATION_WINDOW_EXPIRED'
 assert h.snapshot()==before and set(h.CONFIG.parent.iterdir())==names and h.calls==calls and h.user_active and not h.system_active

def test_cutoff_rechecked_under_lock_before_backup_or_timer_mutation(migration,monkeypatch):
 h=migration;original=m.inspect;count=0
 def inspect(*args):
  nonlocal count
  count+=1;result=original(*args)
  if count==2:monkeypatch.setattr(m.time,'time',lambda:eastern('15:50:00'))
  return result
 monkeypatch.setattr(m,'inspect',inspect)
 before=h.snapshot();config=h.CONFIG.read_bytes()
 result=h.migrate(apply=True);assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and result['failure_code']=='ACTIVATION_WINDOW_EXPIRED'
 assert h.snapshot()==before and h.CONFIG.read_bytes()==config and not list(h.CONFIG.parent.glob('scout-system-migration-backup-*'))
 assert h.user_active and not h.system_active and not h.cert_started and h.stops==0

def test_certification_crossing_cutoff_rolls_back_without_timer_enable(migration,monkeypatch):
 h=migration;original=m.certify
 def certify(*args):
  result=original(*args);monkeypatch.setattr(m.time,'time',lambda:eastern('15:50:00'));return result
 monkeypatch.setattr(m,'certify',certify)
 result=h.migrate(apply=True)
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and not h.user_active and not h.system_active
 assert ['/usr/bin/systemctl','--system','enable','--now','development-scout.timer'] not in h.calls
 assert not any(a[2:]==['start','development-scout.service'] for a in h.calls)


@pytest.mark.parametrize('clock',['12:00:00','10:00:00','08:15:00'])
def test_obsolete_daily_qualification_calendar_rejected(clock):
 raw=Path('systemd/development-scout.timer').read_bytes().replace(b'16:00:00',clock.encode())
 with pytest.raises(ValueError):m.daily_only(raw)


def test_duplicate_1600_calendar_rejected():
 raw=Path('systemd/development-scout.timer').read_bytes()+b'OnCalendar=*-*-* 16:00:00 America/New_York\n'
 with pytest.raises(ValueError):m.daily_only(raw)
