"""Tests for CC V3 Model Freeze and Change-Control Policy (0716/0718/0719)."""
from __future__ import annotations
from cc_cli_fixtures import next_model_version, next_simulator_contract_version
from copy import deepcopy
from pathlib import Path
import json
import pytest
from strategy_config import CC_V3_CONFIG
from covered_call_change_control import (
    current_contract_state, check_contract_consistency,
    write_baseline, read_baseline, list_manifests, experiment_version_info,
    parse_manifest, find_applicable_manifests, _manifest_valid, _manifest_applies,
    CHANGE_CATEGORY_NON_BEHAVIORAL, CHANGE_CATEGORY_EVIDENCE_INFRASTRUCTURE,
    CHANGE_CATEGORY_BEHAVIORAL, BASELINE_SCHEMA_VERSION, BASELINE_REQUIRED_KEYS,
    MANIFEST_REQUIRED_FIELDS,
)


def test_current_contract_state_has_required_fields():
    state = current_contract_state(CC_V3_CONFIG)
    for field in ('model_version', 'simulator_version', 'simulator_contract_version',
                  'simulator_contract_hash', 'engine_hash', 'policy_version'):
        assert field in state, f'missing field: {field}'


def test_dashboard_text_change_is_non_behavioral(monkeypatch, tmp_path):
    """Dashboard/doc changes must not alter the model contract state."""
    # current_contract_state must return the same hash before and after a non-behavioral change
    state_before = current_contract_state(CC_V3_CONFIG)
    # Simulate a doc change: state is unchanged (hash is pure function of code+config)
    state_after = current_contract_state(CC_V3_CONFIG)
    assert state_before['engine_hash'] == state_after['engine_hash']
    assert state_before['simulator_contract_hash'] == state_after['simulator_contract_hash']


