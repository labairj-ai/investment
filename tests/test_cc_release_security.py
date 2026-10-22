"""0724–0728 adversarial release authorization regression tests."""
from cc_cli_fixtures import next_model_version
import json
import subprocess
from pathlib import Path

import pytest
import covered_call_change_control as cc
from strategy_config import CC_V3_CONFIG
from test_cc_adversarial_release import _make_manifest, _run


@pytest.fixture
def transition(tmp_path, monkeypatch):
    prior = cc.current_contract_state(CC_V3_CONFIG)
    current = dict(prior, engine_hash='engine-b', model_version=next_model_version())
    bf, pf, md = tmp_path/'candidate.json', tmp_path/'prior.json', tmp_path/'manifests'
    md.mkdir()
    pf.write_text(json.dumps(dict(prior, schema_version=cc.BASELINE_SCHEMA_VERSION)))
    bf.write_text(json.dumps(dict(current, schema_version=cc.BASELINE_SCHEMA_VERSION)))
    monkeypatch.setattr(cc, 'current_contract_state', lambda cfg: current)
    def check():
        return cc.check_contract_consistency(CC_V3_CONFIG, _baseline_file=bf,
                    trusted_prior_file=pf, _manifests_dir=md)
    return prior, current, bf, pf, md, check


def test_candidate_rewrite_cannot_hide_drift(transition):
    *_, check = transition
    result = check()
    assert not result['ok'] and result['hash_changed']
    assert any('APPLICABLE_MANIFEST' in f for f in result['findings'])


def test_approved_promotion_and_missing_candidate(transition):
    prior, current, bf, pf, md, check = transition
    _make_manifest(md, prior, current)
    assert check()['ok']
    bf.unlink()
    assert any('CANDIDATE_BASELINE_MISMATCH' in f for f in check()['findings'])


@pytest.mark.parametrize('text', ['{', '{}', 'unknown-schema'])
def test_invalid_prior_rejected(transition, text):
    *_, pf, md, check = transition
    if text == 'unknown-schema':
        data=json.loads(pf.read_text()); data['schema_version']='unknown'
        text=json.dumps(data)
    pf.write_text(text)
    assert not check()['ok']


def test_missing_prior_rejected(transition):
    *_, pf, md, check = transition
    pf.unlink()
    assert not check()['ok']


@pytest.mark.parametrize('field,value,code', [
    ('category','WHATEVER','INVALID_CHANGE_CATEGORY'),
    ('cohort_reset_required','false','COHORT_RESET_REQUIRED'),
    ('cohort_reset_required','banana','INVALID_BOOLEAN'),
    ('operator_acknowledged','no','INVALID_BOOLEAN'),
    ('open_chain_policy','anything','INVALID_OPEN_CHAIN_POLICY'),
])
def test_invalid_manifest_semantics(transition, field, value, code):
    prior, current, bf, pf, md, check = transition
    _make_manifest(md, prior, current)
    path = md/'test-manifest.md'
    lines = path.read_text().splitlines()
    path.write_text('\n'.join(f'{field}: {value}' if l.startswith(field+':') else l for l in lines))
    assert any(code in f for f in check()['findings'])


@pytest.mark.parametrize('field', sorted(cc.IDENTITY_FIELDS))
@pytest.mark.parametrize('side', ['prior', 'proposed'])
def test_every_identity_field_bound(transition, field, side):
    prior, current, bf, pf, md, check = transition
    _make_manifest(md, prior, current)
    fm = cc.parse_manifest(md/'test-manifest.md')
    assert cc._manifest_applies(fm, prior, current)
    fm[f'{side}_{field}'] = 'wrong'
    assert not cc._manifest_applies(fm, prior, current)


@pytest.mark.parametrize('field', sorted(cc.VERSION_PATTERNS))
def test_component_versions_forward_backward_malformed(field):
    values = dict(model_version=('cc-v3.2','cc-v3.3'), simulator_version=('cc-virtual-1','cc-virtual-2'),
                  simulator_contract_version=('simulator-contract-1','simulator-contract-2'),
                  policy_version=('shared-live-management-asof-1','shared-live-management-asof-2'),
                  cadence_comparability_policy_version=('cadence-v1','cadence-v2'))
    a,b = values[field]
    assert cc.version_transition(field,a,b) == 'FORWARD'
    assert cc.version_transition(field,b,a) == 'BACKWARD_VERSION'
    assert cc.version_transition(field,a,'banana') == 'MALFORMED_VERSION'
    assert cc.version_transition(field,a,a) == 'NO_VERSION_BUMP'


