"""Prospective evidence/authority security tests on disposable fixtures only."""
import copy
import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from test_development_agent import repo, store, proposal, approved, commit, protection, run_fixture, write_action
from dev_agent import evidence, validation, certification, operations, github, snapshot, readiness
from dev_agent.runner import ContainerValidator
from dev_agent.store import digest
from dev_agent.identity import dashboard_identity
from dev_agent.discovery import git, plan, refresh_plan

ROOT=Path(__file__).resolve().parents[1]
KEY=b'fixture-signing-material-not-operational-0000'


def make_trusted_proof(root,store,cid):
    """Exercise the trusted event/seal API; process output is a test fixture only."""
    candidate=store.get(cid)
    prior=[e['payload'] for e in candidate['events'] if e['kind']=='ITERATION'][-1]
    store.event(cid,'ITERATION',dict(prior,fixture_only=False))
    validator=ContainerValidator('fixture@sha256:'+'a'*64)
    validator.run=lambda root,name,command:dict(name=name,command=command,exit_code=0,status='PASS',inventory=dict(total=2,passed=2,failures=[],skipped=[]))
    validation.execute(root,store,cid,validator)
    return evidence.seal(root,store,cid)


def built(repo,store,tmp_path):
    result,cid,root=run_fixture(repo,store,tmp_path,[write_action('Reviewed change\n')],[dict(disposition='PASS',findings=[])])
    commit(root)
    prior=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='ITERATION'][-1]
    store.event(cid,'ITERATION',dict(prior,fixture_only=False))
    return cid,root


def technical(root,now=None):
    data=dict(version='harness-canary-2',kind='TECHNICAL',status='PASS',harness_hash=certification.harness_hash(root),created=time.time() if now is None else now,components={k:'PASS' for k in certification.TECHNICAL_COMPONENTS})
    data['id']=digest(data);return data


def signed_snapshot(tmp_path):
    path=tmp_path/'isolated.db'
    with sqlite3.connect(path) as db:
        for name in snapshot.REQUIRED_TABLES: db.execute('CREATE TABLE '+name+'(id INTEGER PRIMARY KEY)')
    return path,snapshot.sign_backup(path,key=KEY,source_sha='a'*40)


@pytest.mark.parametrize('gate',validation.GATES)
def test_operator_pass_claims_cannot_create_validation(store,gate):
    cid=store.discover(proposal())
    with pytest.raises(ValueError):store.event(cid,'VALIDATION',dict(name=gate,status='PASS',exit_code=0))
    with pytest.raises(ValueError):store.event(cid,'VALIDATION_BATCH',{'full_suite':'PASS'})


def test_trusted_seal_and_whole_source_staleness(repo,store,tmp_path):
    cid,root=built(repo,store,tmp_path)
    proof=make_trusted_proof(root,store,cid)
    assert proof['status']=='PASS' and evidence.trusted_receipt(root,store,cid,proof)
    (root/'docs/note.md').write_text('Changed after validation')
    with pytest.raises(ValueError):validation.reconstruct(root,store,cid)
    assert not evidence.trusted_receipt(root,store,cid,proof)


@pytest.mark.parametrize('mutation',['candidate','head','missing','duplicate','command','fixture'])
def test_mixed_or_missing_validation_rejected(repo,store,tmp_path,mutation):
    cid,root=built(repo,store,tmp_path);make_trusted_proof(root,store,cid)
    # Simulate corrupted/foreign trusted batch during recovery, without weakening
    # the immutable ledger (which rejects SQL UPDATE/DELETE in existing tests).
    original=store.get
    candidate=original(cid);events=candidate['events']
    records=[e for e in events if e['kind']=='VALIDATION']
    if mutation in {'candidate','head'}: records[0]['payload'][mutation]='b'*40
    elif mutation=='missing':events.remove(records[0])
    elif mutation=='duplicate':events.append(copy.deepcopy(records[0]))
    elif mutation=='command':records[0]['payload']['command']=['python','-c','print("PASS")']
    elif mutation=='fixture':records[0]['payload']['fixture_only']=True
    store.get=lambda ident:candidate if ident==cid else original(ident)
    with pytest.raises(ValueError):validation.reconstruct(root,store,cid)


