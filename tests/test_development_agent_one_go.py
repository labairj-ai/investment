"""One owner decision, automatic technical gates; entirely synthetic, never live credit."""
import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_deployment_agent import authorized_owner,FakeExecutor
from test_development_agent_owner_review import setup as owner_setup
from deployment_agent.admission import authorize
from owner_gateway.core import advance_approved
from development_fixtures import protection_observation

ROOT=Path(__file__).resolve().parents[1]


def test_one_review_authorizes_exact_merge_and_deployment(authorized_owner,tmp_path):
    from deployment_agent.service import deploy
    store,client,obj,data=authorized_owner
    read=client.read;pr=client.pr_identity;merged=False;actions=[]
    client.read=lambda endpoint:dict(login='owner',id=1,type='User') if endpoint=='user' else read(endpoint)
    def identity(number):
        result=pr(number)
        return dict(result,state='MERGED' if merged else 'OPEN',isDraft=False)
    client.pr_identity=identity
    def write(endpoint,payload,method):
        nonlocal merged
        assert method=='PUT' and endpoint.endswith('/pulls/1/merge')
        assert payload['sha']==data['head'];merged=True;actions.append(payload)
        return dict(merged=True,sha='c'*40)
    client.write=write
    assert advance_approved(store,client,1)['merge_sha']=='c'*40
    auth=authorize(store,client,999)
    executor=FakeExecutor(tmp_path)
    receipt=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:authorize(store,client,999))
    assert receipt['status']=='DEPLOYED_VERIFIED' and len(actions)==1
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM dev_events WHERE kind='OWNER_REVIEW'").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM dev_events WHERE kind='OWNER_MERGE'").fetchone()[0]==1
    assert receipt['authorization_id']==999 # original Go, no deployment comment


@pytest.mark.parametrize('failure',['head-ci','merge-ci','main','head','no-go','other-pr','emergency'])
def test_one_go_never_bypasses_technical_gates(authorized_owner,failure):
    store,client,obj,data=authorized_owner;original=client.read
    def read(endpoint):
        value=copy.deepcopy(original(endpoint))
        if '/check-runs' in endpoint and (failure=='head-ci' and data['head'] in endpoint or failure=='merge-ci' and 'c'*40 in endpoint):value['check_runs'][0]['conclusion']='failure'
        if '/branches/main' in endpoint and failure=='main':value['commit']['sha']='d'*40
        return value
    client.read=read
    if failure=='head':client.head='d'*40
    if failure in {'no-go','other-pr'}:
        changed=dict(data,decision='REQUEST_CHANGES') if failure=='no-go' else dict(data,pr=2)
        obj['body']='OWNER-REVIEW solo-owner-2\n'+json.dumps(changed)
    with pytest.raises(ValueError):authorize(store,client,999,emergency_stop=failure=='emergency')


@pytest.fixture
def ready_inputs(owner_setup,monkeypatch):
    from dev_agent import operations,certification,scheduler_health,improvement_loop,build_policy
    store,client,_=owner_setup;now=time.time()
    config=json.loads((ROOT/'config/development_agent.json').read_text());config.update(supervised_loop_enabled=True,supervised_publish_pr=True)
    evidence={name:dict(status='PASS',fixture_only=False,harness_hash='a'*64,created=now,expires_at=now+3600) for name in ('oracle','deployment_agent')}
    evidence['snapshot']=dict(status='PASS',backup_timestamp=now)
    monkeypatch.setattr(operations,'policy',lambda root:config)
    monkeypatch.setattr(operations,'certificates',lambda store:[dict(evidence=evidence)])
    monkeypatch.setattr(certification,'technical_current',lambda *a:True)
    monkeypatch.setattr(certification,'harness_hash',lambda root:'a'*64)
    monkeypatch.setattr(scheduler_health,'health',lambda *a:dict(status='SCHEDULED',enabled=True,active='active',inventory_complete=True,successful_runs=3))
    monkeypatch.setattr(improvement_loop,'require_completed',lambda root:None)
    monkeypatch.setattr(build_policy,'current',lambda *a:dict(source='isolated-test'))
    client.protections=lambda:protection_observation(created=now)
    return store,client,config,evidence,now


