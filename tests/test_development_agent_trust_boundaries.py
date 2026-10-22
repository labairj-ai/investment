"""0803–0809 adversarial checks; fixtures never establish operational readiness."""
from email.message import Message
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import time

import pytest

from test_development_agent import repo, store, commit, proposal
from development_fixtures import protection_observation, start_protection, client, human
from dev_agent import policy, test_oracle, protection, identity, github
from dev_agent.git_exec import run, environment
from dev_agent.runner import ContainerValidator
from dev_agent.store import digest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path',['tests/conftest.py','conftest.py','pytest.ini','.pytest.ini','pytest.toml','.pytest.toml','tox.ini','pyproject.toml','setup.cfg','sitecustomize.py','usercustomize.py'])
def test_runner_configuration_requires_human_start(path):
    assert int(policy.classify([path])['risk'][1:])>=3


def test_plugin_declaration_is_not_an_ordinary_l1_test():
    assert int(policy.classify(['tests/test_plugin.py'],diff='+pytest_plugins=["evil"]')['risk'][1:])>=3


@pytest.mark.parametrize('text',['<script>alert(1)</script>','<p onclick="go()">x</p>',
    '<a href="java&#115;cript:alert(1)">x</a>','<svg><script/></svg>',
    '<svg><use href="https://evil.test/x"/></svg>','<iframe src="/app"/>',
    '<form action="/mutate"/>','<img src="https://evil.test/pixel">',
    '<p style="background:url(https://evil.test/x)">x</p>',
    '<script type="module">import("/x.js")</script>'])
def test_active_content_escalates(text):
    result=policy.classify(['static/view.html'],content={'static/view.html':('<p>old</p>',text)})
    assert int(result['risk'][1:])>=3
    assert result['reasons'][0]['reason']=='active or unproven HTML/SVG content'


def test_passive_and_css_classification():
    assert policy.classify(['static/a.css'])['risk']=='L2'
    assert policy.classify(['static/a.html'])['risk']=='L3'
    assert policy.classify(['static/a.html'],content={'static/a.html':('<p>old</p>','<p>new</p>')})['risk']=='L2'
    assert policy.classify(['static/a.js'])['risk']=='L3'


@pytest.mark.parametrize('name',['pre-commit','prepare-commit-msg','commit-msg','post-commit'])
def test_real_repository_hooks_never_execute(repo,tmp_path,name):
    hooks=repo/'.git/hooks';hooks.mkdir(exist_ok=True)
    marker=tmp_path/'executed'
    hook=hooks/name;hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\nexit 1\n');hook.chmod(0o755)
    (repo/'docs/note.md').write_text('legitimate change')
    run(repo,'add','docs/note.md');run(repo,'commit','-m','trusted operation')
    assert not marker.exists()


def test_global_hooks_and_ambient_git_injection_are_ignored(repo,tmp_path,monkeypatch):
    hooks=tmp_path/'global-hooks';hooks.mkdir();marker=tmp_path/'global-executed'
    hook=hooks/'pre-commit';hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\nexit 1\n');hook.chmod(0o755)
    config=tmp_path/'gitconfig';config.write_text('[core]\n hooksPath = '+str(hooks)+'\n')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL',str(config));monkeypatch.setenv('GIT_CONFIG_COUNT','1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0','core.hooksPath');monkeypatch.setenv('GIT_CONFIG_VALUE_0',str(hooks))
    (repo/'docs/note.md').write_text('legitimate change')
    run(repo,'add','docs/note.md');run(repo,'commit','-m','trusted operation')
    assert not marker.exists() and environment()['GIT_CONFIG_GLOBAL']=='/dev/null'
    assert 'GIT_CONFIG_COUNT' not in environment()
    assert config.read_text().startswith('[core]')  # human configuration untouched


def test_pre_push_and_foreign_transport_cannot_execute(repo,tmp_path):
    marker=tmp_path/'pushed'
    hook=repo/'.git/hooks/pre-push';hook.parent.mkdir(exist_ok=True)
    hook.write_text('#!/bin/sh\ntouch '+str(marker)+'\n');hook.chmod(0o755)
    with pytest.raises(subprocess.CalledProcessError):run(repo,'push',str(tmp_path/'foreign.git'),'HEAD')
    assert not marker.exists()


def test_ambient_executable_clean_filter_fails_closed(repo):
    subprocess.run(['git','-C',str(repo),'config','filter.evil.clean','echo compromised'],check=True)
    with pytest.raises(ValueError,match='filters'):run(repo,'add','.')


