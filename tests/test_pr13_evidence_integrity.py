"""0832–0834: synthetic adapters/ledgers only; no live evidence or authority."""
import copy
import hashlib
import hmac
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from test_development_agent import store,proposal
from dev_agent import scheduler_health,qualification,promotion,stage_control,owner_promotion,operations,certification
from dev_agent.result_collector import canonical
from dev_agent.store import digest
from dev_agent.deployment_evidence import seal
from development_fixtures import deployment_evidence
ROOT=Path(__file__).resolve().parents[1]
KEY=b'fixture-only-observer-authority-not-production-12345'


def schedule_payload(now,*,age=0,invocation='a'*32,source='systemd-observed-timer',status='COLLECTED'):
    start=now-age*86400-3
    slot='scout:'+datetime.fromtimestamp(start,ZoneInfo('America/New_York')).date().isoformat()
    return dict(status=status,slot=slot,head='a'*40,trigger=dict(source=source,invocation=invocation if source=='systemd-observed-timer' else None),started_at=start,ended_at=start+2,duration_seconds=2)


def scheduled_store(store,now):
    scheduler_health.record(store,dict(status='SCHEDULED',created=now-1,enabled=True,active='active'))


def append(store,kind,payload,cid=None):
    with store.connect(True) as db:store._append(db,cid,kind,payload,'fixture:'+str(time.time_ns()))


def inventory(store):
    with store.connect() as db:
        return [tuple(r) for r in db.execute('SELECT * FROM dev_events ORDER BY seq')],[tuple(r) for r in db.execute('SELECT * FROM dev_candidates ORDER BY id')]


def test_manual_success_followed_by_timer_duplicate_never_qualifies(store):
    now=time.time();scheduled_store(store,now)
    append(store,'SCHEDULE',schedule_payload(now,source='operator'))
    duplicate=schedule_payload(now,status='DUPLICATE');append(store,'SCHEDULE_DUPLICATE',duplicate)
    append(store,'SCHEDULE_DUPLICATE',duplicate)
    result=scheduler_health.health(store,now+1)
    assert result['successful_runs']==0 and result['successful_slots']==[]
    assert result['duplicate_runs']==1 and result['timer_fires']==1
    assert result['status']=='AWAITING_FIRST_RUN' and result['last_success'] is None


@pytest.mark.parametrize('status',['COLLECTED','BACKLOG_FULL'])
def test_only_genuine_distinct_scheduled_executions_count(store,status):
    now=time.time();scheduled_store(store,now)
    append(store,'SCHEDULE',schedule_payload(now,status=status))
    append(store,'SCHEDULE',schedule_payload(now,status=status,invocation='b'*32))
    append(store,'SCHEDULE_DUPLICATE',schedule_payload(now,status='DUPLICATE',invocation='c'*32))
    result=scheduler_health.health(store,now)
    assert result['successful_runs']==1 and len(result['successful_slots'])==1
    assert result['timer_fires']==3 and result['duplicate_runs']==1
    assert result['status']=='SCHEDULED'


@pytest.mark.parametrize('kind,status,source',[('SCHEDULE','COLLECTED','operator'),('SCHEDULE','BACKLOG_FULL','operator'),('SCHEDULE','DUPLICATE','systemd-observed-timer'),('SCHEDULE_DUPLICATE','COLLECTED','systemd-observed-timer')])
def test_manual_or_duplicate_records_never_receive_success_credit(store,kind,status,source):
    now=time.time();scheduled_store(store,now);append(store,kind,schedule_payload(now,status=status,source=source))
    assert scheduler_health.health(store,now)['successful_runs']==0


def test_same_invocation_failure_vetoes_apparent_success(store):
    now=time.time();scheduled_store(store,now);p=schedule_payload(now)
    append(store,'SCHEDULE_ATTEMPT',dict(p,status='STARTED'))
    append(store,'SCHEDULE',p);append(store,'SCHEDULE_FAILURE',dict(p,status='FAILED'))
    r=scheduler_health.health(store,now)
    assert r['successful_runs']==0 and r['failed_runs']==1 and r['recent_failure']['status']=='FAILED'


