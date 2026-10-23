"""0816–0824 boundaries use synthetic observations and disposable ledgers only."""
import copy
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import pytest
from test_development_agent import store,repo,proposal
from test_development_agent_owner_review import setup as owner_setup
from dev_agent import github_owner,result_collector,signals,scheduler_health,stage_control,improvement_loop
from dev_agent.identity import HumanIdentity,_PROOF
from dev_agent.store import digest
from scripts import aggregate_release_validation as aggregate
ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failed_gate',['none','agent_contract','full_suite','cc_contract','release_baseline','missing_xml'])
def test_aggregate_runs_every_independent_gate(repo,tmp_path,failed_gate):
    observed=[]
    def invoke(command,**kwargs):
        script=command[1] if len(command)>1 else ''
        gate=next((n for n in aggregate.GATES if n in script),'')
        if command[1:3]==['-m','pytest']:
            gate='full_suite' if any(x.startswith('--junitxml') for x in command) else 'focused_agent_tests'
            if gate=='full_suite' and failed_gate!='missing_xml':
                path=Path(next(x.split('=',1)[1] for x in command if x.startswith('--junitxml')))
                failure='<failure message="deliberate"/>' if failed_gate=='full_suite' else ''
                path.write_text('<testsuites><testsuite><testcase classname="tests.test_fixture" name="case">'+failure+'</testcase></testsuite></testsuites>')
        observed.append(command)
        return SimpleNamespace(returncode=1 if failed_gate!='none' and failed_gate in script or failed_gate==gate and failed_gate!='none' else 0)
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    report=aggregate.run(repo,tmp_path/'results',head,head,invoke=invoke)
    assert len(report['gates'])==8
    assert report['status']==('PASS' if failed_gate=='none' else 'FAIL')
    assert any('scripts/check_cc_contract.py' in c for c in observed)
    assert any('--junitxml=' in ' '.join(c) for c in observed)
    if failed_gate=='missing_xml':assert next(g for g in report['gates'] if g['name']=='release_baseline')['status']=='NOT_RUN'


def test_summary_cannot_pass_missing_gate_or_wrong_sha():
    report=dict(source_unchanged=True,head='a',expected_head='a',gates=[dict(name=n,status='PASS',exit_code=0) for n in aggregate.GATES],pytest=dict(total=1,failed=0))
    assert aggregate.integrity(report)
    report['gates'].pop();assert not aggregate.integrity(report)
    report['expected_head']='b';assert not aggregate.integrity(report)


@pytest.mark.parametrize('raw,exit_code',[('<testsuite><testcase classname="tests.t" name="x"/></testsuite>',0),('<testsuite/>',0),('<testsuite><testcase classname="tests.t" name="x"/><testcase classname="tests.t" name="x"/></testsuite>',0),('<testsuite><testcase classname="tests.t" name="x"><failure/></testcase></testsuite>',0),('',1),('x'*2_000_001,0)])
def test_candidate_xml_exit_zero_and_forged_inventory_never_authorize(raw,exit_code):
    result=result_collector.normalize(raw.encode(),['tests.t::x'],returncode=exit_code)
    assert result['status'] in {'FAIL','UNAVAILABLE'}


def test_separate_oracle_signature_and_binding_required(tmp_path):
    binding=dict(base='b'*40,head='a'*40,image='fixture@sha256:'+'c'*64,candidate_source_tree_hash='d'*64,trusted_test_tree_hash='e'*64)
    key=b'fixture-only-oracle-signing-material-12345678';ids=['tests.t::x']
    receipt=dict(protocol='isolated-oracle-1',isolation='separate-process-no-candidate-imports',binding=binding,expected=ids,results=[dict(id=ids[0],status='PASS')])
    attestation=dict(receipt=receipt,signature=hmac.new(key,result_collector.canonical(receipt),hashlib.sha256).hexdigest())
    assert result_collector.verify(attestation,binding,ids,key=key,process_exit=0)['status']=='PASS'
    with pytest.raises(ValueError):result_collector.verify(attestation,dict(binding,head='f'*40),ids,key=key,process_exit=0)
    with pytest.raises(ValueError):result_collector.verify(attestation,binding,ids,key=b'wrong'*8,process_exit=0)
    with pytest.raises(ValueError):result_collector.verify(attestation,binding,ids,key=key,process_exit=1)
    directory=tmp_path/'collector';path=result_collector.write_final(directory,'receipt',dict(status='UNAVAILABLE'))
    assert path.stat().st_mode&0o077==0
    with pytest.raises(FileExistsError):result_collector.write_final(directory,'receipt',dict(status='PASS'))


