"""Completed oneshot identity: trusted journal evidence, no real host activity."""
import json
import pytest
from types import SimpleNamespace
from pathlib import Path
from ops.discovery import migrate as m,upgrade as u
from test_development_agent_observer_refresh import host
from test_development_agent_scout_migration import migration
from test_development_agent_stopped_recovery import stopped


@pytest.mark.parametrize('manager',['empty','omitted','matching'])
def test_october28_empty_manager_identity_uses_trusted_journal(stopped,manager):
 h=stopped;original=h.invoke;before=u.protected_state()
 def invoke(args,**kw):
  result=original(args,**kw)
  if args[:4]==['/usr/bin/systemctl','--system','show',m.CERT_UNIT] and h.cert_started:
   fields=dict(line.split('=',1) for line in result.stdout.splitlines())
   if manager=='empty':fields['InvocationID']=''
   if manager=='omitted':fields.pop('InvocationID')
   result.stdout='\n'.join(k+'='+v for k,v in fields.items())
  return result
 h.invoke=invoke
 result=h.migrate(apply=True)
 assert result['status']=='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'
 assert result['accepted_runs']==0 and result['certification']['accepted_scout_run'] is False
 assert len(result['certification']['reports'])==3 and u.protected_state()==before
 trace=json.loads((Path(result['backup'])/'certification-trace.json').read_text())
 assert trace['observations']['identity_source']==('manager-and-trusted-journal' if manager=='matching' else 'trusted-journal-only')
 assert trace['observations']['manager_invocation_presence']=={'empty':'empty','omitted':'omitted','matching':'present'}[manager]
 assert trace['observations']['matching_report_count']==3 and trace['observations']['final_identity_valid']=='PASS'


ATTACKS=[('manager_mismatch','INVOCATION_MISMATCH'),('multiple','JOURNAL_IDENTITY_INVALID'),
 ('unreported_invocation','JOURNAL_IDENTITY_INVALID'),('missing_id','JOURNAL_IDENTITY_INVALID'),
 ('untrusted_id','JOURNAL_IDENTITY_INVALID'),('malformed_id','JOURNAL_IDENTITY_INVALID'),
 ('zero_id','JOURNAL_IDENTITY_INVALID'),('array_id','JOURNAL_IDENTITY_INVALID'),
 ('unit','JOURNAL_UNIT_INVALID'),('missing_unit','JOURNAL_UNIT_INVALID'),
 ('boot','JOURNAL_BOOT_INVALID'),('missing_boot','JOURNAL_BOOT_INVALID'),
 ('uid','JOURNAL_UID_INVALID'),('missing_uid','JOURNAL_UID_INVALID'),
 ('stale','JOURNAL_WINDOW_INVALID'),('future','JOURNAL_WINDOW_INVALID'),
 ('monotonic_stale','JOURNAL_WINDOW_INVALID'),('monotonic_future','JOURNAL_WINDOW_INVALID'),
 ('missing_realtime','JOURNAL_WINDOW_INVALID'),('missing_monotonic','JOURNAL_WINDOW_INVALID'),
 ('invalid_timestamp','JOURNAL_WINDOW_INVALID'),('array_timestamp','JOURNAL_WINDOW_INVALID'),
 ('duplicate_phase','REPORT_PROCESS_INVALID'),('reordered_phases','REPORT_PROCESS_INVALID'),
 ('missing_pid','REPORT_PROCESS_INVALID'),('invalid_pid','REPORT_PROCESS_INVALID'),
 ('transport','REPORT_PROCESS_INVALID'),('two','REPORT_COUNT_INVALID'),
 ('missing_boolean','REPORT_SCHEMA_INVALID'),('invalid_boolean','REPORT_BOOLEAN_INVALID')]


