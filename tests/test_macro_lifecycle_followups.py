import json
import sqlite3
from datetime import datetime, timedelta


def test_cached_score_requires_current_contract(tmp_path, monkeypatch):
    import portfolio_ai as pai
    db = tmp_path / "scores.db"
    db.touch()
    monkeypatch.setattr(pai, "DB_PATH", db)
    pai._init_ai_tables()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {"scorer_contract_hash": "old", "rate_sensitivity": {"score": 5, "reason": "x"}}
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO holding_macro_scores(ticker,scores,updated_at) VALUES (?,?,?)",
                     ("XOM", json.dumps(payload), now))
        conn.commit()
        assert pai._classify_macro_coverage("XOM", conn) == "stale_scorer_contract"
    scores, block = pai._get_macro_scores_block(["XOM"])
    assert scores == {}
    assert block == ""


def test_cached_score_missing_contract_is_not_current(tmp_path, monkeypatch):
    import portfolio_ai as pai
    db = tmp_path / "scores.db"
    db.touch()
    monkeypatch.setattr(pai, "DB_PATH", db)
    pai._init_ai_tables()
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO holding_macro_scores(ticker,scores,updated_at) VALUES (?,?,?)",
                     ("XOM", json.dumps({}), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        assert pai._classify_macro_coverage("XOM", conn) == "stale_scorer_contract"


def test_shared_response_parser_rejects_production_invalid_shape():
    import portfolio_ai as pai
    good = {"XOM": {d: {"score": 5, "reason": "because"} for d in pai._MACRO_SCORE_DIMS}}
    assert pai._parse_and_validate_macro_score_response(json.dumps(good), "XOM")["rate_sensitivity"]["score"] == 5
    bad = {"XOM": {d: {"score": 5, "reason": ""} for d in pai._MACRO_SCORE_DIMS}}
    try:
        pai._parse_and_validate_macro_score_response(json.dumps(bad), "XOM")
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("empty reasons must be rejected")


def test_drift_provenance_classifies_contract_and_input_changes(tmp_path, monkeypatch):
    from scripts import validate_macro_scorer as v
    db = tmp_path / "drift.db"
    db.touch()
    monkeypatch.setattr(v, "DB_PATH", db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE holding_macro_scores_history(ticker TEXT,scores TEXT,evidence_hash TEXT,scored_at TEXT)")
        base = {d: {"score": 5, "reason": "x"} for d in v.DIMS}
        first = dict(base, scorer_contract_hash="a", prompt_hash="p")
        second = dict(base, scorer_contract_hash="b", prompt_hash="p")
        conn.execute("INSERT INTO holding_macro_scores_history VALUES (?,?,?,?)", ("XOM", json.dumps(first), "e", "2026-01-01"))
        conn.execute("INSERT INTO holding_macro_scores_history VALUES (?,?,?,?)", ("XOM", json.dumps(second), "e", "2026-01-02"))
        conn.commit()
    result = v.run_drift_detection()
    assert result["provenance_events"] == [{"ticker": "XOM", "classification": "contract_changed"}]


def test_zero_interaction_is_not_negative():
    from scripts.macro_attribution import _rate_interaction_sign
    assert _rate_interaction_sign({"macro": {"rate_interaction": 0}}) is None


def test_generate_scores_refreshes_fresh_old_contract_cache(tmp_path, monkeypatch):
    import macro_context
    import ollama_client
    import portfolio_ai as pai
    db = tmp_path / "scores.db"
    db.touch()
    monkeypatch.setattr(pai, "DB_PATH", db)
    pai._init_ai_tables()
    monkeypatch.setattr(pai, "_load_holdings_csv", lambda: [{"Stock": "XOM"}])
    monkeypatch.setattr(pai, "_fetch_company_evidence", lambda *args: {"evidence_quality": "full"})
    monkeypatch.setattr(pai, "_compute_equity_betas", lambda *args: None)
    monkeypatch.setattr(pai, "_n_samples_for_dim", lambda *args: 1)
    monkeypatch.setattr(macro_context, "fetch", lambda: {})
    monkeypatch.setattr(ollama_client, "available", lambda: True)
    monkeypatch.setattr(pai.time, "sleep", lambda *args: None)
    calls = []
    def stream(prompt, **kwargs):
        calls.append(prompt)
        yield json.dumps({"XOM": {d: {"score": 5, "reason": "fixture"} for d in pai._MACRO_SCORE_DIMS}})
    monkeypatch.setattr(ollama_client, "stream_generate", stream)
    old = {d: {"score": 4, "reason": "old"} for d in pai._MACRO_SCORE_DIMS}
    old["scorer_contract_hash"] = "old-contract"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO holding_macro_scores(ticker,scores,updated_at) VALUES (?,?,datetime('now'))",
                     ("XOM", json.dumps(old)))
        conn.commit()
    result = pai.generate_holding_macro_scores(force=False)
    assert calls and result["XOM"]["scorer_contract_hash"] == pai._compute_scorer_contract_hash()


def test_generate_scores_reuses_fresh_current_contract_cache(tmp_path, monkeypatch):
    import macro_context
    import ollama_client
    import portfolio_ai as pai
    db = tmp_path / "scores.db"
    db.touch()
    monkeypatch.setattr(pai, "DB_PATH", db)
    pai._init_ai_tables()
    monkeypatch.setattr(pai, "_load_holdings_csv", lambda: [{"Stock": "XOM"}])
    monkeypatch.setattr(ollama_client, "available", lambda: True)
    calls = []
    monkeypatch.setattr(ollama_client, "stream_generate", lambda *args, **kwargs: calls.append(True) or iter(()))
    payload = {d: {"score": 5, "reason": "current"} for d in pai._MACRO_SCORE_DIMS}
    payload["scorer_contract_hash"] = pai._compute_scorer_contract_hash()
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO holding_macro_scores(ticker,scores,updated_at) VALUES (?,?,datetime('now'))",
                     ("XOM", json.dumps(payload)))
        conn.commit()
    result = pai.generate_holding_macro_scores(force=False)
    assert result["XOM"]["scorer_contract_hash"] == pai._compute_scorer_contract_hash()
    assert calls == []


def test_dimension_policy_is_single_and_range_is_diagnostic():
    import portfolio_ai as pai
    state = pai._dimension_validation_state(
        {"n": 20, "stdev": 0.45, "range": 2},
        {"n_repeats": 20, "thresholds": {"same_input_score_max_range": 1}},
    )
    assert state == {"stability_class": "stable", "eligible": True,
                    "eligibility_reason": "range_warning", "range_warning": True}
    unstable = pai._dimension_validation_state(
        {"n": 20, "stdev": 1.8, "range": 1}, {"n_repeats": 20, "thresholds": {}}
    )
    assert unstable["eligible"] is False and unstable["stability_class"] == "unstable"


def test_ledger_requires_current_complete_contract(tmp_path, monkeypatch):
    from scripts import validate_macro_scorer as v
    db = tmp_path / "ledger.db"
    db.touch()
    monkeypatch.setattr(v, "DB_PATH", db)
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE macro_scoring_runs(
            run_id TEXT, expected_n INTEGER, scored_n INTEGER, failed_n INTEGER,
            supported_scored_n INTEGER, unsupported_n INTEGER, status TEXT,
            scorer_contract_hash TEXT)""")
        conn.execute("INSERT INTO macro_scoring_runs VALUES (?,?,?,?,?,?,?,?)",
                     ("old", 28, 28, 0, 28, 0, "COMPLETE", "old"))
        conn.commit()
    assert v.run_ledger_integrity("current", True)["status"] == "FAIL"
