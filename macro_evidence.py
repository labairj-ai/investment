"""Point-in-time adapter from ingested financial statements to scorer evidence."""
import math
import sqlite3
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "v3"
MAX_PERIOD_AGE_DAYS = {"Q": 185, "A": 550}
ET = ZoneInfo("America/New_York")


def _timestamp(value):
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=ET)).timestamp()
    except (ValueError, TypeError):
        return None


def financial_evidence(ticker, conn, at=None):
    """Use one statement row, never mix annual/quarterly values or currencies.

    Ingestion stores reporting-currency units, not millions. Currency is not
    recorded in the legacy schema, so the prompt must not label these as USD.
    fetched_at is the conservative availability boundary (not period_end).
    """
    at = time.time() if at is None else at
    today = datetime.fromtimestamp(at, ET).date()
    evidence = {"evidence_schema_version": SCHEMA_VERSION,
                "financial_provenance": {"state": "missing", "source": "company_financials",
                                         "units": "millions of reporting currency; margin in percent",
                                         "currency": "unspecified"}}
    if conn is None:
        return evidence
    try:
        meta = conn.execute("SELECT sector,fetched_at FROM ticker_metadata WHERE ticker=?", (ticker,)).fetchone()
        if meta and _timestamp(meta[1]) is not None and 0 <= at - _timestamp(meta[1]) <= 185 * 86400:
            evidence["sector"] = meta[0]
            evidence["sector_provenance"] = {"source": "ticker_metadata", "available_at": _timestamp(meta[1])}
    except sqlite3.Error:
        pass
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(company_financials)")}
        required = {"period_end", "period_type", "fetched_at", "total_debt", "cash", "gross_profit", "revenue"}
        if not required <= cols:
            return evidence
        rows = conn.execute("SELECT period_end,period_type,fetched_at,total_debt,cash,gross_profit,revenue "
                            "FROM company_financials WHERE ticker=? ORDER BY period_end DESC, "
                            "CASE period_type WHEN 'Q' THEN 0 ELSE 1 END", (ticker,)).fetchall()
        selected = None
        for row in rows:
            available = _timestamp(row[2])
            try:
                age = (today - date.fromisoformat(row[0])).days
            except (TypeError, ValueError):
                continue
            if available is not None and available <= at and row[1] in MAX_PERIOD_AGE_DAYS and age >= 0:
                if age > MAX_PERIOD_AGE_DAYS[row[1]]:
                    evidence["financial_provenance"]["state"] = "stale"
                    continue
                selected = row
                break
        if selected is None:
            return evidence
        period, kind, fetched, debt, cash, profit, revenue = selected
        finite = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        provenance = evidence["financial_provenance"]
        provenance.update(state="available", period_end=period, period_type=kind,
                          available_at=_timestamp(fetched), derivations={})
        if finite(debt) and finite(cash):
            evidence["net_debt"] = (debt - cash) / 1_000_000
            provenance["derivations"]["net_debt"] = {"total_debt": debt, "cash": cash, "formula": "(total_debt-cash)/1e6"}
        if finite(profit) and finite(revenue) and revenue > 0:
            evidence["gross_margin_pct"] = 100 * profit / revenue
            provenance["derivations"]["gross_margin_pct"] = {"gross_profit": profit, "revenue": revenue, "formula": "100*gross_profit/revenue"}
        return evidence
    except sqlite3.Error:
        evidence["financial_provenance"]["state"] = "schema_unavailable"
        return evidence