def owner_comment(client,decision='APPROVE'):
    data=dict(repository=client.repository,pr=1,head=client.head,risk='L0',decision=decision,nonce='fixture-owner-github-0001',rationale='Reviewed',financial_ack=False,execution_ack=False)
    obj=dict(id=123,user=dict(id=1,login='owner',type='User'),performed_via_github_app=None,body=github_owner.HEADER+json.dumps(data),created_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),updated_at=None,issue_url='https://api.github.com/repos/owner/repo/issues/1',html_url='https://github.com/owner/repo/pull/1#issuecomment-123')
    obj['updated_at']=obj['created_at']
    return obj


@pytest.mark.parametrize('decision',['APPROVE','REQUEST_CHANGES','DEFER'])
def test_github_owner_decisions_are_bound_and_idempotent(owner_setup,decision):
    store,client,_=owner_setup;comment=owner_comment(client,decision);original=client.read
    client.read=lambda endpoint:comment if '/issues/comments/' in endpoint else [comment] if '/issues/1/comments?' in endpoint else original(endpoint)
    first=github_owner.ingest(store,client,123)
    assert github_owner.ingest(store,client,123)==first
    from dev_agent.owner_review import state,require
    assert state(store,client,1)['status']==decision
    if decision!='APPROVE':
        with pytest.raises(ValueError):require(store,client,1)
    else:assert require(store,client,1)['status']=='APPROVE'
    client.head='b'*40
    with pytest.raises(ValueError):github_owner.ingest(store,client,123)


@pytest.mark.parametrize('mutation',[{'user':dict(id=2,login='agent',type='User')},{'user':dict(id=1,login='owner',type='Bot')},{'body':'APPROVE'},{'updated_at':'edited'},{'issue_url':'https://api.github.com/repos/owner/repo/issues/2'},{'performed_via_github_app':{'id':1}}])
def test_untrusted_github_approval_objects_fail(owner_setup,mutation):
    store,client,_=owner_setup;comment=dict(owner_comment(client),**mutation);original=client.read
    client.read=lambda endpoint:comment if '/issues/comments/' in endpoint else [comment] if '/issues/1/comments?' in endpoint else original(endpoint)
    with pytest.raises((ValueError,KeyError)):github_owner.ingest(store,client,123)


def test_scheduler_actual_observation_and_staleness(store):
    invoke=lambda *a,**k:SimpleNamespace(stdout='LoadState=loaded\nUnitFileState=enabled\nActiveState=active\nNextElapseUSecRealtime=tomorrow\nLastTriggerUSec=yesterday\n')
    observed=scheduler_health.observe(invoke=invoke);assert observed['status']=='SCHEDULED'
    scheduler_health.record(store,observed)
    assert scheduler_health.health(store)['status']=='AWAITING_FIRST_RUN'
    from test_pr13_evidence_integrity import schedule_payload
    store.event(None,'SCHEDULE',schedule_payload(time.time()))
    assert scheduler_health.health(store)['status']=='SCHEDULED'
    assert scheduler_health.health(store,now=time.time()+3601)['status']=='STALE'
    scheduler_health.record(store,dict(observed,status='DISABLED',enabled=False))
    assert scheduler_health.health(store)['status']=='DISABLED'


def test_signal_redaction_and_stable_recurring_identity(store):
    item=signals.signal('telemetry','dashboard','Dashboard HTTP error',['serve.py'],'journal:cursor password=private',outcome='Restore read-only dashboard health',validation='HTTP probe and full regression',recurrence=2,synthetic=True)
    assert 'private' not in item['evidence_location']
    first=signals.ingest(store,[item]);second=signals.ingest(store,[dict(item,evidence_location='journal:new-cursor')])
    assert first['candidates']==second['candidates'] and second['deduplicated']==1
    assert len(store.list())==1
    assert signals.ingest(store,[item],suppressions={item['signal_id']:time.time()+60})['suppressed']==1


def test_transient_recovery_does_not_manufacture_candidate():
    assert signals.runtime([dict(kind='http_failure',recovered=True,recurrence=1)])==[]


def test_shadow_loop_does_not_invoke_builder_or_write_application(store):
    store.discover(proposal())
    report=improvement_loop.cycle(ROOT,store,None,None,None,None)
    assert report['status']=='SHADOW' and not report['implementation_started']
    assert report['plans'][0]['risk']=='L0'