@pytest.mark.parametrize('field', sorted(cc.VERSION_PATTERNS))
def test_unchanged_behavior_version_drift_rejected(tmp_path, monkeypatch, field):
    state = cc.write_baseline(CC_V3_CONFIG, tmp_path/'prior.json')
    proposed = dict(state)
    proposed[field] = 'banana'
    monkeypatch.setattr(cc,'current_contract_state',lambda cfg: proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG, _baseline_file=tmp_path/'prior.json')
    assert any('UNJUSTIFIED_VERSION_DRIFT' in f for f in result['findings'])


def test_ci_generic_guard(tmp_path):
    # Explicit CI environment independent of the host runner.
    import os, sys
    result = subprocess.run([sys.executable,'scripts/check_cc_contract.py','--update-baseline',
                             '--baseline-file',str(tmp_path/'baseline.json')],
                            env=dict(os.environ, CI='true'), capture_output=True, text=True)
    assert result.returncode == 1
    assert not (tmp_path/'baseline.json').exists()


def test_template_has_complete_machine_fields():
    fm = cc.parse_manifest(Path('cc_change_manifests/.template.md'))
    assert cc.MANIFEST_REQUIRED_FIELDS <= fm.keys()
    assert not cc._manifest_valid(fm)[0]


def test_real_git_history_candidate_tamper_and_exact_sha(transition, tmp_path):
    prior, current, bf, pf, md, check = transition
    repo = tmp_path/'repo'; repo.mkdir()
    def git(*args):
        return subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
    git('init'); git('config','user.email','test@example.com'); git('config','user.name','Test')
    baseline = repo/'.cc_contract_baseline.json'; baseline.write_text(pf.read_text())
    (repo/'behavior.py').write_text('A')
    git('add','.'); git('commit','-m','A'); a=git('rev-parse','HEAD')
    baseline.write_text(bf.read_text()); (repo/'behavior.py').write_text('B')
    git('add','.'); git('commit','-m','B'); b=git('rev-parse','HEAD')
    def validate(ref, expected):
        return cc.check_contract_consistency(CC_V3_CONFIG, _baseline_file=baseline,
                prior_ref=ref, expected_prior_ref=expected, repo=repo, _manifests_dir=md)
    assert not validate(a,a)['ok']
    _make_manifest(md,prior,current)
    assert validate(a,a)['ok']
    assert not validate(a,b)['ok']  # stale A cannot authorize a B→C event
    assert validate(a,a)['trusted_prior_ref'] == a


@pytest.mark.parametrize('event_name', ['push','pull_request'])
def test_cli_exact_event_sha(tmp_path, event_name):
    import os, sys
    sha = subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    event = {'before':sha} if event_name=='push' else {'pull_request':{'base':{'sha':sha}}}
    path=tmp_path/'event.json'; path.write_text(json.dumps(event))
    env=dict(os.environ,GITHUB_ACTIONS='true',GITHUB_EVENT_NAME=event_name,GITHUB_EVENT_PATH=str(path))
    command=[sys.executable,'scripts/check_cc_contract.py','--json']
    result=subprocess.run(command,env=env,capture_output=True,text=True)
    assert result.returncode==0, result.stdout+result.stderr
    assert json.loads(result.stdout)['trusted_prior_ref']==sha
    wrong=subprocess.run(command+['--prior-ref','1'*40],env=env,capture_output=True,text=True)
    assert wrong.returncode==1


