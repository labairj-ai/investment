import sqlite3
from datetime import datetime, timezone

import pytest
from macro_evidence import financial_evidence


@pytest.fixture
def statements():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE company_financials(ticker,period_end,period_type,fetched_at,total_debt,cash,gross_profit,revenue)")
    c.execute("CREATE TABLE ticker_metadata(ticker,sector,fetched_at)")
    yield c
    c.close()


NOW = datetime(2026, 9, 21, tzinfo=timezone.utc).timestamp()


def put(c, period="2026-06-30", kind="Q", fetched="2026-08-01", debt=2000000, cash=3000000, profit=4000000, revenue=10000000):
    c.execute("INSERT INTO company_financials VALUES (?,?,?,?,?,?,?,?)", ("XOM", period, kind, fetched, debt, cash, profit, revenue))


def test_actual_columns_produce_unit_correct_prompt(statements):
    import portfolio_ai as pai
    put(statements)
    evidence = financial_evidence("XOM", statements, NOW)
    assert evidence["net_debt"] == -1
    assert evidence["gross_margin_pct"] == 40
    # The scorer calls the same adapter and retains the existing thresholds.
    ev = pai._fetch_company_evidence("XOM", statements)
    assert ev["evidence_quality_rate"] == "partial"
    assert ev["evidence_quality_inflation"] == "full"
    assert ev["evidence_quality_dollar"] == "none"
    prompt = pai._build_macro_score_request("XOM", ev, {})
    assert "gross_margin=40.0%" in prompt
    assert "net_debt=-1.000M reporting-currency" in prompt


def test_latest_period_not_latest_insert_and_no_future(statements):
    put(statements)
    put(statements, period="2025-12-31", kind="A", debt=9000000)
    put(statements, period="2026-09-30", fetched="2026-10-01", debt=8000000)
    assert financial_evidence("XOM", statements, NOW)["net_debt"] == -1


@pytest.mark.parametrize("kwargs", [{"revenue": 0}, {"revenue": None}, {"profit": None}, {"revenue": float("inf")}])
def test_margin_missing_or_invalid_fails_closed(statements, kwargs):
    put(statements, **kwargs)
    assert "gross_margin_pct" not in financial_evidence("XOM", statements, NOW)


def test_missing_stale_and_future_availability(statements):
    assert "net_debt" not in financial_evidence("XOM", statements, NOW)
    put(statements, fetched="2026-10-01")
    assert "net_debt" not in financial_evidence("XOM", statements, NOW)
    put(statements, period="2024-12-31", kind="A")
    assert financial_evidence("XOM", statements, NOW)["financial_provenance"]["state"] == "stale"


def test_zero_debt_preserved_and_no_cross_period_mix(statements):
    put(statements, debt=0, cash=0)
    assert financial_evidence("XOM", statements, NOW)["net_debt"] == 0
    put(statements, period="2026-07-31", debt=None)
    assert "net_debt" not in financial_evidence("XOM", statements, NOW)