@pytest.mark.parametrize('inventory,status',[({},'PARTIAL'),({'total':1,'passed':0,'failures':['bad'],'skipped':[]},'FAIL')])
def test_zero_exit_without_passing_junit_is_not_pass(repo,store,tmp_path,inventory,status):
    cid,root=built(repo,store,tmp_path);validator=ContainerValidator('fixture@sha256:'+'a'*64)
    validator.run=lambda root,name,cmd:dict(command=cmd,status='PASS',exit_code=0,inventory=inventory)
    records=validation.execute(root,store,cid,validator)
    assert records[0]['status']==status
    assert evidence.seal(root,store,cid)['status']=='PARTIAL'


def test_all_mandatory_commands_and_immediate_immutable_events(repo,store,tmp_path):
    cid,root=built(repo,store,tmp_path);proof=make_trusted_proof(root,store,cid)
    assert {r['name'] for r in proof['validations']}==set(validation.GATES)
    for r in proof['validations']:
        assert r['candidate']==cid and r['head']==proof['head'] and r['source_hash']==proof['source_hash']
        assert r['started_at']<=r['ended_at'] and '@sha256:' in r['sandbox_image_digest']
    with store.connect(True) as db:
        with pytest.raises(sqlite3.IntegrityError):db.execute("DELETE FROM dev_events WHERE kind='VALIDATION'")


@pytest.mark.parametrize('change',['empty','schema','hash','other','stale','future','wal','signature','source','missing'])
def test_snapshot_authenticity_attacks(tmp_path,change):
    path,proof=signed_snapshot(tmp_path)
    if change=='empty':
        empty=tmp_path/'empty.db';sqlite3.connect(empty).close();path=empty
    elif change=='schema':
        # Authenticate a structurally mismatched receipt to exercise the separate schema gate.
        proof['schema_fingerprint']='0'*64
        import hmac,hashlib
        payload={k:v for k,v in proof.items() if k!='signature'}
        proof['signature']=hmac.new(KEY,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    elif change=='hash':proof['backup_sha256']='0'*64
    elif change=='other':
        other=tmp_path/'other.db'
        with sqlite3.connect(other) as db:db.execute('CREATE TABLE unrelated(x)')
        path=other
    elif change=='stale':proof=snapshot.sign_backup(path,key=KEY,source_sha='a'*40,now=time.time()-86401)
    elif change=='future':proof=snapshot.sign_backup(path,key=KEY,source_sha='a'*40,now=time.time()+60)
    elif change=='wal':Path(str(path)+'-wal').touch()
    elif change=='signature':proof['signature']='forged'
    elif change=='source':proof['source_environment']='operator-claimed-production'
    elif change=='missing':proof=None
    before=path.read_bytes()
    assert snapshot.check_snapshot(path,tmp_path,proof,key=KEY)['status']!='PASS'
    assert path.read_bytes()==before


def test_authentic_backup_fixture_readonly_positive_control(tmp_path):
    path,proof=signed_snapshot(tmp_path);before=path.read_bytes()
    result=snapshot.check_snapshot(path,tmp_path,proof,key=KEY)
    assert result['status']=='PASS' and result['schema_fingerprint']==proof['schema_fingerprint']
    assert result['snapshot_sha256_before']==result['snapshot_sha256_after']
    assert path.read_bytes()==before and result['readonly_sql_denied'] and result['runner_write_denied']


def test_technical_canary_does_not_count_as_supervised_success(store):
    result=certification.canary(ROOT)
    assert result['supervised'] is False and result['kind']=='TECHNICAL'
    assert result['components']['authority_adversarial']=='PASS'
    assert not operations.eligibility(ROOT,store)['eligible']
    assert operations.eligibility(ROOT,store)['completed']==0
    cid=store.discover(proposal())
    for kind in ['OPERATIONAL_SUCCESS','START_AUTHORIZATION','TECHNICAL_CERTIFICATION']:
        with pytest.raises(ValueError):store.event(cid,kind,{'actor':'RJ','status':'PASS'})


def start_candidate(repo,store,mode='SUPERVISED',risk='L0'):
    cid=store.discover(proposal())
    plan(repo,store,cid,['The fixture document describes its expected behavior.'],mode=mode)
    commit(repo);ctx=refresh_plan(repo,store,cid)
    if risk!='L0':
        ctx=dict(ctx,risk=risk)
        old=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='PLAN'][-1]
        store.event(cid,'PLAN',dict(old,context=ctx))
    store.decide(cid,'approve','human',ctx,'approve-'+cid,'Explicit fixture approval',identity=dashboard_identity())
    return cid,ctx