def test_pipeline_state_machine_cannot_skip_owner_boundary(store):
    cid=store.discover(proposal())
    improvement_loop.record(store,cid,'DISCOVERED')
    with pytest.raises(ValueError):improvement_loop.record(store,cid,'MERGED')
    with pytest.raises(ValueError):store.event(cid,'PIPELINE',dict(stage='MERGED'))


def test_autonomy_remains_disabled_without_real_evidence(store):
    result=stage_control.report(ROOT,store)
    assert result['stage']=='SHADOW' and not result['eligible'] and not result['autonomous_implementation']
    assert 'current real deployment_agent certificate not PASS' in result['blockers']
    with pytest.raises(ValueError):stage_control.require(ROOT,store)


def test_delegated_build_policy_is_not_owner_pr_approval(owner_setup):
    store,client,human=owner_setup
    from dev_agent import build_policy
    policy=build_policy.approve(ROOT,store,['docs/*'],human=human,nonce='owner-build-policy-0001',rationale='Delegate documentation builds only',expires_at=time.time()+3600)
    assert build_policy.current(ROOT,store)==policy
    cid=store.discover(proposal())
    context=dict(todo='0825',head='a'*40,scope_hash=digest(['docs/note.md']),risk='L0',acceptance_hash='fixture',mode='SUPERVISED')
    store.transition(cid,'PLANNED')
    store.event(cid,'PLAN',dict(context=context,path='.todos/0825-fixture.md'))
    admitted=build_policy.admit(ROOT,store,cid)
    assert not admitted['grants_merge'] and not admitted['grants_deployment']
    assert store.get(cid)['state']=='APPROVED'
    assert not any(e['kind']=='OWNER_REVIEW' for e in store.get(cid)['events'])
    with pytest.raises(ValueError):build_policy.approve(ROOT,store,['docs/*'],human=human,nonce='owner-build-policy-0001',rationale='Replay',expires_at=time.time()+3600)


def test_owner_policy_cannot_admit_governance_or_financial_work(owner_setup):
    store,client,human=owner_setup
    from dev_agent import build_policy
    build_policy.approve(ROOT,store,['*'],human=human,nonce='owner-build-policy-0002',rationale='Broad pattern must still obey deterministic risk',expires_at=time.time()+3600)
    for name in ['AGENTS.md','dev_agent/runner.py','covered_call_v3.py','deployment_agent/service.py']:
        cid=store.discover(proposal(files=[name],problem='Review '+name))
        store.transition(cid,'PLANNED');store.event(cid,'PLAN',dict(context=dict(todo='0825',risk='L0',mode='SUPERVISED'),path='.todos/0825-fixture.md'))
        with pytest.raises(ValueError):build_policy.admit(ROOT,store,cid)


def test_stage_admission_needs_order_current_evidence_and_valid_caps(store,monkeypatch,complete_evidence):
    from dev_agent import owner_promotion
    config=complete_evidence['config'];config.update(autonomous_implementation=True,autonomy_stage='PR')
    assert not stage_control.report(ROOT,store)['eligible'] # Config cannot create owner authority.
    monkeypatch.setattr(owner_promotion,'authorization',lambda *a,**k:dict(status='PASS',authenticated=True,fixture_only=True))
    assert stage_control.require(ROOT,store)['eligible']
    config['daily_implementation_cap']=4
    with pytest.raises(ValueError):stage_control.require(ROOT,store)
    config['daily_implementation_cap']=1;config['autonomous_max_risk']='L3'
    with pytest.raises(ValueError):stage_control.require(ROOT,store)
    config['autonomous_max_risk']='L2';monkeypatch.setenv('DEV_AGENT_KILL_SWITCH','1')
    with pytest.raises(ValueError):stage_control.require(ROOT,store)


def test_builder_cannot_write_authority_or_deployment_paths(repo):
    from dev_agent.guard import WorkspaceGuard
    for path in ['.todos/0825-fake.md','AGENTS.md','config/development_agent.json','.github/workflows/test.yml','deployment_agent/service.py']:
        with pytest.raises(ValueError):WorkspaceGuard(repo,[path])


def test_decision_payload_rejects_ambiguous_json():
    from dev_agent.structured_json import loads
    for raw in ['{"decision":"NO","decision":"APPROVE"}','{"expires_at":NaN}','{"risk":Infinity}']:
        with pytest.raises(ValueError):loads(raw)


def test_synthetic_merge_event_cannot_be_forged(store):
    with pytest.raises(ValueError):store.event(None,'MERGE',dict(merge_sha='a'*40))


