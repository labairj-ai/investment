#!/usr/bin/env python3
"""Warren Buffett NYSE + NASDAQ screener — runs nightly, stores results in buffett.db."""

import json as _json
import math
import os
import random
import smtplib
import sqlite3
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DB_PATH     = PROJECT_DIR / "out" / "buffett.db"
LOCK_FILE   = PROJECT_DIR / "out" / "buffett_screener.lock"


def _safe_float(v, default=None):
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


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
            pe_ratio          REAL,
            p_fcf             REAL,
            ev_ebitda         REAL,
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
            pe_ratio          REAL,
            p_fcf             REAL,
            ev_ebitda         REAL,
            sector            TEXT,
            industry          TEXT,
            dividend_yield    REAL,
            market_cap        REAL,
            layer_rec         INTEGER,
            layer_reason      TEXT,
            scanned_at        TEXT
        );
        CREATE TABLE IF NOT EXISTS buffett_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS buffett_winner_history (
            ticker            TEXT,
            scan_date         TEXT,
            gross_margin      REAL,
            net_income_margin REAL,
            pe_ratio          REAL,
            p_fcf             REAL,
            ev_ebitda         REAL,
            PRIMARY KEY (ticker, scan_date)
        );
    """)
    # Migrate existing tables
    migrations = [
        ("buffett_cache",   "pe_ratio",       "REAL"),
        ("buffett_cache",   "p_fcf",           "REAL"),
        ("buffett_cache",   "ev_ebitda",       "REAL"),
        ("buffett_cache",   "sector",          "TEXT"),
        ("buffett_cache",   "industry",        "TEXT"),
        ("buffett_cache",   "dividend_yield",  "REAL"),
        ("buffett_cache",   "market_cap",      "REAL"),
        ("buffett_winners", "pe_ratio",        "REAL"),
        ("buffett_winners", "p_fcf",           "REAL"),
        ("buffett_winners", "ev_ebitda",       "REAL"),
        ("buffett_winners", "sector",          "TEXT"),
        ("buffett_winners", "industry",        "TEXT"),
        ("buffett_winners", "dividend_yield",   "REAL"),
        ("buffett_winners", "market_cap",       "REAL"),
        ("buffett_winners", "layer_rec",        "INTEGER"),
        ("buffett_winners", "layer_reason",     "TEXT"),
        ("buffett_winners", "value_trap_risk",  "TEXT"),
        ("buffett_winners", "value_trap_flags", "TEXT"),
        ("buffett_cache",   "value_trap_risk",  "TEXT"),
        ("buffett_cache",   "value_trap_flags", "TEXT"),
        ("buffett_winners", "exchange",         "TEXT"),
        ("buffett_cache",   "exchange",         "TEXT"),
        ("buffett_winners", "quality_score",    "INTEGER"),
        ("buffett_winners", "ai_analysis",      "TEXT"),
        ("buffett_winners", "ai_analysis_at",   "TEXT"),
        ("buffett_winners", "ai_layer_rank",    "INTEGER"),
        ("buffett_winners", "ai_layer_rank_at", "TEXT"),
        ("buffett_winners", "country",           "TEXT"),
        ("buffett_cache",   "country",           "TEXT"),
    ]
    for table, col, coltype in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()


def _fetch_tickers_from_url(url):
    import pandas as pd
    df = pd.read_json(url)
    clean = []
    for t in df["symbol"].tolist():
        if "^" in t or ("W" in t and len(t) > 5):
            continue
        t = t.replace(".", "-").replace("/", "-")
        clean.append(t)
    return clean


def get_clean_nyse_tickers():
    try:
        return list(set(_fetch_tickers_from_url(
            "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_full_tickers.json"
        )))
    except Exception:
        return ["BRK-B", "KO", "JNJ", "PG"]


def get_clean_nasdaq_tickers():
    try:
        return list(set(_fetch_tickers_from_url(
            "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_full_tickers.json"
        )))
    except Exception:
        return []


def get_all_tickers():
    """Return deduplicated NYSE + NASDAQ tickers."""
    nyse   = get_clean_nyse_tickers()
    nasdaq = get_clean_nasdaq_tickers()
    return list(set(nyse + nasdaq))


def get_financial_data(ticker):
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        info  = stock.info

        if info.get("quoteType") != "EQUITY":
            return None
        if (info.get("beta") or 0) < 0.1:
            return None

        fin = stock.financials
        bs  = stock.balance_sheet
        cf  = stock.cashflow

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

        rev        = get_val(fin, "Total Revenue")
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

        # Valuation and classification metrics
        pe_ratio      = _safe_float(info.get("trailingPE"))
        market_cap    = info.get("marketCap") or 0
        fcf           = info.get("freeCashflow") or 0
        p_fcf         = round(market_cap / fcf, 1) if fcf and fcf > 0 else None
        ev_ebitda     = _safe_float(info.get("enterpriseToEbitda"))
        sector        = info.get("sector") or ""
        industry      = info.get("industry") or ""
        dividend_yield = _safe_float(info.get("dividendYield"), 0) or 0
        country       = info.get("country") or None
        _exch_raw = info.get("exchange") or ""
        exchange = (
            "NYSE"   if _exch_raw in ("NYQ", "NYS", "NYB", "NYM") else
            "NASDAQ" if _exch_raw.startswith(("NMS", "NGM", "NCM", "NAS")) else
            _exch_raw or None
        )

        def margin(num, den):
            return round((num / den) * 100, 2) if den else 0.0

        equity_adj = equity + abs(treasury)
        trap_risk, trap_flags = _value_trap_risk(fin, cf, info)
        return {
            "ticker":             ticker,
            "company":            info.get("shortName", ticker),
            "price":              info.get("currentPrice", 0) or 0,
            "last_quarter_date":  last_q_date,
            "gross_margin":       margin(gross_profit, rev),
            "sga_margin":         margin(sga, gross_profit),
            "rd_margin":          margin(r_d, gross_profit),
            "depr_margin":        margin(depr, gross_profit),
            "interest_margin":    margin(interest, op_income),
            "net_income_margin":  margin(net_income, rev),
            "capex_margin":       margin(abs(capex), net_income),
            "cash_gt_debt":       "Yes" if cash > total_debt else "No",
            "adj_debt_equity":    round(total_liab / equity_adj, 2) if equity_adj else 0.0,
            "pe_ratio":           round(pe_ratio, 1) if pe_ratio is not None else None,
            "p_fcf":              p_fcf,
            "ev_ebitda":          round(ev_ebitda, 1) if ev_ebitda is not None else None,
            "sector":             sector,
            "industry":           industry,
            "dividend_yield":     round(dividend_yield, 4) if dividend_yield else None,
            "market_cap":         market_cap or None,
            "value_trap_risk":    trap_risk,
            "value_trap_flags":   _json.dumps(trap_flags),
            "exchange":           exchange,
            "country":            country,
        }
    except Exception:
        return None


def _passes_filters(r):
    def _g(key, default):
        v = r.get(key)
        return v if v is not None else default
    return (
        _g("gross_margin", 0)      >= 40
        and _g("sga_margin", 100)      <= 30
        and _g("net_income_margin", 0) >= 20
        and _g("interest_margin", 100) <= 15
        and _g("capex_margin", 100)    <= 50
        and r.get("cash_gt_debt")      == "Yes"
    )


def _value_trap_risk(fin, cf, info):
    """
    Detect value trap signals for a Buffett screener winner.
    A value trap is a company that LOOKS high-quality historically but whose
    underlying business is deteriorating — the screen caught a lagging picture.

    Returns (risk_level: str, flags: list[str])
      risk_level: 'low' | 'medium' | 'high'
      flags:      human-readable warning strings for the UI
    """
    flags = []

    def _gv(df, row, col=0):
        try:
            if row in df.index:
                v = float(df.loc[row].iloc[col])
                return None if (math.isnan(v) or math.isinf(v)) else v
        except Exception:
            pass
        return None

    # ── Multi-year revenue trend ──────────────────────────────────────────
    rev = [_gv(fin, "Total Revenue", i) for i in range(3)]
    if all(v and v > 0 for v in rev):
        if rev[0] < rev[1] and rev[1] < rev[2]:
            pct = (rev[0] / rev[2] - 1) * 100
            flags.append(f"Revenue declining 2 yrs in a row ({pct:+.1f}% over 2yr)")
        elif rev[0] is not None and rev[1] is not None and rev[0] < rev[1] * 0.93:
            pct = (rev[0] / rev[1] - 1) * 100
            flags.append(f"Revenue fell {pct:+.1f}% YoY")
    elif rev[0] and rev[1] and rev[0] < rev[1] * 0.93:
        pct = (rev[0] / rev[1] - 1) * 100
        flags.append(f"Revenue fell {pct:+.1f}% YoY")

    # ── Multi-year net income trend ───────────────────────────────────────
    ni = [_gv(fin, "Net Income", i) for i in range(3)]
    if all(v and v > 0 for v in ni):
        if ni[0] < ni[1] and ni[1] < ni[2]:
            pct = (ni[0] / ni[2] - 1) * 100
            flags.append(f"Net income declining 2 yrs in a row ({pct:+.1f}% over 2yr)")
        elif ni[0] is not None and ni[1] is not None and ni[0] < ni[1] * 0.80:
            pct = (ni[0] / ni[1] - 1) * 100
            flags.append(f"Net income dropped sharply YoY ({pct:+.1f}%)")
    elif ni[0] and ni[1] and ni[0] > 0 and ni[0] < ni[1] * 0.80:
        pct = (ni[0] / ni[1] - 1) * 100
        flags.append(f"Net income dropped sharply YoY ({pct:+.1f}%)")

    # ── Gross margin compression (moat erosion signal) ────────────────────
    gp  = [_gv(fin, "Gross Profit", i) for i in range(3)]
    r3  = [_gv(fin, "Total Revenue", i) for i in range(3)]
    gms = []
    for g, r in zip(gp, r3):
        if g and r and r > 0:
            gms.append(g / r)
        else:
            gms.append(None)
    if len(gms) >= 3 and all(v is not None for v in gms[:3]):
        if gms[0] < gms[1] and gms[1] < gms[2]:
            flags.append(
                f"Gross margin compressing 2 yrs in a row "
                f"({gms[2]*100:.1f}% → {gms[1]*100:.1f}% → {gms[0]*100:.1f}%)"
            )
    elif len(gms) >= 2 and gms[0] is not None and gms[1] is not None:
        if gms[0] < gms[1] - 0.05:
            flags.append(
                f"Gross margin dropped {(gms[1]-gms[0])*100:.1f}pp YoY "
                f"({gms[1]*100:.1f}% → {gms[0]*100:.1f}%)"
            )

    # ── FCF vs net income (earnings quality) ──────────────────────────────
    fcf    = _safe_float(info.get("freeCashflow"))
    ni_ttm = _safe_float(info.get("netIncomeToCommon"))
    if ni_ttm and ni_ttm > 0:
        if fcf is not None and fcf < 0:
            flags.append("Free cash flow is negative despite positive net income")
        elif fcf is not None and fcf < ni_ttm * 0.50:
            ratio = fcf / ni_ttm * 100
            flags.append(
                f"FCF is only {ratio:.0f}% of net income — reported earnings may be overstated"
            )

    # ── Operating cash flow vs net income (accruals) ──────────────────────
    ocf = _gv(cf, "Operating Cash Flow") or _gv(cf, "Cash From Operations")
    ni0 = ni[0] if ni[0] else (_gv(fin, "Net Income") or 0)
    if ni0 and ni0 > 0 and ocf is not None:
        if ocf < 0:
            flags.append(
                "Operating cash flow is negative — reported earnings not converting to cash"
            )
        elif ocf < ni0 * 0.55:
            flags.append(
                f"Operating CF ({ocf/1e6:.0f}M) is only {ocf/ni0*100:.0f}% of net income — accruals concern"
            )

    # ── Forward EPS vs trailing EPS (analyst expectations) ────────────────
    fwd_eps   = _safe_float(info.get("forwardEps"))
    trail_eps = _safe_float(info.get("trailingEps"))
    if fwd_eps is not None and trail_eps and trail_eps > 0:
        if fwd_eps < trail_eps * 0.82:
            decline = (fwd_eps / trail_eps - 1) * 100
            flags.append(
                f"Analysts forecast EPS {decline:+.1f}% below trailing — expected earnings decline"
            )

    # ── Score ──────────────────────────────────────────────────────────────
    # Flags are roughly ordered by severity; any 2+ = high risk
    if len(flags) == 0:
        return "low", []
    elif len(flags) == 1:
        return "medium", flags
    else:
        return "high", flags


def _assign_layer(r):
    """
    Map a Buffett screener winner to a Portfolio Architecture layer (1–5).
    Returns (layer_num: int, reason: str).

    Layer 1 – Structural Ballast:   mega-cap, ultra-stable, loss-absorbing
    Layer 2 – Cash-Flow Engines:    dividend payers, pricing power, pays to wait
    Layer 3 – Compounders:          quality long-duration businesses (default)
    Layer 4 – Convexity/Optionality:small-cap, high-growth, nonlinear upside
    Layer 5 – Shock Absorbers:      defense, energy, utilities, infrastructure monopolies
    """
    sector   = (r.get("sector")   or "").strip()
    industry = (r.get("industry") or "").strip().lower()
    div_yld  = r.get("dividend_yield") or 0
    mcap     = r.get("market_cap")  or 0
    pe       = r.get("pe_ratio")

    # ── Layer 5: Shock Absorbers / Regime Hedges ─────────────────────────────
    if sector == "Energy":
        return 5, "Energy sector — regime hedge"
    if sector == "Utilities":
        return 5, "Utility — infrastructure monopoly"
    if sector == "Basic Materials":
        return 5, "Materials/commodities — regime hedge"
    if any(kw in industry for kw in ["defense", "aerospace", "military", "weapon", "ammunition"]):
        return 5, "Defense/aerospace — regime hedge"
    if any(kw in industry for kw in ["railroad", "rail road", "pipeline", "oil & gas", "oil gas"]):
        return 5, "Infrastructure/energy — regime hedge"
    if any(kw in industry for kw in ["financial data", "financial exchanges", "credit service"]):
        return 5, "Financial data monopoly — regime hedge"

    # ── Layer 2: Cash-Flow Engines ────────────────────────────────────────────
    # dividend_yield is stored as percentage (e.g. 4.56 = 4.56%)
    if div_yld >= 3.0:
        return 2, f"Dividend yield {div_yld:.1f}% — cash-flow engine"
    if div_yld >= 1.5 and sector in ("Financial Services", "Real Estate", "Consumer Defensive"):
        return 2, f"Income-oriented {sector.lower()} — cash-flow engine"

    # ── Layer 4: Convexity / Optionality ─────────────────────────────────────
    if 0 < mcap < 3_000_000_000:
        return 4, f"Small-cap (${mcap/1e9:.1f}B) — convexity/optionality"
    if sector == "Technology" and pe and pe > 40:
        return 4, "High-growth tech — convexity"
    if sector == "Communication Services" and (not pe or pe > 40 or mcap < 10_000_000_000):
        return 4, "High-growth communications — convexity"
    if sector == "Healthcare" and mcap < 5_000_000_000:
        return 4, "Growth healthcare — convexity"

    # ── Layer 1: Structural Ballast ───────────────────────────────────────────
    if mcap > 300_000_000_000 and sector in ("Consumer Defensive", "Financial Services",
                                              "Industrials", "Technology"):
        return 1, f"Mega-cap {sector.lower()} ballast"

    # ── Layer 3: Compounders (default for quality businesses) ─────────────────
    return 3, "Quality compounder — long-duration growth"


def _score_winner(r) -> int:
    """Composite 0-100 quality + valuation score for ranking Buffett winners."""
    score = 0
    gm   = r.get("gross_margin") or 0
    nim  = r.get("net_income_margin") or 0
    pfcf = r.get("p_fcf")
    pe   = r.get("pe_ratio")
    ev   = r.get("ev_ebitda")
    trap = r.get("value_trap_risk") or "low"
    intr = r.get("interest_margin") or 0
    capx = r.get("capex_margin") or 0
    div  = r.get("dividend_yield") or 0

    # Gross margin (moat width)
    if   gm >= 65: score += 10
    elif gm >= 55: score += 8
    elif gm >= 45: score += 5
    else:          score += 3

    # Net income margin (earnings power)
    if   nim >= 35: score += 10
    elif nim >= 25: score += 8
    else:           score += 5  # always >=20 by screener rule

    # P/FCF attractiveness
    if   pfcf is None:   score += 3
    elif pfcf <= 15:     score += 10
    elif pfcf <= 25:     score += 7
    elif pfcf <= 35:     score += 4
    else:                score += 1

    # P/E reasonableness
    if   pe is None: score += 4
    elif pe <= 18:   score += 10
    elif pe <= 25:   score += 7
    elif pe <= 35:   score += 4
    else:            score += 1

    # EV/EBITDA
    if   ev is None: score += 3
    elif ev <= 12:   score += 8
    elif ev <= 18:   score += 5
    else:            score += 2

    # Value trap safety
    if   trap == "low":    score += 12
    elif trap == "medium": score += 6
    # high = 0

    # Interest margin (debt safety — always <=15 by screener)
    if   intr <= 5:  score += 10
    elif intr <= 10: score += 7
    else:            score += 4

    # CapEx efficiency (always <=50 by screener)
    if   capx <= 20: score += 10
    elif capx <= 35: score += 6
    else:            score += 3

    # Dividend bonus (dividend_yield stored as percentage, e.g. 4.56 = 4.56%)
    if   div >= 3.0: score += 5
    elif div >= 1.5: score += 3

    # Cash > debt always true (screener requirement)
    score += 5

    return min(score, 100)


def _send_new_winners_email(new_tickers: list[dict]) -> None:
    """Email a digest of newly qualifying Buffett winners."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")

    email_from = os.getenv("EMAIL_FROM")
    app_pw     = os.getenv("EMAIL_APP_PASSWORD")
    email_to   = os.getenv("EMAIL_TO")

    if not all([email_from, app_pw, email_to]):
        print("[Buffett] Email credentials missing — skipping new-winner notification.")
        return

    ticker_rows = "".join(f"""
        <tr>
          <td style="padding:8px 12px;font-weight:700;color:#1a2340;">{t['ticker']}</td>
          <td style="padding:8px 12px;color:#555;">{t.get('company','—')}</td>
          <td style="padding:8px 12px;">${t['price']:.2f}</td>
          <td style="padding:8px 12px;color:#27ae60;">{t.get('gross_margin',0):.1f}%</td>
          <td style="padding:8px 12px;">{t.get('net_income_margin',0):.1f}%</td>
          <td style="padding:8px 12px;">{t.get('pe_ratio') or '—'}</td>
          <td style="padding:8px 12px;">
            <a href="https://finance.yahoo.com/quote/{t['ticker']}" style="margin-right:6px;">YF</a>
            <a href="https://www.cnbc.com/quotes/{t['ticker'].replace('-','.')}">CNBC</a>
          </td>
        </tr>""" for t in new_tickers)

    count = len(new_tickers)
    html = f"""
    <html><body style="font-family:-apple-system,sans-serif;color:#2c3e50;max-width:640px;margin:0 auto;">
      <h2 style="color:#1a2340;">
        📈 {count} New Buffett Screener Winner{'s' if count != 1 else ''}
      </h2>
      <p style="color:#7f8c8d;font-size:13px;">
        The following ticker{'s' if count != 1 else ''} passed all 6 Buffett quality criteria
        for the first time in today's NYSE scan.
      </p>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#f4f6f9;">
            <th style="padding:8px 12px;text-align:left;color:#7f8c8d;">Ticker</th>
            <th style="padding:8px 12px;text-align:left;color:#7f8c8d;">Company</th>
            <th style="padding:8px 12px;text-align:left;color:#7f8c8d;">Price</th>
            <th style="padding:8px 12px;text-align:left;color:#27ae60;">Gross Margin</th>
            <th style="padding:8px 12px;text-align:left;color:#27ae60;">Net Income</th>
            <th style="padding:8px 12px;text-align:left;color:#7f8c8d;">P/E</th>
            <th style="padding:8px 12px;text-align:left;color:#7f8c8d;">Research</th>
          </tr>
        </thead>
        <tbody>{ticker_rows}</tbody>
      </table>
      <p style="font-size:11px;color:#aaa;margin-top:16px;">
        Criteria: Gross ≥40% · SG&amp;A ≤30% · Net Income ≥20% · Interest ≤15% · CapEx ≤50% · Cash&gt;Debt
      </p>
    </body></html>"""

    subject = f"📈 Buffett Screener: {count} new winner{'s' if count != 1 else ''} — {datetime.now().strftime('%b %d, %Y')}"

    msg = MIMEMultipart("alternative")
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_from, app_pw)
            smtp.send_message(msg)
        print(f"[Buffett] Emailed {count} new winner(s) to {email_to}.")
    except Exception as e:
        print(f"[Buffett] Email failed: {e}")