def test_supervised_admission_does_not_require_autonomy(repo,store,monkeypatch):
    cid,ctx=start_candidate(repo,store)
    (repo/'config').mkdir();(repo/'config/development_agent.json').write_text((ROOT/'config/development_agent.json').read_text())
    monkeypatch.setattr(operations,'policy',lambda root:json.loads((ROOT/'config/development_agent.json').read_text()))
    monkeypatch.setattr(certification,'harness_hash',lambda root:'fixture-harness')
    cert=dict(version='harness-canary-2',kind='TECHNICAL',status='PASS',harness_hash='fixture-harness',created=time.time(),components={k:'PASS' for k in certification.TECHNICAL_COMPONENTS});cert['id']=digest(cert)
    record=operations.authorize_start(repo,store,cid,'SUPERVISED',[cert],{'status':'PASS','created':time.time()},human=dashboard_identity())
    assert record['mode']=='SUPERVISED' and record['context']==ctx
    assert operations.eligibility(ROOT,store)['completed']==0


@pytest.mark.parametrize('variant',['disabled','history','risk','mode','human','technical','protection'])
def test_execution_admission_denials(repo,store,monkeypatch,variant):
    mode='SUPERVISED' if variant=='human' else 'AUTONOMOUS'
    risk='L4' if variant=='risk' else 'L0'
    cid,ctx=start_candidate(repo,store,mode,risk)
    config=json.loads((ROOT/'config/development_agent.json').read_text());config['autonomous_implementation']=variant!='disabled'
    monkeypatch.setattr(operations,'policy',lambda root:config)
    monkeypatch.setattr(certification,'technical_current',lambda *a:variant!='technical')
    if variant not in {'history'}:monkeypatch.setattr(operations,'eligibility',lambda *a,**k:dict(eligible=True))
    if variant=='history':monkeypatch.setattr(operations,'eligibility',lambda *a,**k:dict(eligible=False))
    with pytest.raises(ValueError):operations.authorize_start(repo,store,cid,'SUPERVISED' if variant=='mode' else mode,[],{'status':'FAIL' if variant=='protection' else 'PASS','created':time.time()},human=None)


def remote(**changes):
    return dict(dict(number=1,headRefName='agent/0001/fixture',headRefOid='a'*40,baseRefName='main',headRepository={'nameWithOwner':'owner/repo'},isDraft=False),**changes)


@pytest.mark.parametrize('change',[{'headRefOid':'b'*40},{'headRefName':'main'},{'baseRefName':'develop'},{'headRepository':{'nameWithOwner':'evil/fork'}},{'isDraft':None}])
def test_remote_pr_identity_mismatch(change):
    with pytest.raises(ValueError):github.verify_remote_pr(remote(**change),repository='owner/repo',branch='agent/0001/fixture',head='a'*40)


def test_remote_pr_exact_identity_positive():
    result=github.verify_remote_pr(remote(),repository='owner/repo',branch='agent/0001/fixture',head='a'*40)
    assert result['headRefOid']=='a'*40


def rules():
    return [dict(type='pull_request',ruleset_id=1,parameters=dict(required_approving_review_count=1,dismiss_stale_reviews_on_push=True,require_last_push_approval=True,required_review_thread_resolution=True)),dict(type='required_status_checks',ruleset_id=1,parameters=dict(strict_required_status_checks_policy=True,required_status_checks=[{'context':'test'}])),dict(type='non_fast_forward',ruleset_id=1),dict(type='deletion',ruleset_id=1)]


@pytest.mark.parametrize('classic', [True,False])
def test_effective_classic_and_ruleset_only_positive(classic):
    result=github.effective_protections(protection() if classic else None,[] if classic else rules(),[] if classic else [dict(id=1,enforcement='active',bypass_actors=[])],{'login':'agent'},{'permissions':{'push':True,'admin':False}},visibility=True)
    assert result['status']=='PASS' and result['auto_merge'] is False
    assert all(value is False for value in result['agent_capabilities'].values())


