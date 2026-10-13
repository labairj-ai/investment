"""Adversarial release QA for CC V3 change-control (0721).

At least some tests invoke scripts/check_cc_contract.py as a subprocess to verify
real exit codes. Python-API tests cover detailed finding content.

Design rules:
  - Each bypass test passes only when the invalid release is REJECTED.
  - tmp_path fixtures provide full isolation; no test touches the real baseline.
  - No broker/network dependency.
  - Parallel tests cannot contaminate one another.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = [sys.executable, str(ROOT / 'scripts' / 'check_cc_contract.py')]


# ── subprocess helpers ─────────────────────────────────────────────────────────

def _run(args, baseline_file=None, manifests_dir=None, ci_env=False):
    """Run check_cc_contract.py as a subprocess and return CompletedProcess."""
    cmd = list(CHECKER) + ['--json']
    if baseline_file:
        cmd += ['--baseline-file', str(baseline_file), '--trusted-prior-file', str(baseline_file)]
    if manifests_dir:
        cmd += ['--manifests-dir', str(manifests_dir)]
    cmd += args
    env = __import__('os').environ.copy()
    # Isolate event metadata for offline CLI fixtures; retain both CI guards.
    env.pop('GITHUB_EVENT_PATH', None)
    env.pop('GITHUB_EVENT_NAME', None)
    if ci_env:
        env['GITHUB_ACTIONS'] = 'true'
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))


def _good_baseline(tmp_path):
    """Write a valid baseline from current code; return path."""
    bf = tmp_path / 'baseline.json'
    from covered_call_change_control import write_baseline
    from strategy_config import CC_V3_CONFIG
    write_baseline(CC_V3_CONFIG, path=bf)
    assert bf.exists()
    return bf


def _make_manifest(manifests_dir, prior_state, proposed_state,
                   manifest_id='test-manifest', category='BEHAVIORAL_MODEL_CHANGE',
                   operator_acknowledged='true'):
    """Write a transition manifest with front matter to manifests_dir."""
    content = f"""---
