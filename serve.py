#!/usr/bin/env python3
"""
Investment dashboard server.
Serves static files at http://localhost:5001 and handles:
  GET  /api/covered-calls?ticker=EW  → option chain recommendations (JSON)
  GET  /api/dividends                → upcoming/recent dividend info for all holdings
  GET  /api/earnings                 → next earnings dates for all holdings
  GET  /api/dividend-timeline        → monthly income Jan–Dec
  GET  /api/dividend-lookup          → dividend info for any ticker
  GET  /api/buffett-winners          → Buffett screener results
  GET  /api/cc-positions             → covered call position log
  POST /api/cc-positions             → log a new covered call position
  PATCH /api/cc-positions/<id>       → update position status / close details
"""

import json
import math
import http.server
import os
import smtplib
import sqlite3
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_div_cache      = {"data": None, "ts": 0}
_earn_cache     = {"data": None, "ts": 0}
_timeline_cache = {"data": None, "ts": 0}
_DIV_CACHE_TTL      = 3600
_EARN_CACHE_TTL     = 3600
_TIMELINE_CACHE_TTL = 3600


def _cache_valid(cache, ttl):
    if not cache["data"] or (time.time() - cache["ts"]) > ttl:
        return False
    from datetime import date
    return cache.get("date") == date.today().isoformat()


def _cache_set(cache, data):
    from datetime import date
    cache["data"] = data
    cache["ts"]   = time.time()
    cache["date"] = date.today().isoformat()


PORT = 5001

PROJECT_DIR = Path(__file__).parent
os.chdir(PROJECT_DIR)


def _classify_div_type(info, ticker):
    qt       = (info.get("quoteType")  or "").upper()
    sector   = (info.get("sector")     or "").lower()
    category = (info.get("category")   or "").lower()
    name     = (info.get("longName")   or info.get("shortName") or "").lower()
    muni_kw  = ["municipal", "muni ", "tax-exempt", "tax exempt"]
    if qt == "CRYPTOCURRENCY":
        return "ordinary"
    if "real estate" in sector:
        return "ordinary"
    if any(kw in category or kw in name for kw in muni_kw):
        return "tax_exempt"
    return "qualified"


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _send_email(email_from, app_pw, email_to, subject, html):
    msg = MIMEMultipart("alternative")
    msg["From"]    = email_from
    msg["To"]      = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(email_from, app_pw)
        smtp.send_message(msg)


def _load_email_creds():
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
    return os.getenv("EMAIL_FROM"), os.getenv("EMAIL_APP_PASSWORD"), os.getenv("EMAIL_TO")


