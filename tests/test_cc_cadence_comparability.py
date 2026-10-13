"""Tests for CC Simulator Cadence Comparability (0714)."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone,date
import pytest
from time_utils import parse_timestamp, TZ_EASTERN
from covered_call_validation import (
    classify_cadence_comparability, divergence_category,
    CADENCE_COMPARABILITY_POLICY_VERSION,
)


def _ts(hour,minute=0,day=14):
    """Create an eastern-timezone timestamp for 2026-10-{day}."""
    return datetime(2026,10,day,hour,minute,tzinfo=TZ_EASTERN).isoformat()


def _expiry():
    return date(2026,11,14)


def test_directly_comparable_when_actual_matches_slot():
    # Actual eval at 10:00 exactly; cadence is 30min; slot exists at 10:00
    entry=_ts(9,30)
    actual=[_ts(10,0)]
    result=classify_cadence_comparability(actual,entry,_expiry(),30)
    assert result['comparable_n']>=1
    direct=[s for s in result['slots'] if s['classification']=='COMPARABLE_DIRECT']
    assert len(direct)>=1


def test_virtual_only_slot_when_no_actual_match():
    # Entry at 9:30, actual only evaluated at 15:30; everything between is virtual-only
    entry=_ts(9,30)
    actual=[_ts(15,30)]
    result=classify_cadence_comparability(actual,entry,_expiry(),30)
    assert result['virtual_only_n']>0


def test_no_double_pairing():
    # Two actual timestamps close together should not both pair to the same slot
    entry=_ts(9,30)
    actual=[_ts(10,0),_ts(10,5)]
    result=classify_cadence_comparability(actual,entry,_expiry(),30)
    direct=[s for s in result['slots'] if s['classification']=='COMPARABLE_DIRECT']
    actual_only=result['actual_only']
    # Each actual timestamp pairs to at most one slot
    assert len(direct)+len(actual_only)==len(actual)


def test_action_agreement_denominator_not_double_counted():
    # With no comparable slots, comparable_n should be 0
    entry=_ts(9,30)
    actual=[]
    result=classify_cadence_comparability(actual,entry,_expiry(),30)
    assert result['comparable_n']==0
    assert result['actual_observation_n']==0


def test_actual_only_when_actual_outside_cadence_tolerance():
    # Actual at 16:30 (after close) — not in any cadence slot
    entry=_ts(9,30)
    actual=[_ts(16,30)]  # after close
    result=classify_cadence_comparability(actual,entry,_expiry(),30)
    # 16:30 is after _MARKET_CLOSE_HOUR (16) so no slots exist there
    assert result['actual_only_n']==1


def test_pct_comparable_computed():
    entry=_ts(9,30)
    actual=[_ts(10,0),_ts(10,30)]
    result=classify_cadence_comparability(actual,entry,_expiry(),30)
    assert result['pct_comparable'] is not None
    assert 0<=result['pct_comparable']<=100


def test_cadence_mode_is_strict_matched():
    result=classify_cadence_comparability([],_ts(9,30),_expiry(),30)
    assert result['cadence_mode']=='STRICT_MATCHED_CADENCE'


def test_cadence_policy_version_field():
    result=classify_cadence_comparability([],_ts(9,30),_expiry(),30)
    assert result['cadence_comparability_policy_version']==CADENCE_COMPARABILITY_POLICY_VERSION


def test_divergence_category_virtual_earlier_opportunity():
    # Case with timing error AND virtual_only_n > 0 → VIRTUAL_EARLIER_OPPORTUNITY
    case=dict(
        intervention_timing_error=2,
        human_overrides=[],lookahead_violations=0,state_contamination=0,
        entry_fill_spread_error=0.01,action_agreement=1.0,
        strike_differences=[],expiry_day_differences=[],
        alpha_absolute_error=0,fee_error=0,
        cadence_comparability=dict(virtual_only_n=5,comparable_n=10,actual_only_n=0)
    )
    assert divergence_category(case)=='VIRTUAL_EARLIER_OPPORTUNITY'


def test_divergence_category_data_timing_without_cadence_gap():
    # Timing error but no virtual_only_n → DATA_TIMING (not cadence effect)
    case=dict(
        intervention_timing_error=2,
        human_overrides=[],lookahead_violations=0,state_contamination=0,
        entry_fill_spread_error=0.01,action_agreement=1.0,
        strike_differences=[],expiry_day_differences=[],
        alpha_absolute_error=0,fee_error=0,
        cadence_comparability=dict(virtual_only_n=0,comparable_n=10,actual_only_n=0)
    )
    assert divergence_category(case)=='DATA_TIMING'


def test_divergence_category_policy_mismatch_unchanged():
    # Policy mismatch should still be POLICY_MISMATCH regardless of cadence
    case=dict(
        intervention_timing_error=0,
        human_overrides=[],lookahead_violations=0,state_contamination=0,
        entry_fill_spread_error=0.01,action_agreement=0.8,
        strike_differences=[],expiry_day_differences=[],
        alpha_absolute_error=0,fee_error=0,
        cadence_comparability=dict(virtual_only_n=5,comparable_n=10,actual_only_n=0)
    )
    assert divergence_category(case)=='POLICY_MISMATCH'


def test_certification_invalidated_by_cadence_policy_version_change(tmp_path,monkeypatch):
    from copy import deepcopy
    import covered_call_validation as val
    import covered_call_ledger as ledger
    import covered_call_evidence as evidence
    from strategy_config import CC_V3_CONFIG
    # Verify that a cert with a different cadence policy version is rejected
    monkeypatch.setattr(evidence,'committed_policy',lambda *a:True)
    cfg=deepcopy(CC_V3_CONFIG)
    path=tmp_path/'cc.db'
    # If CADENCE_COMPARABILITY_POLICY_VERSION changes, certs with the old version are rejected
    # We simulate this by checking that certification() skips certs with wrong version
    db=ledger.connect(path);ledger.migrate(db);val.migrate(db)
    import json
    from covered_call_outcomes import digest
    from time_utils import now_utc_iso
    # Insert a fake cert with a different cadence version
    fake_cert=dict(
        simulator_version=val.SIMULATOR_VERSION,
        simulator_contract_version=val.SIMULATOR_CONTRACT_VERSION,
        simulator_contract_hash=val.simulator_contract_hash(cfg),
        config_hash=ledger.config_digest(cfg),
        management_contract=val.management_contract(),
        validation_policy_version=cfg['simulator_validation']['version'],
        cadence_comparability_policy_version='cadence-v0',  # old version
        cohort_ids=[],metrics={},git_sha='abc',certified_at_git_sha='abc',
        management_contract_hash=val.management_contract()['engine_hash'],
        config_contract_hash=val._config_contract_hash(cfg),
    )
    cert_id=digest(fake_cert)
    with db:
        db.execute("INSERT OR IGNORE INTO cc_simulator_validation_runs VALUES(?,?,?,?,?,?)",
            ('run1',now_utc_iso(),val.SIMULATOR_VERSION,ledger.config_digest(cfg),'abc','{}'))
        db.execute("INSERT OR IGNORE INTO cc_simulator_certifications VALUES(?,?,?,?)",
            (cert_id,'run1',now_utc_iso(),json.dumps(fake_cert,sort_keys=True)))
    db.close()
    result=val.certification(cfg,path)
    assert result is None  # old cadence version cert is rejected