@pytest.mark.parametrize('variant',['bypass','inherited','admin','visibility','stale_review','ci','last_push'])
def test_effective_protection_denials(variant):
    active=rules();details=[dict(id=1,enforcement='active',bypass_actors=[])]
    if variant=='bypass':details[0]['bypass_actors']=[{'actor_type':'User','actor_id':1}]
    if variant=='inherited':details=[]
    if variant=='stale_review':active[0]['parameters']['dismiss_stale_reviews_on_push']=False
    if variant=='last_push':active[0]['parameters']['require_last_push_approval']=False
    if variant=='ci':active[1]['parameters']['strict_required_status_checks_policy']=False
    result=github.effective_protections(None,active,details,{'login':'agent'},{'permissions':{'push':True,'admin':variant=='admin'}},visibility=variant!='visibility')
    assert result['status'] in {'FAIL','UNAVAILABLE'} and result['failures']


def test_readiness_empty_ledger_is_read_only_and_explicit(store):
    before=store.path.read_bytes();data=readiness.readiness(ROOT,store)
    assert data['status'] in {'BLOCKED','UNAVAILABLE'} and data['blockers']
    assert data['supervised']['completed']==0 and not data['autonomous_implementation'] and not data['auto_merge']
    assert store.path.read_bytes()==before


def test_stale_or_partial_technical_receipts_never_pass():
    positive=technical(ROOT)
    assert certification.technical_current(ROOT,[positive])
    for change in [{'harness_hash':'stale'},{'components':{}},{'status':'PARTIAL'},{'created':time.time()-86401},{'created':time.time()+60}]:
        changed=dict(positive,**change);changed['id']=digest({k:v for k,v in changed.items() if k!='id'})
        assert not certification.technical_current(ROOT,[changed])
    assert not certification.current(ROOT,[positive])


@pytest.fixture(autouse=True)
def owner_bindings_fixture(monkeypatch):
    # Temporary operator configuration; no operational identity is provisioned.
    monkeypatch.setenv('DEV_AGENT_OWNER_BINDINGS',json.dumps(dict(repository='owner/repo',owner_login='owner',owner_id=1,operators={'os-interactive-cli':['fixture-owner']})))


def seed_completed_pilot(store, *, created=None, harness=None):
    """Seed upstream authenticated adapters to test the final lineage boundary.

    The resulting records exist only in a temporary test database, never in an
    operational certificate directory or the application store.
    """
    cid=store.discover(proposal(problem='Prospective pilot '+str(time.time_ns())))
    head='a'*40;base='b'*40
    ctx=dict(todo='0795',head=base,scope_hash=digest(['docs/note.md']),risk='L0',acceptance_hash='frozen',mode='SUPERVISED')
    proof=dict(id='sealed-'+cid,head=head,base=base,source_hash='source',mode='SUPERVISED',trusted_validation=True,status='PASS',batch='batch-'+cid,validations=[dict(name=n,candidate=cid,head=head,status='PASS',exit_code=0) for n in validation.GATES])
    pr=dict(result=dict(number=1,url='https://github.com/owner/repo/pull/1'),head=head,verified=dict(headRefName='agent/0001/fixture'))
    start=dict(mode='SUPERVISED',authentication_source='os-interactive-cli',context=ctx,harness_hash=harness or certification.harness_hash(ROOT))
    with store.connect(True) as db:
        records=[('PLAN',{'context':ctx}),('APPROVAL',dict(context=ctx,actor='human',authentication_source='os-interactive-cli')),('START_AUTHORIZATION',start),('RUN',dict(run_id='real-'+cid,role='builder',status='PASS',data=dict(mode='SUPERVISED',fixture_only=False,provider=dict(provider='ollama')))),('RUN',dict(run_id='review-'+cid,role='reviewer',status='PASS',data=dict(head=head,source_hash='source',independent_context='review-context'))),('ITERATION',dict(review=dict(disposition='PASS'),fixture_only=False)),('VALIDATION_BATCH',dict(batch=proof['batch'],fixture_only=False)),('RECEIPT',dict(receipt=proof)),('PR',pr),('HUMAN_REVIEW',dict(stage='PR_DISPOSITION',decision='accept',authentication_source='os-interactive-cli',context=dict(ctx,head=head))),('DEPLOYMENT',dict(status='HEALTHY',deployed_sha='c'*40,merge_sha='c'*40)),('STATE',dict(state='DEPLOYED'))]
        for i,(kind,payload) in enumerate(records):store._append(db,cid,kind,payload,f'fixture-lineage:{cid}:{i}')
    class Client:
        repository='owner/repo'
        def read(self,endpoint):
            if '/pulls/' in endpoint:return dict(merged=True,head=dict(sha='a'*40),merge_commit_sha='c'*40,auto_merge=None,merged_by=dict(id=1,login='owner',type='User'))
            return dict(full_name=self.repository,owner=dict(login='owner',id=1,type='User'))
        def read_all(self,endpoint):return [dict(filename='docs/pilot.md',patch='+Pilot')]
        def pr_identity(self,number):return dict(remote(),state='MERGED',reviewDecision='APPROVED',mergeCommit={'oid':'c'*40})
    from dev_agent.owner_review import attest,context
    from dev_agent.identity import HumanIdentity,_PROOF
    client=Client()
    attest(store,client,context(client,1,risk='L0'),'APPROVE','fixture-owner-'+cid,'Reviewed prospective fixture',human=HumanIdentity('fixture-owner','os-interactive-cli',_PROOF))
    return cid,client


