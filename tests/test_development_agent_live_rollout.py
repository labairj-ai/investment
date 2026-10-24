"""0851–0854 source regressions; all identities/data are synthetic, no live credit."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
from types import SimpleNamespace
import urllib.request
import pytest
from test_development_agent import store,proposal
from test_pr13_evidence_integrity import schedule_payload,scheduled_store,append
from dev_agent.github import GitHub,_ReadOnlyGitHubRedirect
from dev_agent import scheduler_health
from dev_agent.store import Store
ROOT=Path(__file__).resolve().parents[1]


def raw_pr():
    return dict(number=15,html_url='https://github.com/owner/repo/pull/15',state='open',merged=False,draft=False,merge_commit_sha='b'*40,
                head=dict(ref='agent/0851/help',sha='a'*40,repo=dict(full_name='owner/repo',name='repo',owner=dict(login='owner'))),
                base=dict(ref='main',repo=dict(full_name='owner/repo')))


def test_rest_identity_does_not_depend_on_empty_cli_repository(monkeypatch):
    client=GitHub('owner/repo');raw=raw_pr();client.read=lambda endpoint:copy.deepcopy(raw)
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('must not use gh pr view normalization'))
    r=client.pr_identity(15)
    assert r['headRepository']['nameWithOwner']=='owner/repo' and r['headRefOid']=='a'*40
    assert r['state']=='OPEN' and r['mergeCommit'] is None
    raw.update(merged=True,state='closed')
    assert client.pr_identity(15)['mergeCommit']==dict(oid='b'*40)


@pytest.mark.parametrize('attack',['wrong_pr','base_repo','head_repo','null_repo','bad_sha','missing_draft','merged_open','bad_merge','wrong_url'])
def test_rest_identity_incomplete_facts_fail_closed(attack):
    raw=raw_pr()
    if attack=='wrong_pr':raw['number']=16
    if attack=='base_repo':raw['base']['repo']['full_name']='other/repo'
    if attack=='head_repo':raw['head']['repo']['full_name']='other/repo'
    if attack=='null_repo':raw['head']['repo']=None
    if attack=='bad_sha':raw['head']['sha']='HEAD'
    if attack=='missing_draft':del raw['draft']
    if attack=='merged_open':raw['merged']=True
    if attack=='bad_merge':raw.update(merged=True,state='closed',merge_commit_sha=None)
    if attack=='wrong_url':raw['html_url']='https://github.com/owner/repo/pull/16'
    client=GitHub('owner/repo');client.read=lambda _:raw
    with pytest.raises(ValueError):client.pr_identity(15)


def test_read_only_http_transport_has_no_cli_dependency_or_token_output(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='fixture-gh-',dir=Path.home()) as directory:
        token=Path(directory)/'read.token';token.write_text('fixture-token-not-real');token.chmod(0o600)
        monkeypatch.setenv('DEV_AGENT_GITHUB_READ_TOKEN_FILE',str(token));requests=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'{"permissions":{"pull":true,"push":false}}'
        def request(req,timeout):requests.append(req);return Response()
        monkeypatch.setattr(urllib.request,'build_opener',lambda *a:SimpleNamespace(open=request))
        monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('read-only host must not need owner gh credentials'))
        assert GitHub('owner/repo').read('repos/owner/repo')['permissions']['push'] is False
        assert requests[0].full_url=='https://api.github.com/repos/owner/repo'
        token.chmod(0o644)
        with pytest.raises(ValueError):GitHub('owner/repo').read('repos/owner/repo')


def test_read_credential_cannot_follow_external_redirect():
    req=urllib.request.Request('https://api.github.com/repos/owner/repo',headers={'Authorization':'Bearer fixture'})
    with pytest.raises(ValueError):_ReadOnlyGitHubRedirect().redirect_request(req,None,302,'redirect',{},'https://attacker.example/steal')


def load_oracle():
    spec=importlib.util.spec_from_file_location('rollout_oracle',ROOT/'ops/validator/static_oracle.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def socket_path():
    # Darwin's Unix socket pathname limit is shorter than pytest's long temp names.
    with tempfile.TemporaryDirectory(prefix='orcl-',dir='/tmp') as directory:
        yield Path(directory)/'s'


def test_stale_private_socket_can_restart_but_live_listener_is_preserved(socket_path):
    oracle=load_oracle();path=socket_path
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));path.chmod(0o600);server.listen()
    with pytest.raises(ValueError,match='active'):oracle.clear_stale_socket(path)
    assert path.is_socket()
    server.close();oracle.clear_stale_socket(path);assert not path.exists()


@pytest.mark.parametrize('attack',['file','symlink','public_socket'])
def test_socket_restart_refuses_permission_or_path_attacks(socket_path,tmp_path,attack):
    oracle=load_oracle();path=socket_path;server=None
    if attack=='file':path.write_text('not a socket')
    if attack=='symlink':path.symlink_to(tmp_path/'absent')
    if attack=='public_socket':
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));server.close();path.chmod(0o666)
    with pytest.raises(ValueError):oracle.clear_stale_socket(path)
    assert path.exists() or path.is_symlink()


def qualifying_payload(now,*,head='a'*40,candidates=(),age=0,invocation='a'*32):
    return dict(schedule_payload(now,age=age,invocation=invocation),head=head,candidates=list(candidates),created=len(candidates),
                deduplicated=0,suppressed=0,signal_count=0,proposal_count=len(candidates),enabled_sources=['ci','telemetry','performance'],unavailable=['user_feedback'])


def test_three_distinct_exact_source_runs_need_separate_host_safety_acceptance(store,monkeypatch):
    now=time.time();scheduled_store(store,now)
    for age,char in enumerate('abc'):append(store,'SCHEDULE',qualifying_payload(now,age=age,invocation=char*32))
    before=store.path.read_bytes()
    report=scheduler_health.acceptance(store,'a'*40,now)
    assert report['successful_runs']==3 and report['status']=='NOT READY' and not report['host_safety_accepted']
    monkeypatch.setattr(scheduler_health,'host_safety',lambda *a:True) # synthetic external boundary only
    assert scheduler_health.acceptance(store,'a'*40,now)['status']=='READY'
    assert scheduler_health.acceptance(store,'b'*40,now)['successful_runs']==0
    assert store.path.read_bytes()==before


@pytest.mark.parametrize('attack',['manual','fixture','duplicate_slot','duplicate_invocation','failed','missing_counts','unavailable_ci','unknown_source_inventory'])
def test_timer_acceptance_cannot_be_filled_by_fixture_manual_or_incomplete_runs(store,attack):
    now=time.time();p=qualifying_payload(now)
    if attack=='manual':p['trigger']=dict(source='operator',invocation=None)
    if attack=='fixture':p['fixture_only']=True
    if attack=='missing_counts':del p['signal_count']
    if attack=='unavailable_ci':p['unavailable']=['CI']
    if attack=='unknown_source_inventory':del p['enabled_sources']
    append(store,'SCHEDULE',p)
    if attack in {'duplicate_slot','duplicate_invocation'}:
        other=qualifying_payload(now,age=0 if attack=='duplicate_slot' else 1,invocation='b'*32 if attack=='duplicate_slot' else 'a'*32)
        append(store,'SCHEDULE',other)
    if attack=='failed':append(store,'SCHEDULE_FAILURE',dict(p,status='FAILED'))
    count=len(scheduler_health.accepted_runs(store,'a'*40,now))
    assert count==(1 if attack in {'duplicate_slot','duplicate_invocation'} else 0)


def test_real_pilot_provenance_requires_accepted_current_candidate_not_fixture(store,monkeypatch):
    now=time.time();scheduled_store(store,now);cid=store.discover(proposal())
    for age,char in enumerate('abc'):append(store,'SCHEDULE',qualifying_payload(now,candidates=[cid],age=age,invocation=char*32))
    with pytest.raises(ValueError):scheduler_health.require_candidate(store,cid,'a'*40,now)
    monkeypatch.setattr(scheduler_health,'host_safety',lambda *a:True)
    assert scheduler_health.require_candidate(store,cid,'a'*40,now)['candidate']==cid
    other=store.discover(proposal(problem='Manually seeded different issue'))
    with pytest.raises(ValueError):scheduler_health.require_candidate(store,other,'a'*40,now)
    store.event(cid,'SIGNAL_OBSERVATION',dict(synthetic=True))
    with pytest.raises(ValueError):scheduler_health.require_candidate(store,cid,'a'*40,now)


def executor_fixture(tmp_path):
    from deployment_agent.executor import Executor
    root=tmp_path/'source';root.mkdir();(root/'out').mkdir();(root/'holdings.csv').write_text('ticker,shares\nFIXTURE,1\n')
    for name in ['investment.db','buffett.db']:
        with sqlite3.connect(root/'out'/name) as db:db.execute('CREATE TABLE value(x)');db.execute("INSERT INTO value VALUES ('fixture')")
    ledger=Store(tmp_path/'authority/development-control.sqlite3');ledger.migrate()
    return Executor(root,tmp_path/'receipts',ledger.path),ledger


def test_controller_backs_up_and_protects_auxiliary_investment_state(tmp_path):
    executor,ledger=executor_fixture(tmp_path);before=executor.protected()
    backup=executor.backup(tmp_path/'backup')
    assert set(backup['databases'])=={'investment.db','buffett.db'}
    assert all(r['integrity']=='ok' for r in backup['databases'].values())
    assert executor.protected_unchanged(before,executor.protected())
    with sqlite3.connect(executor.root/'out/buffett.db') as db:db.execute("UPDATE value SET x='changed'")
    assert not executor.protected_unchanged(before,executor.protected())


def test_new_audit_kinds_are_append_only_but_unknown_kinds_fail(tmp_path):
    executor,ledger=executor_fixture(tmp_path);before=executor.protected()
    with ledger.connect(True) as db:
        for kind in ['OWNER_MERGE','STATIC_VALIDATION']:ledger._append(db,None,kind,{'fixture_only':True},kind)
    assert executor.protected_unchanged(before,executor.protected())
    ledger.event(None,'UNREVIEWED_KIND',{})
    assert not executor.protected_unchanged(before,executor.protected())


def test_read_only_file_bits_do_not_hide_parent_replacement_authority(tmp_path):
    from deployment_agent.installation import permission_findings
    root=tmp_path/'source';root.mkdir();(root/'.env').write_text('fixture')
    findings=permission_findings(root,writable=lambda p:p==root,readable=lambda p:p.name=='.env')
    assert any('replace' in f for f in findings) and any('credentials' in f for f in findings)


def test_installation_source_plan_and_wrong_head_are_bound(tmp_path):
    from ops.validator.install import prepare
    from ops.install_discovery import prepare as discovery_prepare,UNITS
    root=tmp_path/'repo';root.mkdir()
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
    git('init','-q');git('config','user.name','fixture');git('config','user.email','fixture@example.invalid')
    names=['ops/validator/static_oracle.py','ops/validator/investment-static-oracle.service','config/development_agent.json',*['systemd/'+n for n in UNITS]]
    for name in names:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
    git('add','.');git('commit','-qm','synthetic reviewed source');head=git('rev-parse','HEAD')
    git('remote','add','origin','https://github.com/owner/repo.git');git('update-ref','refs/remotes/origin/main',head)
    assert prepare(root,head,'owner/repo')['head']==head
    assert len(discovery_prepare(root,head,'owner/repo')['files'])==6
    with pytest.raises(ValueError):prepare(root,'0'*40,'owner/repo')
    (root/'config/development_agent.json').write_text('{}')
    with pytest.raises(ValueError):discovery_prepare(root,head,'owner/repo')


def test_bootstrap_never_runs_host_commands_from_development_account(monkeypatch):
    from ops.validator import install
    monkeypatch.setattr(install.os,'geteuid',lambda:501)
    with pytest.raises(ValueError):install.apply({},invoke=lambda *a,**k:pytest.fail('no host mutation'))


def test_discovery_bootstrap_refuses_owner_push_capability():
    from ops.install_discovery import verify_reader
    client=SimpleNamespace(repository='owner/repo',read=lambda p:dict(full_name='owner/repo',permissions=dict(pull=True,push=True,admin=True,maintain=True)))
    with pytest.raises(ValueError):verify_reader(client)
    client.read=lambda p:dict(full_name='owner/repo',permissions=dict(pull=True,push=False,admin=False,maintain=False))
    verify_reader(client)


@pytest.mark.parametrize('failure',['none','length','tool_call','bad_json','not_object','duplicate','oversize'])
def test_mlx_builder_adapter_is_bounded_and_never_grants_native_tools(monkeypatch,failure):
    from dev_agent.providers import MLXProvider
    calls=[];content='{"actions":[],"done":true}'
    if failure=='bad_json':content='not JSON'
    if failure=='not_object':content='[]'
    if failure=='duplicate':content='{"done":true,"done":false}'
    message=dict(content=content)
    if failure=='tool_call':message['tool_calls']=[dict(name='shell')]
    raw=json.dumps(dict(choices=[dict(message=message,finish_reason='length' if failure=='length' else 'stop')])).encode()
    if failure=='oversize':raw=b'x'*500001
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return raw
    def open_(request,timeout):calls.append((json.loads(request.data),timeout));return Response()
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:SimpleNamespace(open=open_))
    provider=MLXProvider(MLXProvider.MODEL,'http://100.73.128.40:8080/v1/chat/completions',timeout=500)
    if failure=='none':assert provider.respond(dict(role='builder'))==dict(actions=[],done=True)
    else:
        with pytest.raises(ValueError):provider.respond(dict(role='builder'))
    payload,timeout=calls[0]
    assert timeout==60 and payload['chat_template_kwargs']['enable_thinking'] is False
    assert 'tools' not in payload and payload['max_tokens']==2048


@pytest.mark.parametrize('endpoint',['http://100.73.128.40:8081/v1/chat/completions','https://external.example/v1/chat/completions','http://127.0.0.1:11434/api/chat'])
def test_mlx_cannot_target_news_server_or_unapproved_host(endpoint):
    from dev_agent.providers import MLXProvider
    with pytest.raises(ValueError):MLXProvider(MLXProvider.MODEL,endpoint)
    with pytest.raises(ValueError):MLXProvider('unreviewed/new-download','http://100.73.128.40:8080/v1/chat/completions')


def test_provider_selection_is_operator_configuration_only(monkeypatch):
    from dev_agent.providers import configured_provider,MLXProvider,OllamaProvider
    monkeypatch.delenv('DEV_AGENT_BUILDER_ENDPOINT',raising=False)
    assert isinstance(configured_provider('fixture','builder'),OllamaProvider)
    monkeypatch.setenv('DEV_AGENT_BUILDER_ENDPOINT','http://100.73.128.40:8080/v1/chat/completions')
    assert isinstance(configured_provider(MLXProvider.MODEL,'builder'),MLXProvider)
    with pytest.raises(ValueError):configured_provider(MLXProvider.MODEL,'owner')


def test_low_risk_auto_pr_recommendation_never_changes_activation(store,monkeypatch):
    from dev_agent import promotion
    before=(ROOT/'config/development_agent.json').read_bytes()
    monkeypatch.setattr(promotion,'qualifying_evidence',lambda *a,**k:dict(blockers=['three real releases missing'],safety_configuration={'autonomous_implementation':False}))
    report=promotion.report(ROOT,store)
    assert report['owner_status'].startswith('LOW-RISK AUTO-PR: NOT READY') and not report['enables_autonomy']
    monkeypatch.setattr(promotion,'qualifying_evidence',lambda *a,**k:dict(blockers=[],safety_configuration={'autonomous_implementation':False}))
    report=promotion.report(ROOT,store)
    assert report['owner_status']=='LOW-RISK AUTO-PR: READY' and not report['grants_merge'] and not report['grants_deployment']
    assert (ROOT/'config/development_agent.json').read_bytes()==before


@pytest.mark.parametrize('stop_ok',[True,False])
def test_oracle_partial_bootstrap_never_removes_files_under_running_service(tmp_path,monkeypatch,stop_ok):
    from ops.validator import install
    for name in ('SOURCE','CONFIG','STATE','UNIT'):
        monkeypatch.setattr(install,name,tmp_path/name.lower())
    monkeypatch.setattr(install,'RUNTIME',Path(__file__))
    monkeypatch.setattr(install.sys,'platform','linux')
    monkeypatch.setattr(install.os,'geteuid',lambda:0)
    monkeypatch.setattr(install.os,'chown',lambda *a:None)
    monkeypatch.setattr(install.os,'getgrouplist',lambda *a:[123])
    monkeypatch.setattr(install.pwd,'getpwnam',lambda *a:SimpleNamespace(pw_dir='/nonexistent',pw_shell='/usr/sbin/nologin',pw_gid=123,pw_uid=456))
    monkeypatch.setattr(install.grp,'getgrnam',lambda *a:SimpleNamespace(gr_gid=123))
    monkeypatch.setattr(install,'protected_parents',lambda *a:None)
    def git(root,*args):
        if args[:2]==('bundle','create'):Path(args[2]).write_bytes(b'fixture');return b''
        return ('a'*40+' HEAD\n').encode()
    monkeypatch.setattr(install,'git',git)
    calls=[]
    def invoke(command,**kwargs):
        calls.append(command)
        if 'init' in command:Path(command[-1]).mkdir()
        if 'is-active' in command:raise subprocess.CalledProcessError(1,command)
        return SimpleNamespace(returncode=0 if 'stop' not in command or stop_ok else 1)
    plan=dict(root=str(tmp_path),head='a'*40,repository='owner/repo',files={'ops/validator/static_oracle.py':b'fixture','ops/validator/investment-static-oracle.service':b'fixture'})
    with pytest.raises(subprocess.CalledProcessError):install.apply(plan,invoke=invoke)
    assert any('stop' in c for c in calls)
    assert install.SOURCE.exists() is (not stop_ok)
    assert install.UNIT.exists() is (not stop_ok)
