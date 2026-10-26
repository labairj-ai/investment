"""Disposable recovery fixtures; no host certification or Scout authority."""
import json
from pathlib import Path
import pytest
from ops.discovery import migrate as m,pin_refresh as r
from test_development_agent_scout_migration import migration
from test_development_agent_observer_refresh import host

@pytest.fixture
def stopped(migration):
 h=migration;h.invoke(['/bin/systemctl','stop',r.SERVICE]);h.user_active=h.user_enabled=False;h.calls.clear();h.starts=h.stops=0
 return h


def progress(result):return json.loads(Path(result['progress']).read_text())


def test_stopped_plan_no_mutation(stopped):
 h=stopped;before=h.snapshot();names=set(h.CONFIG.parent.iterdir());calls=len(h.calls);result=h.migrate()
 assert result['status']=='PLAN_ONLY' and result['start_mode']=='STOPPED_ROLLBACK' and not result['changes_applied'] and result['accepted_runs']==0 and not result['grants_implementation']
 assert h.snapshot()==before and set(h.CONFIG.parent.iterdir())==names and h.starts==h.stops==0 and not h.user_active
 assert not any(a[2:]==['enable','--now','development-scout.timer'] for a in h.calls[calls:])


def test_stopped_apply_never_reactivates_old_boundary(stopped):
 h=stopped;result=h.migrate(apply=True)
 assert result['status']=='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS' and result['start_mode']=='STOPPED_ROLLBACK'
 assert h.starts==1 and h.stops==0 and not h.user_active and h.system_active and h.cert_started
 assert not any(a[:2]==['/usr/bin/systemctl','--user'] and 'enable' in a for a in h.calls)
 assert all(not(old and new) for old,new in h.timeline)
 cert=h.calls.index(['/usr/bin/systemctl','--system','start',m.CERT_UNIT]);enable=h.calls.index(['/usr/bin/systemctl','--system','enable','--now','development-scout.timer']);new=h.calls.index(['/bin/systemctl','start',r.SERVICE]);assert cert<enable<new
 data=progress(result);assert data['schema']=='scout-system-migration-progress-1' and data['start_mode']=='STOPPED_ROLLBACK'
 assert data['source_target_sha']==h.head and data['old_boundary_sha']==h.old and len(data['attempt_id'])==32
 passed=[e['stage'] for e in data['stages'] if e['result']=='PASS'];assert passed==[s for s in m.STAGES if s not in {'ROLLBACK_STARTED','ROLLBACK_COMPLETE'}]
 assert all(e['stage_completed_at']>=e['stage_started_at'] for e in data['stages'] if e['result']=='PASS')
 assert Path(result['progress']).stat().st_uid==r.ROOT_UID and Path(result['progress']).stat().st_mode&0o077==0
 assert not list(h.STATE.iterdir())

@pytest.mark.parametrize('attack',['observer_running','timer_enabled','partial_system','live_cert','socket','changed_old'])
def test_stopped_mixed_states_rejected(stopped,monkeypatch,attack):
 h=stopped
 if attack=='observer_running':h.invoke(['/bin/systemctl','start',r.SERVICE])
 elif attack=='timer_enabled':h.user_active=h.user_enabled=True
 elif attack=='partial_system':(m.SYSTEM/'development-scout.service').write_text('partial')
 elif attack=='live_cert':
  original=m.properties
  def props(invoke,name,user=False):
   p=original(invoke,name,user)
   if not user and name==m.CERT_UNIT:p.update(ActiveState='active',MainPID='9')
   return p
  monkeypatch.setattr(m,'properties',props)
 elif attack=='socket':h.SOCKET.write_bytes(b'unexpected socket path')
 elif attack=='changed_old':h.SOURCE.write_text('tampered')
 result=h.migrate();assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and not result['changes_applied']


CODES={'POST_CERT_LEDGER_VERIFIED':'LEDGER_CONTINUITY_CHANGED','POST_CERT_ACCEPTANCE_STATE_VERIFIED':'ACCEPTANCE_STATE_CHANGED','POST_CERT_PROTECTED_STATE_VERIFIED':'PROTECTED_STATE_CHANGED','OLD_USER_TIMER_DISABLED_VERIFIED':'OLD_USER_TIMER_STATE_INVALID','ACTIVATION_WINDOW_VERIFIED':'ACTIVATION_WINDOW_EXPIRED','NEXT_ELAPSE_VERIFIED':'NEXT_ELAPSE_INVALID','NEW_OBSERVER_STARTED':'OBSERVER_START_FAILED'}
@pytest.mark.parametrize('stage',list(CODES))
def test_exact_post_cert_failure_codes_and_rollback(stopped,monkeypatch,stage):
 h=stopped;original=m.Progress.run
 def run(self,name,code,action):
  if name==stage:
   def broken():raise RuntimeError('secret credentials holdings SQL /private/path')
   action=broken
  return original(self,name,code,action)
 monkeypatch.setattr(m.Progress,'run',run)
 result=h.migrate(apply=True)
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and result['failure_stage']==stage and result['failure_code']==CODES[stage]
 data=progress(result);failed=[e for e in data['stages'] if e['result']=='FAIL'];assert failed[-1]['sanitized_failure_code']==CODES[stage]
 assert data['stages'][-1]['stage']=='ROLLBACK_COMPLETE' and data['stages'][-1]['result']=='PASS'
 raw=Path(result['progress']).read_text()+json.dumps(result);assert all(v not in raw for v in ['secret credentials','holdings SQL','/private/path','RuntimeError'])
 assert not h.active and not h.user_active and not h.system_active and not list(h.STATE.iterdir())


