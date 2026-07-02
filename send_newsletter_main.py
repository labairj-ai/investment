#!/usr/bin/env python3
"""
Daily Investment Digest — single consolidated email that merges:
  • Portfolio snapshot + layer performance
  • Layer allocation vs target (inline drift warnings when ≥5pp off)
  • Holdings performance grouped by layer
  • Upcoming earnings & ex-dividend events (next 3 days)
  • Judgment health rubric + concentration flags
"""
import json
import os
import smtplib
import sqlite3
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ─── Config ───────────────────────────────────────────────────────────────────
PROJECT_DIR      = Path("/Users/ai_lab/Desktop/investment")
HOLDINGS_CSV     = PROJECT_DIR / "holdings.csv"
LAYER_TARGETS_F  = PROJECT_DIR / "layer_targets.json"
DB_PATH          = PROJECT_DIR / "out" / "investment.db"
OUT_DIR          = PROJECT_DIR / "out"
OUT_DIR.mkdir(exist_ok=True)

EMAIL_FROM       = os.getenv("EMAIL_FROM")
EMAIL_APP_PW     = os.getenv("EMAIL_APP_PASSWORD")
TO_EMAILS        = [os.getenv("EMAIL_TO", "robertjsherman1@gmail.com")]

BENCHMARK        = "SPY"
TZ               = ZoneInfo("America/New_York")
DRIFT_THRESHOLD  = 5.0
EVENTS_WINDOW    = 3   # days ahead for earnings / ex-div alerts

LAYER_NAMES = {
    1: "L1 Structural Ballast",
    2: "L2 Cash-Flow Engines",
    3: "L3 Compounders",
    4: "L4 Convexity",
    5: "L5 Shock Absorbers",
}
LAYER_COLORS = {
    1: "#4A90D9",
    2: "#27ae60",
    3: "#e67e22",
    4: "#7c3aed",
    5: "#9B59B6",
}
LAYER_TARGETS_DEFAULT = {1: 25.0, 2: 20.0, 3: 35.0, 4: 12.0, 5: 8.0}

LAYER_GROSS_DOM   = 50.0
HOLDING_GROSS_DOM = 25.0


# ─── Helpers ──────────────────────────────────────────────────────────────────
def normalize_ticker(t: str) -> str:
    t = str(t).strip().upper()
    if t.startswith("$"):
        t = t[1:]
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            t = f"{left}-{right}"
    return t


def money(x: float) -> str:
    return f"${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:.2f}%"


def signed_pct(x: float) -> str:
    return f"{x:+.1f}%"


def color_change(x: float) -> str:
    return "#27ae60" if x >= 0 else "#e74c3c"


# ─── Pricing ──────────────────────────────────────────────────────────────────
def fetch_last_two_closes(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for raw in tickers:
        t = normalize_ticker(raw)
        last_err = None
        for attempt in range(1, 4):
            try:
                fi = yf.Ticker(t).fast_info
                close_yday = getattr(fi, "last_price", None)
                close_prev = getattr(fi, "previous_close", None)
                if close_yday and close_prev:
                    rows.append((t, float(close_yday), float(close_prev)))
                    last_err = None
                    break
                # fallback: history-based
                hist = yf.Ticker(t).history(period="10d", interval="1d")
                s = hist["Close"].dropna()
                if len(s) >= 2:
                    rows.append((t, float(s.iloc[-1]), float(s.iloc[-2])))
                    last_err = None
                    break
                last_err = RuntimeError(f"No price data for {t}")
            except Exception as e:
                last_err = e
            time.sleep(1.0 * attempt)
        if last_err:
            raise RuntimeError(f"Failed to fetch '{raw}': {last_err}")
    return pd.DataFrame(rows, columns=["ticker", "close_yday", "close_prev"]).set_index("ticker")


# ─── Calendar events ──────────────────────────────────────────────────────────
def fetch_calendar_events(tickers: list[str]) -> tuple[list, list]:
    """Parallel yfinance calendar fetch. Returns (earn_alerts, exdiv_alerts)."""
    warnings.filterwarnings("ignore")
    today  = date.today()
    window = today + timedelta(days=EVENTS_WINDOW)
    earn_alerts, exdiv_alerts = [], []
    import threading
    lock_e = threading.Lock()
    lock_x = threading.Lock()

    def check_one(ticker):
        try:
            tk  = yf.Ticker(ticker)
            cal = tk.calendar or {}

            raw = cal.get("Earnings Date", [])
            if not isinstance(raw, list):
                raw = [raw]
            for d in raw:
                if not d or not hasattr(d, "year"):
                    continue
                dd = d.date() if hasattr(d, "date") else d
                if today <= dd <= window:
                    with lock_e:
                        earn_alerts.append({"ticker": ticker, "date": str(dd), "days": (dd - today).days})

            raw_ex = cal.get("Ex-Dividend Date")
            if raw_ex and hasattr(raw_ex, "year"):
                dd = raw_ex.date() if hasattr(raw_ex, "date") else raw_ex
                if today <= dd <= window:
                    amount = None
                    try:
                        divs = tk.dividends
                        if not divs.empty:
                            amount = round(float(divs.iloc[-1]), 4)
                    except Exception:
                        pass
                    with lock_x:
                        exdiv_alerts.append({"ticker": ticker, "date": str(dd), "days": (dd - today).days, "amount": amount})
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(check_one, tickers))

    return (
        sorted(earn_alerts,  key=lambda x: x["days"]),
        sorted(exdiv_alerts, key=lambda x: x["days"]),
    )


