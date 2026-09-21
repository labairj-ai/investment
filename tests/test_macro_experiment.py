import json
import sqlite3
import time
from datetime import datetime, timezone

import pytest
import agent_db
from agents.learning import macro_experiment as mx


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_db, "DB_PATH", tmp_path / "experiment.db")
    agent_db.DB_PATH.touch()
    agent_db.migrate()
    conn = agent_db._connect()
    monkeypatch.setattr(mx, "accepted_contract", lambda conn, at: {
        "record_id": "accepted", "accepted_at": 1, "scorer_contract_hash": "scorer",
        "config_version": "v1.7", "config_hash": "config", "model_identity": "model"})
    monkeypatch.setattr(mx, "base_contract", lambda: "base")
    yield conn
    conn.close()


def cohort(db, monkeypatch, *, at=None, run="run", no_macro=False):
    at = time.time() - 1 if at is None else at
    monkeypatch.setattr(mx.time, "time", lambda: at + 1)
    epoch = mx.register_epoch(db, now=at - 1)
    candidates = []
    for ticker, base, rate in (("AAA", 60, 10), ("BBB", 59, 1)):
        snap = {"coverage_state": "company_supported",
                "usable_dimensions": [] if no_macro else ["rate_sensitivity"],
                "rate_sensitivity": {"score": rate}, "macro_acceptance_record_id": "accepted",
                "scorer_contract_hash": "scorer", "macro_config_hash": "config",
                "prompt_hash": "prompt", "evidence_hash": "evidence", "macro_score_timestamp": at - 1}
        eid = run + ticker
        db.execute("INSERT INTO decision_episodes(episode_id,run_id,ticker,captured_at,base_score,sector,macro_snapshot,macro_epoch) VALUES (?,?,?,?,?,?,?,?)",
                   (eid, run, ticker, at, base, "Technology", json.dumps(snap), epoch))
        candidates.append({"ticker": ticker, "_episode_id": eid, "_composite": base, "price": 100})
    cid = mx.observe_cohort(db, epoch, run, run, candidates, at)
    db.commit()
    return epoch, cid, candidates, at


def label(db, candidates, now, version="sessions_v2", null=False):
    for c, alpha in zip(candidates, (.01, .03)):
        db.execute("INSERT INTO episode_outcomes(episode_id,horizon,ticker_return,spy_return,alpha,mfe,mae,labeled_at,horizon_definition_version) VALUES (?,?,?,?,?,?,?,?,?)",
                   (c["_episode_id"], "3m", alpha + .02, .02, None if null else alpha, .1, -.05, now, version))


def test_pairing_is_immutable_idempotent_and_shadow_only(db, monkeypatch):
    epoch, cid, candidates, at = cohort(db, monkeypatch)
    row = db.execute("SELECT * FROM macro_experiment_cohorts").fetchone()
    assert (row["control_ticker"], row["macro_ticker"], row["diverged"]) == ("AAA", "BBB", 1)
    assert [c["_composite"] for c in candidates] == [60, 59]
    assert mx.observe_cohort(db, epoch, "retry", "run", candidates, at) == cid
    assert db.execute("SELECT COUNT(*) FROM virtual_fills").fetchone()[0] == 2
    assert all(r[0].startswith("MACRO_") for r in db.execute("SELECT book_id FROM virtual_fills"))
    assert db.execute("SELECT SUM(is_complete) FROM virtual_book_nav").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE macro_experiment_cohorts SET diverged=0")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE decision_episodes SET macro_snapshot='{}'")
    candidates[0]["price"] = 101
    with pytest.raises(ValueError, match="universe"):
        mx.observe_cohort(db, epoch, "retry", "run", candidates, at)


def test_coverage_gap_excluded_and_no_books(db, monkeypatch):
    epoch, _, _, _ = cohort(db, monkeypatch, no_macro=True)
    report = mx.evaluate(db, epoch_id=epoch)
    assert report["prospective_cohorts"] == 0
    assert report["excluded_cohorts"] == 1
    assert report["evidence_state"] == "INSUFFICIENT"
    assert db.execute("SELECT COUNT(*) FROM virtual_fills").fetchone()[0] == 0


def test_exact_version_maturity_and_missing_labels(db, monkeypatch):
    at = datetime(2025, 1, 2, 15, tzinfo=timezone.utc).timestamp()
    epoch, _, candidates, _ = cohort(db, monkeypatch, at=at)
    now = at + 150 * 86400
    label(db, candidates, now, version="calendar_v1")
    assert mx.sync_labels(db, now=now) == 0
    label(db, candidates, now)
    assert mx.sync_labels(db, now=at + 86400) == 0
    assert mx.sync_labels(db, now=now) == 1
    assert mx.sync_labels(db, now=now) == 0
    report = mx.evaluate(db, now=now, epoch_id=epoch)
    assert report["matured_divergent"] == 1
    assert report["mean_selection_delta"] == pytest.approx(.02)
    assert report["mean_ci"] is None
    assert report["evidence_state"] == "INSUFFICIENT"
    assert report["dimension_ablations"]["rates"]["n"] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("DELETE FROM macro_experiment_labels")