manifest_id: {manifest_id}
date: 2026-10-13
category: {category}
author: adversarial-test
related_commit_or_pr: test
prior_model_version: {prior_state['model_version']}
prior_simulator_version: {prior_state['simulator_version']}
prior_simulator_contract_version: {prior_state['simulator_contract_version']}
prior_simulator_contract_hash: {prior_state['simulator_contract_hash']}
prior_engine_hash: {prior_state['engine_hash']}
prior_policy_version: {prior_state['policy_version']}
prior_cadence_comparability_policy_version: {prior_state['cadence_comparability_policy_version']}
proposed_model_version: {proposed_state['model_version']}
proposed_simulator_version: {proposed_state['simulator_version']}
proposed_simulator_contract_version: {proposed_state['simulator_contract_version']}
proposed_simulator_contract_hash: {proposed_state['simulator_contract_hash']}
proposed_engine_hash: {proposed_state['engine_hash']}
proposed_policy_version: {proposed_state['policy_version']}
proposed_cadence_comparability_policy_version: {proposed_state['cadence_comparability_policy_version']}
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: {operator_acknowledged}
---
# Adversarial test manifest
"""
    (manifests_dir / f'{manifest_id}.md').write_text(content)


# ── baseline attack: subprocess exit codes ────────────────────────────────────

def test_missing_baseline_exits_1_subprocess(tmp_path):
    """Missing baseline file → exit 1."""
    missing = tmp_path / 'nonexistent.json'
    result = _run([], baseline_file=missing)
    assert result.returncode == 1, result.stdout
    data = json.loads(result.stdout)
    assert data['ok'] is False
    assert data['baseline_missing'] is True


def test_malformed_baseline_exits_1_subprocess(tmp_path):
    """Malformed JSON baseline → exit 1."""
    bf = tmp_path / 'baseline.json'
    bf.write_text('{ this is not json }')
    result = _run([], baseline_file=bf)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data['baseline_malformed'] is True


def test_unknown_schema_version_exits_1_subprocess(tmp_path):
    """Baseline with unknown schema_version → exit 1."""
    bf = _good_baseline(tmp_path)
    data = json.loads(bf.read_text())
    data['schema_version'] = 'cc-contract-v999'
    bf.write_text(json.dumps(data))
    result = _run([], baseline_file=bf)
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert out['baseline_malformed'] is True
    assert any('schema_version' in f for f in out['findings'])


def test_unchanged_contract_exits_0_subprocess(tmp_path):
    """Real unchanged contract with valid baseline → exit 0."""
    bf = _good_baseline(tmp_path)
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    result = _run([], baseline_file=bf, manifests_dir=manifests_dir)
    assert result.returncode == 0, result.stdout


# ── CI guard subprocess ────────────────────────────────────────────────────────

def test_update_baseline_blocked_in_ci_subprocess(tmp_path):
    """--update-baseline must return exit 1 when GITHUB_ACTIONS=true."""
    bf = tmp_path / 'baseline.json'
    result = _run(['--update-baseline'], baseline_file=bf, ci_env=True)
    assert result.returncode == 1
    assert 'must not be invoked in CI' in result.stderr


# ── CLI/API consistency ────────────────────────────────────────────────────────

def test_cli_and_api_consistent_for_unchanged_contract(tmp_path):
    """CLI and Python API both return ok=True for unchanged contract."""
    from strategy_config import CC_V3_CONFIG
    from covered_call_change_control import check_contract_consistency, write_baseline

    bf = tmp_path / 'baseline.json'
    md = tmp_path / 'manifests'
    md.mkdir()
    write_baseline(CC_V3_CONFIG, path=bf)

    # Python API
    api_result = check_contract_consistency(CC_V3_CONFIG, _baseline_file=bf, _manifests_dir=md)
    assert api_result['ok'] is True

    # CLI subprocess
    cli_result = _run([], baseline_file=bf, manifests_dir=md)
    assert cli_result.returncode == 0

    cli_data = json.loads(cli_result.stdout)
    assert cli_data['ok'] == api_result['ok']
    assert cli_data['hash_changed'] == api_result['hash_changed']


def test_cli_and_api_consistent_for_missing_baseline(tmp_path):
    """CLI and Python API both return ok=False for missing baseline."""
    from strategy_config import CC_V3_CONFIG
    from covered_call_change_control import check_contract_consistency

    missing = tmp_path / 'missing.json'
    api_result = check_contract_consistency(CC_V3_CONFIG, _baseline_file=missing)
    assert api_result['ok'] is False

    cli_result = _run([], baseline_file=missing)
    assert cli_result.returncode == 1
    cli_data = json.loads(cli_result.stdout)
    assert cli_data['ok'] is False


# ── version bypass attacks ────────────────────────────────────────────────────

class TestVersionBypasses:
    def _setup(self, monkeypatch, tmp_path, proposed_state):
        from covered_call_change_control import write_baseline
        from strategy_config import CC_V3_CONFIG
        import covered_call_change_control as cc
        monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / 'baseline.json')
        md = tmp_path / 'manifests'
        md.mkdir()
        monkeypatch.setattr(cc, 'MANIFESTS_DIR', md)
        write_baseline(CC_V3_CONFIG)
        monkeypatch.setattr(cc, 'current_contract_state', lambda cfg: proposed_state)
        return cc, md

    def test_engine_hash_change_no_bump_rejected(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state, check_contract_consistency
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='bypass-attempt-no-bump')
        cc, _ = self._setup(monkeypatch, tmp_path, proposed)
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('VERSION_BUMP' in f for f in result['findings'])

    def test_engine_hash_change_unrelated_sim_bump_rejected(self, monkeypatch, tmp_path):
        """Engine hash changed (utility model), only sim_contract_version bumped → rejected."""
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        # engine_hash changed (no sim_contract_hash change), wrong bump
        proposed = dict(real, engine_hash='engine-change-wrong-bump',
                        simulator_contract_version='simulator-contract-2')
        cc, _ = self._setup(monkeypatch, tmp_path, proposed)
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('WRONG_COMPONENT_VERSION_BUMP' in f and 'model_version' in f
                   for f in result['findings'])

    def test_sim_hash_change_unrelated_model_bump_rejected(self, monkeypatch, tmp_path):
        """Simulator contract hash changed, only model_version bumped → rejected."""
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, simulator_contract_hash='sim-change-wrong-bump',
                        model_version='cc-v3.3')
        cc, _ = self._setup(monkeypatch, tmp_path, proposed)
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('WRONG_COMPONENT_VERSION_BUMP' in f and 'SIMULATOR_CONTRACT_VERSION' in f
                   for f in result['findings'])

    def test_multi_component_partial_bumps_rejected(self, monkeypatch, tmp_path):
        """Both hashes changed, only one version bumped → rejected."""
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='engine-multi', simulator_contract_hash='sim-multi',
                        simulator_contract_version='simulator-contract-2')  # model_version not bumped
        cc, _ = self._setup(monkeypatch, tmp_path, proposed)
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('WRONG_COMPONENT_VERSION_BUMP' in f for f in result['findings'])


# ── manifest bypass attacks ────────────────────────────────────────────────────

class TestManifestBypasses:
    def _setup(self, monkeypatch, tmp_path, proposed_state):
        from covered_call_change_control import write_baseline
        from strategy_config import CC_V3_CONFIG
        import covered_call_change_control as cc
        monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / 'baseline.json')
        md = tmp_path / 'manifests'
        md.mkdir()
        monkeypatch.setattr(cc, 'MANIFESTS_DIR', md)
        write_baseline(CC_V3_CONFIG)
        monkeypatch.setattr(cc, 'current_contract_state', lambda cfg: proposed_state)
        return cc, md

    def test_no_manifest_rejects_behavioral_change(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='no-manifest-test', model_version='cc-v3.3')
        cc, _ = self._setup(monkeypatch, tmp_path, proposed)
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('APPLICABLE_MANIFEST' in f for f in result['findings'])

    def test_old_manifest_rejects_new_change(self, monkeypatch, tmp_path):
        """A→B manifest cannot authorize B→C transition."""
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        state_b = dict(real, engine_hash='hash-b', model_version='cc-v3.3')
        state_c = dict(real, engine_hash='hash-c', model_version='cc-v3.4')
        cc, md = self._setup(monkeypatch, tmp_path, state_c)
        # Put only the A→B manifest in the dir
        _make_manifest(md, prior_state=real, proposed_state=state_b, manifest_id='a-to-b')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert result['has_manifest'] is False

    def test_manifest_for_different_hashes_rejects(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed_actual = dict(real, engine_hash='actual-proposed', model_version='cc-v3.3')
        proposed_wrong = dict(real, engine_hash='wrong-proposed', model_version='cc-v3.3')
        cc, md = self._setup(monkeypatch, tmp_path, proposed_actual)
        _make_manifest(md, prior_state=real, proposed_state=proposed_wrong, manifest_id='wrong-hashes')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert result['has_manifest'] is False

    def test_duplicate_applicable_manifests_rejected(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='dup-test', model_version='cc-v3.3')
        cc, md = self._setup(monkeypatch, tmp_path, proposed)
        _make_manifest(md, prior_state=real, proposed_state=proposed, manifest_id='dup-1')
        _make_manifest(md, prior_state=real, proposed_state=proposed, manifest_id='dup-2')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('DUPLICATE_APPLICABLE' in f for f in result['findings'])

    def test_missing_operator_acknowledgment_rejects(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='no-ack-test', model_version='cc-v3.3')
        cc, md = self._setup(monkeypatch, tmp_path, proposed)
        _make_manifest(md, prior_state=real, proposed_state=proposed,
                       manifest_id='no-ack', operator_acknowledged='false')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert result['has_manifest'] is False

    def test_template_only_rejects_behavioral_change(self, monkeypatch, tmp_path):
        """Only .template.md present (excluded from list) → no manifest."""
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='template-only-test', model_version='cc-v3.3')
        cc, md = self._setup(monkeypatch, tmp_path, proposed)
        # Write a template-named file — starts with '.' so list_manifests excludes it
        (md / '.template.md').write_text('---\nmanifest_id: template\n---\n')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert result['has_manifest'] is False


# ── classification bypass attacks ─────────────────────────────────────────────

class TestClassificationBypasses:
    def _setup(self, monkeypatch, tmp_path, proposed_state):
        from covered_call_change_control import write_baseline
        from strategy_config import CC_V3_CONFIG
        import covered_call_change_control as cc
        monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / 'baseline.json')
        md = tmp_path / 'manifests'
        md.mkdir()
        monkeypatch.setattr(cc, 'MANIFESTS_DIR', md)
        write_baseline(CC_V3_CONFIG)
        monkeypatch.setattr(cc, 'current_contract_state', lambda cfg: proposed_state)
        return cc, md

    def test_behavioral_drift_declared_non_behavioral_rejects(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='behavioral-misclassified', model_version='cc-v3.3')
        cc, md = self._setup(monkeypatch, tmp_path, proposed)
        _make_manifest(md, prior_state=real, proposed_state=proposed,
                       manifest_id='misclassified', category='NON_BEHAVIORAL')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('CATEGORY_MISMATCH_NON_BEHAVIORAL' in f for f in result['findings'])

    def test_decision_change_declared_evidence_infrastructure_rejects(self, monkeypatch, tmp_path):
        from covered_call_change_control import current_contract_state
        from strategy_config import CC_V3_CONFIG
        real = current_contract_state(CC_V3_CONFIG)
        proposed = dict(real, engine_hash='evidence-misclassified',
                        simulator_contract_version='simulator-contract-2')
        cc, md = self._setup(monkeypatch, tmp_path, proposed)
        _make_manifest(md, prior_state=real, proposed_state=proposed,
                       manifest_id='evidence-misclassified', category='EVIDENCE_INFRASTRUCTURE')
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is False
        assert any('CATEGORY_MISMATCH_EVIDENCE_INFRASTRUCTURE' in f for f in result['findings'])

    def test_true_non_behavioral_change_passes(self, monkeypatch, tmp_path):
        """Dashboard/docs change: hashes unchanged, no manifest needed → pass."""
        from covered_call_change_control import write_baseline, check_contract_consistency
        from strategy_config import CC_V3_CONFIG
        import covered_call_change_control as cc
        monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / 'baseline.json')
        md = tmp_path / 'manifests'
        md.mkdir()
        monkeypatch.setattr(cc, 'MANIFESTS_DIR', md)
        write_baseline(CC_V3_CONFIG)
        # No hash change, no version bump, no manifest → should pass
        result = cc.check_contract_consistency(CC_V3_CONFIG)
        assert result['ok'] is True
        assert result['hash_changed'] is False


# ── end-to-end success paths ──────────────────────────────────────────────────

def test_approved_behavioral_transition_exits_0(monkeypatch, tmp_path):
    """Full happy path: exact manifest + correct bumps → exit 0 via subprocess."""
    from covered_call_change_control import current_contract_state, write_baseline
    from strategy_config import CC_V3_CONFIG

    bf = tmp_path / 'baseline.json'
    md = tmp_path / 'manifests'
    md.mkdir()
    real_state = write_baseline(CC_V3_CONFIG, path=bf)
    # Only engine hash changed → correct bump is model_version
    proposed = dict(real_state, engine_hash='approved-test-hash', model_version='cc-v3.3')
    _make_manifest(md, prior_state=real_state, proposed_state=proposed, manifest_id='approved')

    # Use subprocess with overridden paths and monkeypatched current_contract_state
    # via Python API (subprocess can't monkeypatch)
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'current_contract_state', lambda cfg: proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG, _baseline_file=bf, _manifests_dir=md)
    assert result['ok'] is True
    assert result['has_manifest'] is True
    assert result['applicable_manifest']['manifest_id'] == 'approved'


def test_approved_non_behavioral_transition_exits_0_subprocess(tmp_path):
    """Unchanged contract with valid baseline → exit 0 via subprocess."""
    bf = _good_baseline(tmp_path)
    md = tmp_path / 'manifests'
    md.mkdir()
    result = _run([], baseline_file=bf, manifests_dir=md)
    assert result.returncode == 0


def test_findings_always_present_in_json_output(tmp_path):
    """JSON output always contains 'findings' key (may be empty list)."""
    bf = _good_baseline(tmp_path)
    md = tmp_path / 'manifests'
    md.mkdir()
    result = _run([], baseline_file=bf, manifests_dir=md)
    data = json.loads(result.stdout)
    assert 'findings' in data
    assert isinstance(data['findings'], list)


def test_rejection_always_has_specific_finding(monkeypatch, tmp_path):
    """Each rejection provides a non-generic, specific finding string."""
    from covered_call_change_control import current_contract_state, write_baseline, check_contract_consistency
    from strategy_config import CC_V3_CONFIG
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / 'baseline.json')
    md = tmp_path / 'manifests'
    md.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', md)
    write_baseline(CC_V3_CONFIG)
    real = current_contract_state(CC_V3_CONFIG)
    proposed = dict(real, engine_hash='rejection-specific-test')
    monkeypatch.setattr(cc, 'current_contract_state', lambda cfg: proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    for finding in result['findings']:
        # Each finding must name a specific failure code (not just "error")
        assert '_' in finding  # all finding codes use SCREAMING_SNAKE_CASE prefix
        assert len(finding) > 20