# ── CC positions table ────────────────────────────────────────────────────────
def _init_cc_table():
    db = PROJECT_DIR / "out" / "investment.db"
    if not db.exists():
        return
    conn = sqlite3.connect(str(db), timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cc_positions (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker               TEXT    NOT NULL,
            contracts            INTEGER NOT NULL,
            strike               REAL    NOT NULL,
            expiry               TEXT    NOT NULL,
            premium_per_contract REAL    NOT NULL,
            opened_date          TEXT    NOT NULL,
            status               TEXT    NOT NULL DEFAULT 'open',
            closed_date          TEXT,
            closed_price         REAL,
            notes                TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_cc_table()


# ── Cost-lot tracking table ───────────────────────────────────────────────────
def _init_lots_table():
    db = PROJECT_DIR / "out" / "investment.db"
    if not db.exists():
        return
    conn = sqlite3.connect(str(db), timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_lots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker         TEXT    NOT NULL,
            shares         REAL    NOT NULL,
            cost_per_share REAL    NOT NULL,
            purchase_date  TEXT    NOT NULL,
            notes          TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_lots_table()


def _init_sells_table():
    db = PROJECT_DIR / "out" / "investment.db"
    if not db.exists():
        return
    conn = sqlite3.connect(str(db), timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sell_transactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker        TEXT    NOT NULL,
            shares_sold   REAL    NOT NULL,
            sell_price    REAL    NOT NULL,
            sell_date     TEXT    NOT NULL,
            realized_gain REAL,
            st_gain       REAL,
            lt_gain       REAL,
            fifo_detail   TEXT,
            notes         TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_sells_table()


def _fifo_allocate(lots, shares_to_sell, sell_price, sell_date):
    """FIFO cost basis allocation. lots sorted oldest-first by caller.
    Returns (allocations, error_string_or_None)."""
    from datetime import date as _date
    total_avail = sum(l["shares"] for l in lots)
    if shares_to_sell > total_avail + 1e-6:
        return None, f"Only {total_avail} shares in lots; cannot sell {shares_to_sell}"
    sell_dt   = _date.fromisoformat(sell_date)
    remaining = shares_to_sell
    allocs    = []
    for lot in lots:
        if remaining <= 1e-6:
            break
        purchase_dt = _date.fromisoformat(lot["purchase_date"])
        days_held   = (sell_dt - purchase_dt).days
        term        = "LT" if days_held >= 365 else "ST"
        used        = min(lot["shares"], remaining)
        cost_basis  = round(used * lot["cost_per_share"], 6)
        proceeds    = round(used * sell_price, 6)
        allocs.append({
            "lot_id":        lot["id"],
            "purchase_date": lot["purchase_date"],
            "cost_per_share":lot["cost_per_share"],
            "original_shares":lot["shares"],
            "notes":         lot.get("notes") or "",
            "shares":        round(used, 6),
            "days_held":     days_held,
            "term":          term,
            "cost_basis":    cost_basis,
            "proceeds":      proceeds,
            "gain":          round(proceeds - cost_basis, 6),
        })
        remaining -= used
    return allocs, None


# ── Daily newsletter + drift alert scheduler ──────────────────────────────────
def _check_layer_drift():
    """Compare current layer weights to layer_targets.json. Email if any drift ≥5pp."""
    import csv as _csv

    email_from, app_pw, email_to = _load_email_creds()
    if not all([email_from, app_pw, email_to]):
        return

    targets_file = PROJECT_DIR / "layer_targets.json"
    holdings_csv = PROJECT_DIR / "holdings.csv"
    layer_names  = {
        1: "Layer 1: Structural Ballast",
        2: "Layer 2: Cash-Flow Engines",
        3: "Layer 3: Compounders",
        4: "Layer 4: Convexity / Optionality",
        5: "Layer 5: Shock Absorbers / Regime Hedges",
    }

    holdings = {}
    with open(holdings_csv, newline="") as f:
        for row in _csv.DictReader(f):
            ticker = str(row["Stock"]).strip().upper()
            holdings[ticker] = {
                "shares":    float(row["Shares"]),
                "layer_num": int(str(row["Layer"]).strip()),
            }

    db = PROJECT_DIR / "out" / "investment.db"
    if not db.exists():
        return
    conn = sqlite3.connect(str(db), timeout=10)
    conn.row_factory = sqlite3.Row
    prices = {r["ticker"]: r["price"] for r in conn.execute(
        "SELECT ticker, price FROM holding_day WHERE day = (SELECT MAX(day) FROM holding_day)"
    )}
    conn.close()

    layer_values = {}
    total_value  = 0.0
    for ticker, meta in holdings.items():
        price = prices.get(ticker)
        if not price:
            continue
        value = meta["shares"] * price
        lnum  = meta["layer_num"]
        layer_values[lnum] = layer_values.get(lnum, 0.0) + value
        total_value += value

    if total_value == 0:
        return

    current_weights = {
        lnum: round(val / total_value * 100, 2)
        for lnum, val in layer_values.items()
    }

    if not targets_file.exists():
        targets = {str(lnum): w for lnum, w in current_weights.items()}
        targets_file.write_text(json.dumps(targets, indent=2))
        print("[DriftAlert] Created layer_targets.json from current weights. Edit to set custom targets.")
        return

    try:
        targets = json.loads(targets_file.read_text())
    except Exception:
        return

    THRESHOLD = 5.0
    drifts = []
    for lnum in range(1, 6):
        target  = float(targets.get(str(lnum), current_weights.get(lnum, 0)))
        current = current_weights.get(lnum, 0)
        drift   = current - target
        if abs(drift) >= THRESHOLD:
            drifts.append({
                "layer_num":  lnum,
                "layer_name": layer_names.get(lnum, f"Layer {lnum}"),
                "target":     target,
                "current":    current,
                "drift":      drift,
            })

    if not drifts:
        return

    from datetime import date
    today = date.today().strftime("%b %d, %Y")
    rows  = ""
    for d in drifts:
        direction = "↑ over" if d["drift"] > 0 else "↓ under"
        color     = "#e74c3c" if abs(d["drift"]) >= 10 else "#e67e22"
        rows += f"""<tr>
          <td style="padding:8px 12px;font-weight:600;">{d['layer_name']}</td>
          <td style="padding:8px 12px;">{d['target']:.1f}%</td>
          <td style="padding:8px 12px;font-weight:700;">{d['current']:.1f}%</td>
          <td style="padding:8px 12px;color:{color};font-weight:700;">{d['drift']:+.1f}pp {direction}</td>
        </tr>"""

    html = f"""<html><body style="font-family:-apple-system,sans-serif;color:#2c3e50;max-width:600px;margin:0 auto;">
      <h2 style="color:#1a2340;">⚖️ Layer Drift Alert — {today}</h2>
      <p style="color:#7f8c8d;font-size:13px;">
        {len(drifts)} layer{'s' if len(drifts)!=1 else ''} ha{'ve' if len(drifts)!=1 else 's'}
        drifted ≥{THRESHOLD:.0f}pp from target allocation.
      </p>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#f4f6f9;">
          <th style="padding:8px 12px;text-align:left;">Layer</th>
          <th style="padding:8px 12px;text-align:left;">Target</th>
          <th style="padding:8px 12px;text-align:left;">Current</th>
          <th style="padding:8px 12px;text-align:left;">Drift</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="font-size:11px;color:#aaa;margin-top:16px;">
        Edit <code>layer_targets.json</code> to update your target allocations.
        Alert threshold: ≥{THRESHOLD:.0f} percentage points.
      </p>
    </body></html>"""

    subject = f"⚖️ Layer drift alert: {len(drifts)} layer{'s' if len(drifts)!=1 else ''} off target — {today}"
    try:
        _send_email(email_from, app_pw, email_to, subject, html)
        print(f"[DriftAlert] Sent: {len(drifts)} layer(s) off target.")
    except Exception as e:
        print(f"[DriftAlert] Email failed: {e}")


def _backup_data():
    """Push investment.db, buffett.db, and holdings.csv to the private data repo."""
    script = PROJECT_DIR / "backup_data.sh"
    if not script.exists():
        return
    import subprocess
    result = subprocess.run(
        ["bash", str(script)],
        cwd=str(PROJECT_DIR),
        capture_output=True, text=True, timeout=120
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"[Backup] Failed: {result.stderr.strip()}")


def _run_daily():
    """
    Background thread: runs the newsletter + dashboard once per day at 8 AM ET.
    After a successful newsletter run, checks layer drift.
    """
    import subprocess
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ      = ZoneInfo("America/New_York")
    FLAG    = PROJECT_DIR / "out" / "last_run_date.txt"
    VENV_PY = PROJECT_DIR / "venv" / "bin" / "python3"
    LOG     = PROJECT_DIR / "out" / "newsletter.log"

    def already_ran(today):
        try:
            return FLAG.read_text().strip() == today
        except Exception:
            return False

    def run():
        with open(LOG, "a") as lf:
            lf.write(f"\n=== SCHEDULER {_dt.now(TZ)} ===\n")
            for script in ["send_newsletter_main.py", "generate_dashboard.py"]:
                result = subprocess.run(
                    [str(VENV_PY), str(PROJECT_DIR / script)],
                    cwd=str(PROJECT_DIR),
                    capture_output=True, text=True, timeout=300
                )
                lf.write(result.stdout or "")
                if result.returncode != 0:
                    lf.write(f"ERROR ({script}): {result.stderr}\n")
                    return False
        return True

    while True:
        now   = _dt.now(TZ)
        today = now.date().isoformat()
        if now.hour >= 8 and not already_ran(today):
            print(f"[Scheduler] Running newsletter for {today}…")
            if run():
                FLAG.write_text(today)
                print(f"[Scheduler] Done for {today}.")
                try:
                    _check_layer_drift()
                except Exception as exc:
                    print(f"[DriftAlert] Exception: {exc}")
                try:
                    _backup_data()
                except Exception as exc:
                    print(f"[Backup] Exception: {exc}")
            else:
                print(f"[Scheduler] Failed — will retry in 30 min.")
        time.sleep(1800)


threading.Thread(target=_run_daily, daemon=True).start()


# ── Nightly Buffett screener (2 AM ET) ───────────────────────────────────────
def _run_screener():
    """Background thread: runs the Buffett screener once per day at 2 AM ET."""
    import subprocess
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ      = ZoneInfo("America/New_York")
    FLAG    = PROJECT_DIR / "out" / "last_screener_date.txt"
    VENV_PY = PROJECT_DIR / "venv" / "bin" / "python3"
    LOG     = PROJECT_DIR / "out" / "screener.log"

    def already_ran(today):
        try:
            return FLAG.read_text().strip() == today
        except Exception:
            return False

    while True:
        now   = _dt.now(TZ)
        today = now.date().isoformat()
        if now.hour >= 2 and not already_ran(today):
            print(f"[Screener] Starting Buffett scan for {today}…")
            try:
                with open(LOG, "a") as lf:
                    lf.write(f"\n=== SCREENER {_dt.now(TZ)} ===\n")
                    result = subprocess.run(
                        [str(VENV_PY), str(PROJECT_DIR / "buffett_screener.py")],
                        cwd=str(PROJECT_DIR),
                        capture_output=True, text=True
                    )
                    lf.write(result.stdout or "")
                    if result.returncode != 0:
                        lf.write(f"ERROR: {result.stderr}\n")
                        print(f"[Screener] Failed — check {LOG}")
                    else:
                        FLAG.write_text(today)
                        print(f"[Screener] Done for {today}.")
            except Exception as exc:
                print(f"[Screener] Exception: {exc}")
        time.sleep(1800)


threading.Thread(target=_run_screener, daemon=True).start()


# ── Daily reminder emails (7 AM ET) ──────────────────────────────────────────
def _run_reminders():
    """
    Background thread: daily at 7 AM ET, email upcoming earnings and ex-div
    dates (1–3 days out) for all holdings.
    """
    import warnings
    import yfinance as yf
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt, date, timedelta

    TZ   = ZoneInfo("America/New_York")
    FLAG = PROJECT_DIR / "out" / "last_reminder_date.txt"

    def already_ran(today):
        try:
            return FLAG.read_text().strip() == today
        except Exception:
            return False

    def fetch_alerts():
        warnings.filterwarnings("ignore")
        from covered_call_rec import load_holdings
        holdings = load_holdings()
        today  = date.today()
        window = today + timedelta(days=3)

        earn_alerts  = []
        exdiv_alerts = []

        def check_one(kv):
            ticker, meta = kv
            try:
                tk  = yf.Ticker(ticker)
                cal = tk.calendar or {}

                # Earnings
                raw = cal.get("Earnings Date", [])
                if not isinstance(raw, list):
                    raw = [raw]
                for d in raw:
                    if not d or not hasattr(d, "year"):
                        continue
                    dd = d.date() if hasattr(d, "date") else d
                    if today <= dd <= window:
                        earn_alerts.append({
                            "ticker": ticker,
                            "date":   str(dd),
                            "days":   (dd - today).days,
                        })

                # Ex-dividend
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
                        exdiv_alerts.append({
                            "ticker": ticker,
                            "shares": meta["shares"],
                            "date":   str(dd),
                            "days":   (dd - today).days,
                            "amount": amount,
                        })
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(check_one, holdings.items()))

        return earn_alerts, exdiv_alerts

    def build_and_send(earn_alerts, exdiv_alerts):
        email_from, app_pw, email_to = _load_email_creds()
        if not all([email_from, app_pw, email_to]):
            return

        from datetime import date
        today = date.today().strftime("%b %d, %Y")

        def urgency(days):
            return "🔴" if days <= 1 else "🟡" if days <= 2 else "🟢"

        sections = ""
        if earn_alerts:
            rows = "".join(
                f"<tr><td style='padding:7px 12px;font-weight:700;'>{a['ticker']}</td>"
                f"<td style='padding:7px 12px;'>{a['date']}</td>"
                f"<td style='padding:7px 12px;'>{a['days']}d away {urgency(a['days'])}</td></tr>"
                for a in sorted(earn_alerts, key=lambda x: x["days"])
            )
            sections += f"""<h3 style="color:#1a2340;margin-top:16px;">
                📊 Upcoming Earnings ({len(earn_alerts)} holding{'s' if len(earn_alerts)!=1 else ''})
              </h3>
              <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <thead><tr style="background:#f4f6f9;">
                  <th style="padding:7px 12px;text-align:left;">Ticker</th>
                  <th style="padding:7px 12px;text-align:left;">Date</th>
                  <th style="padding:7px 12px;text-align:left;"></th>
                </tr></thead>
                <tbody>{rows}</tbody>
              </table>"""

        if exdiv_alerts:
            def _payout(a):
                if a.get("amount") and a.get("shares"):
                    return f"${a['amount'] * a['shares']:,.2f}"
                return "—"

            rows = "".join(
                f"<tr><td style='padding:7px 12px;font-weight:700;'>{a['ticker']}</td>"
                f"<td style='padding:7px 12px;'>{a['date']}</td>"
                f"<td style='padding:7px 12px;'>{a['days']}d away {urgency(a['days'])}</td>"
                f"<td style='padding:7px 12px;'>{_payout(a)}</td></tr>"
                for a in sorted(exdiv_alerts, key=lambda x: x["days"])
            )
            sections += f"""<h3 style="color:#1a2340;margin-top:16px;">
                💵 Upcoming Ex-Dividend ({len(exdiv_alerts)} holding{'s' if len(exdiv_alerts)!=1 else ''})
              </h3>
              <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <thead><tr style="background:#f4f6f9;">
                  <th style="padding:7px 12px;text-align:left;">Ticker</th>
                  <th style="padding:7px 12px;text-align:left;">Ex-Date</th>
                  <th style="padding:7px 12px;text-align:left;"></th>
                  <th style="padding:7px 12px;text-align:left;">Est. Payout</th>
                </tr></thead>
                <tbody>{rows}</tbody>
              </table>"""

        count   = len(earn_alerts) + len(exdiv_alerts)
        html    = f"""<html><body style="font-family:-apple-system,sans-serif;color:#2c3e50;max-width:600px;margin:0 auto;">
          <h2 style="color:#1a2340;">⏰ Investment Reminders — {today}</h2>
          <p style="color:#7f8c8d;font-size:13px;">Upcoming events for your holdings in the next 3 days.</p>
          {sections}
          <p style="font-size:11px;color:#aaa;margin-top:24px;">
            Reminder window: 3 days · Edit serve.py → _run_reminders() to adjust.
          </p>
        </body></html>"""
        subject = f"⏰ {count} portfolio event{'s' if count!=1 else ''} in next 3 days — {today}"
        try:
            _send_email(email_from, app_pw, email_to, subject, html)
            print(f"[Reminders] Sent {count} event alert(s).")
        except Exception as e:
            print(f"[Reminders] Email failed: {e}")

    while True:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        now   = _dt.now(TZ)
        today = now.date().isoformat()
        if now.hour >= 7 and not already_ran(today):
            try:
                earn_alerts, exdiv_alerts = fetch_alerts()
                if earn_alerts or exdiv_alerts:
                    build_and_send(earn_alerts, exdiv_alerts)
                else:
                    print(f"[Reminders] No events in next 3 days for {today}.")
                FLAG.write_text(today)
            except Exception as exc:
                print(f"[Reminders] Exception: {exc}")
        time.sleep(1800)


threading.Thread(target=_run_reminders, daemon=True).start()


# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/out/dashboard.html")
            self.end_headers()
            return
        if parsed.path == "/api/covered-calls":
            self._handle_covered_calls(parse_qs(parsed.query))
        elif parsed.path == "/api/dividends":
            self._handle_dividends()
        elif parsed.path == "/api/earnings":
            self._handle_earnings()
        elif parsed.path == "/api/dividend-timeline":
            self._handle_dividend_timeline()
        elif parsed.path == "/api/dividend-lookup":
            self._handle_dividend_lookup(parse_qs(parsed.query))
        elif parsed.path == "/api/buffett-winners":
            self._handle_buffett_winners()
        elif parsed.path == "/api/cc-positions":
            self._handle_cc_positions_get()
        elif parsed.path == "/api/lots":
            self._handle_lots_get(parse_qs(parsed.query).get("ticker", [None])[0])
        elif parsed.path == "/api/sells":
            self._handle_sells_get(parse_qs(parsed.query).get("ticker", [None])[0])
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/cc-positions":
            self._handle_cc_add()
        elif parsed.path == "/api/lots":
            self._handle_lot_add()
        elif parsed.path == "/api/sells":
            self._handle_sell_add()
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        parts  = parsed.path.rstrip("/").split("/")
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "lots" and parts[3].isdigit():
            self._handle_lot_delete(int(parts[3]))
        elif len(parts) == 4 and parts[1] == "api" and parts[2] == "sells" and parts[3].isdigit():
            self._handle_sell_undo(int(parts[3]))
        else:
            self.send_response(404)
            self.end_headers()

    def do_PATCH(self):
        parsed = urlparse(self.path)
        parts  = parsed.path.rstrip("/").split("/")
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "cc-positions" and parts[3].isdigit():
            self._handle_cc_update(int(parts[3]))
        else:
            self.send_response(404)
            self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── CC positions ──────────────────────────────────────────────────────────
    def _handle_cc_positions_get(self):
        try:
            db = PROJECT_DIR / "out" / "investment.db"
            if not db.exists():
                return self._json({"ok": True, "positions": []})
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row
            positions = [dict(r) for r in conn.execute(
                "SELECT * FROM cc_positions ORDER BY opened_date DESC, id DESC"
            )]
            conn.close()
            self._json({"ok": True, "positions": positions})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_cc_add(self):
        try:
            body     = self._read_body()
            required = ["ticker", "contracts", "strike", "expiry",
                        "premium_per_contract", "opened_date"]
            missing  = [f for f in required if not body.get(f)]
            if missing:
                return self._json_error(400, f"Missing fields: {', '.join(missing)}")

            db = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            cur  = conn.execute("""
                INSERT INTO cc_positions
                (ticker, contracts, strike, expiry, premium_per_contract, opened_date, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
            """, (body["ticker"].upper(), int(body["contracts"]), float(body["strike"]),
                  body["expiry"], float(body["premium_per_contract"]),
                  body["opened_date"], body.get("notes", "")))
            conn.commit()
            pos_id = cur.lastrowid
            conn.close()
            self._json({"ok": True, "id": pos_id})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_cc_update(self, pos_id: int):
        try:
            body    = self._read_body()
            db      = PROJECT_DIR / "out" / "investment.db"
            conn    = sqlite3.connect(str(db), timeout=10)
            updates = []
            values  = []
            for field in ["status", "closed_date", "closed_price", "notes"]:
                if field in body:
                    updates.append(f"{field} = ?")
                    values.append(body[field])
            if not updates:
                conn.close()
                return self._json_error(400, "No updatable fields provided")
            values.append(pos_id)
            conn.execute(f"UPDATE cc_positions SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
            conn.close()
            self._json({"ok": True})
        except Exception as e:
            self._json_error(500, str(e))

    # ── Cost lots ─────────────────────────────────────────────────────────────
    def _handle_lots_get(self, ticker=None):
        try:
            db = PROJECT_DIR / "out" / "investment.db"
            if not db.exists():
                return self._json({"ok": True, "lots": []})
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row
            if ticker:
                lots = [dict(r) for r in conn.execute(
                    "SELECT * FROM cost_lots WHERE ticker = ? ORDER BY purchase_date",
                    (ticker.upper(),)
                )]
            else:
                lots = [dict(r) for r in conn.execute(
                    "SELECT * FROM cost_lots ORDER BY ticker, purchase_date"
                )]
            conn.close()
            self._json({"ok": True, "lots": lots})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_lot_add(self):
        try:
            body     = self._read_body()
            required = ["ticker", "shares", "cost_per_share", "purchase_date"]
            missing  = [f for f in required if not body.get(f)]
            if missing:
                return self._json_error(400, f"Missing: {', '.join(missing)}")
            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            cur  = conn.execute("""
                INSERT INTO cost_lots (ticker, shares, cost_per_share, purchase_date, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (body["ticker"].upper(), float(body["shares"]),
                  float(body["cost_per_share"]), body["purchase_date"],
                  body.get("notes", "")))
            conn.commit()
            pos_id = cur.lastrowid
            conn.close()
            self._json({"ok": True, "id": pos_id})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_lot_delete(self, lot_id: int):
        try:
            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            conn.execute("DELETE FROM cost_lots WHERE id = ?", (lot_id,))
            conn.commit()
            conn.close()
            self._json({"ok": True})
        except Exception as e:
            self._json_error(500, str(e))

    # ── Sell transactions ─────────────────────────────────────────────────────
    def _handle_sells_get(self, ticker=None):
        try:
            import json as _json
            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM sell_transactions WHERE ticker=? ORDER BY sell_date DESC, id DESC",
                    (ticker.upper(),)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sell_transactions ORDER BY sell_date DESC, id DESC"
                ).fetchall()
            conn.close()
            sells = []
            for r in rows:
                d = dict(r)
                if d.get("fifo_detail"):
                    d["fifo_detail"] = _json.loads(d["fifo_detail"])
                sells.append(d)
            self._json({"ok": True, "sells": sells})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_sell_add(self):
        try:
            import json as _json
            length = int(self.headers.get("Content-Length", 0))
            data   = _json.loads(self.rfile.read(length))
            ticker      = (data.get("ticker") or "").upper().strip()
            shares_sold = float(data.get("shares_sold", 0))
            sell_price  = float(data.get("sell_price", 0))
            sell_date   = (data.get("sell_date") or "").strip()
            notes       = (data.get("notes") or "").strip()
            if not ticker or shares_sold <= 0 or sell_price <= 0 or not sell_date:
                self._json({"ok": False, "error": "ticker, shares_sold, sell_price, and sell_date required"})
                return
            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row
            lots = [dict(r) for r in conn.execute(
                "SELECT * FROM cost_lots WHERE ticker=? ORDER BY purchase_date ASC, id ASC",
                (ticker,)
            ).fetchall()]
            allocs, error = _fifo_allocate(lots, shares_sold, sell_price, sell_date)
            if error:
                conn.close()
                self._json({"ok": False, "error": error})
                return
            total_gain = round(sum(a["gain"] for a in allocs), 6)
            st_gain    = round(sum(a["gain"] for a in allocs if a["term"] == "ST"), 6)
            lt_gain    = round(sum(a["gain"] for a in allocs if a["term"] == "LT"), 6)
            cur = conn.execute(
                """INSERT INTO sell_transactions
                   (ticker, shares_sold, sell_price, sell_date, realized_gain, st_gain, lt_gain, fifo_detail, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ticker, shares_sold, sell_price, sell_date,
                 total_gain, st_gain, lt_gain, _json.dumps(allocs), notes)
            )
            sell_id = cur.lastrowid
            # Mutate lots: reduce partially consumed, delete fully consumed
            for alloc in allocs:
                remaining = round(alloc["original_shares"] - alloc["shares"], 6)
                if remaining < 1e-4:
                    conn.execute("DELETE FROM cost_lots WHERE id=?", (alloc["lot_id"],))
                else:
                    conn.execute("UPDATE cost_lots SET shares=? WHERE id=?",
                                 (remaining, alloc["lot_id"]))
            conn.commit()
            conn.close()
            self._json({"ok": True, "id": sell_id, "realized_gain": total_gain,
                        "st_gain": st_gain, "lt_gain": lt_gain, "allocations": allocs})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_sell_undo(self, sell_id: int):
        """Undo a sell: restore lots from fifo_detail snapshot, delete the sell record."""
        try:
            import json as _json
            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sell_transactions WHERE id=?", (sell_id,)
            ).fetchone()
            if not row:
                conn.close()
                self._json({"ok": False, "error": "Sell not found"})
                return
            allocs = _json.loads(row["fifo_detail"] or "[]")
            for alloc in allocs:
                existing = conn.execute(
                    "SELECT id, shares FROM cost_lots WHERE id=?", (alloc["lot_id"],)
                ).fetchone()
                if existing:
                    # Lot still exists (was partially consumed) — add shares back
                    conn.execute("UPDATE cost_lots SET shares=? WHERE id=?",
                                 (round(existing["shares"] + alloc["shares"], 6), alloc["lot_id"]))
                else:
                    # Lot was deleted (fully consumed) — re-create it
                    conn.execute(
                        """INSERT INTO cost_lots (id, ticker, shares, cost_per_share, purchase_date, notes)
                           VALUES (?,?,?,?,?,?)""",
                        (alloc["lot_id"], row["ticker"], alloc["original_shares"],
                         alloc["cost_per_share"], alloc["purchase_date"], alloc.get("notes") or "")
                    )
            conn.execute("DELETE FROM sell_transactions WHERE id=?", (sell_id,))
            conn.commit()
            conn.close()
            self._json({"ok": True})
        except Exception as e:
            self._json_error(500, str(e))

    # ── Covered calls ─────────────────────────────────────────────────────────
    def _handle_covered_calls(self, params):
        ticker = (params.get("ticker", [None])[0] or "").upper().strip()
        if not ticker:
            return self._json_error(400, "Missing ticker parameter")

        try:
            from covered_call_rec import analyze, load_holdings
            holdings = load_holdings()

            if ticker not in holdings:
                return self._json_error(404, f"{ticker} not found in holdings")

            h      = holdings[ticker]
            result = analyze(ticker, h["avg_cost"], h["shares"])

            if result is None:
                return self._json({"ok": False, "ticker": ticker,
                                   "error": "No qualifying contracts found in 21–60 DTE window."})

            recs = []
            for _, row in result["recs"].iterrows():
                recs.append({
                    "expiration":       row["expiration"],
                    "strike":           float(row["strike"]),
                    "dte":              int(row["dte"]),
                    "bid":              float(row["bid"]),
                    "ask":              float(row["ask"]),
                    "mid":              float(row["mid"]),
                    "premium_pct":      round(float(row["premium_pct"]), 2),
                    "annualized_ret":   round(float(row["annualized_ret"]), 1),
                    "profit_if_called": round(float(row["profit_if_called"]), 1),
                    "open_interest":    int(_safe_float(row.get("openInterest"))),
                    "volume":           int(_safe_float(row.get("volume"))),
                    "delta":            round(_safe_float(row.get("delta")), 3),
                    "risk_events":      list(row.get("risk_events") or []),
                    "has_avoid":        bool(row.get("has_avoid")),
                    "has_caution":      bool(row.get("has_caution")),
                })

            self._json({
                "ok":                True,
                "ticker":            result["ticker"],
                "current_price":     round(result["current_price"], 2),
                "avg_cost":          round(result["avg_cost"], 2),
                "gain_pct":          round(result["gain_pct"], 2),
                "already_at_target": result["already_at_target"],
                "strike_floor":      round(result["strike_floor"], 2),
                "week52_high":       round(result["week52_high"], 2),
                "week52_high_dt":    result["week52_high_dt"],
                "recs":              recs,
            })

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_dividend_timeline(self):
        try:
            import yfinance as yf
            import warnings
            from collections import defaultdict
            from datetime import date, timedelta
            warnings.filterwarnings("ignore")

            from covered_call_rec import load_holdings

            if _cache_valid(_timeline_cache, _TIMELINE_CACHE_TTL):
                return self._json(_timeline_cache["data"])

            holdings   = load_holdings()
            today      = date.today()
            this_year  = today.year
            this_month = today.strftime("%Y-%m")
            months     = [date(this_year, m, 1).strftime("%Y-%m") for m in range(1, 13)]

            received = defaultdict(float)
            expected = defaultdict(float)

            def fetch_one(kv):
                ticker, meta = kv
                shares  = meta["shares"]
                r_local = defaultdict(float)
                e_local = defaultdict(float)
                try:
                    tk   = yf.Ticker(ticker)
                    divs = tk.dividends
                    if divs.empty:
                        return r_local, e_local
                    for ts, amount in divs.items():
                        d  = ts.date() if hasattr(ts, "date") else ts
                        mk = d.strftime("%Y-%m")
                        if mk in months and d < today:
                            r_local[mk] += float(amount) * shares
                    if len(divs) >= 2:
                        recent    = divs.tail(4)
                        intervals = [(recent.index[i] - recent.index[i-1]).days
                                     for i in range(1, len(recent))]
                        freq_days = int(round(sum(intervals) / len(intervals)))
                        last_date   = divs.index[-1].date()
                        last_amount = float(divs.iloc[-1])
                        next_d = last_date + timedelta(days=freq_days)
                        cutoff = date(this_year, 12, 31)
                        while next_d <= cutoff:
                            mk = next_d.strftime("%Y-%m")
                            if mk in months and next_d > today:
                                e_local[mk] += last_amount * shares
                            next_d += timedelta(days=freq_days)
                except Exception:
                    pass
                return r_local, e_local

            with ThreadPoolExecutor(max_workers=10) as pool:
                for r_local, e_local in pool.map(fetch_one, holdings.items()):
                    for mk, v in r_local.items():
                        received[mk] += v
                    for mk, v in e_local.items():
                        expected[mk] += v

            this_idx = months.index(this_month) if this_month in months else None
            payload  = {
                "ok":             True,
                "months":         months,
                "received":       [round(received.get(mk, 0), 2) for mk in months],
                "expected":       [round(expected.get(mk, 0), 2) for mk in months],
                "this_month":     this_month,
                "this_month_idx": this_idx,
            }
            _cache_set(_timeline_cache, payload)
            self._json(payload)

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_earnings(self):
        try:
            import yfinance as yf
            import warnings
            from datetime import date
            warnings.filterwarnings("ignore")

            from covered_call_rec import load_holdings

            if _cache_valid(_earn_cache, _EARN_CACHE_TTL):
                return self._json(_earn_cache["data"])

            holdings = load_holdings()
            today    = date.today()

            LAYER_NAMES = {
                1: "Layer 1: Structural Ballast",
                2: "Layer 2: Cash-Flow Engines",
                3: "Layer 3: Compounders",
                4: "Layer 4: Convexity / Optionality",
                5: "Layer 5: Shock Absorbers / Regime Hedges",
            }

            def fetch_one(kv):
                ticker, meta = kv
                row = {"ticker": ticker, "layer_num": meta["layer"],
                       "layer": LAYER_NAMES.get(meta["layer"], f"Layer {meta['layer']}")}
                try:
                    tk = yf.Ticker(ticker)
                    upcoming, past = [], []
                    try:
                        cal = tk.calendar or {}
                        raw = cal.get("Earnings Date", [])
                        if not isinstance(raw, list):
                            raw = [raw]
                        for d in raw:
                            if d and hasattr(d, "year"):
                                (upcoming if d >= today else past).append(d)
                    except Exception:
                        pass
                    if not upcoming and not past:
                        try:
                            ed = tk.earnings_dates
                            if ed is not None and not ed.empty:
                                for ts in ed.index:
                                    d = ts.date() if hasattr(ts, "date") else ts
                                    (upcoming if d >= today else past).append(d)
                        except Exception:
                            pass
                    if upcoming:
                        target, is_upcoming = min(upcoming), True
                    elif past:
                        target, is_upcoming = max(past), False
                    else:
                        return row
                    days = (target - today).days
                    row.update({"earnings_date": str(target), "is_upcoming": is_upcoming,
                                "days_to_earn": days})
                except Exception:
                    pass
                return row

            results_raw = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for r in pool.map(fetch_one, holdings.items()):
                    if r.get("earnings_date"):
                        results_raw.append(r)

            seen, results = set(), []
            for r in results_raw:
                if r["ticker"] not in seen:
                    seen.add(r["ticker"])
                    results.append(r)

            results.sort(key=lambda r: (
                0 if r.get("is_upcoming") else 1,
                r.get("days_to_earn", 9999)
            ))

            payload = {"ok": True, "results": results, "as_of": today.isoformat()}
            _cache_set(_earn_cache, payload)
            self._json(payload)

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_dividend_lookup(self, params):
        try:
            import yfinance as yf
            import warnings
            from datetime import date, datetime
            warnings.filterwarnings("ignore")

            ticker = (params.get("ticker", [None])[0] or "").upper().strip()
            shares = float(params.get("shares", ["0"])[0] or 0)
            if not ticker:
                return self._json_error(400, "Missing ticker")

            from covered_call_rec import normalize_ticker
            ticker = normalize_ticker(ticker)

            today = date.today()
            tk    = yf.Ticker(ticker)

            price = None
            try:
                hist  = tk.history(period="2d")
                price = _safe_float(hist["Close"].dropna().iloc[-1]) if not hist.empty else None
            except Exception:
                pass
            if price is None:
                return self._json({"ok": False, "error": f"Could not fetch price for {ticker}"})

            name = ticker
            try:
                info = tk.info or {}
                name = info.get("longName") or info.get("shortName") or ticker
            except Exception:
                info = {}

            last_amount = last_date = annual_rate = None
            try:
                divs = tk.dividends
                if not divs.empty:
                    last_amount = round(float(divs.iloc[-1]), 4)
                    last_date   = divs.index[-1].strftime("%Y-%m-%d")
                    if len(divs) >= 2:
                        intervals = [(divs.index[i] - divs.index[i-1]).days
                                     for i in range(max(1, len(divs)-4), len(divs))]
                        avg_days  = sum(intervals) / len(intervals)
                        freq      = 4 if avg_days < 100 else (2 if avg_days < 250 else 1)
                        annual_rate = round(float(divs.iloc[-1]) * freq, 4)
            except Exception:
                pass

            ex_date = pay_date = None
            try:
                cal     = tk.calendar or {}
                raw_ex  = cal.get("Ex-Dividend Date")
                raw_pay = cal.get("Dividend Date")
                if hasattr(raw_ex,  "strftime"): ex_date  = raw_ex.strftime("%Y-%m-%d")
                if hasattr(raw_pay, "strftime"): pay_date = raw_pay.strftime("%Y-%m-%d")
            except Exception:
                pass
            if not ex_date and last_date:
                ex_date = last_date

            days_to_ex  = (datetime.strptime(ex_date, "%Y-%m-%d").date() - today).days if ex_date else None
            is_upcoming = days_to_ex is not None and days_to_ex >= 0

            try:
                tax_type = _classify_div_type(info, ticker)
            except Exception:
                tax_type = "qualified"

            div_yield     = round(annual_rate / price * 100, 2) if annual_rate and price else None
            total_payout  = round(last_amount * shares, 2) if last_amount and shares else None
            annual_income = round(annual_rate * shares, 2)  if annual_rate and shares else None

            self._json({
                "ok": True, "ticker": ticker, "name": name,
                "price": round(price, 2) if price else None,
                "shares": shares,
                "ex_div_date": ex_date, "pay_date": pay_date,
                "declared_amount": last_amount, "last_date": last_date,
                "annual_rate": annual_rate, "div_yield": div_yield,
                "total_payout": total_payout, "annual_income": annual_income,
                "days_to_ex": days_to_ex, "declared": is_upcoming, "tax_type": tax_type,
            })

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_dividends(self):
        try:
            import yfinance as yf
            import warnings
            from datetime import date, datetime
            warnings.filterwarnings("ignore")

            from covered_call_rec import load_holdings

            if _cache_valid(_div_cache, _DIV_CACHE_TTL):
                return self._json(_div_cache["data"])

            holdings = load_holdings()
            today    = date.today()

            def fetch_one(kv):
                ticker, meta = kv
                shares   = meta["shares"]
                avg_cost = meta["avg_cost"]
                row = {"ticker": ticker, "shares": shares}
                try:
                    tk    = yf.Ticker(ticker)
                    price = None
                    try:
                        hist  = tk.history(period="2d")
                        price = _safe_float(hist["Close"].dropna().iloc[-1]) if not hist.empty else None
                    except Exception:
                        pass
                    row["price"] = price

                    last_amount = last_date = annual_rate = None
                    try:
                        divs = tk.dividends
                        if not divs.empty:
                            last_amount = round(float(divs.iloc[-1]), 4)
                            last_date   = divs.index[-1].strftime("%Y-%m-%d")
                            if len(divs) >= 2:
                                intervals = [(divs.index[i] - divs.index[i-1]).days
                                             for i in range(max(1, len(divs)-4), len(divs))]
                                avg_days  = sum(intervals) / len(intervals)
                                freq = 4 if avg_days < 100 else (2 if avg_days < 250 else 1)
                                annual_rate = round(float(divs.iloc[-1]) * freq, 4)
                    except Exception:
                        pass

                    if not last_amount:
                        return row

                    ex_date = pay_date = None
                    try:
                        cal     = tk.calendar or {}
                        raw_ex  = cal.get("Ex-Dividend Date")
                        raw_pay = cal.get("Dividend Date")
                        if hasattr(raw_ex,  "strftime"): ex_date  = raw_ex.strftime("%Y-%m-%d")
                        if hasattr(raw_pay, "strftime"): pay_date = raw_pay.strftime("%Y-%m-%d")
                    except Exception:
                        pass
                    if not ex_date:
                        try:
                            info = tk.info or {}
                            ts   = info.get("exDividendDate")
                            if ts:
                                ex_date = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    if not ex_date and last_date:
                        ex_date = last_date

                    tax_type = "qualified"
                    try:
                        info     = tk.info or {}
                        tax_type = _classify_div_type(info, ticker)
                    except Exception:
                        pass

                    div_yield  = round(annual_rate / price * 100, 2) if annual_rate and price else None
                    yoc        = round(annual_rate / avg_cost * 100, 2) if annual_rate and avg_cost else None
                    days_to_ex = None
                    if ex_date:
                        days_to_ex = (datetime.strptime(ex_date, "%Y-%m-%d").date() - today).days
                    is_upcoming = days_to_ex is not None and days_to_ex >= 0

                    row.update({
                        "ex_div_date":     ex_date,
                        "pay_date":        pay_date,
                        "declared_amount": last_amount,
                        "annual_rate":     annual_rate,
                        "div_yield":       div_yield,
                        "yield_on_cost":   yoc,
                        "last_amount":     last_amount,
                        "last_date":       last_date,
                        "total_payout":    round(last_amount * shares, 2) if last_amount else None,
                        "annual_income":   round(annual_rate * shares, 2) if annual_rate else None,
                        "days_to_ex":      days_to_ex,
                        "declared":        is_upcoming,
                        "tax_type":        tax_type,
                    })
                except Exception as e:
                    row["error"] = str(e)
                return row

            results_raw = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for row in pool.map(fetch_one, holdings.items()):
                    if row and row.get("last_amount"):
                        results_raw.append(row)

            seen, results = set(), []
            for r in results_raw:
                if r["ticker"] not in seen:
                    seen.add(r["ticker"])
                    results.append(r)

            results.sort(key=lambda r: (
                0 if r.get("declared") else 1,
                r.get("days_to_ex") if r.get("days_to_ex") is not None else 9999,
                r["ticker"]
            ))

            payload = {"ok": True, "results": results, "as_of": today.isoformat()}
            _cache_set(_div_cache, payload)
            self._json(payload)

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_buffett_winners(self):
        try:
            db = PROJECT_DIR / "out" / "buffett.db"
            if not db.exists():
                return self._json({"ok": True, "winners": [], "meta": {}})

            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row

            winners = [dict(r) for r in conn.execute(
                "SELECT * FROM buffett_winners ORDER BY gross_margin DESC"
            )]
            meta = {
                row["key"]: row["value"]
                for row in conn.execute("SELECT key, value FROM buffett_meta")
            }
            cache_count = conn.execute(
                "SELECT COUNT(*) FROM buffett_cache"
            ).fetchone()[0]

            # First-seen date per winner from history table
            try:
                first_seen = {
                    row[0]: row[1]
                    for row in conn.execute(
                        "SELECT ticker, MIN(scan_date) FROM buffett_winner_history GROUP BY ticker"
                    )
                }
            except Exception:
                first_seen = {}

            conn.close()

            for w in winners:
                w["first_seen"] = first_seen.get(w["ticker"])

            scan_running = False
            lock = PROJECT_DIR / "out" / "buffett_screener.lock"
            if lock.exists():
                try:
                    pid = int(lock.read_text().strip())
                    os.kill(pid, 0)
                    scan_running = True
                except (ProcessLookupError, ValueError, OSError):
                    pass

            eta_seconds = None
            if scan_running and cache_count > 0 and meta.get("scan_started") and meta.get("total_tickers"):
                from datetime import datetime as _dt
                try:
                    started = _dt.strptime(meta["scan_started"], "%Y-%m-%d %H:%M:%S")
                    elapsed = (_dt.now() - started).total_seconds()
                    total   = int(meta["total_tickers"])
                    rate    = cache_count / elapsed
                    if rate > 0:
                        eta_seconds = int((total - cache_count) / rate)
                except Exception:
                    pass

            self._json({"ok": True, "winners": winners, "meta": meta,
                        "cache_count": cache_count, "scan_running": scan_running,
                        "eta_seconds": eta_seconds})
        except Exception as e:
            self._json_error(500, str(e))

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, code, msg):
        body = json.dumps({"ok": False, "error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("localhost", PORT), Handler)

url = f"http://localhost:{PORT}/out/dashboard.html"
if sys.stdout.isatty():
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Investment Dashboard → {url}")
    print("Press Ctrl+C to stop.\n")

try:
    server.serve_forever()
except KeyboardInterrupt:
    server.shutdown()
