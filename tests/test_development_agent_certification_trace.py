"""Durable certification decisions in disposable full migration/rollback fixtures."""
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
import pytest
from ops.discovery import migrate as m, upgrade as u
from test_development_agent_scout_migration import migration
from test_development_agent_observer_refresh import host
from test_development_agent_stopped_recovery import stopped

CASES=[('identity','UNIT_IDENTITY_INVALID'),('start','START_FAILED'),('result','RESULT_INVALID'),
 ('exec','EXEC_STATUS_INVALID'),('missing_invocation','INVOCATION_INVALID'),('malformed_invocation','INVOCATION_INVALID'),('empty_invocation','INVOCATION_INVALID'),
 ('journal','JOURNAL_QUERY_FAILED'),('oversize','JOURNAL_OVERSIZE'),('journal_json','JOURNAL_DECODE_INVALID'),
 ('message_json','JOURNAL_DECODE_INVALID'),('later_journal_json','JOURNAL_DECODE_INVALID'),('schema','REPORT_SCHEMA_INVALID'),*[(
 'boolean:'+key,'REPORT_BOOLEAN_INVALID') for key in ('network_namespace_isolated','repository_read_only','protected_state_inaccessible','credentials_inaccessible','process_uid_expected','system_manager_readable','execution_record_current','test_evidence_only')],
 ('credit','REPORT_BOOLEAN_INVALID'),('zero','REPORT_COUNT_INVALID'),('one','REPORT_COUNT_INVALID'),
 ('two','REPORT_COUNT_INVALID'),('four','REPORT_COUNT_INVALID')]


def test_harness_dispatches_current_invoke(stopped):
 h=stopped;original=h.invoke;calls=[]
 def replacement(args,**kw):
  calls.append(list(args))
  return original(args,**kw)
 h.invoke=replacement
 result=h.migrate()
 assert result['status']=='PLAN_ONLY' and calls
 assert not h.cert_started


def test_harness_observes_replacement_certification_error(stopped):
 h=stopped;original=h.invoke;reached=[];before=u.protected_state()
 def replacement(args,**kw):
  if args==['/usr/bin/systemctl','--system','start',m.CERT_UNIT]:
   reached.append(list(args))
   raise RuntimeError('controlled certification fixture failure')
  return original(args,**kw)
 h.invoke=replacement
 result=h.migrate(apply=True)
 assert len(reached)==1
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY'
 assert result['failure_code']=='CERTIFICATION_START_FAILED'
 assert result['accepted_runs']==0 and not result['grants_implementation']
 trace=json.loads((Path(result['backup'])/'certification-trace.json').read_text())
 assert trace['failure_code']=='CERTIFICATION_START_FAILED'
 assert trace['completed_subchecks']==['unit_identity']
 progress=json.loads(Path(result['progress']).read_text())
 assert any(e['stage']=='ROLLBACK_COMPLETE' and e['result']=='PASS' for e in progress['stages'])
 assert u.protected_state()==before and not list(h.STATE.iterdir())


def inject(h,attack):
 original=h.invoke
 def invoke(args,**kw):
  result=original(args,**kw)
  if args[:4]==['/usr/bin/systemctl','--system','show',m.CERT_UNIT] and (m.SYSTEM/m.CERT_UNIT).exists():
   fields=dict(line.split('=',1) for line in result.stdout.splitlines())
   if not h.cert_started and attack=='identity':fields['User']='secret-do-not-retain'
   if h.cert_started:
    if attack=='result':fields['Result']='exit-code'
    if attack=='exec':fields['ExecMainStatus']='1'
    if attack=='missing_invocation':fields.pop('InvocationID')
    if attack=='malformed_invocation':fields['InvocationID']='NOT-AN-ID'
    if attack=='empty_invocation':fields['InvocationID']=''
   result.stdout='\n'.join(k+'='+v for k,v in fields.items())
  if args[:4]==['/usr/bin/systemctl','--system','start',m.CERT_UNIT]:
   assert kw['check'] is False
   if attack=='start':return SimpleNamespace(returncode=1,stdout='secret-do-not-retain',stderr='secret-do-not-retain')
  if args[0]=='/usr/bin/journalctl':
   assert kw['check'] is False and args[-2]=='_SYSTEMD_INVOCATION_ID='+'c'*32
   assert args[-1].startswith('--since=@')
   if attack=='journal':return SimpleNamespace(returncode=1,stdout='',stderr='secret-do-not-retain')
   if attack=='oversize':result.stdout='x'*65537
   elif attack=='journal_json':result.stdout='not-json'
   elif attack=='later_journal_json':result.stdout=json.dumps(dict(MESSAGE='secret-do-not-retain'))+'\nnot-json'
   elif attack=='message_json':result.stdout=json.dumps(dict(MESSAGE='{bad'))
   elif attack in {'schema','credit'} or attack.startswith('boolean:'):
    rows=[json.loads(v) for v in result.stdout.splitlines()];report=json.loads(rows[0]['MESSAGE'])
    if attack=='schema':report['arbitrary']='secret-do-not-retain'
    elif attack.startswith('boolean:'):report[attack.split(':',1)[1]]=False
    else:report['accepted_scout_run']=True
    rows[0]['MESSAGE']=json.dumps(report);result.stdout='\n'.join(json.dumps(v) for v in rows)
   elif attack in {'zero','one','two','four'}:
    count={'zero':0,'one':1,'two':2,'four':4}[attack];line=result.stdout.splitlines()[0];result.stdout='\n'.join([line]*count)
  return result
 h.invoke=invoke