@pytest.mark.parametrize('mutation',[dict(head='short'),dict(slot='scout:1900-01-01'),dict(started_at=None),dict(ended_at=0),dict(duration_seconds=999),dict(trigger=dict(source='systemd-observed-timer',invocation='bad'))])
def test_incomplete_or_wrong_calendar_identity_never_qualifies(store,mutation):
    now=time.time();scheduled_store(store,now);append(store,'SCHEDULE',dict(schedule_payload(now),**mutation))
    assert scheduler_health.health(store,now)['successful_runs']==0


@pytest.fixture
def complete_evidence(store,monkeypatch):
    from test_development_agent_hardening import seed_completed_pilot,fixture_human,technical
    now=time.time();config=operations.policy(ROOT)
    monkeypatch.setattr(operations,'policy',lambda root:config)
    monkeypatch.setattr(qualification,'policy',lambda root:config)
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={'os-interactive-cli':['fixture-owner']})))
    ids=[]
    for age in (8,4,0):
        with monkeypatch.context() as clock:
            clock.setattr(operations.time,'time',lambda age=age:now-age*86400)
            cid,client=seed_completed_pilot(store);operations.record_success(ROOT,store,cid,client,human=fixture_human());ids.append(cid)
    bound=certification.harness_hash(ROOT);cert=technical(ROOT,now-1)
    cert['evidence'].update({k:dict(status='PASS',fixture_only=False,harness_hash=bound,created=now-1,expires_at=now+3600) for k in ('oracle','deployment_agent')})
    cert['evidence']['github']=dict(status='PASS',created=now-1)
    cert['evidence']['snapshot']=dict(status='PASS',provenance_status='PASS',source_environment='optiplex/investment/out/investment.db',backup_timestamp=now-1)
    cert['id']=digest({k:v for k,v in cert.items() if k!='id'})
    certs=[cert];tasks={f'{n:04d}':dict(status='done') for n in [*range(816,824),*range(825,831)]}
    monkeypatch.setattr(qualification,'certificates',lambda store:certs)
    monkeypatch.setattr(qualification,'task_index',lambda root:tasks)
    scheduled_store(store,now)
    for age,char in enumerate('abc'):append(store,'SCHEDULE',schedule_payload(now,age=age,invocation=char*32))
    for stage in ('SHADOW','BUILD_ONLY'):
        for n in range(3):append(store,'STAGE_OBSERVATION',dict(stage=stage,candidate=f'fixture-{stage}-{n}',harness_hash=bound,fixture_only=False))
    return dict(store=store,now=now,config=config,cert=cert,certs=certs,tasks=tasks,ids=ids)


def alter_deployment(store,cid,change):
    with store.connect(True) as db:
        db.execute('DROP TRIGGER IF EXISTS dev_events_update')
        seq,payload=db.execute("SELECT seq,payload FROM dev_events WHERE candidate=? AND kind='DEPLOYMENT'",(cid,)).fetchone()
        value=json.loads(payload);change(value)
        db.execute('UPDATE dev_events SET payload=? WHERE seq=?',(json.dumps(value),seq))


def test_shared_gate_qualifies_read_only_but_cannot_enable_or_authorize(complete_evidence):
    x=complete_evidence;before=inventory(x['store'])
    evidence=qualification.evaluate(ROOT,x['store'],x['now']);r=promotion.report(ROOT,x['store'],x['now'])
    assert evidence['status']=='PASS',evidence['blockers']
    assert r['recommendation']=='GO_FOR_OWNER_STAGE_REVIEW' and r['observation_window']['observation_days']>=7
    assert not evidence['grants_authority'] and not r['enables_autonomy'] and not r['grants_merge'] and not r['grants_deployment']
    x['config'].update(autonomous_implementation=True,autonomy_stage='PR')
    assert qualification.evaluate(ROOT,x['store'],x['now'])['status']=='PASS'
    runtime=stage_control.report(ROOT,x['store'],x['now'])
    assert not runtime['eligible'] and runtime['owner_promotion']['status']=='UNAVAILABLE'
    with pytest.raises(ValueError):stage_control.require(ROOT,x['store'])
    assert inventory(x['store'])==before