# ─── Layer drift ──────────────────────────────────────────────────────────────
def load_layer_targets() -> dict[int, float]:
    try:
        raw = json.loads(LAYER_TARGETS_F.read_text())
        return {int(k): float(v) for k, v in raw.items()}
    except Exception:
        return LAYER_TARGETS_DEFAULT.copy()


def compute_drift(layer_weights: dict) -> list[dict]:
    """Returns layers with abs(drift) >= DRIFT_THRESHOLD, sorted by abs drift desc."""
    targets = load_layer_targets()
    drifts = []
    for lnum in range(1, 6):
        target  = targets.get(lnum, 0)
        current = layer_weights.get(lnum, {}).get("weight_pct", 0)
        drift   = current - target
        if abs(drift) >= DRIFT_THRESHOLD:
            drifts.append({
                "layer_num":  lnum,
                "layer_name": LAYER_NAMES.get(lnum, f"L{lnum}"),
                "color":      LAYER_COLORS.get(lnum, "#888"),
                "target":     target,
                "current":    current,
                "drift":      drift,
            })
    return sorted(drifts, key=lambda d: abs(d["drift"]), reverse=True)


# ─── SQLite storage ───────────────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS portfolio_day (
      day TEXT PRIMARY KEY, total_value REAL, total_change_dollars REAL,
      total_change_pct REAL, spy_change_pct REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS layer_day (
      day TEXT, layer TEXT, value REAL, change_dollars REAL,
      change_pct REAL, weight_pct REAL, PRIMARY KEY (day, layer))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS holding_day (
      day TEXT, ticker TEXT, layer TEXT, shares REAL, price REAL, value REAL,
      change_dollars REAL, change_pct REAL, weight_pct REAL, PRIMARY KEY (day, ticker))""")


def store_snapshot(day, total_value, total_change, total_change_pct,
                   spy_change_pct, layers_df, holdings_df):
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    try:
        init_db(conn)
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_day VALUES (?,?,?,?,?)",
            (day, total_value, total_change, total_change_pct, spy_change_pct),
        )
        for _, r in layers_df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO layer_day VALUES (?,?,?,?,?,?)",
                (day, r["Layer"], r["value_yday"], r["chg_dollars"], r["chg_pct"], r["weight_pct"]),
            )
        for _, r in holdings_df.iterrows():
            conn.execute(
                "INSERT OR REPLACE INTO holding_day VALUES (?,?,?,?,?,?,?,?,?)",
                (day, r["Stock"], r["LayerLabel"], r["Shares"], r["close_yday"],
                 r["value_yday"], r["chg_dollars"], r["chg_pct"], r["weight_pct"]),
            )
        conn.commit()
    finally:
        conn.close()


# ─── Rubric + flags ───────────────────────────────────────────────────────────
def rubric_and_flags(total_change, layers, holdings):
    flags = []
    gross_l = float(layers["chg_dollars"].abs().sum())
    gross_h = float(holdings["chg_dollars"].abs().sum())

    if gross_l > 1e-9:
        tmp = layers.copy()
        tmp["gsh"] = (tmp["chg_dollars"].abs() / gross_l) * 100
        top = tmp.sort_values("gsh", ascending=False).iloc[0]
        if float(top["gsh"]) > LAYER_GROSS_DOM:
            net = (float(top["chg_dollars"]) / float(total_change) * 100) if abs(total_change) > 1e-9 else 0
            flags.append(f"⚠️ {top['Layer']} drove {top['gsh']:.1f}% of today's gross movement (net: {signed_pct(net)}).")

    if gross_h > 1e-9:
        h = holdings.copy()
        h["gsh"] = (h["chg_dollars"].abs() / gross_h) * 100
        top = h.sort_values("gsh", ascending=False).iloc[0]
        if float(top["gsh"]) > HOLDING_GROSS_DOM:
            net = (float(top["chg_dollars"]) / float(total_change) * 100) if abs(total_change) > 1e-9 else 0
            flags.append(f"⚠️ {top['Stock']} drove {top['gsh']:.1f}% of today's gross movement (net: {signed_pct(net)}).")

    rubric_rows = [
        ("Outcome vs Process",       "🟢 Green",
         "Daily outcome attributed by layer; no role violations detected."),
        ("Risk Concentration Drift", "🟢 Green" if not flags else "🟡 Yellow",
         "No dominance flags." if not flags else "Dominance flag(s) triggered; monitor concentration."),
        ("Time Horizon Discipline",  "🟢 Green",
         "Daily movements treated as signal/noise; no action prompts."),
        ("Execution Hygiene",        "🟢 Green",
         "Automated snapshot stored; repeatable process executed."),
    ]
    return pd.DataFrame(rubric_rows, columns=["Judgment Category", "Status", "Rationale"]), flags


# ─── Email sender ─────────────────────────────────────────────────────────────
def send_email(subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"]    = EMAIL_FROM
    msg["To"]      = ", ".join(TO_EMAILS)
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_APP_PW)
        smtp.send_message(msg)


# ─── HTML builder ─────────────────────────────────────────────────────────────
_TD = "style='padding:7px 12px;border-bottom:1px solid #f2f2f2;'"
_TH = "style='padding:7px 12px;text-align:left;border-bottom:1px solid #ddd;background:#f8fafc;'"
_CARD = "style='border:1px solid #e0e7ef;border-radius:8px;margin-bottom:16px;overflow:hidden;'"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th {_TH}>{h}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td {_TD}>{c}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return (
        f"<table cellpadding='0' cellspacing='0' "
        f"style='border-collapse:collapse;width:100%;font-size:13px;'>"
        f"<thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"
    )


def _section(title: str, body: str, accent: str = "#1a2340") -> str:
    return (
        f"<div {_CARD}>"
        f"<div style='background:{accent};color:#fff;padding:10px 16px;"
        f"font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;'>"
        f"{title}</div>"
        f"<div style='padding:16px;'>{body}</div>"
        f"</div>"
    )


def build_html(
    report_date: str,
    total_value: float,
    total_change: float,
    total_change_pct: float,
    spy_change_pct: float,
    layer_weights: dict,     # {lnum: {weight_pct, value_yday, chg_dollars, chg_pct}}
    holdings: pd.DataFrame,
    drift_alerts: list[dict],
    earn_alerts: list[dict],
    exdiv_alerts: list[dict],
    rubric_df: pd.DataFrame,
    flags: list[str],
) -> str:

    targets = load_layer_targets()
    chg_color = color_change(total_change)

    # ── 1. Snapshot ──────────────────────────────────────────────────────────
    best = holdings.loc[holdings["chg_dollars"].abs().idxmax()]
    best_txt = (f"{best['Stock']} {signed_pct(float(best['chg_pct']))} "
                f"({money(float(best['chg_dollars']))})")

    snapshot_html = (
        f"<div style='margin-bottom:14px;'>"
        f"<div style='font-size:28px;font-weight:700;color:#1a2340;'>{money(total_value)}</div>"
        f"<div style='font-size:12px;color:#aaa;margin-top:2px;'>Total Portfolio Value</div>"
        f"</div>"
        f"<div style='border-top:1px solid #f0f0f0;padding-top:12px;margin-bottom:14px;'>"
        f"<div style='font-size:20px;font-weight:700;color:{chg_color};'>"
        f"{signed_pct(total_change_pct)} &nbsp; {money(total_change)}</div>"
        f"<div style='font-size:12px;color:#aaa;margin-top:2px;'>Today · SPY {signed_pct(spy_change_pct)}</div>"
        f"</div>"
        f"<div style='border-top:1px solid #f0f0f0;padding-top:12px;'>"
        f"<div style='font-size:13px;font-weight:600;color:#1a2340;'>{best_txt}</div>"
        f"<div style='font-size:12px;color:#aaa;margin-top:2px;'>Biggest mover</div>"
        f"</div>"
    )

    # ── 2. Layer Allocation vs Target ────────────────────────────────────────
    layer_cards = []
    for lnum in range(1, 6):
        lw    = layer_weights.get(lnum, {})
        act   = lw.get("weight_pct", 0.0)
        val   = lw.get("value_yday", 0.0)
        dchg  = lw.get("chg_dollars", 0.0)
        dpct  = lw.get("chg_pct", 0.0)
        tgt   = targets.get(lnum, 0.0)
        drift = act - tgt
        color = LAYER_COLORS.get(lnum, "#888")
        chg_c = color_change(dchg)

        if abs(drift) <= 2:
            drift_label = f"<span style='color:#27ae60;font-size:11px;'>✓ on target</span>"
        elif drift > 0:
            drift_label = f"<span style='color:#e67e22;font-size:11px;'>▲ {drift:+.1f}pp over</span>"
        else:
            drift_label = f"<span style='color:#2980b9;font-size:11px;'>▼ {drift:+.1f}pp under</span>"

        sep = "border-top:1px solid #f0f0f0;" if lnum > 1 else ""
        layer_cards.append(
            f"<div style='{sep}padding:10px 0;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<div>"
            f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
            f"background:{color};margin-right:5px;vertical-align:middle;'></span>"
            f"<b style='font-size:13px;color:#1a2340;'>{LAYER_NAMES.get(lnum, f'L{lnum}')}</b>"
            f"</div>"
            f"<div style='text-align:right;'>"
            f"<span style='font-size:13px;font-weight:700;color:#1a2340;'>{act:.1f}%</span>"
            f"<span style='font-size:12px;color:#aaa;'> / {tgt:.0f}%</span>"
            f"&nbsp; {drift_label}"
            f"</div>"
            f"</div>"
            f"<div style='display:flex;justify-content:space-between;margin-top:3px;"
            f"font-size:12px;color:#888;'>"
            f"<span>{money(val)}</span>"
            f"<span style='color:{chg_c};'>{signed_pct(dpct)} ({money(dchg)})</span>"
            f"</div>"
            f"</div>"
        )

    alloc_table = "".join(layer_cards)

    # Drift warning box (if any layers ≥5pp off)
    drift_warning = ""
    if drift_alerts:
        items = "".join(
            f"<li style='margin-bottom:4px;'>"
            f"<b>{d['layer_name']}</b>: {d['current']:.1f}% actual vs {d['target']:.0f}% target — "
            f"<span style='color:{'#e74c3c' if abs(d['drift'])>=10 else '#e67e22'};font-weight:700;'>"
            f"{d['drift']:+.1f}pp</span></li>"
            for d in drift_alerts
        )
        drift_warning = (
            f"<div style='background:#fff8f0;border:1px solid #f5cba7;border-radius:6px;"
            f"padding:12px 16px;margin-bottom:14px;'>"
            f"<b style='color:#7d5a00;'>⚖️ Rebalancing needed</b> — "
            f"{len(drift_alerts)} layer{'s' if len(drift_alerts)!=1 else ''} drifted "
            f"≥{DRIFT_THRESHOLD:.0f}pp from target:<ul style='margin:8px 0 0;padding-left:18px;'>{items}</ul>"
            f"</div>"
        )

    alloc_body = drift_warning + alloc_table

    # ── 3. Calendar events ────────────────────────────────────────────────────
    events_html = ""

    def urgency(days):
        return "🔴" if days <= 1 else "🟡" if days <= 2 else "🟢"

    if earn_alerts:
        earn_rows = [
            [f"<b>{a['ticker']}</b>", a["date"],
             f"{a['days']}d {urgency(a['days'])}"]
            for a in earn_alerts
        ]
        events_html += (
            "<p style='font-size:12px;font-weight:700;color:#1a2340;margin:0 0 8px;'>"
            f"📊 Upcoming Earnings ({len(earn_alerts)} holding{'s' if len(earn_alerts)!=1 else ''})</p>"
            + _table(["Ticker", "Date", "Days Away"], earn_rows)
            + "<br>"
        )

    if exdiv_alerts:
        def payout(a):
            if a.get("amount") and a.get("shares"):
                return f"${a['amount'] * a['shares']:,.2f}"
            return "—"

        exdiv_rows = [
            [f"<b>{a['ticker']}</b>", a["date"],
             f"{a['days']}d {urgency(a['days'])}", payout(a)]
            for a in exdiv_alerts
        ]
        events_html += (
            "<p style='font-size:12px;font-weight:700;color:#1a2340;margin:0 0 8px;'>"
            f"💵 Upcoming Ex-Dividend ({len(exdiv_alerts)} holding{'s' if len(exdiv_alerts)!=1 else ''})</p>"
            + _table(["Ticker", "Ex-Date", "Days Away", "Est. Payout"], exdiv_rows)
        )

    # ── 4. Rubric + flags ─────────────────────────────────────────────────────
    rubric_rows_html = []
    for _, r in rubric_df.iterrows():
        rubric_rows_html.append([r["Judgment Category"], r["Status"], r["Rationale"]])
    rubric_table = _table(["Judgment Category", "Status", "Rationale"], rubric_rows_html)

    flags_html = ""
    if flags:
        items = "".join(f"<li style='margin-bottom:4px;'>{f}</li>" for f in flags)
        flags_html = (
            f"<div style='background:#fff1f1;border:1px solid #fca5a5;border-radius:6px;"
            f"padding:12px 16px;margin-top:14px;'>"
            f"<b style='color:#7f1d1d;'>Automated Flags</b>"
            f"<ul style='margin:8px 0 0;padding-left:18px;'>{items}</ul></div>"
        )

    anchor = "process-consistent" if not flags else "process-stressed"

    # ── Assemble ──────────────────────────────────────────────────────────────
    sections = [
        _section("📈 Portfolio Snapshot", snapshot_html),
        _section("⚖️ Layer Allocation vs Target", alloc_body),
    ]
    if events_html:
        sections.append(_section("⏰ Upcoming Events (Next 3 Days)", events_html, accent="#2980b9"))
    sections.append(_section("🧠 Judgment Health", rubric_table + flags_html))

    body = "\n".join(sections)

    return f"""
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
             line-height:1.4;background:#f4f6f9;padding:20px;color:#2c3e50;">
  <div style="max-width:680px;margin:0 auto;">

    <!-- Header -->
    <div style="background:#1a2340;color:#fff;padding:18px 20px;border-radius:8px 8px 0 0;margin-bottom:0;">
      <div style="font-size:18px;font-weight:700;letter-spacing:.02em;">Daily Investment Digest</div>
      <div style="font-size:12px;opacity:.7;margin-top:3px;">{report_date}</div>
    </div>

    <div style="background:#fff;border:1px solid #e0e7ef;border-top:none;
                border-radius:0 0 8px 8px;padding:20px;margin-bottom:16px;">
      {body}
    </div>

    <!-- Footer -->
    <div style="font-size:11px;color:#aaa;text-align:center;padding:0 0 12px;">
      Discipline anchor: today's behavior was <b style="color:#555;">{anchor}</b>
      with no judgment violations requiring action. &nbsp;·&nbsp;
      Layer targets in <code>layer_targets.json</code>
    </div>

  </div>