@pytest.mark.parametrize('attack,suffix',ATTACKS)
def test_trusted_identity_rejections_roll_back_without_credit(stopped,attack,suffix):
 h=stopped;original=h.invoke;before=u.protected_state();ledger=(h.CONTROL/'development-control.sqlite3').read_bytes()
 def invoke(args,**kw):
  result=original(args,**kw)
  if args[:4]==['/usr/bin/systemctl','--system','show',m.CERT_UNIT] and h.cert_started and attack=='manager_mismatch':
   result.stdout=result.stdout.replace('InvocationID='+'c'*32,'InvocationID='+'d'*32)
  if args[0]=='/usr/bin/journalctl':
   rows=[json.loads(line) for line in result.stdout.splitlines()];row=rows[0]
   if attack=='multiple':rows[-1]['_SYSTEMD_INVOCATION_ID']='d'*32
   elif attack=='unreported_invocation':rows.append(dict(row,_SYSTEMD_INVOCATION_ID='d'*32,MESSAGE='unrelated output'))
   elif attack=='missing_id':row.pop('_SYSTEMD_INVOCATION_ID')
   elif attack=='untrusted_id':row['INVOCATION_ID']=row.pop('_SYSTEMD_INVOCATION_ID')
   elif attack=='malformed_id':row['_SYSTEMD_INVOCATION_ID']='bad'
   elif attack=='zero_id':row['_SYSTEMD_INVOCATION_ID']='0'*32
   elif attack=='array_id':row['_SYSTEMD_INVOCATION_ID']=['c'*32,'d'*32]
   elif attack=='unit':row['_SYSTEMD_UNIT']='development-scout.service'
   elif attack=='missing_unit':row.pop('_SYSTEMD_UNIT')
   elif attack=='boot':row['_BOOT_ID']='d'*32
   elif attack=='missing_boot':row.pop('_BOOT_ID')
   elif attack=='uid':row['_UID']='0'
   elif attack=='missing_uid':row.pop('_UID')
   elif attack=='stale':row['__REALTIME_TIMESTAMP']=str(int(row['__REALTIME_TIMESTAMP'])-1)
   elif attack=='future':row['__REALTIME_TIMESTAMP']=str(int(row['__REALTIME_TIMESTAMP'])+1000000)
   elif attack=='monotonic_stale':row['__MONOTONIC_TIMESTAMP']='1'
   elif attack=='monotonic_future':row['__MONOTONIC_TIMESTAMP']=str(int(row['__MONOTONIC_TIMESTAMP'])+1000000)
   elif attack=='missing_realtime':row.pop('__REALTIME_TIMESTAMP')
   elif attack=='missing_monotonic':row.pop('__MONOTONIC_TIMESTAMP')
   elif attack=='invalid_timestamp':row['__REALTIME_TIMESTAMP']='1.5'
   elif attack=='array_timestamp':row['__REALTIME_TIMESTAMP']=['1','2']
   elif attack=='duplicate_phase':rows[-1]['_PID']=row['_PID']
   elif attack=='reordered_phases':rows.reverse()
   elif attack=='missing_pid':row.pop('_PID')
   elif attack=='invalid_pid':row['_PID']='0'
   elif attack=='transport':row['_TRANSPORT']='journal'
   elif attack=='two':rows=rows[:2]
   elif attack in {'missing_boolean','invalid_boolean'}:
    report=json.loads(row['MESSAGE'])
    if attack=='missing_boolean':report.pop('execution_record_current')
    else:report['execution_record_current']=1
    row['MESSAGE']=json.dumps(report)
   result.stdout='\n'.join(json.dumps(row) for row in rows)
  return result
 h.invoke=invoke;result=h.migrate(apply=True)
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and result['failure_code']=='CERTIFICATION_'+suffix
 assert result['accepted_runs']==0 and not result['grants_implementation']
 assert not list(h.STATE.iterdir()) and not h.user_active and not h.system_active
 assert u.protected_state()==before and (h.CONTROL/'development-control.sqlite3').read_bytes()==ledger
 trace=json.loads((Path(result['backup'])/'certification-trace.json').read_text())
 assert trace['certification_result']=='FAIL' and trace['failure_code']==result['failure_code']
 stages=json.loads(Path(result['progress']).read_text())['stages']
 assert any(row['stage']=='ROLLBACK_COMPLETE' and row['result']=='PASS' for row in stages)


def test_retained_october28_sanitized_reports_validate_offline(stopped,monkeypatch):
 """Replay retained evidence into the verifier, never into acceptance or systemd."""
 h=stopped;evidence=json.loads(Path('docs/evidence/scout-certification-20261028.json').read_text())
 records=evidence['reports'];mono=[int(row['trusted_fields']['__MONOTONIC_TIMESTAMP']) for row in records]
 ticks=iter([(mono[0]-100000)/1e6,(mono[-1]+100000)/1e6,(mono[-1]+100001)/1e6])
 monkeypatch.setattr(m.time,'monotonic',lambda:next(ticks))
 monkeypatch.setattr(m.time,'time',lambda:evidence['recorded_failure_completion'])
 monkeypatch.setattr(m.r.pwd,'getpwnam',lambda _:SimpleNamespace(pw_uid=1000))
 def invoke(args,**kw):
  if args[:3]==['/usr/bin/systemctl','--system','show']:
   props=dict(FragmentPath=str(m.SYSTEM/m.CERT_UNIT),DropInPaths='',NeedDaemonReload='no',User='optiplex',Group='optiplex',Result='success',ExecMainStatus='0',InvocationID='')
   return SimpleNamespace(stdout='\n'.join(k+'='+v for k,v in props.items()),returncode=0)
  if args[:3]==['/usr/bin/systemctl','--system','start']:return SimpleNamespace(returncode=0,stdout='',stderr='')
  assert args[0]=='/usr/bin/journalctl'
  return SimpleNamespace(returncode=0,stderr='',stdout='\n'.join(json.dumps(dict(row['trusted_fields'],MESSAGE=json.dumps(row['report']))) for row in records))
 backup=h.CONFIG.parent/'retrospective';backup.mkdir(mode=0o700)
 progress=SimpleNamespace(backup=backup,identity=dict(attempt_id=evidence['attempt_id'],source_target_sha=evidence['source_sha']))
 result=m.certify(invoke,evidence['recorded_start'],progress)
 assert result['invocation']==evidence['unique_trusted_invocation'] and len(result['reports'])==3
 assert result['accepted_scout_run'] is False and not list(h.STATE.iterdir())