BLOCKERS=['task','runs','days','harness','technical','oracle_missing','oracle_fixture','oracle_stale','oracle_harness','oracle_expired','deployment_missing','deployment_fixture','deployment_expired','deployment_stale','deployment_harness','protection','snapshot','snapshot_unsigned','snapshot_future','stop','kill','pause','incident','incident_global','repeat','repeat_global','receipt','recurrence_missing','recurrence_true','scheduler','scheduler_two','scheduler_duplicates','human_merge','auto_merge','risk','cap','cap_bool']
@pytest.mark.parametrize('fault',BLOCKERS)
def test_every_shared_safety_failure_blocks_both_report_and_runtime(complete_evidence,monkeypatch,fault):
    x=complete_evidence;store=x['store'];now=x['now'];cert=x['cert'];e=cert['evidence'];config=x['config'];cid=x['ids'][0]
    if fault=='task':x['tasks']['0828']['status']='in-progress'
    elif fault=='runs':x['ids'].pop();append(store,'STATE',dict(state='REJECTED'),cid=cid)
    elif fault=='days':monkeypatch.setattr(qualification,'eligibility',lambda *a:dict(eligible=False,blockers=['seven-day prospective observation incomplete'],completed=3,observation_days=1))
    elif fault=='harness':monkeypatch.setattr(qualification,'harness_hash',lambda root:'f'*64)
    elif fault=='technical':cert['status']='PARTIAL'
    elif fault.startswith('oracle_') or fault.startswith('deployment_'):
        key='oracle' if fault.startswith('oracle_') else 'deployment_agent';variant=fault.split('_',1)[1]
        if variant=='missing':e.pop(key)
        elif variant=='fixture':e[key]['fixture_only']=True
        elif variant=='stale':e[key]['created']=now-86401
        elif variant=='expired':e[key]['expires_at']=now-1
        elif variant=='harness':e[key]['harness_hash']='f'*64
    elif fault=='protection':e['github']['created']=now-301
    elif fault=='snapshot':e['snapshot']['backup_timestamp']=now-86401
    elif fault=='snapshot_unsigned':e['snapshot'].pop('provenance_status')
    elif fault=='snapshot_future':e['snapshot']['backup_timestamp']=now+1
    elif fault=='stop':config['emergency_stop']=True
    elif fault=='kill':monkeypatch.setenv('DEV_AGENT_KILL_SWITCH','1')
    elif fault=='pause':append(store,'AUTONOMY_PAUSE',dict(created=now-1))
    elif fault=='incident_global':append(store,'DEPLOYMENT',dict(status='DEGRADED',observed_at=now-1))
    elif fault=='incident':append(store,'DEPLOYMENT',dict(status='DEGRADED',observed_at=now-1),cid=cid)
    elif fault in {'repeat','repeat_global'}:
        for _ in range(3):append(store,'PIPELINE',dict(stage='FAILED',created=now-1),cid=cid if fault=='repeat' else None)
    elif fault=='receipt':alter_deployment(store,cid,lambda d:d['deployment_evidence']['receipt'].update(pr=99))
    elif fault=='recurrence_missing':alter_deployment(store,cid,lambda d:d.pop('metrics'))
    elif fault=='recurrence_true':alter_deployment(store,cid,lambda d:d['metrics'].update(defect_recurred=True))
    elif fault.startswith('scheduler'):
        if fault=='scheduler':scheduler_health.record(store,dict(status='STALE',created=now,enabled=True,active='active'))
        else:
            with store.connect(True) as db:
                db.execute('DROP TRIGGER IF EXISTS dev_events_update')
                rows=db.execute("SELECT seq,payload FROM dev_events WHERE kind='SCHEDULE' ORDER BY seq").fetchall()
                for seq,payload in (rows[:1] if fault=='scheduler_two' else rows):
                    p=json.loads(payload);p['status']='DUPLICATE';db.execute("UPDATE dev_events SET kind='SCHEDULE_DUPLICATE',payload=? WHERE seq=?",(json.dumps(p),seq))
    elif fault=='human_merge':config['required_human_merge']=False
    elif fault=='auto_merge':config['auto_merge']=True
    elif fault=='risk':config['autonomous_max_risk']='L3'
    elif fault=='cap':config['daily_implementation_cap']=4
    elif fault=='cap_bool':config['daily_implementation_cap']=True
    cert['id']=digest({k:v for k,v in cert.items() if k!='id'})
    before=inventory(store)
    shared=qualification.evaluate(ROOT,store,now);prepared=promotion.report(ROOT,store,now)
    assert shared['status']=='FAIL' and prepared['recommendation']=='NO-GO',fault
    config.update(autonomous_implementation=True,autonomy_stage='PR')
    # Simulate a future trusted authorization adapter ONLY to isolate evidence
    # parity. The real adapter is unavailable and tested separately above.
    monkeypatch.setattr(owner_promotion,'authorization',lambda *a,**k:dict(status='PASS',authenticated=True,grants_authority=False))
    runtime=stage_control.report(ROOT,store,now)
    assert set(shared['blockers'])<=set(runtime['blockers']) and not runtime['eligible'],fault
    with pytest.raises(ValueError):stage_control.require(ROOT,store)
    assert inventory(store)==before