@pytest.mark.parametrize('path,content,risk',[('docs/note.md','Corrected documented operator detail\n','L0'),('tests/test_added_case.py','def test_added(): assert True\n','L1'),('static/pilot.css','body { color: navy; }\n','L2')])
def test_supervised_policy_journey_reaches_exact_head_pr_fixture(repo,owner_setup,monkeypatch,path,content,risk):
    from dev_agent import build_policy,certification,operations,discovery
    from dev_agent.runner import ContainerValidator
    from dev_agent.providers import ReplayProvider
    from test_development_agent import commit
    from development_fixtures import protection_observation
    store,_,human=owner_setup
    config=json.loads((repo/'config/development_agent.json').read_text());config.update(supervised_loop_enabled=True,supervised_publish_pr=True)
    (repo/'config/development_agent.json').write_text(json.dumps(config))
    (repo/'.gitignore').write_text('.todos/.allocation.lock\n')
    if path.startswith('static/'):(repo/'static').mkdir();(repo/path).write_text('body { color: black; }\n')
    (repo/'.todos/done').mkdir(parents=True)
    for n in range(816,822):(repo/f'.todos/done/{n:04d}-accepted-fixture.md').write_text(f'- **ID:** {n:04d}\n- **Status:** done\n- **Depends:** none\n')
    commit(repo)
    monkeypatch.setattr(certification,'harness_hash',lambda root:'trusted-fixture-harness')
    monkeypatch.setattr(build_policy,'harness_hash',lambda root:'trusted-fixture-harness')
    monkeypatch.setattr(certification,'technical_current',lambda *a,**k:True)
    monkeypatch.setattr(operations,'certificates',lambda store:[dict(evidence=dict(snapshot=dict(status='PASS',backup_timestamp=time.time()-1)))])
    build_policy.approve(repo,store,['docs/*','tests/*','static/*'],human=human,nonce='owner-delegated-test-0001',rationale='Synthetic bounded operator policy',expires_at=time.time()+3600)
    cid=store.discover(proposal(files=[path],problem='Observed missing detail: '+path,focused_tests=['tests/test_oracle.py']))
    validator=ContainerValidator('fixture@sha256:'+'a'*64)
    validator.run=lambda root,name,command:dict(name=name,command=command,exit_code=0,status='PASS',artifact_integrity=dict(status='PASS',fixture_only=True),inventory=dict(total=1,passed=1,failures=[],skipped=[]))
    class Client:
        repository='owner/repo';published=None
        def protections(self):return protection_observation()
        def publish(self,root,branch,head,**kwargs):self.published=(branch,head)
        def handoff(self,branch,title,body,draft):return dict(number=1,url='https://github.com/owner/repo/pull/1')
        def pr_identity(self,number):return dict(number=number,headRefName=self.published[0],headRefOid=self.published[1],baseRefName='main',headRepository=dict(nameWithOwner=self.repository),isDraft=False)
    result=improvement_loop.cycle(repo,store,ReplayProvider([dict(actions=[dict(type='write',path=path,content=content)])]),ReplayProvider([dict(disposition='PASS',findings=[]),dict(disposition='PASS',findings=[])]),validator,Client())
    assert result['status']=='AWAITING_OWNER',result
    assert not result['grants_merge'] and not result['grants_deployment']
    assert store.get(cid)['state']=='PR_OPEN'
    assert not operations.operational_runs(ROOT,store)['qualifying']
    assert discovery.git(repo,'status','--porcelain')==''


def test_activation_only_change_preserves_harness_but_safety_change_invalidates(monkeypatch):
    from dev_agent.certification import harness_hash
    before=harness_hash(ROOT);original=Path.read_text;config=json.loads((ROOT/'config/development_agent.json').read_text())
    monkeypatch.setattr(Path,'read_text',lambda p,*a,**k:json.dumps(config) if p==ROOT/'config/development_agent.json' else original(p,*a,**k))
    config.update(autonomous_implementation=True,autonomy_stage='PR',supervised_loop_enabled=True,supervised_publish_pr=True)
    assert harness_hash(ROOT)==before
    config['daily_implementation_cap']=2
    assert harness_hash(ROOT)!=before