def test_real_qualifying_lineage_counts_once_and_rollback_invalidates(store):
    cid,client=seed_completed_pilot(store)
    first=operations.record_success(ROOT,store,cid,client,human=dashboard_identity())
    assert operations.record_success(ROOT,store,cid,client,human=dashboard_identity())==first
    assert operations.eligibility(ROOT,store)['completed']==1
    with store.connect(True) as db:
        store._append(db,cid,'DEPLOYMENT',dict(status='ROLLED_BACK'),'fixture-rollback')
    assert operations.eligibility(ROOT,store)['completed']==0
    assert operations.operational_runs(ROOT,store)['non_qualifying']


@pytest.mark.parametrize('mutation',['synthetic','replay','fixture','review','head','validation','deployed','scope'])
def test_incomplete_or_synthetic_pilots_never_count(store,mutation):
    cid,client=seed_completed_pilot(store)
    original=store.get;candidate=original(cid)
    def latest(kind):return [e['payload'] for e in candidate['events'] if e['kind']==kind][-1]
    if mutation=='synthetic':latest('APPROVAL').pop('authentication_source')
    if mutation=='replay':[e['payload'] for e in candidate['events'] if e['kind']=='RUN' and e['payload']['role']=='builder'][-1]['data']['provider']['provider']='replay'
    if mutation=='fixture':latest('ITERATION')['fixture_only']=True
    if mutation=='review':latest('HUMAN_REVIEW')['decision']='defer'
    if mutation=='head':latest('RECEIPT')['receipt']['head']='d'*40
    if mutation=='validation':latest('RECEIPT')['receipt']['validations'].pop()
    if mutation=='deployed':latest('DEPLOYMENT')['deployed_sha']='d'*40
    if mutation=='scope':latest('PLAN')['context']=dict(latest('PLAN')['context'],scope_hash='changed')
    store.get=lambda ident:candidate if ident==cid else original(ident)
    with pytest.raises(ValueError):operations.record_success(ROOT,store,cid,client,human=dashboard_identity())
    assert not operations.eligibility(ROOT,store)['eligible']


def test_three_runs_require_seven_calendar_days_and_exact_harness(store,monkeypatch):
    now=time.time()
    for delta in [0,86400,2*86400]:
        cid,client=seed_completed_pilot(store)
        monkeypatch.setattr(operations.time,'time',lambda value=now+delta:value)
        operations.record_success(ROOT,store,cid,client,human=dashboard_identity())
    result=operations.eligibility(ROOT,store,now=now+3*86400)
    assert result['completed']==3 and result['observation_days']==2 and not result['eligible']
    cid,client=seed_completed_pilot(store)
    monkeypatch.setattr(operations.time,'time',lambda:now+8*86400)
    operations.record_success(ROOT,store,cid,client,human=dashboard_identity())
    assert operations.eligibility(ROOT,store,now=now+9*86400)['eligible']
    monkeypatch.setattr(certification,'harness_hash',lambda root:'changed-config-contract')
    assert operations.eligibility(ROOT,store,now=now+9*86400)['completed']==0