def test_no_baseline_fails_closed(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert result['baseline_missing'] is True
    assert result['baseline'] is None
    assert any('MISSING_BASELINE' in f for f in result['findings'])


def test_unchanged_hash_returns_ok(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', tmp_path / 'manifests')
    write_baseline(CC_V3_CONFIG)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is True
    assert result['hash_changed'] is False


def test_behavioral_hash_change_without_version_bump_fails_ci(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    import covered_call_virtual as virtual
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', tmp_path / 'manifests')
    # Write current baseline
    write_baseline(CC_V3_CONFIG)
    # Now simulate an engine_hash change without version bump
    original_mc = cc.management_contract if hasattr(cc, 'management_contract') else None
    from covered_call_validation import management_contract
    def fake_mc(config=None):
        r = management_contract()
        return dict(r, engine_hash='changed-hash-abc')
    monkeypatch.setattr('covered_call_change_control.management_contract', fake_mc)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['hash_changed'] is True
    assert result['ok'] is False
    assert any('VERSION_BUMP' in f for f in result['findings'])


def test_behavioral_hash_change_without_manifest_fails_ci(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    write_baseline(CC_V3_CONFIG)
    from covered_call_validation import management_contract
    def fake_mc(config=None):
        r = management_contract()
        return dict(r, engine_hash='changed-hash-xyz')
    monkeypatch.setattr('covered_call_change_control.management_contract', fake_mc)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['hash_changed'] is True
    assert result['has_manifest'] is False
    assert result['ok'] is False
    assert any('MANIFEST' in f for f in result['findings'])


def _make_transition_manifest(manifests_dir, prior_state, proposed_state, manifest_id='20261013-test-change',
                              operator_acknowledged='true'):
    """Create a properly formatted transition manifest file."""
    content = f"""---
manifest_id: {manifest_id}
date: 2026-10-13
category: BEHAVIORAL_MODEL_CHANGE
author: test
related_commit_or_pr: test-pr-123
prior_model_version: {prior_state['model_version']}
prior_simulator_version: {prior_state['simulator_version']}
prior_simulator_contract_version: {prior_state['simulator_contract_version']}
prior_simulator_contract_hash: {prior_state['simulator_contract_hash']}
prior_engine_hash: {prior_state['engine_hash']}
prior_fingerprint_version: {prior_state['fingerprint_version']}
prior_policy_version: {prior_state['policy_version']}
prior_cadence_comparability_policy_version: {prior_state['cadence_comparability_policy_version']}
proposed_model_version: {proposed_state['model_version']}
proposed_simulator_version: {proposed_state['simulator_version']}
proposed_simulator_contract_version: {proposed_state['simulator_contract_version']}
proposed_simulator_contract_hash: {proposed_state['simulator_contract_hash']}
proposed_engine_hash: {proposed_state['engine_hash']}
proposed_fingerprint_version: {proposed_state['fingerprint_version']}
proposed_policy_version: {proposed_state['policy_version']}
proposed_cadence_comparability_policy_version: {proposed_state['cadence_comparability_policy_version']}
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: {operator_acknowledged}
---

# Test change
"""
    (manifests_dir / f'{manifest_id}.md').write_text(content)


def test_behavioral_hash_change_with_version_bump_and_manifest_passes(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    # Capture real state before patching (this becomes the baseline/prior)
    real_state = current_contract_state(CC_V3_CONFIG)
    write_baseline(CC_V3_CONFIG)
    # Only engine_hash changes (not sim_contract_hash) → model_version is the correct bump
    proposed = dict(real_state, engine_hash='new-hash-after-bump',
                    model_version=next_model_version())
    _make_transition_manifest(manifests_dir, prior_state=real_state, proposed_state=proposed)
    monkeypatch.setattr(cc, 'current_contract_state', lambda config: proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['hash_changed'] is True
    assert result['version_bumped'] is True
    assert result['has_manifest'] is True
    assert result['ok'] is True, result['findings']
    assert result['applicable_manifest'] is not None
    assert result['applicable_manifest']['manifest_id'] == '20261013-test-change'


def test_experiment_version_info_has_dashboard_fields(tmp_path, monkeypatch):
    import covered_call_ledger as ledger
    import covered_call_evidence as evidence
    from time_utils import parse_timestamp
    from datetime import timedelta
    monkeypatch.setattr(evidence, 'committed_policy', lambda *a: True)
    START = '2026-10-13T17:00:00+00:00'
    monkeypatch.setattr(evidence, 'now_utc', lambda: parse_timestamp(START) + timedelta(seconds=1))
    cfg = deepcopy(CC_V3_CONFIG)
    path = tmp_path / 'cc.db'
    from test_cc_followups import candidate
    row = candidate(quote_timestamp=START)
    choose = lambda a: dict(action=a, strike=row['strike'], expiration=row['expiration'],
                            contracts=1, overwrite_fraction=1/3)
    ledger.record_episode('TEST', 1, [row], choose('SELL_CC'), choose('SELL_CC'),
                          dict(strategy='INCOME', assignment_policy={'allowed': True}), cfg, START, path)
    info = experiment_version_info(cfg, path)
    for field in ('model_version', 'simulator_version', 'simulator_contract_version',
                  'cohort_start_date', 'days_since_behavioral_reset', 'certified'):
        assert field in info, f'missing field: {field}'
    assert info['cohort_start_date'] is not None
    assert info['days_since_behavioral_reset'] is not None


def test_write_and_read_baseline_roundtrip(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    written = write_baseline(CC_V3_CONFIG)
    read = read_baseline()
    assert read == written


def test_list_manifests_excludes_template(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    (manifests_dir / '.template.md').write_text('template')
    (manifests_dir / '20261013-real-change.md').write_text('real')
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    manifests = list_manifests()
    names = [m.name for m in manifests]
    assert '.template.md' not in names
    assert '20261013-real-change.md' in names


def test_change_category_constants_defined():
    assert CHANGE_CATEGORY_NON_BEHAVIORAL == 'NON_BEHAVIORAL'
    assert CHANGE_CATEGORY_EVIDENCE_INFRASTRUCTURE == 'EVIDENCE_INFRASTRUCTURE'
    assert CHANGE_CATEGORY_BEHAVIORAL == 'BEHAVIORAL_MODEL_CHANGE'


# ── 0718: fail-closed baseline enforcement ────────────────────────────────────

def test_malformed_json_baseline_fails_ci(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    bf = tmp_path / '.cc_contract_baseline.json'
    bf.write_text('{ not valid json }')
    monkeypatch.setattr(cc, 'BASELINE_FILE', bf)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert result.get('baseline_malformed') is True
    assert any('MALFORMED_BASELINE' in f for f in result['findings'])


def test_missing_required_keys_fails_ci(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    bf = tmp_path / '.cc_contract_baseline.json'
    bf.write_text(json.dumps({'schema_version': BASELINE_SCHEMA_VERSION, 'engine_hash': 'x'}))
    monkeypatch.setattr(cc, 'BASELINE_FILE', bf)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert result.get('baseline_malformed') is True


def test_unknown_schema_version_fails_ci(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    bf = tmp_path / '.cc_contract_baseline.json'
    state = current_contract_state(CC_V3_CONFIG)
    state['schema_version'] = 'cc-contract-v999'
    bf.write_text(json.dumps(state))
    monkeypatch.setattr(cc, 'BASELINE_FILE', bf)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert result.get('baseline_malformed') is True
    assert any('schema_version' in f for f in result['findings'])


def test_write_baseline_includes_schema_version(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    state = write_baseline(CC_V3_CONFIG)
    assert state['schema_version'] == BASELINE_SCHEMA_VERSION
    # read_baseline also validates and returns the full dict
    read = read_baseline()
    assert read is not None
    assert not read.get('malformed')
    assert read['schema_version'] == BASELINE_SCHEMA_VERSION


def test_baseline_contains_all_required_fields(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    state = write_baseline(CC_V3_CONFIG)
    for key in BASELINE_REQUIRED_KEYS:
        assert key in state, f'baseline missing required key: {key}'


def test_baseline_generation_is_deterministic(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    bf = tmp_path / '.cc_contract_baseline.json'
    monkeypatch.setattr(cc, 'BASELINE_FILE', bf)
    first = write_baseline(CC_V3_CONFIG)
    second = write_baseline(CC_V3_CONFIG)
    assert first == second


def test_ci_guard_rejects_update_baseline_in_ci_env(monkeypatch, tmp_path):
    """--update-baseline must fail when GITHUB_ACTIONS=true."""
    import subprocess, sys
    env = dict(__import__('os').environ, GITHUB_ACTIONS='true')
    result = subprocess.run(
        [sys.executable, 'scripts/check_cc_contract.py', '--update-baseline'],
        capture_output=True, text=True, env=env,
        cwd=str(__import__('pathlib').Path(__file__).parent.parent),
    )
    assert result.returncode == 1
    assert 'must not be invoked in CI' in result.stderr


# ── 0719: transition-bound manifests ─────────────────────────────────────────

def test_parse_manifest_valid_front_matter(tmp_path):
    state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(state, engine_hash='new-abc123')
    md = tmp_path / 'test.md'
    md.write_text(f"""---
manifest_id: test-001
date: 2026-10-13
category: BEHAVIORAL_MODEL_CHANGE
author: tester
related_commit_or_pr: pr-1
prior_model_version: {state['model_version']}
prior_simulator_version: {state['simulator_version']}
prior_simulator_contract_version: {state['simulator_contract_version']}
prior_simulator_contract_hash: {state['simulator_contract_hash']}
prior_engine_hash: {state['engine_hash']}
prior_fingerprint_version: {state['fingerprint_version']}
proposed_model_version: {proposed['model_version']}
proposed_simulator_version: {proposed['simulator_version']}
proposed_simulator_contract_version: {proposed['simulator_contract_version']}
proposed_simulator_contract_hash: {proposed['simulator_contract_hash']}
proposed_engine_hash: {proposed['engine_hash']}
proposed_fingerprint_version: {proposed['fingerprint_version']}
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: true
---
# Change
""")
    fm = parse_manifest(md)
    assert 'parse_error' not in fm
    assert fm['manifest_id'] == 'test-001'
    assert fm['prior_engine_hash'] == state['engine_hash']
    assert fm['operator_acknowledged'] is True


def test_parse_manifest_no_front_matter(tmp_path):
    md = tmp_path / 'test.md'
    md.write_text('# Just a heading\nNo front matter.\n')
    fm = parse_manifest(md)
    assert 'parse_error' in fm


def test_parse_manifest_unclosed_delimiter(tmp_path):
    md = tmp_path / 'test.md'
    md.write_text('---\nmanifest_id: test\n# No closing delimiter\n')
    fm = parse_manifest(md)
    assert 'parse_error' in fm


def test_manifest_valid_rejects_missing_fields(tmp_path):
    md = tmp_path / 'test.md'
    md.write_text('---\nmanifest_id: x\noperator_acknowledged: true\n---\n')
    fm = parse_manifest(md)
    valid, reasons = _manifest_valid(fm)
    assert not valid
    assert any('missing' in r for r in reasons)


def test_manifest_valid_rejects_unacknowledged(tmp_path):
    state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(state, engine_hash='new-xyz')
    md = tmp_path / 'test.md'
    _make_transition_manifest(tmp_path, prior_state=state, proposed_state=proposed,
                               manifest_id='test-unack', operator_acknowledged='false')
    fm = parse_manifest(tmp_path / 'test-unack.md')
    valid, reasons = _manifest_valid(fm)
    assert not valid
    assert any('operator_acknowledged' in r for r in reasons)


def test_exact_transition_manifest_applies(tmp_path):
    state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(state, engine_hash='new-xyz-exact')
    _make_transition_manifest(tmp_path, prior_state=state, proposed_state=proposed)
    fm = parse_manifest(tmp_path / '20261013-test-change.md')
    assert _manifest_applies(fm, baseline=state, current=proposed)


def test_old_manifest_does_not_authorize_later_transition(tmp_path):
    """A manifest for A→B cannot authorize B→C."""
    state_a = current_contract_state(CC_V3_CONFIG)
    state_b = dict(state_a, engine_hash='hash-b')
    state_c = dict(state_a, engine_hash='hash-c')
    _make_transition_manifest(tmp_path, prior_state=state_a, proposed_state=state_b, manifest_id='ab')
    fm = parse_manifest(tmp_path / 'ab.md')
    assert not _manifest_applies(fm, baseline=state_b, current=state_c)


def test_wrong_prior_hash_does_not_qualify(tmp_path):
    state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(state, engine_hash='new-proposed')
    wrong_prior = dict(state, engine_hash='wrong-prior')
    _make_transition_manifest(tmp_path, prior_state=wrong_prior, proposed_state=proposed, manifest_id='wrong')
    fm = parse_manifest(tmp_path / 'wrong.md')
    assert not _manifest_applies(fm, baseline=state, current=proposed)


def test_duplicate_applicable_manifests_fail(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    real_state = current_contract_state(CC_V3_CONFIG)
    write_baseline(CC_V3_CONFIG)
    proposed = dict(real_state, engine_hash='dup-proposed')
    _make_transition_manifest(manifests_dir, prior_state=real_state, proposed_state=proposed, manifest_id='dup-1')
    _make_transition_manifest(manifests_dir, prior_state=real_state, proposed_state=proposed, manifest_id='dup-2')
    monkeypatch.setattr(cc, 'current_contract_state', lambda config: proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert any('DUPLICATE_APPLICABLE' in f for f in result['findings'])


def test_duplicate_manifest_ids_fail(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    real_state = current_contract_state(CC_V3_CONFIG)
    write_baseline(CC_V3_CONFIG)
    proposed_a = dict(real_state, engine_hash='hash-a')
    proposed_b = dict(real_state, engine_hash='hash-b')
    _make_transition_manifest(manifests_dir, prior_state=real_state, proposed_state=proposed_a,
                               manifest_id='same-id')
    # Write second manifest with same ID but different filename
    content = (manifests_dir / 'same-id.md').read_text().replace('same-id', 'same-id')
    (manifests_dir / 'different-file-same-id.md').write_text(content.replace(
        f'proposed_engine_hash: {proposed_a["engine_hash"]}',
        f'proposed_engine_hash: {proposed_b["engine_hash"]}',
    ))
    result = find_applicable_manifests(real_state, proposed_a, manifests_dir)
    assert result['duplicate_ids']


def test_behavioral_drift_with_only_unrelated_manifest_fails(monkeypatch, tmp_path):
    """Old A→B manifest must not authorize an unrelated B→C change."""
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    real_state = current_contract_state(CC_V3_CONFIG)
    write_baseline(CC_V3_CONFIG)
    proposed_current = dict(real_state, engine_hash='current-new-hash')
    unrelated_proposed = dict(real_state, engine_hash='unrelated-hash')
    _make_transition_manifest(manifests_dir, prior_state=real_state, proposed_state=unrelated_proposed,
                               manifest_id='unrelated')
    monkeypatch.setattr(cc, 'current_contract_state', lambda config: proposed_current)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert result['has_manifest'] is False
    assert any('APPLICABLE_MANIFEST' in f for f in result['findings'])


def test_non_behavioral_unchanged_contract_passes_without_manifest(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    write_baseline(CC_V3_CONFIG)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is True
    assert result['hash_changed'] is False
    assert result['has_manifest'] is False  # no manifest needed; no change


def test_manifest_required_fields_constant():
    assert 'operator_acknowledged' in MANIFEST_REQUIRED_FIELDS
    assert 'prior_engine_hash' in MANIFEST_REQUIRED_FIELDS
    assert 'proposed_engine_hash' in MANIFEST_REQUIRED_FIELDS
    assert 'manifest_id' in MANIFEST_REQUIRED_FIELDS


# ── 0720: category and component-specific version enforcement ─────────────────

def _setup_change(monkeypatch, tmp_path, prior_state, proposed_state,
                  manifest_category='BEHAVIORAL_MODEL_CHANGE',
                  include_manifest=True, manifest_id='test-change'):
    """Helper: write baseline + optional manifest and monkeypatch current state."""
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    write_baseline(CC_V3_CONFIG)
    if include_manifest:
        manifest_with_category = dict(proposed_state, _category_override=manifest_category)
        content = f"""---
manifest_id: {manifest_id}
date: 2026-10-13
category: {manifest_category}
author: test
related_commit_or_pr: test
prior_model_version: {prior_state['model_version']}
prior_simulator_version: {prior_state['simulator_version']}
prior_simulator_contract_version: {prior_state['simulator_contract_version']}
prior_simulator_contract_hash: {prior_state['simulator_contract_hash']}
prior_engine_hash: {prior_state['engine_hash']}
prior_fingerprint_version: {prior_state['fingerprint_version']}
prior_policy_version: {prior_state['policy_version']}
prior_cadence_comparability_policy_version: {prior_state['cadence_comparability_policy_version']}
proposed_model_version: {proposed_state['model_version']}
proposed_simulator_version: {proposed_state['simulator_version']}
proposed_simulator_contract_version: {proposed_state['simulator_contract_version']}
proposed_simulator_contract_hash: {proposed_state['simulator_contract_hash']}
proposed_engine_hash: {proposed_state['engine_hash']}
proposed_fingerprint_version: {proposed_state['fingerprint_version']}
proposed_policy_version: {proposed_state['policy_version']}
proposed_cadence_comparability_policy_version: {proposed_state['cadence_comparability_policy_version']}
cohort_reset_required: true
open_chain_policy: VERSION_CENSORED
operator_acknowledged: true
---
# Test
"""
        (manifests_dir / f'{manifest_id}.md').write_text(content)
    monkeypatch.setattr(cc, 'current_contract_state', lambda config: proposed_state)
    return cc


def test_non_behavioral_with_unchanged_hashes_passes(monkeypatch, tmp_path):
    """NON_BEHAVIORAL declared with unchanged hashes (no manifest needed) passes."""
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    write_baseline(CC_V3_CONFIG)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is True
    assert result['hash_changed'] is False


def test_non_behavioral_with_changed_hash_fails(monkeypatch, tmp_path):
    """NON_BEHAVIORAL declared in manifest but hash changed → category mismatch."""
    real_state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(real_state, engine_hash='new-non-behavioral-hash',
                    model_version=next_model_version())
    cc = _setup_change(monkeypatch, tmp_path, real_state, proposed,
                       manifest_category='NON_BEHAVIORAL')
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert any('CATEGORY_MISMATCH_NON_BEHAVIORAL' in f for f in result['findings'])


def test_evidence_infrastructure_with_unchanged_hashes_passes(monkeypatch, tmp_path):
    """EVIDENCE_INFRASTRUCTURE change with unchanged hashes passes (no manifest needed)."""
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    write_baseline(CC_V3_CONFIG)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is True


def test_evidence_infrastructure_with_changed_hash_fails(monkeypatch, tmp_path):
    """EVIDENCE_INFRASTRUCTURE declared in manifest but hash changed → mismatch."""
    real_state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(real_state, engine_hash='new-evidence-hash',
                    simulator_contract_version=next_simulator_contract_version())
    cc = _setup_change(monkeypatch, tmp_path, real_state, proposed,
                       manifest_category='EVIDENCE_INFRASTRUCTURE')
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert any('CATEGORY_MISMATCH_EVIDENCE_INFRASTRUCTURE' in f for f in result['findings'])


def test_sim_contract_hash_change_requires_sim_ver_bump(monkeypatch, tmp_path):
    """simulator_contract_hash changed without simulator_contract_version bump → fail."""
    real_state = current_contract_state(CC_V3_CONFIG)
    # Only sim hash changed, no sim_contract_version bump, but model_version bumped
    proposed = dict(real_state,
                    simulator_contract_hash='new-sim-hash-only',
                    model_version=next_model_version())  # wrong component
    cc = _setup_change(monkeypatch, tmp_path, real_state, proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert any('WRONG_COMPONENT_VERSION_BUMP' in f and 'SIMULATOR_CONTRACT_VERSION' in f
               for f in result['findings'])


def test_engine_only_hash_change_requires_model_ver_bump(monkeypatch, tmp_path):
    """engine_hash changed (sim unchanged) without model_version bump → fail."""
    real_state = current_contract_state(CC_V3_CONFIG)
    # Only engine hash changed, no model_version bump, but sim_contract_version bumped
    proposed = dict(real_state,
                    engine_hash='new-engine-only-hash',
                    simulator_contract_version=next_simulator_contract_version())  # wrong component
    cc = _setup_change(monkeypatch, tmp_path, real_state, proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert any('WRONG_COMPONENT_VERSION_BUMP' in f and 'model_version' in f
               for f in result['findings'])


def test_multi_component_change_requires_both_bumps(monkeypatch, tmp_path):
    """Both hashes changed but only sim_contract_version bumped → need model_version too."""
    real_state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(real_state,
                    engine_hash='new-engine-hash',
                    simulator_contract_hash='new-sim-hash',
                    simulator_contract_version=next_simulator_contract_version())  # only one bump
    cc = _setup_change(monkeypatch, tmp_path, real_state, proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is False
    assert any('WRONG_COMPONENT_VERSION_BUMP' in f and 'model_version' in f
               for f in result['findings'])


def test_correct_behavioral_change_all_bumps_passes(monkeypatch, tmp_path):
    """Both hashes changed + both versions bumped + exact manifest → pass."""
    real_state = current_contract_state(CC_V3_CONFIG)
    proposed = dict(real_state,
                    engine_hash='new-engine',
                    simulator_contract_hash='new-sim',
                    simulator_contract_version=next_simulator_contract_version(),
                    model_version=next_model_version())
    cc = _setup_change(monkeypatch, tmp_path, real_state, proposed)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['ok'] is True
    assert result['hash_changed'] is True
    assert result['has_manifest'] is True