def test_trusted_base_oracle_ignores_candidate_test_and_runner_changes(repo):
    base=run(repo,'rev-parse','HEAD').stdout.strip();original=test_oracle.files(repo,base)
    (repo/'tests/test_oracle.py').write_text('import pytest\npytest.skip("hide everything",allow_module_level=True)\n')
    (repo/'tests/conftest.py').write_text('raise RuntimeError("candidate plugin ran")\n')
    (repo/'sitecustomize.py').write_text('raise RuntimeError("startup injection")\n')
    (repo/'pytest.ini').write_text('[pytest]\naddopts=--ignore=tests\n')
    assert test_oracle.files(repo,base)==original
    assert 'tests/conftest.py' not in original and 'sitecustomize.py' not in original
    assert test_oracle.tree_hash(original)==test_oracle.tree_hash(test_oracle.files(repo,base))


def test_unreconstructable_base_oracle_fails_closed(repo):
    with pytest.raises((ValueError,subprocess.CalledProcessError)):test_oracle.files(repo,'f'*40)


def test_container_receives_only_trusted_mandatory_tests_and_configs(repo,monkeypatch):
    import dev_agent.runner as module
    base=run(repo,'rev-parse','HEAD').stdout.strip()
    (repo/'tests/test_oracle.py').write_text('raise RuntimeError("candidate test")\n')
    (repo/'tests/conftest.py').write_text('raise RuntimeError("candidate plugin")\n')
    (repo/'sitecustomize.py').write_text('raise RuntimeError("startup")\n')
    (repo/'pytest.ini').write_text('[pytest]\naddopts=--ignore=tests\n')
    real=subprocess.run;seen=[]
    def invoke(argv,**kwargs):
        if argv[0]!='docker':return real(argv,**kwargs)
        if argv[1]=='rm':return subprocess.CompletedProcess(argv,0)
        mounts=[argv[i+1] for i,a in enumerate(argv[:-1]) if a=='--mount']
        mount=next(m for m in mounts if 'dst=/source,' in m)
        source=Path(mount.split('src=',1)[1].split(',')[0])
        assert mount.endswith(',readonly')
        assert (source/'tests/test_oracle.py').read_text()=='def test_oracle(): assert True\n'
        assert not (source/'tests/conftest.py').exists()
        assert not (source/'sitecustomize.py').exists() and not (source/'pytest.ini').exists()
        assert '--network=none' in argv and '--pull=never' in argv and '-I' in argv
        assert not any('GITHUB_TOKEN' in a or 'docker.sock' in a for a in argv)
        artifact=next(m for m in mounts if 'dst=/artifacts' in m)
        dest=Path(artifact.split('src=',1)[1].split(',')[0])
        (dest/'inventory.json').write_text(json.dumps(['tests.test_oracle::test_oracle']))
        (dest/'results.xml').write_text('<testsuites><testsuite><testcase classname="tests.test_oracle" name="test_oracle"/></testsuite></testsuites>')
        seen.append(argv);return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(module.shutil,'which',lambda name:'/fixture/docker')
    monkeypatch.setattr(module.subprocess,'run',invoke)
    validator=ContainerValidator('fixture@sha256:'+'a'*64);validator.prior_base=base
    result=validator.run(repo,'full_suite',['python','-m','pytest','tests/'])
    assert result['status']=='PASS' and seen
    assert result['trusted_test_tree_hash']==test_oracle.tree_hash(test_oracle.files(repo,base))
    assert result['candidate_source_tree_hash']


def proxy_handler(actor='alice@example.test',peer='127.0.0.1',listener='127.0.0.1'):
    headers=Message()
    if actor is not None:headers['Tailscale-User-Login']=actor
    return SimpleNamespace(headers=headers,client_address=(peer,1234),server=SimpleNamespace(server_address=(listener,5001)))


def test_unique_proxy_operator_identity_and_no_payload_actor(monkeypatch):
    monkeypatch.setenv('DEV_AGENT_IDENTITY_SOURCE','tailscale-serve')
    monkeypatch.setenv('DEV_AGENT_OPERATORS','alice@example.test,bob@example.test')
    alice=identity.dashboard_identity(proxy_handler());bob=identity.dashboard_identity(proxy_handler('bob@example.test'))
    assert alice.actor!=bob.actor and alice.source=='tailscale-serve-loopback'
    assert not any('token' in key.lower() for key in alice.audit())