def test_owner_ready_implies_real_runtime_entry_admits(ready_inputs):
    from dev_agent.readiness import owner_status
    from dev_agent.improvement_loop import supervised_admission
    store,client,config,evidence,now=ready_inputs
    assert owner_status(ROOT,store,client=client,now=now)['status']=='READY'
    assert supervised_admission(ROOT,store,client,now=now)['status']=='READY'
    # Both call the same actual gate; no parallel readiness authority.
    config['supervised_loop_enabled']=False
    assert owner_status(ROOT,store,client=client,now=now)['status']=='NOT READY'
    with pytest.raises(ValueError):supervised_admission(ROOT,store,client,now=now)


@pytest.mark.parametrize('failure',['oracle','deployment_agent','github','kill','discovery'])
def test_owner_not_ready_has_plain_reason_and_runtime_refuses(ready_inputs,monkeypatch,failure):
    from dev_agent.readiness import owner_status
    from dev_agent.improvement_loop import supervised_admission
    from dev_agent import scheduler_health
    store,client,config,evidence,now=ready_inputs
    if failure in evidence:evidence[failure]['status']='UNAVAILABLE'
    if failure=='github':client.protections=lambda:protection_observation(created=now-301)
    if failure=='kill':monkeypatch.setenv('DEV_AGENT_KILL_SWITCH','1')
    if failure=='discovery':monkeypatch.setattr(scheduler_health,'health',lambda *a:dict(successful_runs=2))
    result=owner_status(ROOT,store,client=client,now=now)
    assert result['status']=='NOT READY' and result['reason']
    with pytest.raises(ValueError):supervised_admission(ROOT,store,client,now=now)


def test_no_go_connector_never_calls_merge(owner_setup,monkeypatch):
    from owner_gateway import core
    store,client,_=owner_setup;calls=[]
    monkeypatch.setattr(core,'record_decision',lambda *a,**k:calls.append(k) or dict(decision=k['decision']))
    monkeypatch.setattr(core,'advance_approved',lambda *a:pytest.fail('No-Go cannot merge'))
    assert core.go_no_go(store,client,dict(risk='L5',pr=1),'No-Go')['status']=='NO_GO'
    assert calls[0]['decision']=='REQUEST_CHANGES'
    assert calls[0]['financial_ack'] and calls[0]['execution_ack'] # internal reviewed-risk metadata


def test_normal_stage_path_does_not_consume_legacy_promotion(monkeypatch,owner_setup):
    from dev_agent import stage_control,owner_promotion,qualification
    store,_,_=owner_setup
    monkeypatch.setattr(owner_promotion,'authorization',lambda *a,**k:pytest.fail('legacy promotion must not be consumed'))
    monkeypatch.setattr(owner_promotion,'require_runtime_binding',lambda *a,**k:pytest.fail('legacy promotion must not gate runtime'))
    monkeypatch.setattr(qualification,'evaluate',lambda *a,**k:dict(blockers=[]))
    # Missing normal activation Go must still fail closed.
    assert not stage_control.report(ROOT,store)['eligible']


def test_activation_derives_authority_from_ordinary_review(authorized_owner,monkeypatch):
    from dev_agent import owner_promotion,github,git_exec
    from dev_agent.github_owner import ingest
    store,client,obj,data=authorized_owner
    data.update(risk='L5',financial_ack=True,execution_ack=True,nonce='activation-single-go-0001')
    obj['body']='OWNER-REVIEW solo-owner-2\n'+json.dumps(data)
    ingest(store,client,999)
    monkeypatch.setenv('DEV_AGENT_PROMOTION_PR','1')
    monkeypatch.setattr(github,'GitHub',lambda repository:client)
    monkeypatch.setattr(git_exec,'output',lambda *a:'c'*40)
    proof=owner_promotion.activation_authority(ROOT,store)
    assert proof['status']=='PASS' and proof['origin']['id']==999
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM dev_events WHERE kind='OWNER_AUTONOMY_PROMOTION'").fetchone()[0]==0
    client.head='e'*40
    with pytest.raises(ValueError):owner_promotion.activation_authority(ROOT,store)


def test_owner_ready_respects_runtime_daily_limit(ready_inputs):
    from dev_agent.readiness import owner_status
    from datetime import datetime
    from zoneinfo import ZoneInfo
    store,client,config,evidence,now=ready_inputs
    slot=datetime.fromtimestamp(now,ZoneInfo('America/New_York')).date().isoformat()
    with store.connect(True) as db:store._append(db,None,'START_AUTHORIZATION',dict(slot=slot),'synthetic-start')
    assert owner_status(ROOT,store,client=client,now=now)['status']=='NOT READY'


