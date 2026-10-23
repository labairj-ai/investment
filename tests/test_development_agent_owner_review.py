"""Owner authority tests use disposable ledger and synthetic authenticated boundary."""
import copy
import json
from email.message import Message
from types import SimpleNamespace
import pytest
from dev_agent import owner_review as owner
from dev_agent.identity import HumanIdentity,_PROOF,dashboard_identity
from dev_agent.store import Store
from dev_agent.solo_protection import verify


class Client:
    repository='owner/repo'
    head='a'*40
    author='owner'
    files=[dict(filename='docs/note.md',patch='+Text')]
    def read(self,endpoint):
        if '/comments?' in endpoint:return []
        if '/pulls/' in endpoint:return dict(merged=True,head=dict(sha=self.head),merge_commit_sha='c'*40,auto_merge=None,merged_by=dict(id=1,login='owner',type='User'))
        return dict(full_name=self.repository,owner=dict(login='owner',id=1,type='User'))
    def protections(self):
        from development_fixtures import protection_observation
        return protection_observation(repository=self.repository)
    def read_all(self,endpoint):return self.files
    def pr_identity(self,number):return dict(number=number,baseRefName='main',state='OPEN',headRefOid=self.head,headRepository=dict(nameWithOwner=self.repository),author=dict(login=self.author),reviewDecision='APPROVED')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    binding=dict(repository='owner/repo',owner_login='owner',owner_id=1,operators={'os-interactive-cli':['human-owner'],'tailscale-serve':['owner@example.com']})
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(binding))
    monkeypatch.setenv('DEV_AGENT_OPERATORS','owner@example.com')
    store=Store(tmp_path/'development-control.sqlite3');store.migrate()
    return store,Client(),HumanIdentity('human-owner','os-interactive-cli',_PROOF)


def approve(setup,*,risk='L0',nonce='deliberate-owner-review-0001',**kwargs):
    store,client,human=setup
    return owner.attest(store,client,owner.context(client,1,risk=risk),'APPROVE',nonce,'Reviewed complete exact-head diff',human=human,**kwargs)


def test_owner_authorship_and_green_ci_never_approve(setup):
    store,client,_=setup
    assert owner.state(store,client,1)['status']=='MISSING'
    with pytest.raises(ValueError):owner.require(store,client,1)
    approve(setup)
    assert owner.require(store,client,1)['status']=='APPROVE'


def test_stale_head_and_replay_rejected(setup):
    store,client,_=setup
    approve(setup)
    with pytest.raises(ValueError,match='replayed'):approve(setup)
    client.head='b'*40
    assert owner.state(store,client,1)['status']=='STALE'
    with pytest.raises(ValueError):owner.require(store,client,1)


@pytest.mark.parametrize('risk,financial,execution,allowed',[('L3',False,False,True),('L4',False,False,False),('L4',True,False,True),('L5',True,False,False),('L5',True,True,True)])
def test_risk_domain_acknowledgments(setup,risk,financial,execution,allowed):
    if allowed:approve(setup,risk=risk,financial_ack=financial,execution_ack=execution)
    else:
        with pytest.raises(ValueError):approve(setup,risk=risk,financial_ack=financial,execution_ack=execution)


def test_financial_diff_cannot_claim_documentation_risk(setup):
    setup[1].files=[dict(filename='covered_call_v3.py',patch='+changed')]
    with pytest.raises(ValueError):approve(setup,risk='L0')


def test_model_or_shared_token_identity_cannot_attest(setup):
    store,client,_=setup
    for human in [None,dict(actor='owner'),HumanIdentity("shared-token", "authenticated-dashboard", _PROOF),HumanIdentity('agent','os-interactive-cli',_PROOF)]:
        with pytest.raises(ValueError):owner.attest(store,client,owner.context(client,1,risk='L0'),'APPROVE','untrusted-identity-0001','rationale',human=human)
    with pytest.raises(ValueError):store.event(None,'OWNER_REVIEW',{},'forged')


def test_defer_and_request_changes_revoke_approval(setup):
    store,client,human=setup
    approve(setup)
    for decision in ['DEFER','REQUEST_CHANGES']:
        owner.attest(store,client,owner.context(client,1,risk='L0'),decision,'owner-decision-'+decision.replace('_','-'),'',human=human)
        assert owner.state(store,client,1)['status']==decision
        with pytest.raises(ValueError):owner.require(store,client,1)


def test_proxy_requires_unique_identity_and_loopback_listener(setup,monkeypatch):
    monkeypatch.setenv('DEV_AGENT_IDENTITY_SOURCE','tailscale-serve')
    headers=Message();headers['Tailscale-User-Login']='owner@example.com'
    handler=SimpleNamespace(headers=headers,client_address=('127.0.0.1',1000),server=SimpleNamespace(server_address=('127.0.0.1',8080)))
    assert owner.owner_identity(handler).actor=='owner@example.com'
    handler.server.server_address=('0.0.0.0',8080)
    with pytest.raises(ValueError):owner.owner_identity(handler)
    handler.server.server_address=('127.0.0.1',8080);headers['Tailscale-User-Login']='owner@example.com'
    with pytest.raises(ValueError):owner.owner_identity(handler)


def rules_fixture():
    baseline=dict(id=10,enforcement='active',bypass_actors=[],rules=[dict(type='pull_request',parameters=dict(required_approving_review_count=0,required_review_thread_resolution=True,require_last_push_approval=False)),dict(type='required_status_checks',parameters=dict(strict_required_status_checks_policy=True,required_status_checks=[dict(context='test'),dict(context='owner-review',integration_id=99)])),dict(type='deletion'),dict(type='non_fast_forward')])
    updates=dict(id=11,enforcement='active',bypass_actors=[dict(actor_id=5,actor_type='RepositoryRole',bypass_mode='pull_request')],rules=[dict(type='update')])
    active=[dict(rule,ruleset_id=r['id']) for r in [baseline,updates] for rule in r['rules']]
    return active,[baseline,updates]


