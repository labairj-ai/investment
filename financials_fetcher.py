#!/usr/bin/env python3
"""
Fetch 5 years of quarterly + annual financial statements and forward estimates
for each stock holding (ETFs/funds skipped). Stores in investment.db.
Cache TTL: 7 days.
"""
import json
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH     = PROJECT_DIR / "out" / "investment.db"
CACHE_TTL   = 7 * 86400  # 7 days

_FUND_TICKERS = {
    "VTSAX", "VFIAX", "VVIAX", "VTMGX", "FSPTX", "SLYV", "SCHD",
    "IGV", "GLD", "TLT", "BTC", "BTC-USD", "VBTLX", "VWELX",
}
_FUND_KEYWORDS = {
    "etf", "fund", "index", "trust", "vanguard", "ishares", "schwab",
    "fidelity", "spdr", "invesco", "wisdomtree", "dimensional", "pimco",
    "blackrock", "proshares", "direxion", "grayscale",
}


def _init_tables():
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS company_financials (
        ticker           TEXT,
        period_type      TEXT,
        period_end       TEXT,
        revenue          REAL,
        gross_profit     REAL,
        operating_income REAL,
        net_income       REAL,
        eps_diluted      REAL,
        free_cash_flow   REAL,
        total_debt       REAL,
        cash             REAL,
        total_equity     REAL,
        fetched_at       TEXT,
        PRIMARY KEY (ticker, period_type, period_end)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS company_estimates (
        ticker          TEXT PRIMARY KEY,
        next_q_eps_est  REAL,
        next_q_rev_est  REAL,
        curr_yr_eps_est REAL,
        next_yr_eps_est REAL,
        price_target    REAL,
        recommendation  TEXT,
        fetched_at      TEXT
    )""")
    conn.commit()
    conn.close()


def _is_fund(ticker, company_names=None):
    if ticker in _FUND_TICKERS:
        return True
    name = ((company_names or {}).get(ticker) or "").lower()
    return any(kw in name for kw in _FUND_KEYWORDS)


def _safe(val):
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _df_get(df, col, *keys):
    for k in keys:
        try:
            if k in df.index:
                v = _safe(df.loc[k, col])
                if v is not None:
                    return v
        except Exception:
            pass
    return None


def _fetch_one(ticker):
    """Return (quarterly_rows, annual_rows, estimates_dict) for one ticker."""
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")

    tk = yf.Ticker(ticker)
    q_rows, a_rows, estimates = [], [], {}

    # ── Quarterly ──────────────────────────────────────────────────────────────
    try:
        qf  = tk.quarterly_financials
        qbs = tk.quarterly_balance_sheet
        qcf = tk.quarterly_cashflow

        for col in list(qf.columns)[:20]:
            period_end = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
            rev = _df_get(qf,  col, "Total Revenue", "Revenue")
            gp  = _df_get(qf,  col, "Gross Profit")
            oi  = _df_get(qf,  col, "Operating Income", "EBIT")
            ni  = _df_get(qf,  col, "Net Income")
            eps = _df_get(qf,  col, "Diluted EPS", "Basic EPS")
            dbt = _df_get(qbs, col, "Total Debt", "Long Term Debt")
            csh = _df_get(qbs, col, "Cash And Cash Equivalents",
                          "Cash Cash Equivalents And Short Term Investments", "Cash")
            eq  = _df_get(qbs, col, "Stockholders Equity",
                          "Total Stockholders Equity", "Common Stock Equity")
            ocf = _df_get(qcf, col, "Operating Cash Flow",
                          "Cash Flow From Continuing Operating Activities")
            cpx = _df_get(qcf, col, "Capital Expenditure", "Capital Expenditures")
            fcf = (ocf + cpx) if (ocf is not None and cpx is not None) else None

            q_rows.append(dict(period_end=period_end, revenue=rev, gross_profit=gp,
                               operating_income=oi, net_income=ni, eps_diluted=eps,
                               free_cash_flow=fcf, total_debt=dbt, cash=csh,
                               total_equity=eq))
    except Exception as e:
        print(f"[financials] {ticker} quarterly: {e}")

    # ── Annual ─────────────────────────────────────────────────────────────────
    try:
        af  = tk.financials
        abs_ = tk.balance_sheet
        acf = tk.cashflow

        for col in list(af.columns)[:5]:
            period_end = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
            rev = _df_get(af,   col, "Total Revenue", "Revenue")
            gp  = _df_get(af,   col, "Gross Profit")
            oi  = _df_get(af,   col, "Operating Income", "EBIT")
            ni  = _df_get(af,   col, "Net Income")
            eps = _df_get(af,   col, "Diluted EPS", "Basic EPS")
            dbt = _df_get(abs_, col, "Total Debt", "Long Term Debt")
            csh = _df_get(abs_, col, "Cash And Cash Equivalents",
                          "Cash Cash Equivalents And Short Term Investments", "Cash")
            eq  = _df_get(abs_, col, "Stockholders Equity",
                          "Total Stockholders Equity", "Common Stock Equity")
            ocf = _df_get(acf,  col, "Operating Cash Flow",
                          "Cash Flow From Continuing Operating Activities")
            cpx = _df_get(acf,  col, "Capital Expenditure", "Capital Expenditures")
            fcf = (ocf + cpx) if (ocf is not None and cpx is not None) else None

            a_rows.append(dict(period_end=period_end, revenue=rev, gross_profit=gp,
                               operating_income=oi, net_income=ni, eps_diluted=eps,
                               free_cash_flow=fcf, total_debt=dbt, cash=csh,
                               total_equity=eq))
    except Exception as e:
        print(f"[financials] {ticker} annual: {e}")

    # ── Forward estimates ──────────────────────────────────────────────────────
    try:
        info = tk.info or {}
        estimates["price_target"]   = _safe(info.get("targetMeanPrice"))
        estimates["recommendation"] = info.get("recommendationKey", "")

        ee = tk.earnings_estimate
        if ee is not None and not ee.empty:
            for label, key in (("+1q", "next_q_eps_est"), ("0y", "curr_yr_eps_est"),
                               ("+1y", "next_yr_eps_est")):
                if label in ee.index:
                    estimates[key] = _safe(ee.loc[label, "avg"])

        re = tk.revenue_estimate
        if re is not None and not re.empty and "+1q" in re.index:
            estimates["next_q_rev_est"] = _safe(re.loc["+1q", "avg"])
    except Exception as e:
        print(f"[financials] {ticker} estimates: {e}")

    return q_rows, a_rows, estimates


def fetch_all(tickers, company_names=None, force=False):
    """Fetch and store financials for all stock tickers. Skips funds."""
    _init_tables()
    company_names = company_names or {}
    stock_tickers = [t for t in tickers if not _is_fund(t, company_names)]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cutoff  = time.time() - CACHE_TTL

    conn = sqlite3.connect(str(DB_PATH), timeout=30)

    for ticker in stock_tickers:
        if not force:
            row = conn.execute(
                "SELECT fetched_at FROM company_estimates WHERE ticker=?", (ticker,)
            ).fetchone()
            if row and row[0]:
                try:
                    ts = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").timestamp()
                    if ts > cutoff:
                        print(f"[financials] {ticker} — fresh, skipping")
                        continue
                except Exception:
                    pass

        print(f"[financials] Fetching {ticker}…")
        try:
            q_rows, a_rows, estimates = _fetch_one(ticker)

            for r in q_rows:
                conn.execute("""INSERT OR REPLACE INTO company_financials
                    (ticker,period_type,period_end,revenue,gross_profit,operating_income,
                     net_income,eps_diluted,free_cash_flow,total_debt,cash,total_equity,fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ticker, "Q", r["period_end"], r["revenue"], r["gross_profit"],
                     r["operating_income"], r["net_income"], r["eps_diluted"],
                     r["free_cash_flow"], r["total_debt"], r["cash"], r["total_equity"], now_str))

            for r in a_rows:
                conn.execute("""INSERT OR REPLACE INTO company_financials
                    (ticker,period_type,period_end,revenue,gross_profit,operating_income,
                     net_income,eps_diluted,free_cash_flow,total_debt,cash,total_equity,fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ticker, "A", r["period_end"], r["revenue"], r["gross_profit"],
                     r["operating_income"], r["net_income"], r["eps_diluted"],
                     r["free_cash_flow"], r["total_debt"], r["cash"], r["total_equity"], now_str))

            conn.execute("""INSERT OR REPLACE INTO company_estimates
                (ticker,next_q_eps_est,next_q_rev_est,curr_yr_eps_est,next_yr_eps_est,
                 price_target,recommendation,fetched_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (ticker,
                 estimates.get("next_q_eps_est"), estimates.get("next_q_rev_est"),
                 estimates.get("curr_yr_eps_est"), estimates.get("next_yr_eps_est"),
                 estimates.get("price_target"), estimates.get("recommendation", ""),
                 now_str))

            conn.commit()
        except Exception as e:
            print(f"[financials] {ticker} FAILED: {e}")

        time.sleep(0.6)

    conn.close()
    print("[financials] Done.")


# ── Formatted summary for AI prompts ─────────────────────────────────────────

def get_financial_summary(ticker):
    """
    Return compact multi-line financial summary for injection into AI prompts.
    Returns empty string if no data or ticker is a fund.
    """
    if _is_fund(ticker) or not DB_PATH.exists():
        return ""

    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row

    a_rows = conn.execute("""SELECT * FROM company_financials
        WHERE ticker=? AND period_type='A'
        ORDER BY period_end DESC LIMIT 5""", (ticker,)).fetchall()

    q_rows = conn.execute("""SELECT * FROM company_financials
        WHERE ticker=? AND period_type='Q'
        ORDER BY period_end DESC LIMIT 8""", (ticker,)).fetchall()

    est = conn.execute(
        "SELECT * FROM company_estimates WHERE ticker=?", (ticker,)).fetchone()

    conn.close()

    if not a_rows and not q_rows:
        return ""

    def fm(v):
        if v is None:
            return "N/A"
        av = abs(v)
        sign = "-" if v < 0 else ""
        if av >= 1e9:
            return f"{sign}${av/1e9:.1f}B"
        if av >= 1e6:
            return f"{sign}${av/1e6:.0f}M"
        return f"{sign}${av:.0f}"

    def pct(a, b):
        if a is None or b is None or b == 0:
            return "—"
        return f"{a/b*100:.1f}%"

    lines = [f"── {ticker} FINANCIALS ──"]

    if a_rows:
        lines.append("Annual (oldest→newest):")
        for r in reversed(list(a_rows)):
            yr  = r["period_end"][:4]
            gm  = pct(r["gross_profit"], r["revenue"])
            om  = pct(r["operating_income"], r["revenue"])
            lines.append(
                f"  {yr}: rev {fm(r['revenue'])} | gross {gm} | op {om} | "
                f"net {fm(r['net_income'])} | FCF {fm(r['free_cash_flow'])} | "
                f"debt {fm(r['total_debt'])} | cash {fm(r['cash'])}"
            )

    if q_rows:
        lines.append("Recent quarters (newest first):")
        for r in q_rows[:6]:
            q   = r["period_end"][:7]
            eps = f"${r['eps_diluted']:.2f}" if r["eps_diluted"] is not None else "—"
            lines.append(
                f"  {q}: rev {fm(r['revenue'])} | net {fm(r['net_income'])} | "
                f"EPS {eps} | FCF {fm(r['free_cash_flow'])}"
            )

    if est:
        parts = []
        if est["curr_yr_eps_est"] is not None:
            parts.append(f"curr-yr EPS est ${est['curr_yr_eps_est']:.2f}")
        if est["next_yr_eps_est"] is not None:
            parts.append(f"next-yr EPS est ${est['next_yr_eps_est']:.2f}")
        if est["price_target"] is not None:
            parts.append(f"price target ${est['price_target']:.2f}")
        if est["recommendation"]:
            parts.append(f"rec: {est['recommendation'].upper()}")
        if parts:
            lines.append("Estimates: " + " | ".join(parts))

    return "\n".join(lines)


if __name__ == "__main__":
    import csv, sys
    holdings_path = PROJECT_DIR / "holdings.csv"
    tickers = []
    with open(holdings_path, newline="") as f:
        for row in csv.DictReader(f):
            t = row.get("Stock", "").strip().upper()
            if t:
                tickers.append(t)
    tickers = list(dict.fromkeys(tickers))
    force = "--force" in sys.argv
    fetch_all(tickers, force=force)
