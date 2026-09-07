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