def test_new_owner_no_revokes_old_ok_without_waiting_for_ingestion(owner_setup):
    store,client,_=owner_setup;first=owner_comment(client);second=copy.deepcopy(first);second['id']=124;second['html_url']='https://github.com/owner/repo/pull/1#issuecomment-124'
    payload=json.loads(second['body'][len(github_owner.HEADER):]);payload.update(decision='REQUEST_CHANGES',nonce='explicit-owner-new-no-0001');second['body']=github_owner.HEADER+json.dumps(payload)
    objects=[first];original=client.read
    client.read=lambda endpoint:first if '/issues/comments/123' in endpoint else second if '/issues/comments/124' in endpoint else objects if '/issues/1/comments?' in endpoint else original(endpoint)
    github_owner.ingest(store,client,123)
    from dev_agent.owner_review import require
    assert require(store,client,1)['status']=='APPROVE'
    objects.append(second)
    with pytest.raises(ValueError):require(store,client,1)
    github_owner.ingest(store,client,124)
    with pytest.raises(ValueError):require(store,client,1)


def test_autonomy_configuration_requires_l5_execution_authority():
    from dev_agent.policy import classify
    assert classify(['config/development_agent.json'])['risk']=='L5'


def test_software_metrics_never_infer_user_acceptance_or_use_financial_pnl(store):
    from dev_agent.software_metrics import summary
    store.discover(proposal())
    value=summary(store)
    assert value['user_acceptance'] is None and not value['investment_performance_used'] and value['authority_effect']=='NONE'
    assert value['candidate_pr_rate']==0


def test_missing_foundation_acceptance_blocks_supervised_implementation(repo):
    with pytest.raises(ValueError):improvement_loop.require_completed(repo)


CONNECTOR_APP=dict(id=1144995,slug='chatgpt-codex-connector',node_id='A_fixture',name='ChatGPT Codex Connector',owner=dict(login='openai',type='Organization'))


def allow_connector(monkeypatch):
    import os
    bindings=json.loads(os.environ['DEV_AGENT_OWNER_BINDINGS'])
    bindings['allowed_github_apps']=[dict(id=1144995,slug='chatgpt-codex-connector')]
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(bindings))


@pytest.mark.parametrize('decision',['APPROVE','REQUEST_CHANGES','DEFER'])
def test_real_shape_connector_owner_review_requires_explicit_allowlist(owner_setup,monkeypatch,decision):
    store,client,_=owner_setup;comment=owner_comment(client,decision)
    comment['performed_via_github_app']=dict(CONNECTOR_APP);original=client.read
    client.read=lambda endpoint:comment if '/issues/comments/' in endpoint else [comment] if '/issues/1/comments?' in endpoint else original(endpoint)
    with pytest.raises(ValueError):github_owner.ingest(store,client,123)
    allow_connector(monkeypatch)
    first=github_owner.ingest(store,client,123)
    assert github_owner.ingest(store,client,123)==first
    from dev_agent.owner_review import state
    assert state(store,client,1)['status']==decision
    client.head='f'*40
    with pytest.raises(ValueError):github_owner.ingest(store,client,123)


@pytest.mark.parametrize('mutation',[
    {'performed_via_github_app':dict(CONNECTOR_APP,id=99)},
    {'performed_via_github_app':dict(CONNECTOR_APP,slug='other-app')},
    {'performed_via_github_app':dict(CONNECTOR_APP,id='1144995')},
    {'user':dict(id=2,login='agent',type='User')},
    {'user':dict(id=1,login='owner',type='Bot')},
    {'updated_at':'edited'},
])
def test_connector_allowlist_never_bypasses_owner_review_guards(owner_setup,monkeypatch,mutation):
    store,client,_=owner_setup;allow_connector(monkeypatch)
    comment=dict(owner_comment(client),performed_via_github_app=dict(CONNECTOR_APP));comment.update(mutation);original=client.read
    client.read=lambda endpoint:comment if '/issues/comments/' in endpoint else [comment] if '/issues/1/comments?' in endpoint else original(endpoint)
    with pytest.raises(ValueError):github_owner.ingest(store,client,123)


@pytest.mark.parametrize('ci_variable',['GITHUB_ACTIONS','CI'])
def test_aggregate_leaves_ci_prior_authority_to_event_checker(monkeypatch,ci_variable):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False);monkeypatch.delenv('CI',raising=False)
    assert aggregate.cc_command('python','a'*40)==['python','scripts/check_cc_contract.py','--prior-ref','a'*40]
    monkeypatch.setenv(ci_variable,'true')
    assert aggregate.cc_command('python','attacker-prior')==['python','scripts/check_cc_contract.py']

from test_pr13_evidence_integrity import complete_evidence