def test_future_owner_promotion_shape_is_never_authentication(store):
    now=time.time();context=dict(repository='owner/repo',harness_hash='a'*64,activation_pr=3,head='b'*40,stage='PR',maximum_risk='L2',daily_cap=1,owner_login='owner',owner_id=10)
    record=dict(context,protocol=owner_promotion.PROTOCOL,created=now,nonce='fixture-owner-promotion-0001',rationale='Deliberate future owner decision')
    assert owner_promotion.validate_binding(record,context,now)==dict(binding_valid=True,authenticated=False,grants_authority=False)
    for changed in [dict(context,head='c'*40),dict(context,harness_hash='c'*64)]:
        with pytest.raises(ValueError):owner_promotion.validate_binding(record,changed,now)
    with pytest.raises(ValueError):owner_promotion.validate_binding(record,context,now+86401)
    with pytest.raises(ValueError):store.event(None,'OWNER_AUTONOMY_PROMOTION',record)
    append(store,'OWNER_AUTONOMY_PROMOTION',record)
    assert owner_promotion.authorization(ROOT,store)['status']=='UNAVAILABLE'


def changed_evidence(envelope,kind):
    r=copy.deepcopy(envelope['receipt'])
    if kind=='pr':r['pr']+=1
    elif kind=='repository':
        r['repository']='other/repo'
        for field in ('head_ci','merge_ci'):r[field]['url']=r[field]['url'].replace('owner/repo','other/repo')
    elif kind=='head':r['head']='d'*40;r['head_ci']['head']='d'*40
    elif kind=='merge':
        for field in ('merge_sha','deployed_sha','main_sha'):r[field]='d'*40
        r['merge_ci']['head']='d'*40
    elif kind=='fixture':r['fixture_only']=True
    elif kind=='manual':r['actor']='manual-owner-authorized'
    return seal(r)


@pytest.fixture
def observed_transaction(tmp_path):
    from test_deployment_agent import FakeExecutor,authorization
    from deployment_agent.service import deploy
    executor=FakeExecutor(tmp_path);auth=authorization()
    raw=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    return executor,raw


@pytest.mark.parametrize('fault',['pr','repository','head','merge','fixture','manual','outer_main','outer_deployed','not_verified','digest'])
def test_observer_cross_binding_rejects_internally_valid_wrong_receipts(observed_transaction,fault):
    from deployment_agent.observer import observe
    executor,raw=observed_transaction
    if fault=='outer_main':raw['main_sha']='d'*40
    elif fault=='outer_deployed':raw['deployed_sha']='d'*40
    elif fault=='not_verified':raw['protected_state_verified']=False
    elif fault=='digest':raw['deployment_evidence']['sha256']='d'*64
    else:raw['deployment_evidence']=changed_evidence(raw['deployment_evidence'],fault)
    before=copy.deepcopy(raw)
    with pytest.raises(ValueError):observe(executor,raw,key=KEY,now=raw['finished']+301)
    assert raw==before


