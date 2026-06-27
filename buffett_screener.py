#!/usr/bin/env python3
"""Warren Buffett NYSE screener — runs nightly, stores results in buffett.db."""

import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "out" / "buffett.db"


def _init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS buffett_cache (
            ticker            TEXT PRIMARY KEY,
            company           TEXT,
            price             REAL,
            last_quarter_date TEXT,
            gross_margin      REAL,
            sga_margin        REAL,
            rd_margin         REAL,
            depr_margin       REAL,
            interest_margin   REAL,
            net_income_margin REAL,
            capex_margin      REAL,
            cash_gt_debt      TEXT,
            adj_debt_equity   REAL,
            scanned_at        TEXT
        );
        CREATE TABLE IF NOT EXISTS buffett_winners (
            ticker            TEXT PRIMARY KEY,
            company           TEXT,
            price             REAL,
            last_quarter_date TEXT,
            gross_margin      REAL,
            sga_margin        REAL,
            net_income_margin REAL,
            interest_margin   REAL,
            capex_margin      REAL,
            cash_gt_debt      TEXT,
            scanned_at        TEXT
        );
        CREATE TABLE IF NOT EXISTS buffett_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()


def get_clean_nyse_tickers():
    try:
        import pandas as pd
        url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_full_tickers.json"
        df = pd.read_json(url)
        clean = []
        for t in df["symbol"].tolist():
            if "^" in t or ("W" in t and len(t) > 5):
                continue
            t = t.replace(".", "-").replace("/", "-")
            clean.append(t)
        return list(set(clean))
    except Exception:
        return ["BRK-B", "KO", "JNJ", "PG"]


def get_financial_data(ticker):
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        info = stock.info

        if info.get("quoteType") != "EQUITY":
            return None
        if (info.get("beta") or 0) < 0.1:
            return None

        fin = stock.financials
        bs = stock.balance_sheet
        cf = stock.cashflow

        if fin.empty or bs.empty:
            return None

        last_q_ts = info.get("mostRecentQuarter", 0)
        last_q_date = (
            datetime.fromtimestamp(last_q_ts).strftime("%Y-%m-%d")
            if last_q_ts else None
        )

        def get_val(df, row_name, year_index=0):
            try:
                if row_name in df.index:
                    return float(df.loc[row_name].iloc[year_index])
                return 0.0
            except Exception:
                return 0.0

        rev = get_val(fin, "Total Revenue")
        if rev == 0:
            return None

        gross_profit = get_val(fin, "Gross Profit")
        sga          = get_val(fin, "Selling General Administrative")
        r_d          = get_val(fin, "Research Development")
        depr         = get_val(cf, "Depreciation And Amortization") or get_val(cf, "Depreciation")
        interest     = get_val(fin, "Interest Expense")
        op_income    = get_val(fin, "Operating Income")
        net_income   = get_val(fin, "Net Income")
        capex        = get_val(cf, "Capital Expenditure")
        cash         = get_val(bs, "Cash And Cash Equivalents")
        total_debt   = get_val(bs, "Total Debt")
        total_liab   = get_val(bs, "Total Liabilities Net Minority Interest")
        equity       = get_val(bs, "Stockholders Equity")
        treasury     = get_val(bs, "Treasury Stock")

        def margin(num, den):
            return round((num / den) * 100, 2) if den else 0.0

        equity_adj = equity + abs(treasury)
        return {
            "ticker":            ticker,
            "company":           info.get("shortName", ticker),
            "price":             info.get("currentPrice", 0) or 0,
            "last_quarter_date": last_q_date,
            "gross_margin":      margin(gross_profit, rev),
            "sga_margin":        margin(sga, gross_profit),
            "rd_margin":         margin(r_d, gross_profit),
            "depr_margin":       margin(depr, gross_profit),
            "interest_margin":   margin(interest, op_income),
            "net_income_margin": margin(net_income, rev),
            "capex_margin":      margin(abs(capex), net_income),
            "cash_gt_debt":      "Yes" if cash > total_debt else "No",
            "adj_debt_equity":   round(total_liab / equity_adj, 2) if equity_adj else 0.0,
        }
    except Exception:
        return None


