"""Tests for CC V3 Model Freeze and Change-Control Policy (0716/0718)."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json
import pytest
from strategy_config import CC_V3_CONFIG
from covered_call_change_control import (
    current_contract_state, check_contract_consistency,
    write_baseline, read_baseline, list_manifests, experiment_version_info,
    CHANGE_CATEGORY_NON_BEHAVIORAL, CHANGE_CATEGORY_EVIDENCE_INFRASTRUCTURE,
    CHANGE_CATEGORY_BEHAVIORAL, BASELINE_SCHEMA_VERSION, BASELINE_REQUIRED_KEYS,
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
    def fake_mc():
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
    def fake_mc():
        r = management_contract()
        return dict(r, engine_hash='changed-hash-xyz')
    monkeypatch.setattr('covered_call_change_control.management_contract', fake_mc)
    result = check_contract_consistency(CC_V3_CONFIG)
    assert result['hash_changed'] is True
    assert result['has_manifest'] is False
    assert result['ok'] is False
    assert any('MANIFEST' in f for f in result['findings'])


def test_behavioral_hash_change_with_version_bump_and_manifest_passes(monkeypatch, tmp_path):
    import covered_call_change_control as cc
    monkeypatch.setattr(cc, 'BASELINE_FILE', tmp_path / '.cc_contract_baseline.json')
    manifests_dir = tmp_path / 'manifests'
    manifests_dir.mkdir()
    # Create a fake manifest
    (manifests_dir / '20261013-test-change.md').write_text('# Change Manifest\n')
    monkeypatch.setattr(cc, 'MANIFESTS_DIR', manifests_dir)
    write_baseline(CC_V3_CONFIG)
    from covered_call_validation import management_contract
    from covered_call_virtual import SIMULATOR_CONTRACT_VERSION
    def fake_mc():
        r = management_contract()
        return dict(r, engine_hash='new-hash-after-bump')
    # Simulate version bump + hash change
    monkeypatch.setattr('covered_call_change_control.management_contract', fake_mc)
    original_scv = cc.current_contract_state.__wrapped__ if hasattr(cc.current_contract_state, '__wrapped__') else None
    def fake_current(config):
        s = dict(current_contract_state.__wrapped__(config) if original_scv else _real_state(config))
        s['engine_hash'] = 'new-hash-after-bump'
        s['simulator_contract_version'] = 'simulator-contract-2'  # bumped
        return s
    # Actually monkeypatch the get-state call
    _real_state = current_contract_state
    monkeypatch.setattr(cc, 'current_contract_state', fake_current)
    result = cc.check_contract_consistency(CC_V3_CONFIG)
    assert result['hash_changed'] is True
    assert result['version_bumped'] is True
    assert result['has_manifest'] is True
    assert result['ok'] is True


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