def test_null_alpha_is_unevaluable(db, monkeypatch):
    at = datetime(2025, 1, 2, 15, tzinfo=timezone.utc).timestamp()
    epoch, _, candidates, _ = cohort(db, monkeypatch, at=at)
    now = at + 150 * 86400
    label(db, candidates, now, null=True)
    assert mx.sync_labels(db, now=now) == 0
    assert mx.evaluate(db, now=now, epoch_id=epoch)["unevaluable_matured"] == 1


def test_epoch_changes_are_not_pooled(db, monkeypatch):
    first, _, _, _ = cohort(db, monkeypatch)
    monkeypatch.setattr(mx, "base_contract", lambda: "changed")
    second = mx.register_epoch(db)
    assert second != first
    assert mx.evaluate(db)["prospective_cohorts"] == 0
    assert mx.evaluate(db, epoch_id=first)["prospective_cohorts"] == 1


def test_bootstrap_clusters_dates_and_is_reproducible():
    p = mx.load_protocol()
    assert mx.summarize([("one", .03)] * 100, p)["mean_ci"] is None
    pairs = [("one", .03)] * 10 + [("two", -.02)] * 10
    summary = mx.summarize(pairs, p)
    assert summary == mx.summarize(pairs, p)
    assert summary["mean_ci"][0] < 0 < summary["mean_ci"][1]


def test_stages_and_missing_dimensions_are_bounded():
    p = mx.load_protocol()
    assert mx.adjustment({"coverage_state": "company_supported", "usable_dimensions": []}, p) == 0
    assert mx.stage_adjustment(60, 100) == 60
    for stage in range(1, 5):
        with pytest.raises(ValueError, match="promotion"):
            mx.stage_adjustment(60, 100, stage)
        assert mx.stage_adjustment(60, 100, stage, evidence_positive=True, approved=True, near_tie_gap=0) <= 65
    assert mx.stage_adjustment(60, 100, 1, evidence_positive=True, approved=True, near_tie_gap=2) == 60


def test_historical_and_future_enrollment_rejected(db, monkeypatch):
    epoch, _, candidates, at = cohort(db, monkeypatch)
    monkeypatch.setattr(mx.time, "time", lambda: at + 400)
    with pytest.raises(ValueError, match="historical"):
        mx.observe_cohort(db, epoch, "old", "run", candidates, at)
    monkeypatch.setattr(mx.time, "time", lambda: at - 1)
    with pytest.raises(ValueError, match="historical"):
        mx.observe_cohort(db, epoch, "future", "run", candidates, at)


def test_migrations_are_repeatable(db):
    mx.migrate(db)
    assert len(db.execute("PRAGMA table_info(macro_experiment_cohorts)").fetchall()) == 22


@pytest.fixture
def provenance_db(db, monkeypatch):
    import portfolio_ai as pai
    monkeypatch.setattr(pai, "DB_PATH", agent_db.DB_PATH)
    pai._init_ai_tables()
    contract = pai._compute_scorer_contract_hash()
    model = pai.ollama_client.DEFAULT_MODEL
    artifact = {"activated": True, "verdict": "PASS", "run_type": "acceptance",
                "scorer_contract_hash": contract, "validation_config_version": "v1.7",
                "validation_config_hash": "config", "model_identity": model}
    db.execute("INSERT INTO macro_acceptance_state(contract,accepted_at,record_id,scorer_contract_hash) VALUES (?,?,?,?)",
               ("macro_validation_v1", "2025-01-01T00:00:00Z", "acc", contract))
    db.execute("INSERT INTO macro_validation_runs(record_id,output_path,run_type,verdict,artifact_json,recorded_at) VALUES (?,?,?,?,?,?)", ("acc", "fixture", "acceptance", "PASS", json.dumps(artifact), "2025-01-01"))
    scores = {"scorer_contract_hash": contract, "model_version": model, "prompt_hash": "prompt", "evidence_hash": "evidence"}
    from agents.learning.macro_provenance import DIMS
    for dim in DIMS:
        scores[dim] = {"score": 5}
        scores[pai._DIM_EV_KEY[dim]] = "full"
        db.execute("INSERT INTO macro_dimension_validation(acceptance_record_id,ticker,dimension,eligible,config_hash,scorer_contract_hash,n_samples,model_identity) VALUES (?,?,?,?,?,?,?,?)",
                   ("acc", "XOM", dim, 1, "config", contract, 20, model))
    db.execute("INSERT INTO holding_macro_scores(ticker,scores,updated_at,run_id) VALUES (?,?,?,?)",
               ("XOM", json.dumps(scores), "2025-01-02T10:00:00-05:00", "score-run"))
    db.execute("INSERT INTO macro_scoring_run_items(run_id,ticker,status,completed_at,scorer_contract_hash) VALUES (?,?,?,?,?)", ("score-run", "XOM", "SUPPORTED", "2025-01-02T10:00:00-05:00", contract))
    db.commit()
    return db, scores