def test_autonomy_budget_and_emergency_stop(repo,store,monkeypatch):
    cid,_=start_candidate(repo,store,mode='AUTONOMOUS')
    config=json.loads((ROOT/'config/development_agent.json').read_text());config.update(autonomous_implementation=True,daily_implementation_cap=1)
    monkeypatch.setattr(operations,'policy',lambda root:config)
    monkeypatch.setattr(operations,'eligibility',lambda *a,**k:dict(eligible=True))
    monkeypatch.setattr(certification,'technical_current',lambda *a:True)
    monkeypatch.setattr(certification,'harness_hash',lambda root:'fixture-harness')
    protections=dict(status='PASS',created=time.time())
    assert operations.authorize_start(repo,store,cid,'AUTONOMOUS',[],protections)['mode']=='AUTONOMOUS'
    with pytest.raises(ValueError,match='daily implementation'):operations.authorize_start(repo,store,cid,'AUTONOMOUS',[],protections)
    monkeypatch.setenv('DEV_AGENT_KILL_SWITCH','1')
    with pytest.raises(ValueError,match='disabled'):operations.authorize_start(repo,store,cid,'AUTONOMOUS',[],protections)


@pytest.mark.parametrize('document',[
    '<testsuites><testsuite errors="1"><testcase name="ok"/></testsuite></testsuites>',
    '<testsuites><testsuite><error>collection failed</error><testcase name="ok"/></testsuite></testsuites>',
])
def test_junit_suite_level_failures_are_not_pass(tmp_path,document):
    path=tmp_path/'inventory.xml';path.write_text(document)
    assert evidence.junit(path)['failures']


def test_unapproved_junit_override_is_denied(repo):
    validator=ContainerValidator('fixture@sha256:'+'a'*64)
    with pytest.raises(ValueError):validator.run(repo,'full_suite',['python','-m','pytest','tests/','--junitxml=/tmp/forged.xml'])


def test_disabling_autonomy_stops_pipeline_before_builder(repo,store,tmp_path):
    from dev_agent.autonomy import progress
    from dev_agent.worktrees import Worktrees
    cid,ctx=start_candidate(repo,store,mode='AUTONOMOUS')
    manager=Worktrees(repo,store.path.parent/'worktrees');record=manager.create(ctx['todo'],ctx['head'])
    store.event(cid,'WORKTREE',record)
    class NeverBuilder:
        def respond(self,*args):raise AssertionError('Builder must not be invoked')
    class Client:
        def protections(self):return dict(status='PASS',created=time.time())
    # Missing certificates/config in the disposable fixture fails closed before
    # any provider action. A real disabled installation is separately covered by
    # admission tests with all other gates passing.
    with pytest.raises((ValueError,FileNotFoundError)):
        progress(repo,store,cid,NeverBuilder(),NeverBuilder(),ContainerValidator('fixture@sha256:'+'a'*64),Client())
    assert store.get(cid)['state']=='APPROVED'


def test_publishing_cannot_target_main_or_unreviewed_repository(repo,monkeypatch):
    client=github.GitHub('owner/repo')
    with pytest.raises(ValueError):client.publish(repo,'main',git(repo,'rev-parse','HEAD'))


def test_approval_validation_scope_is_frozen(repo,store,monkeypatch):
    cid,ctx=start_candidate(repo,store)
    event=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='PLAN'][-1]
    store.event(cid,'PLAN',dict(event,focused_tests=['tests/different.py']))
    monkeypatch.setattr(operations,'policy',lambda root:json.loads((ROOT/'config/development_agent.json').read_text()))
    with pytest.raises(ValueError,match='validation scope changed'):
        operations.authorize_start(repo,store,cid,'SUPERVISED',[],dict(status='PASS',created=time.time()),human=dashboard_identity())


def test_new_failed_certification_invalidates_prior_success():
    good=technical(ROOT)
    bad=dict(good,status='PARTIAL');bad['id']=digest({k:v for k,v in bad.items() if k!='id'})
    assert certification.technical_current(ROOT,[good])
    assert not certification.technical_current(ROOT,[good,bad])