@pytest.mark.parametrize('change',[{'actor':None},{'actor':'mallory@example.test'},{'peer':'100.100.100.100'},{'listener':'0.0.0.0'}])
def test_shared_token_and_spoofed_identity_cannot_authenticate(monkeypatch,change):
    monkeypatch.setenv('DEV_AGENT_IDENTITY_SOURCE','tailscale-serve');monkeypatch.setenv('DEV_AGENT_OPERATORS','alice@example.test')
    with pytest.raises(ValueError):identity.dashboard_identity(proxy_handler(**change))


def test_operator_actor_overrides_supplied_actor_in_ledger(repo,store):
    from dev_agent.discovery import plan
    cid=store.discover(proposal());ctx=plan(repo,store,cid,['The requested documentation is complete.'])
    store.decide(cid,'approve','mallory',ctx,'unique','scope approved',identity=human())
    approval=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='APPROVAL'][-1]
    assert approval['actor']=='alice@example.test' and approval['decision_nonce']=='unique'
    with pytest.raises(ValueError):store.decide(cid,'approve','bob',ctx,'unique','replay',identity=human('bob@example.test'))


@pytest.mark.parametrize('stage',['pr_disposition','merge','deployment_observation','pilot_success'])
@pytest.mark.parametrize('variant',['fail','stale','identity','policy','unavailable'])
def test_protection_drift_at_late_boundaries_is_rejected(repo,store,stage,variant):
    from dev_agent.discovery import plan
    cid=store.discover(proposal());ctx=plan(repo,store,cid,['The requested documentation is complete.'])
    store.decide(cid,'approve','human',ctx,'admit',identity=human())
    adapter=client();start_protection(store,cid,adapter,ROOT)
    if variant=='fail':adapter.protections=lambda:protection_observation(status='FAIL')
    elif variant=='stale':adapter.protections=lambda:protection_observation(created=time.time()-301)
    elif variant=='identity':adapter.protections=lambda:protection_observation(identity='administrator')
    elif variant=='policy':adapter.protections=lambda:protection_observation(effective={'pr':True,'checks':True,'review':True,'new_rule':True})
    else:adapter.protections=lambda:dict(status='UNAVAILABLE')
    with pytest.raises(ValueError):protection.require(store,cid,adapter,stage,root=ROOT)
    events=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='PROTECTION']
    assert events[-1]['status']=='FAIL' and events[-1]['reason']
    assert store.get(cid)['state']=='NEEDS_HUMAN'


def test_stable_protection_has_bound_identity_policy_and_raw_evidence(repo,store):
    from dev_agent.discovery import plan
    cid=store.discover(proposal());plan(repo,store,cid,['The requested documentation is complete.'])
    adapter=client();start=start_protection(store,cid,adapter,ROOT)
    for stage in ['publish','pr_handoff','pr_disposition','merge','deployment_observation','pilot_success']:
        observation=protection.require(store,cid,adapter,stage,root=ROOT)
        assert observation['policy_hash']==start['policy_hash'] and observation['identity']=='agent'
        assert observation['raw_evidence_hash']==digest(adapter.protections()['evidence'])


def test_ci_workflow_has_no_host_candidate_execution():
    workflow=(ROOT/'.github/workflows/test.yml').read_text()
    assert 'contents: read' in workflow and 'persist-credentials: false' in workflow
    assert 'DEV_AGENT_ORCHESTRATOR_SHA' in workflow and 'DEV_AGENT_VALIDATOR_IMAGE' in workflow
    assert 'pip install' not in workflow and 'continue-on-error' not in workflow
    assert 'pull_request_target' not in workflow and 'secrets.' not in workflow
    for line in workflow.splitlines():
        if 'uses:' in line:assert len(line.split('@')[1].split()[0])==40


def test_forged_junit_inventory_cannot_satisfy_mandatory_validation(repo,monkeypatch):
    import dev_agent.runner as module
    base=run(repo,'rev-parse','HEAD').stdout.strip();real=subprocess.run
    def invoke(argv,**kwargs):
        if argv[0]!='docker':return real(argv,**kwargs)
        if argv[1]=='rm':return subprocess.CompletedProcess(argv,0)
        mounts=[argv[i+1] for i,a in enumerate(argv[:-1]) if a=='--mount']
        artifact=next(m for m in mounts if 'dst=/artifacts' in m)
        out=Path(artifact.split('src=',1)[1].split(',')[0])
        (out/'inventory.json').write_text(json.dumps(['tests.test_oracle::test_oracle']))
        (out/'results.xml').write_text('<testsuites><testsuite><testcase classname="candidate" name="fabricated_pass"/></testsuite></testsuites>')
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(module.shutil,'which',lambda name:'/fixture/docker');monkeypatch.setattr(module.subprocess,'run',invoke)
    validator=ContainerValidator('fixture@sha256:'+'a'*64);validator.prior_base=base
    assert validator.run(repo,'full_suite',['python','-m','pytest','tests/'])['status']=='FAIL'
    assert validator._full_junit is None
    # The exact same candidate-owned report is supplemental only and cannot
    # replace the mandatory inventory or supply a mandatory validation success.
    assert validator.run(repo,'supplemental_tests',['python','-m','pytest','tests/'])['status']=='PASS'
    assert validator._full_junit is None


