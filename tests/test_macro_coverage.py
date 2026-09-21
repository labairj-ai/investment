import json
import sqlite3
import time

import pytest
import agent_db
from agents.learning import macro_coverage as cov
from agents.learning.macro_provenance import snapshot, accepted_contract, DIMS
from agents.learning.macro_experiment import balanced_coverage, load_protocol, adjustment


@pytest.fixture
def db(mem_db, monkeypatch):
    import portfolio_ai as pai
    from scripts import validate_macro_scorer as v
    monkeypatch.setattr(pai, "DB_PATH", mem_db)
    pai._init_ai_tables()
    conn = agent_db._connect()
    config = v._load_validation_config()
    contract = pai._compute_scorer_contract_hash()
    model = pai.ollama_client.DEFAULT_MODEL
    artifact = {"activated": True, "verdict": "PASS", "run_type": "acceptance",
                "scorer_contract_hash": contract, "validation_config_version": "v1.8",
                "validation_config_hash": "config", "model_identity": model, "config_used": config}
    conn.execute("INSERT INTO macro_acceptance_state(contract,accepted_at,record_id,scorer_contract_hash) VALUES (?,?,?,?)",
                 ("macro_validation_v1", "2026-01-01T00:00:00Z", "acc", contract))
    conn.execute("INSERT INTO macro_validation_runs VALUES (?,?,?,?,?,?)",
                 ("acc", "fixture", "acceptance", "PASS", json.dumps(artifact), "2026-01-01"))
    conn.commit()
    monkeypatch.setattr(pai, "_compute_equity_betas", lambda ticker: {})
    monkeypatch.setattr(pai, "_fetch_company_evidence", lambda ticker, conn: {
        "evidence_quality": "partial", "evidence_quality_rate": "partial",
        "evidence_quality_inflation": "full", "evidence_quality_dollar": "none", "evidence_quality_geo": "none",
        "net_debt": 1, "gross_margin_pct": 30})
    monkeypatch.setattr(v, "_score_one_ticker", lambda *args: {d: {"score": 5, "reason": "fixture"} for d in DIMS})
    monkeypatch.setattr(v.time, "sleep", lambda seconds: None)
    yield conn
    conn.close()


def test_collection_is_separate_and_cannot_grant_eligibility(db):
    rid = cov.score_candidates(db, ["AAA"])
    assert db.execute("SELECT status FROM macro_candidate_scoring_runs WHERE run_id=?", (rid,)).fetchone()[0] == "COMPLETE"
    assert db.execute("SELECT COUNT(*) FROM holding_macro_scores").fetchone()[0] == 0
    assert snapshot("AAA", db, time.time() + 2)["usable_dimensions"] == []
    assert db.execute("SELECT COUNT(*) FROM macro_coverage_validation").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM macro_candidate_score_history").fetchone()[0] == 1


def test_supplemental_certification_is_immutable_and_point_in_time(db):
    cov.score_candidates(db, ["AAA"])
    before = time.time()
    cid = cov.certify(db, ["AAA"])
    now = time.time() + 2
    snap = snapshot("AAA", db, now)
    assert snap["coverage_certified"] is True
    assert set(snap["usable_dimensions"]) == {"rate_sensitivity", "inflation_hedge"}
    assert snap["dimension_eligibility"]["rate_sensitivity"]["certification_id"] == cid
    acc = accepted_contract(db, now)
    assert cov.coverage_row(db, acc, "AAA", "rate_sensitivity", before) is None
    assert cov.coverage_row(db, dict(acc, config_hash="wrong"), "AAA", "rate_sensitivity", now) is None
    assert db.execute("SELECT record_id FROM macro_acceptance_state").fetchone()[0] == "acc"
    assert db.execute("SELECT COUNT(*) FROM macro_dimension_validation").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM macro_validation_runs").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE macro_coverage_validation SET eligible=1")


def test_missing_repeat_cannot_certify(db, monkeypatch):
    from scripts import validate_macro_scorer as v
    monkeypatch.setattr(v, "run_repeatability", lambda *a, **kw: {"AAA": {d: {"n": 19, "mean": 5, "stdev": 0, "range": 0} for d in DIMS}})
    cid = cov.certify(db, ["AAA"])
    assert db.execute("SELECT status FROM macro_coverage_certifications WHERE certification_id=?", (cid,)).fetchone()[0] == "FAILED"
    assert db.execute("SELECT SUM(eligible) FROM macro_coverage_validation").fetchone()[0] == 0


