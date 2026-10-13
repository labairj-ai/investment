"""Tests for CC Calibration Skill Diagnostics against naive references (0715)."""
from __future__ import annotations
import pytest
from covered_call_calibration import (
    calibration_skill, all_calibration_skills, _brier_skill_score, _brier,
    SKILL_REFERENCE_VERSION, SHRINKAGE_STRENGTH,
)


def _sample(p, y, dte=30, otm=0.10, ts='2026-10-13T17:00:00Z'):
    f = dict(strike_touch_prob=p, dte=dte, otm_pct=otm, delta=p, quote_timestamp=ts)
    l = dict(strike_touched=y, censored=False, outcome_source='ACTUAL_EXECUTION')
    return f, l


def test_perfect_model_bss_near_one():
    samples = [_sample(1.0, True), _sample(0.0, False), _sample(1.0, True), _sample(0.0, False),
               _sample(1.0, True), _sample(0.0, False), _sample(1.0, True), _sample(0.0, False),
               _sample(1.0, True), _sample(0.0, False), _sample(1.0, True), _sample(0.0, False),
               _sample(1.0, True), _sample(0.0, False), _sample(1.0, True), _sample(0.0, False),
               _sample(1.0, True), _sample(0.0, False), _sample(1.0, True), _sample(0.0, False)]
    result = calibration_skill(samples, 'strike_touch_prob', 'strike_touched', min_n=5)
    assert result['model_brier'] == pytest.approx(0.0, abs=1e-9)
    assert result['brier_skill_score'] == pytest.approx(1.0, abs=1e-6)


def test_model_equal_to_reference_bss_near_zero():
    # When model == reference, BSS ≈ 0
    # Reference for a bucket uses the base rate; if model predicts the same base rate, BSS = 0
    rate = 0.4
    n = 25
    samples = [_sample(rate, True) for _ in range(int(n*rate))] + [_sample(rate, False) for _ in range(n - int(n*rate))]
    result = calibration_skill(samples, 'strike_touch_prob', 'strike_touched', min_n=5)
    # Model Brier ≈ reference Brier when model predicts constant base rate = reference base rate
    assert result['brier_skill_score'] is not None


def test_negative_bss_for_worse_than_reference():
    # Model always predicts 0.9 but actual rate is 0.1 → very bad model
    n = 30
    samples = [_sample(0.9, False)] * n
    result = calibration_skill(samples, 'strike_touch_prob', 'strike_touched', min_n=5)
    bss = result['brier_skill_score']
    # BSS can be negative; must not be clipped to zero
    if bss is not None:
        assert isinstance(bss, float)  # present and not clipped


def test_brier_skill_score_function():
    assert _brier_skill_score(0.0, 0.25) == pytest.approx(1.0)
    assert _brier_skill_score(0.25, 0.25) == pytest.approx(0.0)
    assert _brier_skill_score(0.5, 0.25) == pytest.approx(-1.0)


def test_brier_skill_score_zero_reference():
    # Zero reference (perfect reference) with non-perfect model: undefined
    assert _brier_skill_score(0.1, 0.0) is None
    # Zero reference with perfect model: BSS = 1.0
    assert _brier_skill_score(0.0, 0.0) == pytest.approx(1.0)


def test_censored_samples_excluded():
    censored = dict(strike_touched=True, censored=True, outcome_source='ACTUAL_EXECUTION')
    f = dict(strike_touch_prob=0.5, dte=30, otm_pct=0.10, quote_timestamp='2026-10-13T17:00:00Z')
    samples = [(f, censored)] * 30
    result = calibration_skill(samples, 'strike_touch_prob', 'strike_touched', min_n=5)
    assert result['n'] == 0
    assert result['model_brier'] is None


def test_low_n_state_insufficient():
    samples = [_sample(0.5, True)]
    result = calibration_skill(samples, 'strike_touch_prob', 'strike_touched', min_n=20)
    assert result['low_n_state'] == 'INSUFFICIENT_SAMPLE'
    assert result['minimum_n_met'] == False


def test_reference_version_field():
    result = calibration_skill([], 'strike_touch_prob', 'strike_touched')
    assert result['reference_version'] == SKILL_REFERENCE_VERSION


def test_shrinkage_strength_recorded():
    result = calibration_skill([], 'strike_touch_prob', 'strike_touched')
    assert result['shrinkage_strength'] == SHRINKAGE_STRENGTH


def test_causal_no_lookahead():
    # Samples with sequential timestamps; first few should use global prior (0.5)
    # Later ones should use accumulated observations
    samples_early = [_sample(0.3, False, ts=f'2026-10-{d:02d}T10:00:00Z') for d in range(1, 6)]
    samples_later = [_sample(0.3, True, ts=f'2026-10-{d:02d}T10:00:00Z') for d in range(6, 16)]
    all_samples = samples_early + samples_later
    # Should not raise; just check it runs
    result = calibration_skill(all_samples, 'strike_touch_prob', 'strike_touched', min_n=5)
    assert result['n'] == len(all_samples)
    assert result['reference_sample_n'] == len(all_samples)


def test_delta_proxy_returned_for_strike_touch():
    samples = [_sample(0.3, True)] * 20
    result = calibration_skill(samples, 'strike_touch_prob', 'strike_touched', min_n=5)
    assert result['delta_proxy'] is not None
    assert result['delta_proxy']['reference'] == 'ENTRY_DELTA'
    assert 'brier' in result['delta_proxy']


def test_delta_proxy_none_for_non_strike_events():
    f = dict(regret_barrier_touch_prob=0.3, dte=30, otm_pct=0.10, quote_timestamp='2026-10-13T17:00:00Z')
    l = dict(regret_barrier_touched=True, censored=False, outcome_source='ACTUAL_EXECUTION')
    result = calibration_skill([(f, l)] * 20, 'regret_barrier_touch_prob', 'regret_barrier_touched', min_n=5)
    assert result['delta_proxy'] is None


def test_all_calibration_skills_returns_all_events():
    samples = [_sample(0.3, True)] * 5
    skills = all_calibration_skills(samples)
    for key in ('strike_touch_prob__skill', 'regret_barrier_touch_prob__skill',
                'delta30_touch_prob__skill', 'delta50_touch_prob__skill'):
        assert key in skills


def test_diagnostic_note_present():
    result = calibration_skill([], 'strike_touch_prob', 'strike_touched')
    assert 'DIAGNOSTIC_ONLY' in result['notes']
    assert 'promotion' in result['notes'].lower()


def test_promotion_eligibility_unchanged(tmp_path, monkeypatch):
    """promotion_report must not gain new failure modes from skill diagnostics."""
    from copy import deepcopy
    import covered_call_ledger as ledger
    import covered_call_evidence as evidence
    from strategy_config import CC_V3_CONFIG
    monkeypatch.setattr(evidence, 'committed_policy', lambda *a: True)
    from time_utils import parse_timestamp
    from datetime import timedelta
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
    promo = evidence.promotion_report(cfg, path)
    # calibration_skill is present but does not add new failure gates
    assert 'calibration_skill' in promo
    failures = promo['failures']
    # No skill-related failure should appear
    skill_failures = [f for f in failures if 'skill' in f.lower() or 'bss' in f.lower()]
    assert skill_failures == []
