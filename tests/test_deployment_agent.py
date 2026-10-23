"""Fixed deployment transaction tests never touch production or call systemctl."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from deployment_agent.service import deploy,recover


class FakeExecutor:
    def __init__(self,tmp_path,*,failure=None):
        self.root=tmp_path/'source';self.root.mkdir();(self.root/'config').mkdir()
        (self.root/'config/development_agent.json').write_text(json.dumps(dict(auto_merge=False,required_human_merge=True,autonomous_implementation=False,supervised_loop_enabled=False,supervised_publish_pr=False)))
        self.receipts=tmp_path/'receipts';self.sha='a'*40;self.active=True;self.failure=failure;self.operations=[];self.mutated=False
    def git(self,*args):
        if args==('rev-parse','HEAD'):return self.sha
        if args==('status','--porcelain','--untracked-files=no'):return ''
        raise ValueError('unexpected Git operation')
    def service(self,verb):
        self.operations.append(verb)
        if verb=='is-active':return 'active' if self.active else 'inactive'
        if self.failure=='restart' and self.sha=='b'*40 and verb=='start':raise ValueError('restart failed')
        self.active=verb!='stop';return ''
    def config_hash(self):return 'configuration'
    def protected(self):return dict(holdings_sha256='mutated' if self.mutated else 'unchanged',ledger='unchanged',investment='unchanged')
    def preflight(self,origin):
        if self.failure=='dirty':raise ValueError('tracked dirty')
        return dict(prior_sha=self.sha,service='active',service_configuration_hash=self.config_hash(),protected=self.protected(),untracked=['runtime-overlay'])
    def backup(self,path):
        if self.failure=='backup':raise ValueError('backup failed')
        return dict(sha256='f'*64,integrity='ok')
    def checkout(self,sha,origin):
        self.operations.append(('checkout',sha));self.sha=sha
        if self.failure=='holdings' and sha=='b'*40:self.mutated=True
    def health(self):
        good=not (self.sha=='b'*40 and self.failure in {'dashboard','canary'})
        return dict(checks=dict(service=self.active,dashboard=good,development_dashboard=good,unauthorized_api_denied=True,advisor=good,authenticated_api=True),canary=dict(functional_contract='PASS',mutation_safety='PASS',production_state_unchanged=True),activation=dict(autonomous_implementation=False,supervised_loop_enabled=False,supervised_publish_pr=False,auto_merge=False),autonomous_implementation=False)


def authorization():
    from development_fixtures import deployment_evidence
    e=deployment_evidence(head='c'*40,merge='b'*40)['receipt']
    return dict(main_sha='b'*40,head_ci=e['head_ci'],merge_ci=e['merge_ci'],repository='owner/repo',authorization_id=123,authorization_url='https://github.com/owner/repo/pull/1#issuecomment-123',pr=1,head='c'*40,merge_sha='b'*40,nonce='unique-deployment-nonce-0001',deployment_actor='owner')


def test_successful_exact_merge_deploy_and_idempotence(tmp_path):
    executor=FakeExecutor(tmp_path);auth=authorization()
    receipt=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    assert receipt['status']=='DEPLOYED_VERIFIED' and receipt['deployed_sha']=='b'*40
    assert receipt['prior_sha']=='a'*40 and receipt['backup']['integrity']=='ok'
    assert deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)['idempotent']
    assert executor.operations.count(('checkout','b'*40))==1


@pytest.mark.parametrize('failure',['dirty','backup','restart','dashboard','canary','holdings'])
def test_failures_never_report_success_and_keep_financial_data(tmp_path,failure):
    executor=FakeExecutor(tmp_path,failure=failure);auth=authorization()
    receipt=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    assert receipt['status'] in {'FAILED_PRECHECK','ROLLED_BACK','DEPLOYED_DEGRADED'}
    assert executor.sha=='a'*40
    assert (executor.receipts/'deploy-123.json').exists()
    if failure=='holdings':assert executor.mutated # code rollback must not overwrite investment state


def test_changed_admission_prevents_deployment(tmp_path):
    executor=FakeExecutor(tmp_path);auth=authorization()
    receipt=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:dict(auth,merge_sha='d'*40))
    assert receipt['status']=='FAILED_PRECHECK' and 'stop' not in executor.operations


def test_interrupted_deploy_requires_recovery(tmp_path):
    executor=FakeExecutor(tmp_path);executor.receipts.mkdir(mode=0o700)
    from dev_agent.result_collector import write_final
    write_final(executor.receipts,'pending',dict(prior_sha='a'*40,target='b'*40,authorization_id=123,protected=executor.protected()))
    executor.sha='b'*40;auth=authorization()
    with pytest.raises(ValueError):deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    receipt=recover(executor,'https://github.com/owner/repo.git')
    assert receipt['status']=='ROLLED_BACK' and executor.sha=='a'*40


def test_executor_exposes_no_arbitrary_service_command(tmp_path):
    from deployment_agent.executor import Executor
    root=tmp_path/'source';root.mkdir();ledger=tmp_path/'ledger';ledger.write_text('fixture')
    commands=[]
    def invoke(command,**kwargs):commands.append(command);return SimpleNamespace(stdout='active')
    executor=Executor(root,tmp_path/'receipts',ledger,invoke=invoke)
    with pytest.raises(ValueError):executor.service('restart; arbitrary command')
    assert commands==[]
    assert executor.service('is-active')=='active'
    assert commands[0]==['/bin/systemctl','--no-ask-password','is-active','investment.service']


@pytest.fixture
def authorized_owner(owner_setup):
    from test_development_agent_owner_review import approve
    import time
    store,client,human=owner_setup;approve(owner_setup)
    data=dict(repository=client.repository,pr=1,head=client.head,merge_sha='c'*40,nonce='fixture-deployment-owner-0001',expires_at=time.time()+3600,rationale='Deploy the reviewed merged SHA',execution_ack=True)
    obj=dict(id=999,user=dict(id=1,login='owner',type='User'),performed_via_github_app=None,body='OWNER-DEPLOY deployment-1\n'+json.dumps(data),created_at='unchanged',updated_at='unchanged',issue_url='https://api.github.com/repos/owner/repo/issues/1',html_url='https://github.com/owner/repo/pull/1#issuecomment-999')
    original=client.read;pr=client.pr_identity
    client.pr_identity=lambda number:dict(pr(number),state='MERGED',mergeCommit=dict(oid='c'*40))
    def read(endpoint):
        if '/issues/comments/' in endpoint:return obj
        if '/check-runs' in endpoint:
            sha='c'*40 if '/commits/'+('c'*40) in endpoint else client.head
            return dict(total_count=1,check_runs=[dict(id=1,name='test',head_sha=sha,status='completed',conclusion='success',html_url='https://github.com/owner/repo/actions/runs/1/job/2')])
        if '/compare/' in endpoint:return dict(status='ahead')
        if '/branches/main' in endpoint:return dict(commit=dict(sha='c'*40))
        return original(endpoint)
    client.read=read
    return store,client,obj,data


from test_development_agent_owner_review import setup as owner_setup


def test_deployment_admission_requires_owner_review_and_both_exact_ci_heads(authorized_owner):
    from deployment_agent.admission import authorize
    store,client,obj,data=authorized_owner
    result=authorize(store,client,999)
    assert result['merge_sha']=='c'*40 and result['head']==client.head
    with pytest.raises(ValueError):authorize(store,client,999,emergency_stop=True)
    client.head='d'*40
    with pytest.raises(ValueError):authorize(store,client,999)


@pytest.mark.parametrize('mutation',[dict(head='b'*40),dict(merge_sha='b'*40),dict(execution_ack=False),dict(expires_at=1),dict(repository='other/repo')])
def test_deployment_wrong_or_stale_authorization_never_admits(authorized_owner,mutation):
    from deployment_agent.admission import authorize
    store,client,obj,data=authorized_owner
    obj['body']='OWNER-DEPLOY deployment-1\n'+json.dumps(dict(data,**mutation))
    with pytest.raises(ValueError):authorize(store,client,999)


def test_deployment_nonce_cannot_be_reused_for_another_owner_object(tmp_path):
    executor=FakeExecutor(tmp_path);auth=authorization()
    assert deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)['status']=='DEPLOYED_VERIFIED'
    changed=dict(auth,authorization_id=124)
    with pytest.raises(ValueError):deploy(executor,changed,origin='https://github.com/owner/repo.git',admit_again=lambda:changed)


def test_deployment_git_cannot_push_or_use_ambient_filters(tmp_path):
    from deployment_agent.executor import Executor
    root=tmp_path/'source';root.mkdir();ledger=tmp_path/'ledger';ledger.write_text('fixture');calls=[]
    def invoke(command,**kwargs):calls.append(command);return SimpleNamespace(returncode=0,stdout=b'filter.evil.smudge arbitrary-process')
    executor=Executor(root,tmp_path/'receipts',ledger,invoke=invoke)
    with pytest.raises(ValueError):executor.git('push','origin','main')
    assert not calls
    with pytest.raises(ValueError):executor.git('status','--porcelain','--untracked-files=no')
    assert len(calls)==1 and 'core.hooksPath=/dev/null' in calls[0] and 'protocol.ssh.allow=never' in calls[0]


def test_rollback_does_not_report_a_successful_deployment_exit():
    from deployment_agent.service import exit_code
    assert exit_code(dict(status='DEPLOYED_VERIFIED'))==0
    assert exit_code(dict(status='ROLLED_BACK'))==1
    assert exit_code(dict(status='ROLLED_BACK'),recovery=True)==0
    assert exit_code(dict(status='FAILED_PRECHECK'))==1


def test_signed_post_deploy_observation_requires_real_time_window(tmp_path):
    from deployment_agent.observer import observe
    import time
    executor=FakeExecutor(tmp_path);auth=authorization();receipt=deploy(executor,auth,origin='https://github.com/owner/repo.git',admit_again=lambda:auth)
    key=b'fixture-only-software-observation-key-123456789'
    assert observe(executor,receipt,key=key,now=receipt['finished']+1)['status']=='OBSERVATION_PENDING'
    healthy=observe(executor,receipt,key=key,now=receipt['finished']+301)
    assert healthy['observation']['status']=='HEALTHY'
    assert 'holdings_before' not in healthy['observation'] and healthy['observation']['repository']=='owner/repo'
    executor.mutated=True
    failed=observe(executor,receipt,key=key,now=receipt['finished']+302)
    assert failed['observation']['status']=='DEGRADED'
    def crash():raise ValueError('health unavailable')
    executor.health=crash
    assert observe(executor,receipt,key=key,now=receipt['finished']+303)['observation']['status']=='DEGRADED'


def test_deployment_queue_ignores_agents_and_limits_one_fixed_job(owner_setup,tmp_path):
    from deployment_agent.poller import pending
    store,client,_=owner_setup
    rows=[dict(id=1,user=dict(id=2,login='agent',type='User'),body='OWNER-DEPLOY deployment-1\n{}'),dict(id=2,user=dict(id=1,login='owner',type='User'),body='OWNER-DEPLOY deployment-1\n{}'),dict(id=3,user=dict(id=1,login='owner',type='User'),body='OWNER-DEPLOY deployment-1\n{}')]
    client.read=lambda endpoint:rows
    assert pending(client,tmp_path)==[2]
    (tmp_path/'deploy-2.json').write_text('{}')
    assert pending(client,tmp_path)==[3]


def test_ledger_append_only_development_records_are_expected_but_mutation_is_not(tmp_path):
    from deployment_agent.executor import Executor
    from dev_agent.store import Store
    import sqlite3
    root=tmp_path/'source';root.mkdir();(root/'holdings.csv').write_text('ticker,shares\nFIXTURE,10\n')
    (root/'out').mkdir();
    with sqlite3.connect(root/'out/investment.db') as db:db.execute('CREATE TABLE financial(value)')
    ledger=Store(tmp_path/'authority/development-control.sqlite3');ledger.migrate()
    executor=Executor(root,tmp_path/'receipts',ledger.path)
    before=executor.protected();ledger.event(None,'SCHEDULE',dict(status='COLLECTED'))
    after=executor.protected()
    assert before!=after and executor.protected_unchanged(before,after)
    with sqlite3.connect(ledger.path) as db:db.execute('DROP TRIGGER dev_events_update');db.execute("UPDATE dev_events SET payload='{}'")
    assert not executor.protected_unchanged(before,executor.protected())


@pytest.mark.parametrize('mutation',[None,{'performed_via_github_app':dict(id=1144995,slug='other-app')},{'performed_via_github_app':dict(id=9,slug='chatgpt-codex-connector')},{'user':dict(id=2,login='agent',type='User')},{'user':dict(id=1,login='owner',type='Bot')},{'updated_at':'edited'}])
def test_real_shape_connector_owner_deploy_keeps_all_admission_guards(authorized_owner,monkeypatch,mutation):
    from test_continuous_improvement import CONNECTOR_APP,allow_connector
    from deployment_agent.admission import authorize
    store,client,obj,data=authorized_owner
    obj['performed_via_github_app']=dict(CONNECTOR_APP)
    with pytest.raises(ValueError):authorize(store,client,999)
    allow_connector(monkeypatch)
    # Approval policy is SHA-bound and policy-bound: refresh under explicit app policy.
    from test_development_agent_owner_review import approve
    from dev_agent.identity import HumanIdentity,_PROOF
    approve((store,client,HumanIdentity('human-owner','os-interactive-cli',_PROOF)),nonce='connector-policy-review-0002')
    if mutation:
        obj.update(mutation)
        with pytest.raises(ValueError):authorize(store,client,999)
    else:
        assert authorize(store,client,999)['merge_sha']==data['merge_sha']
        obj['body']='OWNER-DEPLOY deployment-1\n'+json.dumps(dict(data,head='f'*40))
        with pytest.raises(ValueError):authorize(store,client,999)