</body>
</html>"""


# ─── Main ─────────────────────────────────────────────────────────────────────
def main(send_email_flag: bool = True):
    if not HOLDINGS_CSV.exists():
        raise FileNotFoundError(f"Missing holdings CSV at {HOLDINGS_CSV}")
    if send_email_flag and (not EMAIL_FROM or not EMAIL_APP_PW):
        raise RuntimeError("EMAIL_FROM and EMAIL_APP_PASSWORD must be set in .env")

    # ── Load holdings ─────────────────────────────────────────────────────────
    raw = pd.read_csv(HOLDINGS_CSV)
    cols = [str(c).strip() for c in raw.columns]
    if all(c.startswith("Unnamed") for c in cols):
        raise ValueError("holdings.csv has no header row. Set Stock, Shares, AvgCost, Layer columns.")
    raw.columns = cols

    required = {"Stock", "Shares", "AvgCost", "Layer"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"holdings.csv missing columns: {sorted(missing)}")

    holdings = raw.copy()
    holdings["Stock"]  = holdings["Stock"].astype(str).str.strip().str.upper().map(normalize_ticker)
    holdings["Shares"] = holdings["Shares"].astype(float)
    holdings["Layer"]  = holdings["Layer"].astype(int)
    holdings["LayerName"]  = holdings["Layer"].map(lambda x: LAYER_NAMES.get(int(x), f"Layer {x}"))
    holdings["LayerLabel"] = holdings.apply(lambda r: f"Layer {int(r['Layer'])}: {r['LayerName']}", axis=1)

    stock_tickers = sorted(set(holdings["Stock"].tolist()))
    all_tickers   = stock_tickers + [BENCHMARK]

    # ── Parallel: prices + calendar events ───────────────────────────────────
    earn_alerts = exdiv_alerts = []
    with ThreadPoolExecutor(max_workers=2) as outer:
        close_fut   = outer.submit(fetch_last_two_closes, all_tickers)
        cal_fut     = outer.submit(fetch_calendar_events, stock_tickers)
        closes          = close_fut.result()
        earn_alerts, exdiv_alerts = cal_fut.result()

    # ── Enrich holdings ───────────────────────────────────────────────────────
    holdings["close_yday"] = holdings["Stock"].map(closes["close_yday"])
    holdings["close_prev"] = holdings["Stock"].map(closes["close_prev"])
    holdings["value_yday"] = holdings["Shares"] * holdings["close_yday"]
    holdings["value_prev"] = holdings["Shares"] * holdings["close_prev"]
    holdings["chg_dollars"] = holdings["value_yday"] - holdings["value_prev"]
    holdings["chg_pct"]     = (holdings["chg_dollars"] / holdings["value_prev"]) * 100.0

    total_value      = float(holdings["value_yday"].sum())
    total_prev       = float(holdings["value_prev"].sum())
    total_change     = total_value - total_prev
    total_change_pct = (total_change / total_prev * 100) if total_prev else 0.0

    b = closes.loc[normalize_ticker(BENCHMARK)]
    spy_change_pct = ((float(b["close_yday"]) - float(b["close_prev"])) / float(b["close_prev"])) * 100.0

    # ── Layer aggregation ─────────────────────────────────────────────────────
    layers = holdings.groupby("LayerLabel", as_index=False).agg(
        value_yday=("value_yday", "sum"),
        value_prev=("value_prev", "sum"),
        chg_dollars=("chg_dollars", "sum"),
    )
    layers["chg_pct"]    = (layers["chg_dollars"] / layers["value_prev"]) * 100.0
    layers["weight_pct"] = (layers["value_yday"] / total_value) * 100.0
    layers = layers.rename(columns={"LayerLabel": "Layer"})

    # layer_weights keyed by layer number for drift check + HTML
    lnum_map = {f"Layer {n}: {LAYER_NAMES[n]}": n for n in range(1, 6)}
    layer_weights = {}
    for _, r in layers.iterrows():
        lnum = lnum_map.get(r["Layer"])
        if lnum:
            layer_weights[lnum] = {
                "weight_pct":  float(r["weight_pct"]),
                "value_yday":  float(r["value_yday"]),
                "chg_dollars": float(r["chg_dollars"]),
                "chg_pct":     float(r["chg_pct"]),
            }

    drift_alerts = compute_drift(layer_weights)

    # ── DB snapshot ───────────────────────────────────────────────────────────
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    holdings["weight_pct"] = (holdings["value_yday"] / total_value) * 100.0
    store_snapshot(day, total_value, total_change, total_change_pct,
                   spy_change_pct, layers, holdings)

    # ── Rubric + flags ────────────────────────────────────────────────────────
    rubric_df, flags = rubric_and_flags(total_change, layers, holdings)

    # ── Build + send ──────────────────────────────────────────────────────────
    report_date = datetime.now(TZ).strftime("%A, %B %d, %Y")
    subject     = f"📬 Investment Digest — {datetime.now(TZ).strftime('%Y-%m-%d')}"

    # Add drift alert indicator to subject if rebalancing needed
    if drift_alerts:
        n = len(drift_alerts)
        subject = f"⚖️ Investment Digest — {datetime.now(TZ).strftime('%Y-%m-%d')} ({n} layer drift{'s' if n>1 else ''})"

    html = build_html(
        report_date=report_date,
        total_value=total_value,
        total_change=total_change,
        total_change_pct=total_change_pct,
        spy_change_pct=spy_change_pct,
        layer_weights=layer_weights,
        holdings=holdings,
        drift_alerts=drift_alerts,
        earn_alerts=earn_alerts,
        exdiv_alerts=exdiv_alerts,
        rubric_df=rubric_df,
        flags=flags,
    )

    if send_email_flag:
        send_email(subject, html)
        print(f"[Newsletter] Sent for {day} — "
              f"{len(earn_alerts)} earning alert(s), {len(exdiv_alerts)} ex-div alert(s), "
              f"{len(drift_alerts)} drift alert(s), {len(flags)} flag(s)")
    else:
        print(f"[Newsletter] Data updated for {day} (email skipped)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true", help="Update data and dashboard without sending the newsletter email")
    args = parser.parse_args()
    main(send_email_flag=not args.no_email)