@pytest.mark.parametrize('stage',[s for s in m.STAGES if s not in {'PREFLIGHT_VERIFIED','ROLLBACK_STARTED','ROLLBACK_COMPLETE'}])
def test_every_transaction_stage_has_durable_failure_and_stops(stopped,monkeypatch,stage):
 h=stopped;original=m.Progress.run
 def run(self,name,code,action):
  if name==stage:
   def broken():raise ValueError('sensitive data')
   action=broken
  return original(self,name,code,action)
 monkeypatch.setattr(m.Progress,'run',run);result=h.migrate(apply=True)
 assert 'NOT_READY' in result['status'] and result['failure_stage'] in {stage,'ROLLBACK_COMPLETE'}
 assert result['failure_code'] in m.FAILURE_CODES and not h.active and not h.user_active and not h.system_active
 assert 'sensitive data' not in json.dumps(result)+Path(result['progress']).read_text()


def test_persistent_stamp_gets_distinct_code_and_is_not_deleted(stopped,monkeypatch):
 h=stopped;original=m.Progress.run
 def run(self,name,code,action):
  if name=='ACTIVATION_WINDOW_VERIFIED':m.STAMP.write_text('external fixture history')
  return original(self,name,code,action)
 monkeypatch.setattr(m.Progress,'run',run);result=h.migrate(apply=True)
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and result['failure_stage']=='ACTIVATION_WINDOW_VERIFIED' and result['failure_code']=='PERSISTENT_TIMER_STAMP_PRESENT'
 assert m.STAMP.read_text()=='external fixture history' and not h.system_active


def test_rollback_failure_is_explicit(stopped,monkeypatch):
 h=stopped
 def corrupt(invoke,start):
  (next(h.CONFIG.parent.glob('scout-system-migration-backup-*'))/'0').write_text('corrupt');raise ValueError('private')
 monkeypatch.setattr(m,'certify',corrupt);result=h.migrate(apply=True)
 assert result['failure_stage']=='ROLLBACK_COMPLETE' and result['failure_code']=='ROLLBACK_FAILED' and result['initial_failure_code']=='SANDBOX_CERTIFICATION_FAILED'
 assert not h.active and not h.user_active and not h.system_active


@pytest.mark.parametrize('kind',['ledger','acceptance','protected','old_timer'])
def test_actual_post_cert_state_changes_are_detected(stopped,monkeypatch,kind):
 h=stopped;original=m.certify
 def certify(*args):
  value=original(*args)
  if kind=='ledger':
   import sqlite3
   with sqlite3.connect(h.CONTROL/'development-control.sqlite3') as db:db.execute("INSERT INTO dev_events VALUES(2,'foreign',NULL,'FOREIGN',2,'{}')")
  elif kind=='acceptance':(h.STATE/'timer-fires.json').write_text('[]')
  elif kind=='protected':(h.ROOT/'holdings.csv').write_text('external synthetic change')
  else:h.user_active=h.user_enabled=True
  return value
 monkeypatch.setattr(m,'certify',certify);result=h.migrate(apply=True)
 expected={'ledger':('POST_CERT_LEDGER_VERIFIED','LEDGER_CONTINUITY_CHANGED'),'acceptance':('POST_CERT_ACCEPTANCE_STATE_VERIFIED','ACCEPTANCE_STATE_CHANGED'),'protected':('POST_CERT_PROTECTED_STATE_VERIFIED','PROTECTED_STATE_CHANGED'),'old_timer':('OLD_USER_TIMER_DISABLED_VERIFIED','OLD_USER_TIMER_STATE_INVALID')}
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and (result['failure_stage'],result['failure_code'])==expected[kind]
 assert not h.active and not h.user_active and not h.system_active
 if kind=='acceptance':assert (h.STATE/'timer-fires.json').read_text()=='[]'
 if kind=='protected':assert (h.ROOT/'holdings.csv').read_text()=='external synthetic change'


def test_existing_backup_is_preserved_without_old_transition(stopped):
 h=stopped;backup=h.CONFIG.parent/('scout-system-migration-backup-'+h.head);backup.mkdir();(backup/'keep').write_text('retained')
 before=h.snapshot();result=h.migrate(apply=True)
 assert result['status']=='PREFLIGHT_FAILED_NOT_READY' and (backup/'keep').read_text()=='retained' and h.snapshot()==before and h.starts==h.stops==0