def test_observer_actual_head_health_and_protected_state_can_never_be_hidden(observed_transaction):
    from deployment_agent.observer import observe
    executor,raw=observed_transaction;now=raw['finished']+301
    assert observe(executor,raw,key=KEY,now=now)['observation']['status']=='HEALTHY'
    executor.sha='d'*40
    assert observe(executor,raw,key=KEY,now=now)['observation']['status']=='DEGRADED'
    executor.sha=raw['merge_sha'];executor.mutated=True
    assert observe(executor,raw,key=KEY,now=now)['observation']['status']=='DEGRADED'
    executor.mutated=False;original=executor.health
    executor.health=lambda:dict(checks=dict(service=False))
    assert observe(executor,raw,key=KEY,now=now)['observation']['status']=='DEGRADED'
    executor.health=lambda:dict(checks={})
    assert observe(executor,raw,key=KEY,now=now)['observation']['status']=='DEGRADED'


@pytest.fixture
def candidate_observation(store,monkeypatch):
    from test_development_agent_hardening import seed_completed_pilot
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=10,operators={'os-interactive-cli':['fixture-owner']})))
    cid,client=seed_completed_pilot(store,pending=True)
    candidate=store.get(cid);pr=next(e['payload'] for e in candidate['events'] if e['kind']=='PR');now=time.time()-1
    body=dict(protocol='software-observation-1',repository=client.repository,pr=pr['result']['number'],head=pr['head'],deployment_intent_id=123,merge_sha='c'*40,deployed_sha='c'*40,environment='OptiPlex',deployed_at=now-600,observed_at=now,window_seconds=300,metrics=dict(service_healthy=True,protected_state_unchanged=True,defect_recurrence_checked=True,defect_recurred=False),evidence=['synthetic-trusted-observer-test'],status='HEALTHY',deployment_evidence=deployment_evidence(pr=pr['result']['number']))
    return store,cid,client,body


def sign(body):return dict(observation=body,signature=hmac.new(KEY,canonical(body),hashlib.sha256).hexdigest())


@pytest.mark.parametrize('fault',['pr','repository','head','merge','fixture','manual','outer_pr','outer_repository','outer_head','outer_merge','outer_deployed','digest','signature','clock','empty_metrics','missing_evidence'])
def test_signed_mismatched_observation_has_zero_state_or_event_mutation(candidate_observation,fault):
    from dev_agent.improvement_loop import accept_observation
    store,cid,client,body=candidate_observation
    if fault in {'pr','repository','head','merge','fixture','manual'}:body['deployment_evidence']=changed_evidence(body['deployment_evidence'],fault)
    elif fault=='outer_pr':body['pr']+=1
    elif fault=='outer_repository':body['repository']='other/repo'
    elif fault=='outer_head':body['head']='d'*40
    elif fault=='outer_merge':body['merge_sha']='d'*40
    elif fault=='outer_deployed':body['deployed_sha']='d'*40
    elif fault=='digest':body['deployment_evidence']['sha256']='d'*64
    elif fault=='clock':body['window_seconds']=-1
    elif fault=='empty_metrics':body['metrics']={}
    elif fault=='missing_evidence':body.pop('deployment_evidence')
    signed=sign(body)
    if fault=='signature':signed['signature']='d'*64
    before=inventory(store);state=store.get(cid)['state']
    with pytest.raises(ValueError):accept_observation(ROOT,store,cid,client,signed,key=KEY)
    assert inventory(store)==before and store.get(cid)['state']==state
    assert not any(e['kind']=='OPERATIONAL_SUCCESS' for e in store.get(cid)['events'])