def test_failed_collection_and_lost_process_reconcile(db, monkeypatch):
    from scripts import validate_macro_scorer as v
    monkeypatch.setattr(v, "_score_one_ticker", lambda *args: None)
    rid = cov.score_candidates(db, ["AAA", "BBB"])
    row = db.execute("SELECT * FROM macro_candidate_scoring_runs WHERE run_id=?", (rid,)).fetchone()
    assert (row["status"], row["expected_n"], row["scored_n"], row["failed_n"]) == ("FAILED", 2, 0, 2)
    db.execute("INSERT INTO macro_candidate_scoring_runs VALUES ('lost','STARTED',1,NULL,1,0,0,'h','acc','[]')")
    db.execute("INSERT INTO macro_candidate_scoring_run_items VALUES ('lost','AAA','PENDING','h',NULL,NULL)")
    db.commit()
    cov.reconcile_runs(db, time.time())
    row = db.execute("SELECT status,failed_n FROM macro_candidate_scoring_runs WHERE run_id='lost'").fetchone()
    assert tuple(row) == ("FAILED", 1)


def candidate(ticker, score, dims, certified=True):
    snap = {"coverage_certified": certified, "coverage_state": "company_supported", "usable_dimensions": dims}
    snap.update({d: {"score": 10} for d in dims})
    return {"ticker": ticker, "base_score": score, "risk_eligible": 1, "macro_snapshot": json.dumps(snap)}


def test_balanced_common_dimensions_and_inclusive_envelope():
    rates, inflation, dollar, geo = "rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk"
    rows = [candidate("AAA", 80, [rates, inflation, dollar]), candidate("BBB", 75, [rates, inflation]),
            candidate("CCC", 70, [rates, inflation, geo]), candidate("OUT", 69, [], False)]
    p = load_protocol()
    envelope, common, reason = balanced_coverage(rows, p)
    assert {c["ticker"] for c in envelope} == {"AAA", "BBB", "CCC"}
    assert set(common) == {rates, inflation} and reason is None
    # Original +/- quarter weights cancel; no renormalization or other dimensions.
    assert all(adjustment(json.loads(c["macro_snapshot"]), p, common) == 0 for c in envelope)
    assert rows[-1]["base_score"] + p["adjustment_cap"] < rows[0]["base_score"] - p["adjustment_cap"]
    assert balanced_coverage(rows, dict(p, adjustment_cap=2))[0] == rows[:1]


def test_missing_certificate_and_missing_common_evidence_are_distinct():
    p = load_protocol()
    rows = [candidate("AAA", 80, ["rate_sensitivity"]), candidate("BBB", 79, ["inflation_hedge"])]
    assert balanced_coverage(rows, p)[2] == "no_common_usable_macro_dimensions"
    rows[1] = candidate("BBB", 79, ["rate_sensitivity"], False)
    assert balanced_coverage(rows, p)[2] == "coverage_incomplete"


def test_real_handler_canary_isolated_replay_and_clock(db, monkeypatch, sample_snapshot, tmp_path):
    from agents import opportunity_agent as oa
    from agents import snapshot as portfolio_snapshot
    from agents.learning import macro_experiment as mx
    from scripts.run_macro_coverage_canary import run
    cov.score_candidates(db, ["AAA"])
    cov.certify(db, ["AAA"])
    # Advance the decision clock beyond second-resolution publication guards.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 2)
    monkeypatch.setattr(portfolio_snapshot, "build_portfolio_snapshot", lambda: sample_snapshot)
    monkeypatch.setattr(oa, "_get_buffett_winners", lambda: [{"ticker": "AAA", "quality_score": 100, "price": 100, "sector": "Technology"}])
    monkeypatch.setattr(oa, "_get_manual_candidates", lambda: [])
    monkeypatch.setattr(oa, "_get_current_tickers", lambda: set())
    monkeypatch.setattr(oa, "_get_layer_weights", lambda: {})
    monkeypatch.setattr(oa, "_get_holding_sectors", lambda held: {})
    monkeypatch.setattr(oa, "_composite", lambda *args: 80)
    monkeypatch.setattr(oa, "_llm_select", lambda candidates, weights: {"ticker": "AAA", "why": "fixture", "action": "RESEARCH"})
    target = tmp_path / "canary.json"
    assert run(target)
    result = json.loads(target.read_text())
    assert result["production_parity"] and result["trade_intents_unchanged"]
    assert len(result["books"]) == 2
    assert db.execute("SELECT COUNT(*) FROM macro_experiment_cohorts").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM decision_episodes").fetchone()[0] == 1
    assert mx.evaluate(db)["collection_started_at"] is not None