def _flush(conn, results, now_str, scanned_so_far, total_tickers, complete,
           ever_winners=None):
    """Commit cache, rewrite winners, update meta, email new tickers, record history."""
    # Commit any pending cache-hit UPDATEs from the main loop before anything
    # else runs — this ensures pe_ratio / p_fcf / ev_ebitda are persisted even
    # if an error occurs later in this function.
    conn.commit()
    winners = [r for r in results if _passes_filters(r)]

    # Only email on the final flush, and only for tickers that have NEVER
    # appeared in buffett_winner_history — so existing winners don't trigger
    # repeat notifications on every scan run.
    if complete and ever_winners is not None:
        new_winners = [w for w in winners if w["ticker"] not in ever_winners]
        if new_winners:
            _send_new_winners_email(new_winners)

    # Preserve AI analysis across scans (DELETE+INSERT would wipe it otherwise)
    saved_ai = {}
    try:
        for row in conn.execute(
            "SELECT ticker, ai_analysis, ai_analysis_at FROM buffett_winners "
            "WHERE ai_analysis IS NOT NULL"
        ):
            saved_ai[row[0]] = (row[1], row[2])
    except Exception:
        pass

    conn.execute("DELETE FROM buffett_winners")
    for w in winners:
        layer_rec, layer_reason = _assign_layer(w)
        quality_score = _score_winner(w)
        ai_analysis, ai_analysis_at = saved_ai.get(w["ticker"], (None, None))
        conn.execute("""
            INSERT OR REPLACE INTO buffett_winners
            (ticker, company, price, last_quarter_date,
             gross_margin, sga_margin, net_income_margin,
             interest_margin, capex_margin, cash_gt_debt,
             pe_ratio, p_fcf, ev_ebitda,
             sector, industry, dividend_yield, market_cap,
             layer_rec, layer_reason,
             value_trap_risk, value_trap_flags,
             exchange, quality_score, ai_analysis, ai_analysis_at,
             country, scanned_at)
            VALUES (:ticker, :company, :price, :last_quarter_date,
                    :gross_margin, :sga_margin, :net_income_margin,
                    :interest_margin, :capex_margin, :cash_gt_debt,
                    :pe_ratio, :p_fcf, :ev_ebitda,
                    :sector, :industry, :dividend_yield, :market_cap,
                    :layer_rec, :layer_reason,
                    :value_trap_risk, :value_trap_flags,
                    :exchange, :quality_score, :ai_analysis, :ai_analysis_at,
                    :country, :scanned_at)
        """, {**w, "scanned_at": w.get("scanned_at", now_str),
              "layer_rec": layer_rec, "layer_reason": layer_reason,
              "quality_score": quality_score,
              "ai_analysis": ai_analysis, "ai_analysis_at": ai_analysis_at})

    if complete:
        conn.execute(
            "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('last_scan', ?)",
            (now_str,)
        )
        # Write one history row per winner for this scan date
        scan_date = now_str[:10]
        for w in winners:
            conn.execute("""
                INSERT OR IGNORE INTO buffett_winner_history
                (ticker, scan_date, gross_margin, net_income_margin, pe_ratio, p_fcf, ev_ebitda)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (w["ticker"], scan_date,
                  w.get("gross_margin"), w.get("net_income_margin"),
                  w.get("pe_ratio"), w.get("p_fcf"), w.get("ev_ebitda")))

    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('tickers_scanned', ?)",
        (str(scanned_so_far),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('winners_found', ?)",
        (str(len(winners)),)
    )
    conn.commit()

    # Mirror winners into candidate_universe so the user can track/reject/watch them
    try:
        import agent_db as _adb
        for w in winners:
            _adb.upsert_candidate(
                ticker=w["ticker"],
                source="BUFFETT",
                buffett_score=_score_winner(w),
            )
    except Exception as _ce:
        print(f"[Buffett] candidate_universe upsert failed: {_ce}")


def _acquire_lock():
    """Return True if we got the lock, False if another instance is running."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"[Buffett] Already running (PID {pid}), exiting.")
            return False
        except (ProcessLookupError, ValueError):
            LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def run():
    import yfinance as yf

    if not _acquire_lock():
        return False

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    _init_db(conn)

    tickers = get_all_tickers()
    print(f"[Buffett] Scanning {len(tickers)} NYSE + NASDAQ tickers…")

    cache = {
        row["ticker"]: dict(row)
        for row in conn.execute("SELECT * FROM buffett_cache")
    }

    results = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Record scan start for ETA computation
    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('scan_started', ?)",
        (now_str,)
    )
    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('total_tickers', ?)",
        (str(len(tickers)),)
    )
    # Reset progress counter so the UI shows 0% immediately, not leftover from last run.
    conn.execute(
        "INSERT OR REPLACE INTO buffett_meta (key, value) VALUES ('tickers_scanned', '0')"
    )
    conn.commit()

    # Capture the full set of tickers ever seen as winners — used by _flush
    # to distinguish genuinely new discoveries from repeat qualifiers.
    # Read this ONCE before any flush can mutate buffett_winners.
    ever_winners = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT ticker FROM buffett_winner_history"
        )
    }

    for i, ticker in enumerate(tickers):
        should_fetch = True

        if ticker in cache:
            try:
                info       = yf.Ticker(ticker).info
                new_q_ts   = info.get("mostRecentQuarter", 0)
                new_q_date = (
                    datetime.fromtimestamp(new_q_ts).strftime("%Y-%m-%d")
                    if new_q_ts else None
                )
                cached_date = cache[ticker].get("last_quarter_date")
                if new_q_date and new_q_date == cached_date:
                    should_fetch = False
                    row = dict(cache[ticker])
                    # Valuation metrics move with price — always refresh them
                    # even on a cache hit so they're never stale/null.
                    pe_ratio   = _safe_float(info.get("trailingPE"))
                    market_cap = info.get("marketCap") or 0
                    fcf        = info.get("freeCashflow") or 0
                    p_fcf      = round(market_cap / fcf, 1) if fcf and fcf > 0 else None
                    ev_ebitda  = _safe_float(info.get("enterpriseToEbitda"))
                    row["pe_ratio"]       = round(pe_ratio, 1) if pe_ratio is not None else None
                    row["p_fcf"]          = p_fcf
                    row["ev_ebitda"]      = round(ev_ebitda, 1) if ev_ebitda is not None else None
                    row["price"]          = (info.get("currentPrice")
                                             or info.get("regularMarketPrice")
                                             or row.get("price"))
                    row["sector"]         = info.get("sector") or row.get("sector") or ""
                    row["industry"]       = info.get("industry") or row.get("industry") or ""
                    div = _safe_float(info.get("dividendYield"), 0) or 0
                    row["dividend_yield"] = round(div, 4) if div else row.get("dividend_yield")
                    row["market_cap"]     = info.get("marketCap") or row.get("market_cap")
                    row["country"]        = info.get("country") or row.get("country")
                    results.append(row)
                    # Keep cache current with today's valuation + classification
                    conn.execute(
                        "UPDATE buffett_cache SET pe_ratio=?, p_fcf=?, ev_ebitda=?, price=?,"
                        " sector=?, industry=?, dividend_yield=?, market_cap=?, country=?"
                        " WHERE ticker=?",
                        (row["pe_ratio"], row["p_fcf"], row["ev_ebitda"], row["price"],
                         row["sector"], row["industry"], row["dividend_yield"],
                         row["market_cap"], row["country"], ticker)
                    )
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
                     cash_gt_debt, adj_debt_equity,
                     pe_ratio, p_fcf, ev_ebitda,
                     sector, industry, dividend_yield, market_cap,
                     value_trap_risk, value_trap_flags, exchange, country, scanned_at)
                    VALUES (:ticker, :company, :price, :last_quarter_date,
                            :gross_margin, :sga_margin, :rd_margin, :depr_margin,
                            :interest_margin, :net_income_margin, :capex_margin,
                            :cash_gt_debt, :adj_debt_equity,
                            :pe_ratio, :p_fcf, :ev_ebitda,
                            :sector, :industry, :dividend_yield, :market_cap,
                            :value_trap_risk, :value_trap_flags, :exchange, :country, :scanned_at)
                """, data)
            time.sleep(random.uniform(0.5, 1.5))
        else:
            time.sleep(0.05)

        if i > 0 and i % 50 == 0:
            _flush(conn, results, now_str, i, len(tickers), complete=False,
                   ever_winners=ever_winners)
            print(f"[Buffett] {i}/{len(tickers)} processed…")

    _flush(conn, results, now_str, len(tickers), len(tickers), complete=True,
           ever_winners=ever_winners)
    conn.close()
    LOCK_FILE.unlink(missing_ok=True)

    winners_count = sum(1 for r in results if _passes_filters(r))
    print(f"[Buffett] Done. {winners_count} winners from {len(results)} scanned.")


if __name__ == "__main__":
    import sys
    _my_pid = str(os.getpid())
    try:
        completed = run()
    except Exception:
        # Only delete the lock if WE own it — a process that crashed because the
        # DB was locked by another scan must not evict that scan's lock entry.
        try:
            if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == _my_pid:
                LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if completed is False:
        sys.exit(1)