@pytest.mark.parametrize('event_name', ['push', 'pull_request'])
def test_real_cli_git_transition_and_manifest_replay(tmp_path, event_name):
    """Actual CLI computes B from files; committed A remains its event authority."""
    import os, sys, shutil
    repo=tmp_path/'repo'; (repo/'scripts').mkdir(parents=True)
    root=Path(__file__).resolve().parent.parent
    for name in ('covered_call_change_control.py','covered_call_fingerprint.py','scripts/check_cc_contract.py'):
        shutil.copyfile(root/name,repo/name)
    state=cc.current_contract_state(CC_V3_CONFIG)
    def write_state(value):
        (repo/'state.json').write_text(json.dumps(value))
        (repo/'.cc_contract_baseline.json').write_text(json.dumps(dict(value,schema_version=cc.BASELINE_SCHEMA_VERSION)))
    loader="import json\nfrom pathlib import Path\ns=json.loads(Path(__file__).with_name('state.json').read_text())\n"
    (repo/'strategy_config.py').write_text('CC_V3_CONFIG={}\n')
    (repo/'covered_call_validation.py').write_text(loader+"CADENCE_COMPARABILITY_POLICY_VERSION=s['cadence_comparability_policy_version']\ndef management_contract(config=None): return s\n")
    (repo/'covered_call_v3.py').write_text(loader+"VERSION=s['model_version']\n")
    (repo/'covered_call_virtual.py').write_text(loader+"OPEN_CHAIN_POLICY='VERSION_CENSORED'\nSIMULATOR_VERSION=s['simulator_version']\nSIMULATOR_CONTRACT_VERSION=s['simulator_contract_version']\ndef simulator_contract_hash(config): return s['simulator_contract_hash']\n")
    def git(*args):
        return subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
    git('init');git('config','user.name','Test');git('config','user.email','test@example.com')
    write_state(state);git('add','.');git('commit','-m','A');a=git('rev-parse','HEAD')
    b_state=dict(state,engine_hash='b',model_version=next_model_version())
    write_state(b_state)
    md=repo/'cc_change_manifests';md.mkdir()
    event_path=tmp_path/'event.json'
    env=dict(os.environ,GITHUB_ACTIONS='true',GITHUB_EVENT_NAME=event_name,GITHUB_EVENT_PATH=str(event_path))
    def run(prior):
        event={'before':prior} if event_name=='push' else {'pull_request':{'base':{'sha':prior}}}
        event_path.write_text(json.dumps(event))
        return subprocess.run([sys.executable,'scripts/check_cc_contract.py','--json'],cwd=repo,env=env,capture_output=True,text=True)
    rejected=run(a)
    assert rejected.returncode==1 and json.loads(rejected.stdout)['hash_changed']
    _make_manifest(md,state,b_state,manifest_id='ab')
    approved=run(a)
    assert approved.returncode==0, approved.stdout+approved.stderr
    git('add','.');git('commit','-m','B');b=git('rev-parse','HEAD')
    write_state(dict(b_state,engine_hash='c',model_version=next_model_version(2)))
    replay=run(b)
    assert replay.returncode==1
    assert any('APPLICABLE_MANIFEST' in f for f in json.loads(replay.stdout)['findings'])


@pytest.mark.parametrize('candidate', ['malformed', 'stale', 'missing'])
def test_candidate_tampering_with_unchanged_behavior_rejected(tmp_path, candidate):
    prior=tmp_path/'prior.json'; bf=tmp_path/'candidate.json'
    state=cc.write_baseline(CC_V3_CONFIG,prior)
    if candidate=='malformed':
        bf.write_text('{')
    elif candidate=='stale':
        bf.write_text(json.dumps(dict(state,engine_hash='tampered')))
    result=cc.check_contract_consistency(CC_V3_CONFIG,_baseline_file=bf,trusted_prior_file=prior)
    assert not result['ok'] and not result['hash_changed']
    assert any('CANDIDATE_BASELINE' in f for f in result['findings'])


@pytest.mark.parametrize('value,code', [('cc-v3.1','BACKWARD_VERSION'),('banana','MALFORMED_VERSION'),('cc-v3.02','MALFORMED_VERSION')])
def test_matching_candidate_invalid_bump_rejected(transition, value, code):
    prior,current,bf,pf,md,check=transition
    current['model_version']=value
    bf.write_text(json.dumps(dict(current,schema_version=cc.BASELINE_SCHEMA_VERSION)))
    _make_manifest(md,prior,current)
    result=check()
    assert result['version_bumped'] is False
    assert any(code in f for f in result['findings'])
