"""Test: compute_valuation_metrics works on a fresh in-memory DB (0124 test 5).

Catches schema omissions where financials_fetcher.compute_valuation_metrics inserts
a column that doesn't exist in the CREATE TABLE — e.g. the earlier shares_period_end
regression where the column was in the INSERT but not in the CREATE TABLE statement.
"""
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_compute_valuation_metrics_on_fresh_db(mem_db):
    """compute_valuation_metrics succeeds on a freshly migrated DB with no prior rows."""
    import agent_db
    import financials_fetcher

    # Open connection to the temp DB (already migrated by mem_db fixture)
    conn = sqlite3.connect(str(mem_db), timeout=10)
    conn.row_factory = sqlite3.Row

    # company_financials is created by financials_fetcher._init_tables(), not agent_db.migrate()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_financials (
            ticker              TEXT,
            period_type         TEXT,
            period_end          TEXT,
            revenue             REAL,
            gross_profit        REAL,
            operating_income    REAL,
            net_income          REAL,
            eps_diluted         REAL,
            free_cash_flow      REAL,
            total_debt          REAL,
            cash                REAL,
            total_equity        REAL,
            shares_outstanding  REAL,
            shares_period_end   REAL,
            fetched_at          TEXT,
            PRIMARY KEY (ticker, period_type, period_end)
        )
    """)
    conn.commit()

    # Seed 4 quarterly rows — minimum for TTM computation
    periods = [
        ("2025-03-31", 1.0e9),
        ("2025-06-30", 1.1e9),
        ("2025-09-30", 1.2e9),
        ("2025-12-31", 1.3e9),
    ]
    for period_end, rev in periods:
        conn.execute(
            """INSERT OR REPLACE INTO company_financials
               (ticker, period_type, period_end, revenue, gross_profit, operating_income,
                net_income, eps_diluted, free_cash_flow, total_debt, cash, total_equity,
                shares_outstanding, shares_period_end, fetched_at)
               VALUES ('AAPL', 'Q', ?, ?, ?, ?, ?, 1.5, ?, 50e9, 30e9, 60e9, 15e9, 15e9, '2026-01-01')""",
            (period_end, rev, rev * 0.4, rev * 0.25, rev * 0.20, rev * 0.15),
        )
    conn.commit()

    # Mock yfinance to return price data covering all quarters
    import pandas as pd
    mock_hist = pd.DataFrame(
        {"Close": [150.0, 155.0, 160.0, 165.0]},
        index=pd.to_datetime(["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]),
    )
    mock_hist.index.name = "Date"

    mock_ticker_obj = MagicMock()
    mock_ticker_obj.history.return_value = mock_hist

    from unittest.mock import patch
    with patch("yfinance.Ticker", return_value=mock_ticker_obj):
        result = financials_fetcher.compute_valuation_metrics("AAPL", conn=conn)

    conn.close()

    # TTM needs 4 quarters; with exactly 4 quarterly rows, we get exactly 1 TTM period
    assert result > 0, (
        f"Expected >0 upserted valuation rows, got {result}. "
        "This may indicate a schema mismatch between financials_fetcher and company_financials."
    )

    # Verify rows written to historical_valuation_metrics
    conn2 = agent_db._connect()
    rows = conn2.execute(
        "SELECT * FROM historical_valuation_metrics WHERE ticker='AAPL'"
    ).fetchall()
    conn2.close()

    assert len(rows) > 0, "historical_valuation_metrics should have at least one row"
    row = dict(rows[0])

    # All ratio columns must be present (schema integrity check)
    for col in ("pe", "ps", "ev_fcf", "p_fcf", "ev_revenue", "ev_ebit_proxy"):
        assert col in row, f"Expected column '{col}' in historical_valuation_metrics"

    # At least one ratio should be non-null (we have revenue, so ps should work)
    assert row.get("ps") is not None, "ps ratio should be computable from seeded revenue data"