def test_receipts_bind_both_oracle_and_candidate_hashes(repo,store,tmp_path):
    from test_development_agent_hardening import built,make_trusted_proof
    cid,work=built(repo,store,tmp_path);proof=make_trusted_proof(work,store,cid)
    batch=[e['payload'] for e in store.get(cid)['events'] if e['kind']=='VALIDATION_BATCH'][-1]
    expected=test_oracle.tree_hash(test_oracle.files(work,proof['base']))
    assert batch['trusted_test_tree_hash']==expected
    assert batch['candidate_source_tree_hash']==proof['source_hash']
    assert all(v['trusted_test_tree_hash']==expected and v['candidate_source_tree_hash']==proof['source_hash'] for v in proof['validations'])
    supplemental=[e for e in store.get(cid)['events'] if e['kind']=='SUPPLEMENTAL_VALIDATION']
    assert len(supplemental)==1 and len(proof['validations'])==7


@pytest.mark.parametrize('boundary',['merge','pilot_success'])
@pytest.mark.parametrize('failure',['admin','bypass','stale','unavailable'])
def test_actual_merge_and_pilot_apis_reject_protection_failure(store,boundary,failure):
    from test_development_agent_hardening import seed_completed_pilot
    from dev_agent import operations
    cid,adapter=seed_completed_pilot(store)
    if failure=='stale':adapter.protections=lambda:protection_observation(created=time.time()-301)
    elif failure=='unavailable':adapter.protections=lambda:dict(status='UNAVAILABLE')
    else:adapter.protections=lambda:protection_observation(status='FAIL',failures=[failure])
    with pytest.raises(ValueError):
        if boundary=='merge':github.record_merge(store,cid,adapter)
        else:operations.record_success(ROOT,store,cid,adapter,human=human())
    assert store.get(cid)['state']=='NEEDS_HUMAN'
    assert not operations.operational_runs(ROOT,store)['qualifying']


def test_missing_runtime_is_unavailable_not_pass(monkeypatch):
    from dev_agent import containment
    monkeypatch.setattr(containment.shutil,'which',lambda name:None)
    assert containment.probe('fixture@sha256:'+'a'*64)['status']=='UNAVAILABLE'


def test_restored_policy_does_not_erase_drift_or_requalify_old_pilot(store):
    from test_development_agent_hardening import seed_completed_pilot
    from dev_agent import operations
    cid,adapter=seed_completed_pilot(store)
    operations.record_success(ROOT,store,cid,adapter,human=human())
    assert operations.operational_runs(ROOT,store)['qualifying']
    good=adapter.protections
    adapter.protections=lambda:protection_observation(status='FAIL')
    with pytest.raises(ValueError):github.record_merge(store,cid,adapter)
    adapter.protections=good
    with pytest.raises(ValueError,match='fresh human scope'):operations.record_success(ROOT,store,cid,adapter,human=human())
    assert not operations.operational_runs(ROOT,store)['qualifying']
    assert store.get(cid)['state']=='NEEDS_HUMAN'


def test_candidate_added_test_is_supplemental_without_replacing_base_focus(repo):
    from dev_agent.validation import manifest
    base=run(repo,'rev-parse','HEAD').stdout.strip()
    (repo/'tests/test_new.py').write_text('def test_new(): assert True\n')
    focused=manifest(['tests/test_new.py'],base,root=repo)[0]
    assert focused[0]=='focused_tests' and focused[1][3]=='tests/'
    assert 'tests/test_new.py' not in focused[1]
    assert 'tests/test_oracle.py' in test_oracle.files(repo,base)


def test_ambiguous_content_representation_cannot_be_classified_passive():
    with pytest.raises(ValueError):policy.classify(['static/a.svg'],content={'static/a.svg':'<script/>'})