def _passes_filters(r):
    return (
        r.get("gross_margin", 0)      >= 40
        and r.get("sga_margin", 100)      <= 30
        and r.get("net_income_margin", 0) >= 20
        and r.get("interest_margin", 100) <= 15
        and r.get("capex_margin", 100)    <= 50
        and r.get("cash_gt_debt")         == "Yes"
    )


LOCK_FILE = PROJECT_DIR / "out" / "buffett_screener.lock"


def _acquire_lock():
    """Return True if we got the lock, False if another instance is running."""
    import os
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)  # signal 0 = just check if process exists
            print(f"[Buffett] Already running (PID {pid}), exiting.")
            return False
        except (ProcessLookupError, ValueError):
            LOCK_FILE.unlink(missing_ok=True)  # stale lock
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def run():
    import os
    import yfinance as yf

    if not _acquire_lock():
        return

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    _init_db(conn)

    tickers = get_clean_nyse_tickers()
    print(f"[Buffett] Scanning {len(tickers)} NYSE tickers…")

    cache = {
        row["ticker"]: dict(row)
        for row in conn.execute("SELECT * FROM buffett_cache")
    }

    results = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i, ticker in enumerate(tickers):
        should_fetch = True

        if ticker in cache:
            try:
                fast_info = yf.Ticker(ticker).info
                new_q_ts = fast_info.get("mostRecentQuarter", 0)
                new_q_date = (
                    datetime.fromtimestamp(new_q_ts).strftime("%Y-%m-%d")
                    if new_q_ts else None
                )
                cached_date = cache[ticker].get("last_quarter_date")
                if new_q_date and new_q_date == cached_date:
                    should_fetch = False
                    results.append(dict(cache[ticker]))
            except Exception:
                pass

        if should_fetch:
            data = get_financial_data(ticker)
            if data:
                data["scanned_at"] = now_str
                results.append(data)
                conn.execute("""
                    INSERT OR REPLACE INTO buffett_cache
                    (ticker, company, price, last_quarter_date,
                     gross_margin, sga_margin, rd_margin, depr_margin,
                     interest_margin, net_income_margin, capex_margin,
                     cash_gt_debt, adj_debt_equity, scanned_at)
                    VALUES (:ticker, :company, :price, :last_quarter_date,
                            :gross_margin, :sga_margin, :rd_margin, :depr_margin,
                            :interest_margin, :net_income_margin, :capex_margin,
                            :cash_gt_debt, :adj_debt_equity, :scanned_at)
                """, data)
            time.sleep(random.uniform(0.5, 1.5))
        else:
            time.sleep(0.05)

        if i > 0 and i % 100 == 0:
            conn.commit()
            print(f"[Buffett] {i}/{len(tickers)} processed…")

    conn.commit()

    winners = [r for r in results if _passes_filters(r)]

    conn.execute("DELETE FROM buffett_winners")
    for w in winners:
        conn.execute("""
            INSERT OR REPLACE INTO buffett_winners
            (ticker, company, price, last_quarter_date,
             gross_margin, sga_margin, net_income_margin,
             interest_margin, capex_margin, cash_gt_debt, scanned_at)
            VALUES (:ticker, :company, :price, :last_quarter_date,
                    :gross_margin, :sga_margin, :net_income_margin,
                    :interest_margin, :capex_margin, :cash_gt_debt, :scanned_at)
        """, {**w, "scanned_at": w.get("scanned_at", now_str)})

    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('last_scan', ?)",
        (now_str,)
    )
    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('tickers_scanned', ?)",
        (str(len(tickers)),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('winners_found', ?)",
        (str(len(winners)),)
    )
    conn.commit()
    conn.close()
    LOCK_FILE.unlink(missing_ok=True)

    print(f"[Buffett] Done. {len(winners)} winners from {len(results)} scanned.")


if __name__ == "__main__":
    try:
        run()
    finally:
        LOCK_FILE.unlink(missing_ok=True)