def test_cross_candidate_replay_is_rejected_even_with_duplicate_pr_lineage(candidate_observation):
    from dev_agent.improvement_loop import accept_observation
    store,cid,client,body=candidate_observation
    other=store.discover(proposal(problem='Different synthetic candidate'))
    for event in store.get(cid)['events']:
        if event['kind'] in {'PR','MERGE','PIPELINE'}:append(store,event['kind'],event['payload'],cid=other)
    before=inventory(store)
    for target in (other,cid):
        with pytest.raises(ValueError,match='candidate'):accept_observation(ROOT,store,target,client,sign(body),key=KEY)
        assert inventory(store)==before


def test_valid_bound_signed_observation_completes_real_shape_lineage(candidate_observation):
    from dev_agent.improvement_loop import accept_observation
    from dev_agent.github_owner import HEADER
    from datetime import timezone
    store,cid,client,body=candidate_observation;original=client.read
    stamp=datetime.now(timezone.utc).isoformat();pr=body['pr']
    comment=dict(id=901,user=dict(id=10,login='owner',type='User'),body=HEADER+json.dumps(dict(repository=client.repository,pr=pr,head=body['head'],risk='L0',decision='APPROVE',nonce='fixture-observed-owner-0001',rationale='Reviewed synthetic test head',financial_ack=False,execution_ack=False)),created_at=stamp,updated_at=stamp,issue_url=f'https://api.github.com/repos/{client.repository}/issues/{pr}',html_url=f'https://github.com/{client.repository}/pull/{pr}#issuecomment-901')
    def read(endpoint):
        if '/issues/comments/901' in endpoint:return comment
        if '/comments?' in endpoint:return [comment]
        return original(endpoint)
    client.read=read
    assert store.get(cid)['state']=='PR_OPEN'
    result=accept_observation(ROOT,store,cid,client,sign(body),key=KEY)
    assert result['status']=='CLOSED' and store.get(cid)['state']=='CLOSED'
    phases=[e['payload']['stage'] for e in store.get(cid)['events'] if e['kind']=='PIPELINE']
    assert phases==['DEPLOYMENT_PENDING','DEPLOYED','OBSERVING','CLOSED']
    assert len([e for e in store.get(cid)['events'] if e['kind']=='OPERATIONAL_SUCCESS'])==1
    before=inventory(store);assert accept_observation(ROOT,store,cid,client,sign(body),key=KEY)['idempotent']
    assert inventory(store)==before


def test_stage_order_and_owner_authentication_remain_stricter_than_shared_evidence(complete_evidence,monkeypatch):
    x=complete_evidence;store=x['store'];x['config'].update(autonomous_implementation=True,autonomy_stage='PR')
    monkeypatch.setattr(owner_promotion,'authorization',lambda *a,**k:dict(status='PASS',authenticated=False))
    assert not stage_control.report(ROOT,store,x['now'])['eligible']
    monkeypatch.setattr(owner_promotion,'authorization',lambda *a,**k:dict(status='PASS',authenticated=True,fixture_only=True))
    assert stage_control.report(ROOT,store,x['now'])['eligible']
    with store.connect(True) as db:
        db.execute('DROP TRIGGER dev_events_update')
        rows=db.execute("SELECT seq,payload FROM dev_events WHERE kind='STAGE_OBSERVATION'").fetchall()
        for seq,payload in rows:
            p=json.loads(payload);p['fixture_only']=True;db.execute('UPDATE dev_events SET payload=? WHERE seq=?',(json.dumps(p),seq))
    r=stage_control.report(ROOT,store,x['now'])
    assert not r['eligible'] and any('shadow cycles' in b for b in r['blockers'])


def test_timer_duplicate_cannot_refresh_expired_success_window(store):
    now=time.time();scheduled_store(store,now)
    p=schedule_payload(now-37*3600)
    append(store,'SCHEDULE',p)
    append(store,'SCHEDULE_DUPLICATE',schedule_payload(now,status='DUPLICATE',invocation='b'*32))
    r=scheduler_health.health(store,now+1)
    assert r['successful_runs']==1 and r['duplicate_runs']==1
    assert r['status']=='STALE' and r['last_success']==p['ended_at']
