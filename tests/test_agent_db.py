"""Tests for agent_db.py — executed_actions ledger and briefing helpers."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_insert_and_get_executed_action(mem_db, monkeypatch):
    import agent_db
    monkeypatch.setattr(agent_db, "DB_PATH", mem_db)

    exec_id = agent_db.insert_executed_action(
        ticker="ANET",
        action="EXIT",
        execution_date="2026-09-06",
        quantity=120.0,
        execution_price=185.0,
        fees=5.0,
        notes="sold all",
    )
    assert exec_id > 0

    rows = agent_db.get_executions_for_rec(None)
    # recommendation_id=None — returns rows where rec_id IS NULL
    assert any(r["ticker"] == "ANET" for r in rows)


def test_get_executions_for_ticker(mem_db, monkeypatch):
    import agent_db
    monkeypatch.setattr(agent_db, "DB_PATH", mem_db)

    agent_db.insert_executed_action(ticker="BRK-B", action="TRIM", execution_date="2026-08-01",
                                    quantity=10.0, execution_price=350.0)
    agent_db.insert_executed_action(ticker="BRK-B", action="TRIM", execution_date="2026-09-01",
                                    quantity=5.0, execution_price=355.0)

    rows = agent_db.get_executions_for_ticker("BRK-B")
    assert len(rows) == 2
    # Should be sorted descending by execution_date
    assert rows[0]["execution_date"] >= rows[1]["execution_date"]


def test_get_executions_for_ticker_with_since(mem_db, monkeypatch):
    import agent_db
    monkeypatch.setattr(agent_db, "DB_PATH", mem_db)

    agent_db.insert_executed_action(ticker="SCHD", action="HOLD", execution_date="2026-06-01",
                                    quantity=10.0, execution_price=78.0)
    agent_db.insert_executed_action(ticker="SCHD", action="TRIM", execution_date="2026-09-01",
                                    quantity=5.0, execution_price=82.0)

    rows = agent_db.get_executions_for_ticker("SCHD", since_date="2026-07-01")
    assert len(rows) == 1
    assert rows[0]["execution_date"] == "2026-09-01"


def test_insert_agent_run_with_audit_fields(mem_db, monkeypatch):
    import json
    import agent_db
    monkeypatch.setattr(agent_db, "DB_PATH", mem_db)

    run_id = agent_db.insert_agent_run(
        agent_type="sell_trim",
        scope="portfolio",
        ticker="ANET",
        trigger_type="portfolio_scope",
        trigger_key="sell_trim_daily",
        model="mlx-community/Qwen3.6-35B-A3B-4bit",
        prompt_version="sell_trim_v2",
        input_hash="abc123def456",
        input_snapshot={
            "ticker": "ANET",
            "price": 180.0,
            "thesis_version": 2,
            "financial_period": "2026-06-30",
        },
    )
    assert run_id > 0

    conn = agent_db._connect()
    row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()

    assert row["trigger_type"] == "portfolio_scope"
    assert row["trigger_key"] == "sell_trim_daily"
    assert row["model"] == "mlx-community/Qwen3.6-35B-A3B-4bit"
    assert row["prompt_version"] == "sell_trim_v2"
    assert row["input_hash"] == "abc123def456"
    assert row["input_snapshot_json"] is not None

    # 0078: verify manifest has thesis_version and financial_period fields
    snap = json.loads(row["input_snapshot_json"])
    assert snap.get("thesis_version") == 2
    assert snap.get("financial_period") == "2026-06-30"


# ── 0086: dependency metadata_json round-trip ────────────────────────────────

def test_dependency_metadata_persists_and_merges(mem_db):
    """write_dependencies() persists metadata; get_open_recs_with_deps() merges it."""
    import agent_db
    # Create a minimal run + recommendation
    run_id = agent_db.insert_agent_run("covered_call")
    rec_id = agent_db.insert_recommendation(
        run_id=run_id, ticker="ANET", action="SELL_CC",
        recommendation_score=60, confidence=70, priority="normal",
        why_now="IV is high", rationale="test", counter_case="", no_action_case="",
    )
    # Write a dependency with metadata
    agent_db.write_dependencies(rec_id, [
        {
            "dependency_type": "OPTION_IV",
            "dependency_key": "ANET",
            "original_value": "0.48",
            "tolerance": 0.20,
            "invalidating_event": None,
            "metadata": {"strike": 175, "expiration": "2026-10-16", "threshold": 0.20},
        }
    ])
    recs = agent_db.get_open_recs_with_deps()
    assert len(recs) == 1
    deps = recs[0]["deps"]
    assert len(deps) == 1
    dep = deps[0]
    # metadata fields should be merged into the dep dict
    assert dep["dependency_type"] == "OPTION_IV"
    assert dep.get("strike") == 175
    assert dep.get("expiration") == "2026-10-16"
    assert dep.get("threshold") == 0.20


def test_dependency_without_metadata_still_works(mem_db):
    """Deps without a 'metadata' key should not break write or read."""
    import agent_db
    run_id = agent_db.insert_agent_run("sell_trim")
    rec_id = agent_db.insert_recommendation(
        run_id=run_id, ticker="BRK.B", action="HOLD",
        recommendation_score=20, confidence=60, priority="low",
        why_now="", rationale="", counter_case="", no_action_case="",
    )
    agent_db.write_dependencies(rec_id, [
        {
            "dependency_type": "PRICE",
            "dependency_key": "BRK.B",
            "original_value": "420.0",
            "tolerance": 0.05,
            "invalidating_event": "PRICE_THRESHOLD",
        }
    ])
    recs = agent_db.get_open_recs_with_deps()
    assert recs[0]["deps"][0]["dependency_type"] == "PRICE"
    # No metadata keys injected beyond the base fields
    assert "strike" not in recs[0]["deps"][0]


# ── 0087: option quote snapshot writer ───────────────────────────────────────

def test_upsert_option_quote_snapshot_creates_row(mem_db):
    """upsert_option_quote_snapshot stores a row and retrieval works."""
    import agent_db
    agent_db.upsert_option_quote_snapshot(
        ticker="ANET",
        strike=175.0,
        expiration="2026-10-16",
        iv=0.48,
        bid=3.20,
        ask=3.40,
        spread_pct=0.059,
    )
    snap = agent_db.get_latest_option_snapshot("ANET", 175.0, "2026-10-16")
    assert snap is not None
    assert abs(float(snap["iv"]) - 0.48) < 0.001
    assert abs(float(snap["bid"]) - 3.20) < 0.001
    assert abs(float(snap["spread_pct"]) - 0.059) < 0.001


def test_upsert_option_quote_snapshot_updates_on_conflict(mem_db):
    """Two upserts for same contract produce two time-series rows; get_latest returns newest."""
    import agent_db, time as _time
    agent_db.upsert_option_quote_snapshot("ANET", 175.0, "2026-10-16", iv=0.48, bid=3.20, ask=3.40, spread_pct=0.059)
    _time.sleep(0.01)
    agent_db.upsert_option_quote_snapshot("ANET", 175.0, "2026-10-16", iv=0.32, bid=2.10, ask=2.30, spread_pct=0.095)
    snap = agent_db.get_latest_option_snapshot("ANET", 175.0, "2026-10-16")
    assert snap is not None
    # get_latest should return most recent (iv=0.32)
    assert abs(float(snap["iv"]) - 0.32) < 0.001


# ── 0088: earnings/event writer ───────────────────────────────────────────────

def test_upsert_event_calendar_creates_row(mem_db):
    """upsert_event_calendar stores an earnings event row."""
    import agent_db
    agent_db.upsert_event_calendar(
        ticker="ANET",
        event_type="EARNINGS",
        event_date="2026-10-28",
        confidence="provider_estimated",
        source="yfinance.calendar",
    )
    events = agent_db.get_events_for_ticker("ANET", event_type="EARNINGS")
    assert len(events) == 1
    assert events[0]["event_date"] == "2026-10-28"
    assert events[0]["confidence"] == "provider_estimated"


def test_upsert_event_calendar_deduplicates(mem_db):
    """Same (ticker, event_type, event_date) upserts, not duplicates."""
    import agent_db
    agent_db.upsert_event_calendar("ANET", "EARNINGS", "2026-10-28", confidence="estimated")
    agent_db.upsert_event_calendar("ANET", "EARNINGS", "2026-10-28", confidence="provider_estimated")
    events = agent_db.get_events_for_ticker("ANET", event_type="EARNINGS")
    assert len(events) == 1
    assert events[0]["confidence"] == "provider_estimated"


def test_upsert_earnings_date_creates_row(mem_db):
    """upsert_earnings_date stores an earnings_dates row."""
    import agent_db
    agent_db.upsert_earnings_date("ANET", "2026-10-28", confirmed_by="yfinance",
                                   confidence="provider_estimated", source="yfinance.calendar")
    row = agent_db.get_latest_earnings_date("ANET")
    assert row is not None
    assert row["event_date"] == "2026-10-28"
    assert row["confirmed_by"] == "yfinance"


# ── 0089: estimate history writer ────────────────────────────────────────────

def test_append_estimate_history_first_value_always_appended(mem_db):
    """First estimate value is always stored regardless of materiality."""
    import agent_db
    appended = agent_db.append_estimate_history("ANET", "+1y", "EPS", 8.50)
    assert appended is True
    rows = agent_db.get_estimate_history("ANET", "+1y", "EPS")
    assert len(rows) == 1
    assert abs(rows[0]["estimate_value"] - 8.50) < 0.001


def test_append_estimate_history_skips_small_change(mem_db):
    """Estimate change < 2% within 30 days is skipped."""
    import agent_db
    agent_db.append_estimate_history("ANET", "+1y", "EPS", 8.50)
    # 0.5% change — below materiality threshold
    appended = agent_db.append_estimate_history("ANET", "+1y", "EPS", 8.54)
    assert appended is False
    rows = agent_db.get_estimate_history("ANET", "+1y", "EPS")
    assert len(rows) == 1


def test_append_estimate_history_records_material_change(mem_db):
    """Estimate change ≥ 2% is always recorded regardless of time elapsed."""
    import agent_db
    agent_db.append_estimate_history("ANET", "+1y", "EPS", 8.50)
    # 5.9% change — above materiality threshold
    appended = agent_db.append_estimate_history("ANET", "+1y", "EPS", 9.00)
    assert appended is True
    rows = agent_db.get_estimate_history("ANET", "+1y", "EPS")
    assert len(rows) == 2
    assert abs(rows[0]["estimate_value"] - 9.00) < 0.001  # newest first
