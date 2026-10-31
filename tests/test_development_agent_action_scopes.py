"""Action separation with synthetic GitHub, isolated ledgers and frozen old code."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from dev_agent import github_owner as g,owner_review as o
from deployment_agent.admission import authorize
from deployment_agent.poller import pending
from deployment_agent.service import deploy
from test_development_agent_owner_review import setup as owner_setup
from test_deployment_agent import authorized_owner,FakeExecutor,authorization,scoped_transaction_policy


def replace(store,client,obj,data,**changes):
    data.update(changes);obj['body']=g.ACTION_HEADER+json.dumps(data)
    return g.ingest(store,client,obj['id'])


def test_merge_only_exact_head_merges_without_deployment(authorized_owner):
    from owner_gateway.core import advance_approved
    store,client,obj,data=authorized_owner
    data['nonce']='fresh-merge-only-00001';replace(store,client,obj,data,action='MERGE_ONLY')
    original=client.read;identity=client.pr_identity;writes=[]
    client.read=lambda ep:dict(login='owner',id=1,type='User') if ep=='user' else original(ep)
    client.pr_identity=lambda n:dict(identity(n),state='OPEN',isDraft=False)
    client.write=lambda ep,payload,method:writes.append((ep,payload,method)) or dict(merged=True,sha='c'*40)
    result=advance_approved(store,client,1)
    assert result['merge_sha']=='c'*40 and result['deployment_authorized'] is False
    assert writes==[('repos/owner/repo/pulls/1/merge',dict(sha=data['head'],merge_method='merge',_pr=1),'PUT')]
    with pytest.raises(ValueError,match='consumed'):advance_approved(store,client,1)
    assert len(writes)==1
    with pytest.raises(ValueError):authorize(store,client,999)


@pytest.mark.parametrize('action',['MERGE_ONLY',None,'UNKNOWN',[],True])
def test_deployment_scope_cannot_be_missing_or_reinterpreted(authorized_owner,action,tmp_path):
    store,client,obj,data=authorized_owner
    changed=dict(data,action=action);obj['body']=g.ACTION_HEADER+json.dumps(changed)
    with pytest.raises((ValueError,TypeError)):authorize(store,client,999)
    assert pending(client,tmp_path)==[]


@pytest.mark.parametrize('field,value',[
 ('head','d'*40),('repository','other/repo'),('pr',2),('owner_id',2),('owner_login','agent'),
 ('financial_ack',False),('execution_ack',False),('risk','L4'),('source_head','e'*40),('policy_hash','e'*64),
 ('issued_at',1),('issued_at',True),('nonce','short'),('action','UNKNOWN')])
def test_scoped_owner_attacks_fail_closed(authorized_owner,field,value):
    store,client,obj,data=authorized_owner
    obj['body']=g.ACTION_HEADER+json.dumps(dict(data,**{field:value}))
    with pytest.raises((ValueError,TypeError)):g.ingest(store,client,999)
    with pytest.raises((ValueError,TypeError)):o.require_action(store,client,1,'MERGE')


@pytest.mark.parametrize('attack',['missing','legacy_header','legacy_object','duplicate','edited','wrong_owner','superseded','scope_substitution','timestamp_changed'])
def test_ambiguous_or_replaced_approval_never_authorizes_action(authorized_owner,attack):
    store,client,obj,data=authorized_owner;original=client.read
    if attack=='missing':data.pop('action');obj['body']=g.ACTION_HEADER+json.dumps(data)
    if attack=='legacy_header':obj['body']=g.HEADER+json.dumps(data)
    if attack=='legacy_object':obj['body']=g.HEADER+json.dumps({k:v for k,v in data.items() if k in g.FIELDS})
    if attack=='duplicate':obj['body']=g.ACTION_HEADER+json.dumps(data)[:-1]+',"action":"MERGE_ONLY"}'
    if attack=='edited':obj['updated_at']='2026-01-01T00:00:00Z'
    if attack=='wrong_owner':obj['user']=dict(id=2,login='agent',type='User')
    if attack=='scope_substitution':obj['body']=g.ACTION_HEADER+json.dumps(dict(data,action='MERGE_ONLY'))
    if attack=='timestamp_changed':obj['created_at']=obj['updated_at']='2000-01-01T00:00:00Z'
    if attack=='superseded':
        newer=copy.deepcopy(obj);newer['id']=1000;newer['body']=g.ACTION_HEADER+json.dumps(dict(data,decision='DEFER',nonce='newer-defer-nonce-0001'))
        client.read=lambda ep:[obj,newer] if '/issues/1/comments?' in ep else original(ep)
    with pytest.raises(ValueError):o.require_action(store,client,1,'MERGE')


def test_cross_object_nonce_replay_rejected(authorized_owner):
    store,client,obj,data=authorized_owner;old=client.read
    other=copy.deepcopy(obj);other.update(id=1000,html_url='https://github.com/owner/repo/pull/1#issuecomment-1000')
    client.read=lambda ep:other if '/issues/comments/1000' in ep else [other] if '/issues/1/comments?' in ep else old(ep)
    with pytest.raises(ValueError,match='nonce replay'):g.ingest(store,client,1000)


@pytest.mark.parametrize('stage',['before_merge','after_merge','ci_pending','ci_pass'])
def test_frozen_deployed_poller_never_discovers_v3_merge_only(authorized_owner,tmp_path,monkeypatch,stage):
    store,client,obj,data=authorized_owner
    data['nonce']='new-frozen-poller-nonce-0001';replace(store,client,obj,data,action='MERGE_ONLY')
    path=Path(__file__).parent/'frozen/legacy_deployment_poller_a27.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='0d00fb1d714da011275c0ef590bfa31104d7b41b11f406b3eb33f9e88e601e08'
    spec=importlib.util.spec_from_file_location('deployment_agent._frozen_a27',path)
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    # Prove header non-discovery, not a denial by any newly updated verifier.
    import deployment_agent.admission as admission
    monkeypatch.setattr(admission,'authorize',lambda *a,**k:pytest.fail('legacy poller discovered merge-only object'))
    monkeypatch.setattr(g,'verified_object',lambda *a:pytest.fail('legacy header admitted new object'))
    original=client.read;identity=client.pr_identity
    def read(ep):
        if '/check-runs' in ep:
            sha=data['head'] if stage=='before_merge' else 'c'*40
            return dict(total_count=1,check_runs=[dict(id=1,name='test',head_sha=sha,status='in_progress' if stage=='ci_pending' else 'completed',conclusion=None if stage=='ci_pending' else 'success')])
        if '/issues/comments?' in ep:return [copy.deepcopy(obj)]
        if '/pulls?per_page=100' in ep:return [dict(number=1,merge_commit_sha='c'*40)]
        return original(ep)
    client.read=read
    client.read_all=lambda ep:[copy.deepcopy(obj)]
    client.pr_identity=lambda n:dict(identity(n),state='OPEN' if stage=='before_merge' else 'MERGED')
    before={p.name for p in tmp_path.iterdir()}
    # Concurrent repeated polls exercise both recent-comment and current-main
    # rediscovery paths. The old verifier/admission must never even be reached.
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _:legacy.pending(client,tmp_path),range(12)))==[[]]*12
    assert {p.name for p in tmp_path.iterdir()}==before


def test_new_poller_never_queues_merge_only_after_merge_or_ci(authorized_owner,tmp_path):
    store,client,obj,data=authorized_owner;data['nonce']='new-scoped-only-0001';replace(store,client,obj,data,action='MERGE_ONLY')
    old=client.read;client.read=lambda ep:[obj] if '/issues/comments?' in ep else [dict(number=1,merge_commit_sha='c'*40)] if '/pulls?per_page=100' in ep else old(ep)
    read_all=client.read_all;client.read_all=lambda ep:[obj] if '/comments' in ep else read_all(ep)
    for _ in range(4):assert pending(client,tmp_path)==[]
    with pytest.raises(ValueError,match='MERGE_ONLY'):authorize(store,client,999)


@pytest.mark.parametrize('tamper',['both','top','embedded','missing','identity','legacy'])
def test_executor_independently_rejects_bad_scope_before_any_mutation(owner_setup,tmp_path,tamper):
    executor=FakeExecutor(tmp_path);auth=authorization()
    if tamper in {'both','top'}:auth['action']='MERGE_ONLY'
    if tamper in {'both','embedded'}:auth['action_authorization']['action']='MERGE_ONLY'
    if tamper=='missing':auth['action_authorization'].pop('action')
    if tamper=='identity':auth['head']='d'*40
    if tamper=='legacy':auth.pop('authorization_contract')
    with pytest.raises(ValueError):deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    assert not executor.operations and not executor.receipts.exists()


def test_policy_must_explicitly_support_deployment(authorized_owner,monkeypatch):
    store,client,obj,data=authorized_owner
    binding=o.policy();binding['authorized_actions']=['MERGE_ONLY'];monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(binding))
    with pytest.raises(ValueError):authorize(store,client,999)


def test_legacy_approval_remains_evidence_but_is_not_merge_or_deploy_authority(owner_setup):
    from test_development_agent_owner_review import approve
    from scripts.check_owner_review import check
    store,client,_=owner_setup;approve(owner_setup)
    assert o.require(store,client,1)['status']=='APPROVE'
    with pytest.raises(ValueError):check(store,client,1,client.head)


@pytest.fixture
def bootstrap(owner_setup,monkeypatch):
    from owner_gateway import scout_merge_only as b
    store,client,_=owner_setup
    bindings=o.policy();bindings.update(repository=b.REPOSITORY,authorized_actions=['MERGE_ONLY'])
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(bindings))
    client.repository=b.REPOSITORY;client.head=b.HEAD
    state=dict(merged=False,main=b.BASE,ci=True,actor='owner',mergeable=True)
    objects=[];writes=[]
    def identity(n):return dict(number=n,baseRefName='main',state='MERGED' if state['merged'] else 'OPEN',headRefOid=client.head,headRepository=dict(nameWithOwner=client.repository),isDraft=False,mergeCommit=dict(oid='c'*40) if state['merged'] else None)
    def read(ep):
        if ep=='user':return dict(login=state['actor'],id=1,type='User')
        if '/issues/comments/' in ep:return next(x for x in objects if str(x['id'])==ep.rsplit('/',1)[1])
        if '/comments?' in ep:return objects
        if '/branches/main' in ep:return dict(commit=dict(sha=state['main']))
        if '/check-runs' in ep:return dict(total_count=2,check_runs=[dict(id=i,name=n,head_sha=b.HEAD,status='completed',conclusion='success' if state['ci'] else 'failure') for i,n in enumerate(('native-systemd255','test'),1)])
        if '/pulls/34' in ep:return dict(base=dict(sha=b.BASE),mergeable=state['mergeable'],merged=state['merged'],head=dict(sha=b.HEAD),merge_commit_sha='c'*40,auto_merge=None,merged_by=dict(id=1,login='owner',type='User'))
        return dict(full_name=client.repository,owner=dict(login='owner',id=1,type='User'))
    def write(ep,payload,method):
        from datetime import datetime,timezone
        writes.append((ep,payload,method))
        if method=='POST':
            stamp=datetime.now(timezone.utc).isoformat()
            obj=dict(id=123,user=dict(id=1,login='owner',type='User'),performed_via_github_app=None,body=payload['body'],created_at=stamp,updated_at=stamp,issue_url='https://api.github.com/repos/'+client.repository+'/issues/34',html_url='https://github.com/'+client.repository+'/pull/34#issuecomment-123')
            objects.append(obj);return obj
        assert method=='PUT' and payload==dict(sha=b.HEAD,merge_method='merge',_pr=34)
        state.update(merged=True,main='c'*40);return dict(merged=True,sha='c'*40)
    original_all=client.read_all
    client.read_all=lambda ep:objects if ep.endswith('/comments') else original_all(ep)
    client.read=read;client.write=write;client.pr_identity=identity
    return store,client,state,writes,b


def test_isolated_bootstrap_only_issues_v3_and_exact_immediate_merge(bootstrap):
    store,client,state,writes,b=bootstrap
    reviewed=b.inspect(client)
    result=b.merge_once(store,client,reviewed,deliberate_action='MERGE_ONLY',nonce='fresh-authenticated-owner-0001',rationale='Merge only; no production authority',financial_ack=True,execution_ack=True)
    assert result['merge_sha']=='c'*40 and result['transition_authorized'] is result['deployment_authorized'] is False
    assert [w[2] for w in writes]==['POST','PUT']
    assert writes[0][1]['body'].startswith(g.ACTION_HEADER)
    assert json.loads(writes[0][1]['body'][len(g.ACTION_HEADER):])['action']=='MERGE_ONLY'
    with pytest.raises(ValueError):b.merge_once(store,client,reviewed,deliberate_action='MERGE_ONLY',nonce='fresh-authenticated-owner-0001',rationale='replay',financial_ack=True,execution_ack=True)
    assert len(writes)==2


@pytest.mark.parametrize('failure',['head','main','ci','actor','mergeable','action','ack'])
def test_bootstrap_rejects_before_any_write(bootstrap,failure):
    store,client,state,writes,b=bootstrap;reviewed=b.inspect(client)
    if failure=='head':client.head='d'*40
    if failure=='main':state['main']='d'*40
    if failure=='ci':state['ci']=False
    if failure=='actor':state['actor']='agent'
    if failure=='mergeable':state['mergeable']=False
    with pytest.raises(ValueError):b.merge_once(store,client,reviewed,deliberate_action='MERGE_AND_DEPLOY' if failure=='action' else 'MERGE_ONLY',nonce='fresh-authenticated-owner-0001',rationale='Merge only',financial_ack=failure!='ack',execution_ack=True)
    assert not writes


def test_bootstrap_refuses_prior_generic_approval_even_if_v3_would_supersede_it(bootstrap):
    store,client,state,writes,b=bootstrap
    original=client.read_all
    client.read_all=lambda ep:[dict(body=g.HEADER+'{}')] if ep.endswith('/comments') else original(ep)
    with pytest.raises(ValueError,match='legacy owner object'):b.inspect(client)
    assert writes==[]


def test_bootstrap_detects_concurrent_legacy_review_after_issuance(bootstrap):
    store,client,state,writes,b=bootstrap;reviewed=b.inspect(client);original=client.read_all
    client.read_all=lambda ep:([dict(body=g.HEADER+'{}')] if writes else []) if ep=='repos/'+b.REPOSITORY+'/issues/34/comments' else original(ep)
    with pytest.raises(ValueError,match='legacy owner object'):
        b.merge_once(store,client,reviewed,deliberate_action='MERGE_ONLY',nonce='concurrent-owner-scope-0001',rationale='Merge only',financial_ack=True,execution_ack=True)
    assert len(writes)==1 and writes[0][2]=='POST'


def test_old_verifier_and_separate_scout_transition_cannot_consume_merge_only(authorized_owner):
    store,client,obj,data=authorized_owner;data['nonce']='new-transition-isolated-0001';replace(store,client,obj,data,action='MERGE_ONLY')
    path=Path(__file__).parent/'frozen/legacy_github_owner_a27.py'
    spec=importlib.util.spec_from_file_location('dev_agent._frozen_owner_a27',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    with pytest.raises(ValueError,match='versioned'):old.verified_object(client,999)
    # Execute the exact frozen PR34 verifier, without invoking any privileged
    # adapter, filesystem transaction, staging or production controller.
    path=Path(__file__).parent/'frozen/scout_epoch_authorization_1f25.py'
    def require(ok,message):
        if not ok:raise ValueError(message)
    ns=dict(require=require,SCOPE='scout-source-epoch-transition-once')
    exec(compile(path.read_text(),str(path),'exec'),ns)
    cap=dict(repository='owner/repo',owner_object='https://github.com/owner/repo/pull/1#issuecomment-999',reviewed_head=data['head'],nonce=data['nonce'],old_head='b'*40,target_head='c'*40)
    with pytest.raises(ValueError,match='upgrade scope'):ns['live_authorization'](cap,client)


def test_changed_controller_policy_revokes_existing_scoped_authority(authorized_owner,monkeypatch):
    store,client,obj,data=authorized_owner;binding=o.policy();binding['issuer_source_head']='e'*40
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(binding))
    with pytest.raises(ValueError):o.require_action(store,client,1,'MERGE')


def test_object_replacement_during_validation_is_rejected(authorized_owner):
    store,client,obj,data=authorized_owner;old=client.read;calls=[0]
    def read(ep):
        if '/issues/comments/999' in ep:
            calls[0]+=1
            return copy.deepcopy(obj) if calls[0]==1 else dict(obj,body=g.ACTION_HEADER+json.dumps(dict(data,action='MERGE_ONLY')))
        return old(ep)
    client.read=read
    with pytest.raises(ValueError,match='changed during'):g.verified_object(client,999)


@pytest.mark.parametrize('writer',['agent','owner'])
def test_actual_write_transport_owner_is_checked_before_mutation(owner_setup,monkeypatch,writer):
    from owner_gateway import core
    from types import SimpleNamespace
    store,reader,_=owner_setup;client=core.OwnerClient(reader);calls=[]
    def run(args,**kw):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(dict(type='User',login=writer,id=1 if writer=='owner' else 2)) if args==['gh','api','user'] else json.dumps(dict(merged=True,sha='c'*40)))
    monkeypatch.setattr(core.subprocess,'run',run)
    payload=dict(sha=reader.head,merge_method='merge',_pr=1)
    if writer=='agent':
        with pytest.raises(ValueError,match='actual GitHub write'):client.write('repos/owner/repo/pulls/1/merge',payload,'PUT')
        assert calls==[['gh','api','user']]
    else:
        assert client.write('repos/owner/repo/pulls/1/merge',payload,'PUT')['merged']
        assert calls[1][:4]==['gh','api','--method','PUT']


def test_merge_action_must_be_fresh_even_if_original_deployment_decision_stays_valid(authorized_owner):
    from datetime import datetime,timezone,timedelta
    from owner_gateway.core import advance_approved
    store,client,obj,data=authorized_owner
    stamp=datetime.now(timezone.utc)-timedelta(hours=2)
    data.update(issued_at=stamp.timestamp(),nonce='stale-merge-new-nonce-0001')
    obj.update(created_at=stamp.isoformat(),updated_at=stamp.isoformat())
    replace(store,client,obj,data)
    original=client.read;identity=client.pr_identity
    client.read=lambda ep:dict(login='owner',id=1,type='User') if ep=='user' else original(ep)
    client.pr_identity=lambda n:dict(identity(n),state='OPEN',isDraft=False)
    client.write=lambda *a:pytest.fail('expired merge action cannot write')
    with pytest.raises(ValueError,match='fresh merge action'):advance_approved(store,client,1)


def test_frozen_legacy_and_scout_verifiers_have_exact_reviewed_content():
    expected={'legacy_deployment_poller_a27.py': '0d00fb1d714da011275c0ef590bfa31104d7b41b11f406b3eb33f9e88e601e08', 'legacy_github_owner_a27.py': '7942ec78729f9e30237cda32e795a39b76ff7d325735fcf839e4e2da5e74d332', 'scout_epoch_authorization_1f25.py': 'cac3f8a707c75b0c0835ee8708bb172d6a8e6010f9e781025689fabeef211054'}
    for name,sha in expected.items():assert hashlib.sha256((Path(__file__).parent/'frozen'/name).read_bytes()).hexdigest()==sha


@pytest.mark.parametrize('scope',['MERGE_ONLY',None,'legacy'])
def test_interrupted_recovery_cannot_mutate_from_merge_only_or_unscoped_evidence(owner_setup,tmp_path,scope):
    from deployment_agent.service import recover
    from dev_agent.result_collector import write_final
    executor=FakeExecutor(tmp_path);executor.receipts.mkdir(mode=0o700)
    auth=authorization()
    if scope=='MERGE_ONLY':auth['action_authorization']['action']=auth['action']='MERGE_ONLY'
    if scope is None:auth['action_authorization'].pop('action')
    if scope=='legacy':auth={}
    write_final(executor.receipts,'pending',dict(prior_sha='a'*40,target='b'*40,authorization_id=123,protected=executor.protected(),scope=auth))
    with pytest.raises(ValueError):recover(executor,'https://github.com/owner/repo.git')
    assert executor.operations==[] and executor.sha=='a'*40


def test_duplicate_remote_nonce_is_rejected_without_a_local_ingestion_record(authorized_owner):
    store,client,obj,data=authorized_owner
    older=copy.deepcopy(obj);older['id']=998
    original=client.read_all
    client.read_all=lambda ep:[older,obj] if '/comments' in ep else original(ep)
    with pytest.raises(ValueError,match='nonce replay'):g.verified_object(client,999)


def test_remote_nonce_cannot_be_reissued_by_a_fresh_owner_ledger(authorized_owner):
    from owner_gateway.core import record_decision
    from dev_agent.store import Store
    store,client,obj,data=authorized_owner;original=client.read
    fresh=Store(store.path.parent/'fresh'/'development-control.sqlite3');fresh.migrate()
    client.read=lambda ep:dict(login='owner',id=1,type='User') if ep=='user' else original(ep)
    client.write=lambda *a:pytest.fail('remote replay must stop before issuance')
    with pytest.raises(ValueError,match='nonce replay'):
        record_decision(fresh,client,o.context(client,1,risk='L5'),decision='APPROVE',nonce=data['nonce'],rationale='replay',action='MERGE_ONLY',financial_ack=True,execution_ack=True)


def test_executor_rejects_upstream_relabeling_even_when_both_action_flags_say_deploy(owner_setup,tmp_path):
    executor=FakeExecutor(tmp_path);auth=authorization()
    auth['owner_review']['action_binding']['action']='MERGE_ONLY'
    # Faulty upstream asserts deployment in both outer and embedded fields. The
    # independently retained authenticated review still binds MERGE_ONLY.
    assert auth['action']==auth['action_authorization']['action']=='MERGE_AND_DEPLOY'
    with pytest.raises(ValueError,match='authenticated owner review'):
        deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    assert executor.operations==[] and not executor.receipts.exists()


def test_executor_rejects_owner_object_substitution(owner_setup,tmp_path):
    executor=FakeExecutor(tmp_path);auth=authorization()
    auth['owner_review']['origin']['id']=124
    with pytest.raises(ValueError,match='owner object differs'):
        deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    assert executor.operations==[] and not executor.receipts.exists()