def test_solo_protection_separates_owner_authority_from_agent(setup):
    active,rules=rules_fixture()
    args=dict(administrators=[dict(id=1,login='owner')],owner_check_app_id=99)
    repo=dict(full_name='owner/repo',owner=dict(login='owner',id=1,type='User'),permissions=dict(admin=False,maintain=False,push=True,pull=True))
    assert verify(active,rules,dict(id=2,login='agent'),repo,**args)['status']=='PASS'
    assert verify(active,rules,dict(id=1,login='owner'),repo,**args)['status']=='FAIL'
    rules[0]['bypass_actors']=[dict(actor_id=5,actor_type='RepositoryRole',bypass_mode='always')]
    assert verify(active,rules,dict(id=2,login='agent'),repo,**args)['status']=='FAIL'


def test_required_owner_check_cannot_be_spoofed_by_another_app(setup):
    active,rules=rules_fixture()
    result=verify(active,rules,dict(id=2,login='agent'),dict(full_name='owner/repo',owner=dict(login='owner',id=1,type='User'),permissions=dict(admin=False,maintain=False,push=True,pull=True)),administrators=[dict(id=1,login='owner')],owner_check_app_id=100)
    assert result['status']=='FAIL'


def test_owner_gate_requires_latest_exact_head_ci(setup):
    from scripts.check_owner_review import check
    store,client,_=setup
    approve(setup)
    original=client.read
    runs=[dict(id=1,name='test',head_sha=client.head,status='completed',conclusion='success',html_url='https://github.com/owner/repo/actions/runs/1')]
    client.read=lambda endpoint:dict(total_count=len(runs),check_runs=runs) if 'check-runs' in endpoint else original(endpoint)
    assert check(store,client,1,client.head)['status']=='PASS'
    runs.append(dict(runs[0],id=2,conclusion='failure'))
    with pytest.raises(ValueError):check(store,client,1,client.head)
    with pytest.raises(ValueError):check(store,client,1,'b'*40)


def test_agent_merge_evidence_cannot_replace_owner_review(setup):
    from dev_agent.github import record_merge
    store,client,_=setup
    cid=store.discover(dict(source='user',title='fixture',problem='fixture issue',evidence=['fixture'],outcome='fixture result',files=['docs/note.md'],category='DOCUMENT'))
    store.event(cid,'PR',dict(result=dict(number=1,url='https://github.com/owner/repo/pull/1'),verified=dict(headRefName='agent/0001/fixture'),head=client.head))
    from development_fixtures import start_protection
    start_protection(store,cid,client)
    original=client.pr_identity
    client.pr_identity=lambda number:dict(original(number),headRefName='agent/0001/fixture',headRepositoryOwner=dict(login='owner'),isDraft=False,state='MERGED',mergeCommit=dict(oid='c'*40))
    with pytest.raises(ValueError,match='owner approval'):record_merge(store,cid,client)
    approve(setup)
    assert record_merge(store,cid,client)['merge_sha']=='c'*40


def test_handoff_requires_owner_merge_and_actual_main_ancestry(setup):
    from scripts.pr6_owner_handoff import handoff
    store,client,human=setup
    original_read=client.read
    client.read=lambda endpoint:dict(total_count=1,check_runs=[dict(id=1,name='test',head_sha=client.head,status='completed',conclusion='success')]) if 'check-runs' in endpoint else dict(status='ahead') if '/compare/' in endpoint else original_read(endpoint)
    owner.attest(store,client,owner.context(client,6,risk='L0'),'APPROVE','owner-reviewed-pr-six-0001','Reviewed',human=human)
    assert handoff(store,client)['status']=='READY_FOR_HUMAN_MERGE'
    original_pr=client.pr_identity
    client.pr_identity=lambda number:dict(original_pr(number),state='MERGED',mergeCommit=dict(oid='c'*40))
    result=handoff(store,client)
    assert result['required_deploy_sha']=='c'*40 and not result['deployed']
    previous=client.read
    client.read=lambda endpoint:dict(status='diverged') if '/compare/' in endpoint else previous(endpoint)
    with pytest.raises(ValueError):handoff(store,client)


def test_http_dispatch_routes_owner_review_without_importing_production(monkeypatch):
    import ast
    from pathlib import Path
    from urllib.parse import urlparse
    from dev_agent import dashboard
    tree=ast.parse((Path(__file__).resolve().parents[1]/'serve.py').read_text())
    handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
    method=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name=='do_POST')
    namespace={'urlparse':urlparse}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<isolated HTTP dispatcher>','exec'),namespace)
    monkeypatch.setattr(dashboard,'handle',lambda handler,path,mutation=False:(path,mutation))
    assert namespace['do_POST'](SimpleNamespace(path='/api/development-agent/owner-review'))==('/api/development-agent/owner-review',True)


@pytest.mark.parametrize('mutation',[dict(auto_merge={'enabled_by':'agent'}),dict(merged_by=dict(id=2,login='agent',type='Bot')),dict(merge_commit_sha='d'*40),dict(head=dict(sha='d'*40))])
def test_automated_or_wrong_identity_merge_is_rejected(setup,mutation):
    _,client,_=setup
    original=client.read
    client.read=lambda endpoint:dict(original(endpoint),**mutation) if '/pulls/' in endpoint else original(endpoint)
    with pytest.raises(ValueError):owner.verify_merge_actor(client,1,client.head,'c'*40)