def test_reviewed_source_supplies_only_l0_build_scope(owner_setup):
    from dev_agent.build_policy import current
    store,_,_=owner_setup
    scope=current(ROOT,store)
    assert scope['source']=='reviewed-supervised-scope' and scope['max_risk']=='L0'
    assert scope['patterns']==['docs/help/*.md','docs/help/*.txt']
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM dev_events WHERE kind='BUILD_POLICY'").fetchone()[0]==0


def test_retired_second_approval_issuers_cannot_write(owner_setup):
    from owner_gateway.core import authorize_deployment,authorize_autonomy_promotion
    store,client,_=owner_setup
    client.write=lambda *a:pytest.fail('retired ceremony cannot write')
    for issuer in (authorize_deployment,authorize_autonomy_promotion):
        with pytest.raises(ValueError,match='retired'):issuer(store,client)


def test_original_go_remains_valid_without_daily_owner_renewal(authorized_owner):
    from dev_agent.github_owner import ingest
    from datetime import datetime,timezone,timedelta
    store,client,obj,data=authorized_owner
    stamp=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    obj.update(created_at=stamp,updated_at=stamp)
    data['nonce']='older-owner-go-0001';obj['body']='OWNER-REVIEW solo-owner-2\n'+json.dumps(data)
    ingest(store,client,999)
    assert authorize(store,client,999)['authorization_id']==999


def test_deployment_queue_recovers_original_go_after_ci_delay(authorized_owner,tmp_path):
    from deployment_agent.poller import pending
    store,client,obj,data=authorized_owner
    original=client.read
    def read(endpoint):
        if '/issues/comments?' in endpoint:return []
        if '/pulls?per_page=100' in endpoint:return [dict(number=1,merge_commit_sha='c'*40)]
        return original(endpoint)
    read_all=client.read_all
    client.read=read;client.read_all=lambda endpoint:[obj] if endpoint.endswith('/comments') else read_all(endpoint)
    assert pending(client,tmp_path)==[999]


def test_missing_static_installation_cannot_be_certified(monkeypatch):
    from dev_agent.static_validation import installed
    monkeypatch.delenv('DEV_AGENT_STATIC_ORACLE_SOURCE_SHA256',raising=False)
    with pytest.raises(ValueError,match='unavailable'):installed(ROOT,'a'*40,'b'*40)


def test_runtime_follows_approved_document_release_without_promotion_pointer(authorized_owner,monkeypatch):
    from dev_agent import owner_promotion,github,git_exec
    store,client,obj,data=authorized_owner
    original=client.read
    client.read=lambda endpoint:[dict(number=1,merge_commit_sha='c'*40)] if '/pulls?per_page=100' in endpoint else original(endpoint)
    monkeypatch.delenv('DEV_AGENT_PROMOTION_PR',raising=False)
    monkeypatch.setattr(github,'GitHub',lambda repository:client)
    monkeypatch.setattr(git_exec,'output',lambda *a:'c'*40)
    assert owner_promotion.activation_authority(ROOT,store)['status']=='PASS'
    # Low-risk owner review cannot increase the runtime risk ceiling.
    from dev_agent import operations
    cfg=operations.policy(ROOT);cfg['autonomous_max_risk']='L3'
    monkeypatch.setattr(operations,'policy',lambda root:cfg)
    with pytest.raises(ValueError):owner_promotion.activation_authority(ROOT,store)


@pytest.mark.parametrize('failure',['unmerged','merge-ci','wrong-installed-source'])
def test_runtime_activation_does_not_skip_release_transition(authorized_owner,monkeypatch,failure):
    from dev_agent import owner_promotion,github,git_exec
    store,client,obj,data=authorized_owner
    original=client.read;identity=client.pr_identity
    def read(endpoint):
        result=copy.deepcopy(original(endpoint))
        if failure=='merge-ci' and '/commits/'+('c'*40)+'/check-runs' in endpoint:
            result['check_runs'][0]['conclusion']='failure'
        return result
    client.read=read
    if failure=='unmerged':client.pr_identity=lambda n:dict(identity(n),state='OPEN')
    monkeypatch.setenv('DEV_AGENT_PROMOTION_PR','1')
    monkeypatch.setattr(github,'GitHub',lambda repository:client)
    monkeypatch.setattr(git_exec,'output',lambda *a:'d'*40 if failure=='wrong-installed-source' else 'c'*40)
    with pytest.raises(ValueError):owner_promotion.activation_authority(ROOT,store)