def test_real_provenance_uses_same_database_and_typed_eligibility(provenance_db):
    from agents.learning.macro_provenance import snapshot, DIMS
    db, _ = provenance_db
    at = datetime(2025, 1, 2, 16, tzinfo=timezone.utc).timestamp()
    snap = snapshot("XOM", db, at)
    assert snap["usable_dimensions"] == list(DIMS)
    assert snap["macro_acceptance_record_id"] == "acc"
    assert snap["macro_config_version"] == "v1.7"
    db.execute("UPDATE macro_dimension_validation SET eligible=0 WHERE dimension='rate_sensitivity'")
    assert "rate_sensitivity" not in snapshot("XOM", db, at)["usable_dimensions"]
    assert snapshot("SPY", db, at)["coverage_state"] == "fund_unsupported"


def test_provenance_future_stale_and_wrong_contract_fail_closed(provenance_db):
    from agents.learning.macro_provenance import snapshot
    db, scores = provenance_db
    at = datetime(2025, 1, 2, 16, tzinfo=timezone.utc).timestamp()
    assert snapshot("XOM", db, at - 7200)["coverage_state"] == "future_or_invalid_score"
    assert snapshot("XOM", db, at + 30 * 86400)["coverage_state"] == "stale_score"
    scores["scorer_contract_hash"] = "wrong"
    db.execute("UPDATE holding_macro_scores SET scores=?", (json.dumps(scores),))
    assert snapshot("XOM", db, at)["usable_dimensions"] == []


def test_capture_freezes_accepted_epoch_snapshot(provenance_db, monkeypatch):
    from agents.learning.episode_capture import capture_candidate_episode
    db, _ = provenance_db
    at = datetime(2025, 1, 2, 16, tzinfo=timezone.utc).timestamp()
    eid = capture_candidate_episode(1, {"ticker": "XOM", "_composite": 60}, captured_at=at, macro_epoch="epoch")
    row = db.execute("SELECT * FROM decision_episodes WHERE episode_id=?", (eid,)).fetchone()
    assert row["macro_acceptance_record_id"] == "acc"
    assert row["macro_config_version"] == "v1.7"
    assert json.loads(row["macro_usable_dimensions"])
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE decision_episodes SET macro_epoch='changed' WHERE episode_id=?", (eid,))


def test_automatic_sweep_records_excluded_cohort_without_recommendation(db, monkeypatch, sample_snapshot):
    from agents import opportunity_agent as oa
    from agents.contracts import AgentContext
    monkeypatch.setattr(oa, "_get_buffett_winners", lambda: [{"ticker": "NO_MACRO", "quality_score": 0}])
    monkeypatch.setattr(oa, "_get_manual_candidates", lambda: [])
    monkeypatch.setattr(oa, "_get_current_tickers", lambda: set())
    monkeypatch.setattr(oa, "_get_layer_weights", lambda: {})
    monkeypatch.setattr(oa, "_get_holding_sectors", lambda held: {})
    monkeypatch.setattr(oa, "_composite", lambda *args: 0)
    assert oa.run_opportunity_hunter(AgentContext(run_id=42, snapshot=sample_snapshot, trigger_type="scheduled")) == []
    row = db.execute("SELECT * FROM macro_experiment_cohorts").fetchone()
    assert row["status"] == "EXCLUDED"
    assert row["exclusion_reason"] == "no_base_eligible_candidates"
    episode = db.execute("SELECT * FROM decision_episodes").fetchone()
    assert episode["macro_epoch"] == row["epoch_id"]
    assert episode["captured_at"] == row["captured_at"]


def test_report_uses_complete_mtm_not_cost_basis(db, monkeypatch):
    epoch, _, _, _ = cohort(db, monkeypatch)
    bid = mx._book_ids(epoch)[0]
    assert mx._book_report(db, bid)["cumulative_return"] is None
    db.execute("INSERT INTO virtual_book_nav(book_id,date,total_nav,is_complete) VALUES (?,?,?,1)", (bid, "2025-01-02", 101000))
    db.execute("INSERT INTO virtual_book_nav(book_id,date,total_nav,is_complete) VALUES (?,?,?,1)", (bid, "2025-01-03", 100000))
    report = mx._book_report(db, bid)
    assert report["complete_days"] == 2
    assert report["cumulative_return"] == 0
    assert report["max_drawdown"] == pytest.approx(1 - 100000 / 101000)


def test_future_financial_evidence_is_rejected(db, monkeypatch):
    epoch, _, candidates, at = cohort(db, monkeypatch)
    candidates[0]["scanned_at"] = "2099-01-01"
    with pytest.raises(ValueError, match="financial evidence"):
        mx.observe_cohort(db, epoch, "future", "run", candidates, at)