def test_readiness_eligible_fixture_requires_enabled_policy_and_fresh_evidence(store,monkeypatch):
    now=time.time()
    for days in [8,4,0]:
        cid,client=seed_completed_pilot(store)
        with monkeypatch.context() as clock:
            clock.setattr(operations.time,'time',lambda age=days:now-age*86400)
            operations.record_success(ROOT,store,cid,client,human=dashboard_identity())
    cert=technical(ROOT,now)
    cert['evidence']=dict(sandbox={'status':'PASS'},snapshot=dict(status='PASS',backup_timestamp=now,schema_fingerprint='schema'),github=dict(status='PASS',created=now))
    cert['id']=digest({k:v for k,v in cert.items() if k!='id'})
    monkeypatch.setattr(readiness,'certificates',lambda store:[cert])
    monkeypatch.setattr(readiness.shutil,'which',lambda name:'/fixture/docker')
    config=json.loads((ROOT/'config/development_agent.json').read_text());config['autonomous_implementation']=True
    monkeypatch.setattr(readiness,'policy',lambda root:config)
    monkeypatch.setattr(operations,'policy',lambda root:config)
    result=readiness.readiness(ROOT,store,now)
    assert result['status']=='AUTONOMY_ELIGIBLE' and result['autonomous_starts_allowed']
    config['autonomous_implementation']=False
    assert readiness.readiness(ROOT,store,now)['status']=='SUPERVISED_ONLY'
    stale=dict(cert,harness_hash='prior-version');stale['id']=digest({k:v for k,v in stale.items() if k!='id'})
    monkeypatch.setattr(readiness,'certificates',lambda store:[stale])
    result=readiness.readiness(ROOT,store,now)
    assert result['certification_stale'] and result['technical_certification']=='STALE' and not result['autonomous_starts_allowed']


def test_disposition_recheck_invalidates_advanced_remote_head(repo,store,tmp_path):
    cid,root=built(repo,store,tmp_path);proof=make_trusted_proof(root,store,cid)
    branch=git(root,'branch','--show-current')
    class Client:
        repository='owner/repo'
        head=proof['head']
        def protections(self):return {'status':'PASS'}
        def handoff(self,*args):return dict(number=1,url='https://github.com/owner/repo/pull/1')
        def pr_identity(self,number):return remote(headRefName=branch,headRefOid=self.head)
    client=Client();github.prepare_pr(root,store,cid,proof,client)
    assert github.recheck_pr(store,cid,client)['status']=='PASS'
    client.head='b'*40
    assert github.recheck_pr(store,cid,client)['status']=='NEEDS_HUMAN'
    assert store.get(cid)['state']=='NEEDS_HUMAN'


def test_observed_merge_is_read_only_and_exact_head(store):
    cid,client=seed_completed_pilot(store)
    event=github.record_merge(store,cid,client)
    assert event['merge_sha']=='c'*40 and event['source']=='github-verified-merge'
    assert github.record_merge(store,cid,client)==event


def test_validation_container_excludes_host_git_and_secrets(repo,monkeypatch):
    import dev_agent.runner as runner_module
    (repo/'.env').write_text('fixture sensitive material')
    real_run=subprocess.run
    observed=[]
    monkeypatch.setattr(runner_module.shutil,'which',lambda name:'/fixture/docker')
    def invoke(command,**kwargs):
        if command[0]!='docker':return real_run(command,**kwargs)
        observed.append(command)
        mounts=[command[i+1] for i,value in enumerate(command[:-1]) if value=='--mount']
        src=next(m for m in mounts if 'dst=/source,' in m)
        source=Path(src.split('src=',1)[1].split(',')[0])
        assert src.endswith('readonly') and not (source/'.git').exists() and not (source/'.env').exists()
        assert not list(source.glob('*.bundle'))
        assert '--network=none' in command and '--pull=never' in command
        assert not any('/var/run' in value for value in command)
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(runner_module.subprocess,'run',invoke)
    validator=ContainerValidator('fixture@sha256:'+'a'*64)
    result=validator.run(repo,'full_suite',['python','-m','pytest','tests/'])
    assert result['status']=='PARTIAL' and observed  # no JUnit despite exit zero


def test_cc_gate_prior_file_is_extracted_from_exact_approved_commit(repo,monkeypatch):
    import dev_agent.runner as runner_module
    original='{"reviewed":"prior"}'
    (repo/'.cc_contract_baseline.json').write_text(original);base=commit(repo)
    (repo/'.cc_contract_baseline.json').write_text('{"untrusted":"candidate"}')
    real_run=subprocess.run
    monkeypatch.setattr(runner_module.shutil,'which',lambda name:'/fixture/docker')
    def invoke(command,**kwargs):
        if command[0]!='docker':return real_run(command,**kwargs)
        authority=next(command[i+1] for i,value in enumerate(command[:-1]) if value=='--mount' and 'dst=/authority,' in command[i+1])
        directory=Path(authority.split('src=',1)[1].split(',')[0])
        assert authority.endswith('readonly')
        assert (directory/'prior-cc-baseline.json').read_text()==original
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(runner_module.subprocess,'run',invoke)
    validator=ContainerValidator('fixture@sha256:'+'a'*64);validator.prior_base=base
    result=validator.run(repo,'cc_contract',['python','scripts/check_cc_contract.py','--trusted-prior-file','/authority/prior-cc-baseline.json'])
    assert result['status']=='PASS'