@pytest.mark.parametrize('attack,suffix',CASES)
def test_specific_failure_retains_trace_after_stopped_rollback(stopped,attack,suffix):
 h=stopped;before=u.protected_state();inject(h,attack);result=h.migrate(apply=True)
 code='CERTIFICATION_'+suffix
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY'
 assert (result['failure_stage'],result['failure_code'])==('SANDBOX_CERTIFICATION_PASSED',code)
 assert result['accepted_runs']==0 and not result['grants_implementation']
 backup=Path(result['backup']);path=backup/'certification-trace.json';raw=path.read_text();trace=json.loads(raw)
 assert trace['certification_result']=='FAIL' and trace['failure_code']==code
 assert 'secret-do-not-retain' not in raw and not path.is_symlink()
 assert stat.S_IMODE(path.stat().st_mode)==0o600 and path.stat().st_uid==os.getuid()
 progress=json.loads(Path(result['progress']).read_text())
 assert trace['attempt_id']==progress['attempt_id'] and trace['source_target_sha']==h.head
 assert any(e['stage']=='ROLLBACK_COMPLETE' and e['result']=='PASS' for e in progress['stages'])
 if attack=='later_journal_json':assert trace['observations']['parsing_counters']['total_journal_json_lines']==1
 if attack=='empty_invocation':assert trace['observations']['post_run_properties']['InvocationID']==''
 assert trace['completed_subchecks'] or attack=='identity'
 assert u.protected_state()==before and not h.system_active and not h.user_active
 assert not list(h.STATE.iterdir())


def test_success_retains_exact_query_and_zero_credit(stopped,monkeypatch):
 h=stopped;original=m.certify;clock=1793103560.3052843
 def certify(invoke,start,progress):return original(invoke,clock,progress)
 monkeypatch.setattr(m,'certify',certify)
 result=h.migrate(apply=True)
 assert result['status']=='MIGRATED_AWAITING_GENUINE_SYSTEM_TIMER_RUNS'
 trace=json.loads((Path(result['backup'])/'certification-trace.json').read_text());obs=trace['observations']
 assert trace['certification_result']=='PASS' and trace['failure_code'] is None
 assert trace['certification_started_at_repr']==repr(clock)
 assert obs['start_returncode']==obs['journal_returncode']==0
 assert obs['post_run_properties']['Result']=='success' and obs['post_run_properties']['ExecMainStatus']=='0'
 assert obs['journal_query']['since_argument']=='--since=@'+str(clock)
 assert obs['journal_query']['arguments'][-2]=='_SYSTEMD_INVOCATION_ID='+'c'*32
 assert obs['parsing_counters']==dict(total_journal_json_lines=3,json_message_candidates=3,decoded_candidate_reports=3,exact_schema_reports=3,valid_boolean_reports=3,final_accepted_reports=3)
 assert result['accepted_runs']==0 and result['certification']['accepted_scout_run'] is False
 assert not list(h.STATE.iterdir())


def test_trace_persist_failure_is_specific_and_rolls_back(stopped,monkeypatch):
 h=stopped;original=u.write
 def write(path,*args):
  if path.name=='certification-trace.next':raise OSError('secret-do-not-retain')
  return original(path,*args)
 monkeypatch.setattr(u,'write',write);result=h.migrate(apply=True)
 assert result['failure_code']=='CERTIFICATION_TRACE_PERSIST_FAILED'
 assert result['status']=='ROLLED_BACK_STOPPED_NOT_READY' and result['accepted_runs']==0
 assert 'secret-do-not-retain' not in json.dumps(result)


@pytest.mark.parametrize('attack',['symlink','temporary_symlink','mode','bound','directory_fsync'])
def test_trace_storage_fails_closed_without_overwriting_foreign_data(host,monkeypatch,attack):
 from types import SimpleNamespace
 backup=host.CONFIG.parent/'trace-backup';backup.mkdir(mode=0o700)
 progress=SimpleNamespace(backup=backup,identity=dict(attempt_id='a'*32,source_target_sha=host.head))
 foreign=host.base/'foreign';foreign.write_text('do not overwrite')
 path=backup/'certification-trace.json'
 if attack=='symlink':path.symlink_to(foreign)
 if attack=='temporary_symlink':(backup/'certification-trace.next').symlink_to(foreign)
 if attack=='mode':path.write_text('{}');path.chmod(0o644)
 if attack=='directory_fsync':
  original=u.sync
  def sync(where):
   if where==backup:raise OSError('private')
   return original(where)
  monkeypatch.setattr(u,'sync',sync)
 with pytest.raises(m.MigrationFailure) as error:
  trace=m.CertificationTrace(progress,1793103560.3052843)
  if attack=='bound':trace.data['observations']['invalid_fixture']='x'*16384;trace.persist()
 assert error.value.code=='CERTIFICATION_TRACE_PERSIST_FAILED'
 assert foreign.read_text()=='do not overwrite'
 if attack=='bound':assert json.loads(path.read_text())['observations']=={}
