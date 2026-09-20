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