def test_readiness_exposes_invalid_auto_merge_configuration(store,monkeypatch):
    config=json.loads((ROOT/'config/development_agent.json').read_text());config['auto_merge']=True
    monkeypatch.setattr(readiness,'policy',lambda root:config)
    state=readiness.readiness(ROOT,store)
    assert state['auto_merge'] is True and 'human merge policy violation' in state['blockers']
    assert not state['autonomous_starts_allowed']


@pytest.mark.parametrize('path,risk',[('docs/note.md','L0'),('static/pilot.css','L2')])
def test_eligible_low_risk_pipeline_reaches_verified_pr_fixture(repo,store,monkeypatch,path,risk):
    from dev_agent import autonomy
    from dev_agent.worktrees import Worktrees
    from dev_agent.providers import ReplayProvider
    config=json.loads((ROOT/'config/development_agent.json').read_text());config['autonomous_implementation']=True
    (repo/'config').mkdir();(repo/'config/development_agent.json').write_text(json.dumps(config))
    if path.startswith('static/'):(repo/'static').mkdir();(repo/path).write_text('body { color: black; }\n')
    commit(repo)
    cid=store.discover(proposal(files=[path]))
    plan(repo,store,cid,['The requested low-risk presentation or documentation change is visible.'],mode='AUTONOMOUS')
    commit(repo);ctx=refresh_plan(repo,store,cid)
    assert ctx['risk']==risk
    store.decide(cid,'approve','fixture-human',ctx,'auto-'+cid,identity=dashboard_identity())
    manager=Worktrees(repo,store.path.parent/'worktrees');record=manager.create(ctx['todo'],ctx['head']);store.event(cid,'WORKTREE',record)
    monkeypatch.setattr(certification,'technical_current',lambda *a,**k:True)
    monkeypatch.setattr(certification,'harness_hash',lambda root:'fixture-certified-harness')
    monkeypatch.setattr(operations,'eligibility',lambda *a,**k:dict(eligible=True))
    monkeypatch.setattr(autonomy,'current',lambda *a,**k:True)
    validator=ContainerValidator('fixture@sha256:'+'a'*64)
    validator.run=lambda root,name,command:dict(name=name,command=command,exit_code=0,status='PASS',inventory=dict(total=2,passed=2,failures=[],skipped=[]))
    class Client:
        repository='owner/repo'
        published=None
        def protections(self):return dict(status='PASS',created=time.time())
        def publish(self,root,branch,head):self.published=(branch,head)
        def handoff(self,branch,title,body,draft):
            assert not draft and 'execution mode AUTONOMOUS' in body
            return dict(number=1,url='https://github.com/owner/repo/pull/1')
        def pr_identity(self,number):return remote(headRefName=self.published[0],headRefOid=self.published[1])
    client=Client()
    content='After: documented fixture detail\n' if risk=='L0' else 'body { color: navy; }\n'
    result=autonomy.progress(repo,store,cid,ReplayProvider([dict(actions=[dict(type='write',path=path,content=content)])]),ReplayProvider([dict(disposition='PASS',findings=[]),dict(disposition='PASS',findings=[])]),validator,client)
    assert result['status']=='PR_OPEN',result
    assert result['mode']=='AUTONOMOUS' and result['grants_merge'] is False and result['grants_deployment'] is False
    assert store.get(cid)['state']=='PR_OPEN'
    assert not operations.operational_runs(ROOT,store)['qualifying']


def test_stricter_snapshot_freshness_policy_is_honored(tmp_path):
    path,_=signed_snapshot(tmp_path)
    proof=snapshot.sign_backup(path,key=KEY,source_sha='a'*40,now=time.time()-13*3600)
    assert snapshot.check_snapshot(path,tmp_path,proof,key=KEY)['status']=='PASS'
    assert snapshot.check_snapshot(path,tmp_path,proof,key=KEY,max_age_hours=12)['status']=='FAIL'
