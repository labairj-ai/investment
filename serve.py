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

import collections
import csv as _csv_mod
import datetime
import json
import math
import http.server
import os
import smtplib
import sqlite3
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import ollama_client

_div_cache      = {"data": None, "ts": 0}
_earn_cache     = {"data": None, "ts": 0}
_timeline_cache = {"data": None, "ts": 0}
_DIV_CACHE_TTL      = 3600
_EARN_CACHE_TTL     = 3600
_TIMELINE_CACHE_TTL = 3600
_data_cache_lock = threading.Lock()  # guards _div/_earn/_timeline caches

_cc_analyze_cache = {}   # {ticker: {"result": obj, "ts": float}}
_cc_ai_cache      = {}   # {ticker: {"insight": dict, "model": str, "ts": float}}
_CC_ANALYZE_TTL   = 300  # 5 minutes — shared between recommendations and AI
_CC_AI_TTL        = 1800 # 30 minutes — reuse AI insight within a session
_cc_analyze_lock  = threading.Lock()
_cc_ai_lock       = threading.Lock()

# Timestamp until which we report scan_running=True even before the lock
# file appears — covers the subprocess startup latency (~30-60 s).
_scan_launching_until = 0.0


def _cache_valid(cache, ttl):
    with _data_cache_lock:
        if cache["data"] is None or (time.time() - cache["ts"]) > ttl:
            return False
        from datetime import date
        return cache.get("date") == date.today().isoformat()


def _cache_set(cache, data):
    with _data_cache_lock:
        from datetime import date
        cache["data"] = data
        cache["ts"]   = time.time()
        cache["date"] = date.today().isoformat()


def _cc_analyze_get(ticker):
    with _cc_analyze_lock:
        entry = _cc_analyze_cache.get(ticker)
        if entry and time.time() - entry["ts"] < _CC_ANALYZE_TTL:
            return entry["result"]
    return None


def _cc_analyze_set(ticker, result):
    with _cc_analyze_lock:
        _cc_analyze_cache[ticker] = {"result": result, "ts": time.time()}


def _cc_ai_get(ticker):
    with _cc_ai_lock:
        entry = _cc_ai_cache.get(ticker)
        if entry and time.time() - entry["ts"] < _CC_AI_TTL:
            return entry
    return None


def _cc_ai_set(ticker, insight, model):
    with _cc_ai_lock:
        _cc_ai_cache[ticker] = {"insight": insight, "model": model, "ts": time.time()}


# ── Analysis job store ────────────────────────────────────────────────────────
# Jobs run in background threads; browser polls /api/analysis-job/<id> until done.
# This decouples the HTTP connection lifetime from the analysis duration so phone
# locks and app switches no longer abort the run.
_jobs: dict = {}
_jobs_lock = threading.Lock()
_JOB_TTL = 600  # expire completed jobs after 10 minutes

_chat_active: set = set()  # tracks in-flight chat streams by "context_type:ticker"
_ai_insight_lock = threading.Lock()
_ai_insight_generating = False  # True while background generation is running

_news_summary_lock = threading.Lock()
_news_summary_generating = False


def _job_create(kind: str) -> str:
    job_id = uuid.uuid4().hex[:16]
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running", "kind": kind,
            "progress": "", "result": None, "error": None, "ts": time.time(),
        }
        cutoff = time.time() - _JOB_TTL
        stale = [k for k, v in _jobs.items() if v["ts"] < cutoff and v["status"] != "running"]
        for k in stale:
            del _jobs[k]
    return job_id


def _job_update(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
            _jobs[job_id]["ts"] = time.time()


def _job_get(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


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


def _next_business_day(d, offset=1):
    """Return d + offset business days (Mon–Fri)."""
    from datetime import timedelta
    result = d
    added  = 0
    while added < offset:
        result += timedelta(days=1)
        if result.weekday() < 5:
            added += 1
    return result


def _sa_lookup_pay_date(sa_map: dict, ex_date: str) -> str | None:
    """Return SA pay date for ex_date, tolerating a ±1-day offset (Yahoo vs SA often disagree)."""
    from datetime import datetime as _dt, timedelta
    if ex_date in sa_map:
        return sa_map[ex_date]
    ex_dt = _dt.strptime(ex_date, "%Y-%m-%d").date()
    for delta in (-1, 1):
        key = (ex_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
        if key in sa_map:
            return sa_map[key]
    return None


def _fetch_sa_pay_date(ticker):
    """Scrape stockanalysis.com dividend history and return {ex_date: pay_date}.
    Tries the stocks URL first, falls back to the ETF URL."""
    import urllib.request, re
    slug = ticker.lower()
    for url in (
        f"https://stockanalysis.com/stocks/{slug}/dividend/",
        f"https://stockanalysis.com/etf/{slug}/dividend/",
    ):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "*/*",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode()
            mapping = {}
            for m in re.finditer(r'\{dt:"(\d{4}-\d{2}-\d{2})"[^}]+pay:"(\d{4}-\d{2}-\d{2})"', html):
                mapping[m.group(1)] = m.group(2)
            if mapping:
                return mapping
        except Exception:
            pass
    return {}


# Tickers that are mutual funds with no public pay-date API.
# For these we estimate: pay ≈ ex_date + 1 business day (Vanguard/Fidelity practice).
_MUTUAL_FUND_TICKERS = {"VTSAX", "VFIAX", "VVIAX", "VTMGX", "VGTSX", "FSPTX", "FXAIX", "FSKAX"}


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


def _normalize_ticker(t: str) -> str:
    t = str(t).strip().upper().lstrip("$")
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            t = f"{left}-{right}"
    return t


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
            close_type           TEXT,
            net_premium          REAL,
            notes                TEXT
        )
    """)
    # Migrate existing tables that predate these columns
    for col, typedef in [
        ("close_type",    "TEXT"),
        ("net_premium",   "REAL"),
        ("current_mark",  "REAL"),
        ("prev_mark",     "REAL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE cc_positions ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass
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
        try:
            lt_cutoff = purchase_dt.replace(year=purchase_dt.year + 1)
        except ValueError:  # Feb 29 purchase in non-leap target year → Mar 1
            lt_cutoff = purchase_dt.replace(year=purchase_dt.year + 1, month=3, day=1)
        term        = "LT" if sell_dt > lt_cutoff else "ST"
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


# ── Daily newsletter scheduler ────────────────────────────────────────────────


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
    Background thread: runs the unified weekly newsletter + dashboard once per week on Saturday at 7 AM ET.
    The newsletter itself handles portfolio snapshot, layer drift, earnings/ex-div events,
    and the judgment rubric in a single email.
    """
    import socket, subprocess
    if socket.gethostname() != "optiplex":
        print(f"[Scheduler] Not on production host ({socket.gethostname()!r}) — newsletter disabled.")
        return
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ                = ZoneInfo("America/New_York")
    FLAG              = PROJECT_DIR / "out" / "last_run_date.txt"
    REFRESH_FLAG      = PROJECT_DIR / "out" / "last_refresh_date.txt"
    REFRESH_5PM_FLAG  = PROJECT_DIR / "out" / "last_refresh_5pm_date.txt"
    MACRO_SCORE_FLAG  = PROJECT_DIR / "out" / "last_macro_score_date.txt"
    VENV_PY           = PROJECT_DIR / "venv" / "bin" / "python3"
    LOG               = PROJECT_DIR / "out" / "newsletter.log"

    def already_ran(today):
        try:
            return FLAG.read_text().strip() == today
        except Exception:
            return False

    def already_refreshed(today):
        try:
            return REFRESH_FLAG.read_text().strip() == today
        except Exception:
            return False

    def already_refreshed_5pm(today):
        try:
            return REFRESH_5PM_FLAG.read_text().strip() == today
        except Exception:
            return False

    def already_macro_scored(today):
        try:
            return MACRO_SCORE_FLAG.read_text().strip() == today
        except Exception:
            return False

    def run_macro_scores(today):
        import portfolio_ai as _pai
        with open(LOG, "a") as lf:
            lf.write(f"\n=== MACRO SCORES {_dt.now(TZ)} ===\n")
            lf.write("[PortfolioAI] Running Saturday macro scores for holdings…\n")
            try:
                _pai._init_ai_tables()
                _pai.generate_holding_macro_scores(force=True)
                MACRO_SCORE_FLAG.write_text(today)
                lf.write("[PortfolioAI] Macro scores done.\n")
                print(f"[Scheduler] Macro scores done for {today}.")
            except Exception as _e:
                lf.write(f"[PortfolioAI] Macro scores error: {_e}\n")
                print(f"[Scheduler] Macro scores failed: {_e}")

    def run(send_email=True):
        cmd = [str(VENV_PY), str(PROJECT_DIR / "send_newsletter_main.py")]
        if not send_email:
            cmd.append("--no-email")
        with open(LOG, "a") as lf:
            lf.write(f"\n=== SCHEDULER {_dt.now(TZ)} ===\n")
            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_DIR),
                capture_output=True, text=True, timeout=300
            )
            lf.write(result.stdout or "")
            if result.returncode != 0:
                lf.write(f"ERROR (send_newsletter_main.py): {result.stderr}\n")
                return False
            if send_email:
                # Mark sent before dashboard — prevents duplicate email if dashboard fails
                FLAG.write_text(today)
            lf.write("[LayerAI] Running nightly layer rankings…\n")
            try:
                _run_layer_ai_rankings()
                lf.write("[LayerAI] Done.\n")
            except Exception as _e:
                lf.write(f"[LayerAI] Error: {_e}\n")
            lf.write("[NewsRefresh] Fetching news summaries before insight…\n")
            try:
                import csv as _csv
                import news_fetcher as _nf
                import portfolio_ai as _pai
                _tickers = []
                _csv_path = PROJECT_DIR / "holdings.csv"
                if _csv_path.exists():
                    with open(_csv_path, newline="") as _f:
                        for _row in _csv.DictReader(_f):
                            _t = str(_row.get("Stock", "")).strip().upper()
                            if _t:
                                _tickers.append(_t)
                _tickers = list(dict.fromkeys(_tickers))
                _nf.fetch(_tickers, force=True)
                _pai.generate_news_summaries(force=True)
                lf.write("[NewsRefresh] News summaries done.\n")
            except Exception as _e:
                lf.write(f"[NewsRefresh] Failed (insight will run without news findings): {_e}\n")
            lf.write("[PortfolioAI] Generating daily insight + macro scores…\n")
            try:
                _pai._init_ai_tables()
                _insight = _pai.generate_daily_insight(force=True)
                if "error" not in _insight:
                    lf.write("[PortfolioAI] Daily insight done.\n")
                else:
                    lf.write(f"[PortfolioAI] Insight error: {_insight.get('error')}\n")
                _pai.generate_holding_macro_scores(force=False)
                lf.write("[PortfolioAI] Macro scores done.\n")
            except Exception as _e:
                lf.write(f"[PortfolioAI] Error: {_e}\n")
            result = subprocess.run(
                [str(VENV_PY), str(PROJECT_DIR / "generate_dashboard.py")],
                cwd=str(PROJECT_DIR),
                capture_output=True, text=True, timeout=300
            )
            lf.write(result.stdout or "")
            if result.returncode != 0:
                lf.write(f"ERROR (generate_dashboard.py): {result.stderr}\n")
        return True

    while True:
        now   = _dt.now(TZ)
        today = now.date().isoformat()
        if now.weekday() == 5 and now.hour >= 7 and not already_ran(today):
            print(f"[Scheduler] Running newsletter for {today}…")
            if run(send_email=True):
                print(f"[Scheduler] Done for {today}.")
                try:
                    _backup_data()
                except Exception as exc:
                    print(f"[Backup] Exception: {exc}")
            else:
                print(f"[Scheduler] Failed — will retry in 30 min.")
        # Macro scores: always run Saturday at 1 AM ET regardless of newsletter flag
        if now.weekday() == 5 and now.hour >= 1 and not already_macro_scored(today):
            run_macro_scores(today)
        elif already_ran(today) and now.hour >= 17 and not already_refreshed_5pm(today):
            print(f"[Scheduler] Running 5 PM price refresh for {today}…")
            if run(send_email=False):
                REFRESH_5PM_FLAG.write_text(today)
                print(f"[Scheduler] 5 PM refresh done for {today}.")
            else:
                print(f"[Scheduler] 5 PM refresh failed — will retry in 30 min.")
        elif already_ran(today) and now.hour >= 21 and now.minute >= 30 and not already_refreshed(today):
            print(f"[Scheduler] Running 9:30 PM OTC price refresh for {today}…")
            if run(send_email=False):
                REFRESH_FLAG.write_text(today)
                print(f"[Scheduler] 9:30 PM refresh done for {today}.")
            else:
                print(f"[Scheduler] 9:30 PM refresh failed — will retry in 30 min.")
        time.sleep(1800)


threading.Thread(target=_run_daily, daemon=True).start()


# ── Scheduled news refresh (6 AM, 12 PM, 5 PM ET, Mon–Fri) ──────────────────

def _run_news_refresh():
    """
    Background thread: refresh holding-news headlines + AI summaries at
    6 AM, 12 PM, and 5 PM ET on weekdays only.
    Checks every 10 minutes; each slot fires once per calendar day.
    """
    import socket
    if socket.gethostname() != "optiplex":
        print(f"[NewsRefresh] Not on production host ({socket.gethostname()!r}) — disabled.")
        return
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ  = ZoneInfo("America/New_York")
    LOG = PROJECT_DIR / "out" / "news_refresh.log"

    # (label, target_hour) — fires when now.hour >= target_hour
    SLOTS = [("06", 6), ("12", 12), ("17", 17)]
    _done = set()  # {(date_str, label)} already run this server session

    def _do_refresh(label, today):
        global _news_summary_generating
        LOG.parent.mkdir(exist_ok=True)
        print(f"[NewsRefresh] {label}:00 ET refresh starting for {today}…")
        try:
            import csv as _csv
            import news_fetcher
            import portfolio_ai as _pai

            # Load current tickers from holdings.csv
            tickers = []
            csv_path = PROJECT_DIR / "holdings.csv"
            if csv_path.exists():
                with open(csv_path, newline="") as f:
                    for row in _csv.DictReader(f):
                        t = str(row.get("Stock", "")).strip().upper()
                        if t:
                            tickers.append(t)
            tickers = list(dict.fromkeys(tickers))

            # Step 1: fresh headline + excerpt fetch (force bypasses 30-min cache)
            news_fetcher.fetch(tickers, force=True)

            # Step 2: AI summaries — respect the lock used by API handlers
            with _news_summary_lock:
                already = _news_summary_generating
                if not already:
                    _news_summary_generating = True

            if already:
                print(f"[NewsRefresh] {label}: summary already generating, skipping AI step.")
            else:
                try:
                    _pai.generate_news_summaries(force=True)
                except Exception as e:
                    print(f"[NewsRefresh] {label} summary error: {e}")
                    with open(LOG, "a") as lf:
                        lf.write(f"[{_dt.now(TZ)}] {label}:00 summary FAILED: {e}\n")
                finally:
                    with _news_summary_lock:
                        _news_summary_generating = False

            # Step 3: after morning news summaries, generate the daily portfolio insight
            if label == "06":
                print(f"[NewsRefresh] 06: generating daily portfolio insight…")
                try:
                    _insight = _pai.generate_daily_insight(force=False)
                    if "error" in _insight:
                        print(f"[NewsRefresh] 06: insight error: {_insight['error']}")
                        with open(LOG, "a") as lf:
                            lf.write(f"[{_dt.now(TZ)}] 06:00 insight FAILED: {_insight['error']}\n")
                    else:
                        print(f"[NewsRefresh] 06: daily portfolio insight done.")
                        with open(LOG, "a") as lf:
                            lf.write(f"[{_dt.now(TZ)}] 06:00 insight done.\n")
                except Exception as _e:
                    print(f"[NewsRefresh] 06: insight exception: {_e}")
                    with open(LOG, "a") as lf:
                        lf.write(f"[{_dt.now(TZ)}] 06:00 insight EXCEPTION: {_e}\n")

            with open(LOG, "a") as lf:
                lf.write(f"[{_dt.now(TZ)}] {label}:00 refresh done — {len(tickers)} tickers\n")
            print(f"[NewsRefresh] {label}:00 refresh done.")
        except Exception as exc:
            print(f"[NewsRefresh] {label} refresh failed: {exc}")
            with open(LOG, "a") as lf:
                lf.write(f"[{_dt.now(TZ)}] {label}:00 refresh FAILED: {exc}\n")

    while True:
        now     = _dt.now(TZ)
        today   = now.date().isoformat()
        weekday = now.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
        if weekday < 5:
            for label, target_hour in SLOTS:
                key = (today, label)
                if key not in _done and now.hour >= target_hour:
                    _done.add(key)
                    _do_refresh(label, today)
        time.sleep(600)  # check every 10 minutes


threading.Thread(target=_run_news_refresh, daemon=True).start()


# ── Nightly Buffett screener (2 AM ET) ───────────────────────────────────────
def _auto_ai_analyze_winners(log_file=None):
    """After a successful scan, generate AI analysis for any winner missing it or older than 30 days."""
    import json as _json
    STALE_DAYS    = 6   # refresh before the 7-day on-demand cache expires
    NIGHTLY_LIMIT = 200  # Mac Studio M1 Max handles this comfortably before 7:15 AM newsletter
    db = PROJECT_DIR / "out" / "buffett.db"
    if not db.exists():
        return
    if not ollama_client.available():
        msg = "[Screener] Ollama not available — skipping auto AI analysis."
        print(msg)
        if log_file:
            log_file.write(msg + "\n")
        return

    try:
        conn = sqlite3.connect(str(db), timeout=30)
        conn.row_factory = sqlite3.Row
        winners = [dict(r) for r in conn.execute("SELECT * FROM buffett_winners ORDER BY quality_score DESC")]
        conn.close()
    except Exception as e:
        print(f"[Screener] Auto-AI: DB read error: {e}")
        return

    cutoff = (datetime.datetime.now() - datetime.timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    stale = [
        w for w in winners
        if not w.get("ai_analysis") or (w.get("ai_analysis_at") or "") < cutoff
    ]
    # Always process winners with no analysis first, then oldest-refreshed ones
    stale.sort(key=lambda w: (0 if not w.get("ai_analysis") else 1, -(w.get("quality_score") or 0)))
    to_analyze = stale[:NIGHTLY_LIMIT]

    if not to_analyze:
        print("[Screener] Auto-AI: all winners have fresh analysis, skipping.")
        return

    print(f"[Screener] Auto-AI: analyzing {len(to_analyze)}/{len(stale)} stale winner(s) (capped at {NIGHTLY_LIMIT}/night)…")
    if log_file:
        log_file.write(f"[Auto-AI] Analyzing {len(to_analyze)}/{len(stale)} stale winner(s)…\n")

    for w in to_analyze:
        ticker = w["ticker"]
        try:
            div_pct = f"{w['dividend_yield']:.1f}%" if w.get("dividend_yield") else "None"
            mcap = w.get("market_cap") or 0
            mcap_fmt = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else (f"${mcap/1e6:.0f}M" if mcap else "N/A")
            trap_flags = []
            try:
                trap_flags = _json.loads(w.get("value_trap_flags") or "[]")
            except Exception:
                pass
            trap_flags_text = "; ".join(trap_flags) if trap_flags else "none"

            prompt = f"""You are a stock analyst. Analyze this Buffett screener winner. Return ONLY valid JSON, no other text.

{w.get('company', ticker)} ({ticker}) — {w.get('sector', '?')} / {w.get('industry', '?')}
Price: ${w.get('price', 0):.2f} | Market Cap: {mcap_fmt} | Exchange: {w.get('exchange', '?')}
Layer assignment: {w.get('layer_rec', '?')} — {w.get('layer_reason', '?')}
Value Trap Risk: {w.get('value_trap_risk', 'unknown')}
Trap flags: {trap_flags_text}

Quality Metrics (passed Buffett screen):
  Gross Margin: {w.get('gross_margin', 0):.1f}%  | Net Income Margin: {w.get('net_income_margin', 0):.1f}%
  Interest/OpIncome: {w.get('interest_margin', 0):.1f}% | CapEx/NetIncome: {w.get('capex_margin', 0):.1f}%
  Quality Score: {w.get('quality_score', 'N/A')}/100

Valuation:
  P/E: {w.get('pe_ratio') or 'N/A'}x | P/FCF: {w.get('p_fcf') or 'N/A'}x | EV/EBITDA: {w.get('ev_ebitda') or 'N/A'}x
  Dividend Yield: {div_pct}

Return this JSON structure:
{{
  "thesis": "<2-sentence investment case for buying this stock now>",
  "moat_strength": "<strong|moderate|weakening>",
  "moat_note": "<one sentence on competitive advantage>",
  "valuation": "<cheap|fair|stretched>",
  "valuation_note": "<one sentence on P/E and FCF vs quality>",
  "top_risk": "<single most important risk to the thesis>",
  "conviction": <integer 1 to 5>,
  "layer_fit": "<one sentence on why this fits or does not fit layer {w.get('layer_rec', '?')}>"
}}"""

            full_text = ""
            for tok in ollama_client.stream_generate(prompt, model=ollama_client.DEFAULT_MODEL, num_predict=700):
                full_text += tok

            dec = _json.JSONDecoder()
            try:
                start = full_text.index("{")
            except ValueError:
                raise ValueError(f"LLM returned no JSON object. Output: {full_text[:200]!r}")
            analysis, _ = dec.raw_decode(full_text, start)

            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn2 = sqlite3.connect(str(db), timeout=10)
            try:
                conn2.execute(
                    "UPDATE buffett_winners SET ai_analysis=?, ai_analysis_at=? WHERE ticker=?",
                    (_json.dumps(analysis), now_str, ticker)
                )
                conn2.commit()
            finally:
                conn2.close()
            print(f"[Screener] Auto-AI: {ticker} done (conviction={analysis.get('conviction')})")
            if log_file:
                log_file.write(f"[Auto-AI] {ticker}: conviction={analysis.get('conviction')}\n")
        except Exception as e:
            print(f"[Screener] Auto-AI: {ticker} failed — {e}")
            if log_file:
                log_file.write(f"[Auto-AI] {ticker}: ERROR — {e}\n")
        time.sleep(1)  # brief pause between Ollama calls


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
            FLAG.write_text(today)   # mark today before running — prevents retries on crash
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
                        print(f"[Screener] Done for {today}.")
                        _auto_ai_analyze_winners(lf)
            except Exception as exc:
                print(f"[Screener] Exception: {exc}")
        time.sleep(1800)


threading.Thread(target=_run_screener, daemon=True).start()


# ── Weekly financials refresh (Sunday 1 AM ET) ───────────────────────────────

def _run_financials_refresh():
    """Refresh 5-year financial statements + estimates for all stock holdings once a week."""
    import socket
    if socket.gethostname() != "optiplex":
        return
    import csv as _csv
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ   = ZoneInfo("America/New_York")
    FLAG = PROJECT_DIR / "out" / "last_financials_refresh.txt"

    def already_ran_this_week():
        try:
            from datetime import date as _date, timedelta as _td
            last = _date.fromisoformat(FLAG.read_text().strip())
            # Consider "this week" = within 6 days
            return (_date.today() - last).days < 6
        except Exception:
            return False

    while True:
        now = _dt.now(TZ)
        if now.weekday() == 6 and now.hour == 1 and not already_ran_this_week():
            try:
                print("[Financials] Starting weekly refresh…")
                import financials_fetcher
                holdings_path = PROJECT_DIR / "holdings.csv"
                tickers = []
                with open(holdings_path, newline="") as f:
                    for row in _csv.DictReader(f):
                        t = row.get("Stock", "").strip().upper()
                        if t:
                            tickers.append(t)
                tickers = list(dict.fromkeys(tickers))
                financials_fetcher.fetch_all(tickers, force=False)
                FLAG.write_text(_dt.now(TZ).date().isoformat())
                print("[Financials] Weekly refresh complete.")
            except Exception as e:
                print(f"[Financials] Refresh failed: {e}")
        time.sleep(1800)


threading.Thread(target=_run_financials_refresh, daemon=True).start()


# ── Background analysis runners ───────────────────────────────────────────────

def _run_buffett_job(job_id: str, ticker_symbol: str, mode: str) -> None:
    """Runs yfinance Buffett analysis in a background thread; writes result to job store."""
    try:
        import yfinance as yf
        import pandas as pd

        _job_update(job_id, progress="Fetching financial data…")
        stock = yf.Ticker(ticker_symbol)

        if mode == "ttm":
            income_stmt   = stock.quarterly_financials
            balance_sheet = stock.quarterly_balance_sheet
            cash_flow     = stock.quarterly_cashflow
        else:
            income_stmt   = stock.financials
            balance_sheet = stock.balance_sheet
            cash_flow     = stock.cashflow

        if income_stmt.empty:
            _job_update(job_id, status="error", error=f"No financial data found for {ticker_symbol}")
            return

        def get_val(df, keys, col=0):
            if isinstance(keys, str):
                keys = [keys]
            for key in keys:
                if key in df.index:
                    try:
                        if col < df.shape[1]:
                            v = df.iloc[df.index.get_loc(key), col]
                            if not pd.isna(v):
                                return float(v)
                    except Exception:
                        pass
            return 0.0

        def get_flow(df, keys):
            if mode != "ttm":
                return get_val(df, keys, 0)
            if isinstance(keys, str):
                keys = [keys]
            for key in keys:
                if key in df.index:
                    try:
                        n = min(4, df.shape[1])
                        vals = [float(df.iloc[df.index.get_loc(key), i])
                                for i in range(n)
                                if not pd.isna(df.iloc[df.index.get_loc(key), i])]
                        if vals:
                            return sum(vals)
                    except Exception:
                        pass
            return 0.0

        def prior_col(df):
            if mode == "ttm":
                return 4 if df.shape[1] > 4 else (1 if df.shape[1] > 1 else 0)
            return 1

        _job_update(job_id, progress="Computing Buffett metrics…")

        revenue         = get_flow(income_stmt, ["Total Revenue", "Revenue"])
        gross_profit    = get_flow(income_stmt, ["Gross Profit", "Net Interest Income"])
        sga             = get_flow(income_stmt, ["Selling General And Administration", "Operating Expense"])
        rnd             = get_flow(income_stmt, "Research And Development")
        depreciation    = get_flow(cash_flow,  ["DepreciationAndAmortization", "Depreciation"])
        if depreciation == 0:
            depreciation = get_flow(income_stmt, "Reconciled Depreciation")
        interest_exp    = get_flow(income_stmt, ["Interest Expense", "Interest Expense Non Operating"])
        op_income       = get_flow(income_stmt, ["Operating Income", "Operating Profit"])
        net_income      = get_flow(income_stmt, ["Net Income", "Net Income Common Stockholders"])
        eps_current     = get_val(income_stmt,   "Basic EPS", 0)
        eps_prev        = get_val(income_stmt,   "Basic EPS", prior_col(income_stmt))
        cash            = get_val(balance_sheet, ["Cash And Cash Equivalents", "Cash Financial"])
        total_debt      = get_val(balance_sheet, ["Total Debt", "Long Term Debt"])
        equity          = get_val(balance_sheet, ["Stockholders Equity", "Total Equity Gross Minority Interest"])
        treasury_stock  = get_val(balance_sheet, "Treasury Stock")
        preferred_stock = get_val(balance_sheet, "Preferred Stock")
        re_cur          = get_val(balance_sheet, "Retained Earnings", 0)
        re_1            = get_val(balance_sheet, "Retained Earnings", prior_col(balance_sheet))
        capex           = abs(get_flow(cash_flow, ["Capital Expenditure", "Capital Expenditures"]))

        is_financial = (gross_profit == 0 and revenue > 0)
        results = []

        def check(metric, value_str, criteria, passed, note=""):
            results.append({"Metric": metric, "Value": value_str, "Criteria": criteria,
                             "Result": "PASS" if passed else "FAIL", "Note": note})

        gm = (gross_profit / revenue) if revenue else 0
        if is_financial:
            results.append({"Metric": "Gross Margin", "Value": "N/A", "Criteria": "> 40%",
                             "Result": "N/A", "Note": "Bank / Insurer"})
            gp_valid = False
        else:
            check("Gross Margin", f"{gm:.1%}", "> 40%", gm > 0.40)
            gp_valid = gross_profit > 0

        if gp_valid:
            check("SG&A Margin",         f"{sga/gross_profit:.1%}",         "< 30%", sga/gross_profit < 0.30)
            check("R&D Margin",          f"{rnd/gross_profit:.1%}",         "< 30%", rnd/gross_profit < 0.30)
            check("Depreciation Margin", f"{depreciation/gross_profit:.1%}","< 10%", depreciation/gross_profit < 0.10)
        else:
            for m in ["SG&A Margin", "R&D Margin", "Depreciation Margin"]:
                check(m, "Neg/Zero GP", m.split()[0], False)

        if op_income > 0:
            check("Interest Margin", f"{interest_exp/op_income:.1%}", "< 15%", interest_exp/op_income < 0.15)
        else:
            check("Interest Margin", "Neg Op Inc", "< 15%", False, "Op Income negative")

        nm = (net_income / revenue) if revenue else 0
        check("Net Income Margin", f"{nm:.1%}", "> 20%", nm > 0.20)
        check("EPS Growth", f"${eps_current:.2f} vs ${eps_prev:.2f}", "Trend Up", eps_current > eps_prev)
        check("Retained Earnings", "Trending up" if re_cur > re_1 else "Declining", "Growth", re_cur > re_1)
        check("Cash vs Debt", f"${cash/1e9:.2f}B vs ${total_debt/1e9:.2f}B", "Cash > Debt", cash > total_debt)

        if equity > 0:
            de = total_debt / equity
            check("Debt / Equity", f"{de:.2f}", "< 0.80", de < 0.80)
        else:
            check("Debt / Equity", "Neg Equity", "< 0.80", False)

        check("Preferred Stock", f"${preferred_stock/1e6:.1f}M" if preferred_stock else "$0", "None", preferred_stock == 0)
        check("Share Buybacks", f"${treasury_stock/1e6:.1f}M" if treasury_stock else "$0", "Present", treasury_stock != 0)

        if net_income > 0:
            cm = capex / net_income
            check("CapEx / Net Income", f"{cm:.1%}", "< 25%", cm < 0.25)
        else:
            check("CapEx / Net Income", "Neg Net Inc", "< 25%", False, "Net income negative")

        try:
            price = float(stock.history(period="1d")["Close"].iloc[-1])
        except Exception:
            price = 0.0

        score = sum(1 for r in results if r["Result"] == "PASS")

        period_label = None
        try:
            col = income_stmt.columns[0]
            col_dt = pd.Timestamp(col)
            yr = col_dt.year
            mo = col_dt.strftime("%b")
            day = col_dt.strftime("%d").lstrip("0")
            if mode == "ttm":
                qtr = (col_dt.month - 1) // 3 + 1
                period_label = f"TTM as of Q{qtr} {yr} (ended {mo} {day}, {yr})"
                n_q = len(income_stmt.columns)
                quarters_used = min(4, n_q)
                period_label += f" · {quarters_used}Q summed"
            else:
                if col_dt.month == 12:
                    period_label = f"FY {yr} annual (Dec {day}, {yr})"
                else:
                    period_label = f"FY {yr} annual (fiscal year ended {mo} {day}, {yr})"
                n_years = len(income_stmt.columns)
                if n_years > 1:
                    period_label += f" · most recent of {n_years} available"
        except Exception:
            period_label = None

        _job_update(job_id, status="done", result={
            "ok": True, "ticker": ticker_symbol, "price": price,
            "score": score, "max_score": len(results), "results": results,
            "period_label": period_label,
        })
    except Exception as e:
        _job_update(job_id, status="error", error=str(e))


def _run_cc_ai_job(job_id: str, ticker: str) -> None:
    """Runs CC AI analysis (Ollama) in a background thread; streams tokens into progress field."""
    try:
        if not ollama_client.available():
            _job_update(job_id, status="error",
                        error="Ollama not available — make sure ollama is running on the server")
            return

        from covered_call_rec import analyze, load_holdings, ai_context
        _job_update(job_id, progress="Loading holdings…")
        holdings = load_holdings()
        if ticker not in holdings:
            _job_update(job_id, status="error", error=f"{ticker} not found in holdings")
            return
        h = holdings[ticker]

        cached_ai = _cc_ai_get(ticker)
        if cached_ai:
            _job_update(job_id, status="done", result={
                "ok": True, "ticker": ticker,
                "insight": cached_ai["insight"], "model": cached_ai["model"], "cached": True,
            })
            return

        result = _cc_analyze_get(ticker)
        if result is None:
            _job_update(job_id, progress="Fetching option chain…")
            result = analyze(ticker, h["avg_cost"], h["shares"])
            if result is not None:
                _cc_analyze_set(ticker, result)
        if result is None or result["recs"].empty:
            _job_update(job_id, status="error", error="No qualifying option contracts found to analyze")
            return

        prompt = ai_context(ticker, result, h["shares"], h.get("layer", "?"))
        _job_update(job_id, progress="Sending to AI…")

        full_text = ""
        for tok in ollama_client.stream_generate(prompt):
            full_text += tok
            _job_update(job_id, progress=full_text)

        try:
            _dec = json.JSONDecoder()
            _start = full_text.index('{')
            insight, _ = _dec.raw_decode(full_text, _start)
        except (ValueError, json.JSONDecodeError):
            _job_update(job_id, status="error", error="AI returned malformed JSON — try again")
            return

        def _to_str(v):
            if isinstance(v, str):   return v
            if isinstance(v, dict):  return " ".join(str(x) for x in v.values())
            if isinstance(v, list):  return "; ".join(str(x) for x in v)
            return str(v)

        for field in ("iv_context", "roll_strategy", "timing_advice"):
            if field in insight:
                insight[field] = _to_str(insight[field])

        # Overwrite strike/expiration from actual contract data — the model
        # often leaves the placeholder value (0.00) in the recommendation object.
        _rec = insight.get("recommendation", {})
        _rank = max(0, int(_rec.get("rank", 1)) - 1)
        if _rank < len(result["recs"]):
            _row = result["recs"].iloc[_rank]
            _rec["strike"]     = float(_row["strike"])
            _rec["expiration"] = str(_row["expiration"])
            insight["recommendation"] = _rec

        _cc_ai_set(ticker, insight, ollama_client.DEFAULT_MODEL)
        _job_update(job_id, status="done", result={
            "ok": True, "ticker": ticker,
            "insight": insight, "model": ollama_client.DEFAULT_MODEL,
        })
    except Exception as e:
        _job_update(job_id, status="error", error=str(e))


def _run_layer_ai_rankings() -> None:
    """Run AI layer ranking for all active layers and persist ranks to DB. Called nightly."""
    db = PROJECT_DIR / "out" / "buffett.db"
    if not db.exists() or not ollama_client.available():
        return
    import csv as _csv
    try:
        conn = sqlite3.connect(str(db), timeout=10)
        conn.row_factory = sqlite3.Row
        active_layers = [r[0] for r in conn.execute(
            "SELECT DISTINCT layer_rec FROM buffett_winners WHERE layer_rec IS NOT NULL ORDER BY layer_rec"
        ).fetchall()]
        conn.close()
    except Exception:
        return

    layer_names = {1: "Structural Ballast", 2: "Cash-Flow Engine", 3: "Compounder",
                   4: "Convexity/Optionality", 5: "Shock Absorber"}

    for layer_num in active_layers:
        try:
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                "SELECT ticker, company, sector, gross_margin, net_income_margin, "
                "pe_ratio, p_fcf, ev_ebitda, dividend_yield, quality_score, value_trap_risk "
                "FROM buffett_winners WHERE layer_rec=? AND value_trap_risk='low' "
                "ORDER BY quality_score DESC LIMIT 5",
                (layer_num,)
            ).fetchall()]
            conn.close()
            if not rows:
                continue

            layer_name = layer_names.get(layer_num, f"Layer {layer_num}")
            n_stocks = len(rows)
            stock_lines = []
            for r in rows:
                div = f"{r['dividend_yield']*100:.1f}%" if r.get("dividend_yield") else "—"
                stock_lines.append(
                    f"  {r['ticker']} ({r.get('company','?')}, {r.get('sector','?')}): "
                    f"Score={r.get('quality_score','?')}/100, "
                    f"GrossMargin={r.get('gross_margin',0):.0f}%, "
                    f"NetIncome={r.get('net_income_margin',0):.0f}%, "
                    f"P/E={r.get('pe_ratio') or 'N/A'}, P/FCF={r.get('p_fcf') or 'N/A'}, Div={div}"
                )

            prompt = (
                f"You are a stock analyst. I am giving you exactly {n_stocks} stocks. "
                f"Rank ONLY these {n_stocks} stocks from 1 (best) to {n_stocks} (worst) as "
                f"Layer {layer_num} ({layer_name}) investments. Do not reference any other stocks.\n\n"
                f"Stocks to rank:\n{chr(10).join(stock_lines)}\n\n"
                f"Return ONLY valid JSON, no other text. Use rank 1 through {n_stocks} only:\n"
                f'{{"summary":"<2-sentence overview>","ranked":['
                f'{{"ticker":"BEST","rank":1,"note":"<why>"}},...]}}'
            )

            full_text = ""
            for tok in ollama_client.stream_generate(prompt, model=ollama_client.DEFAULT_MODEL, num_predict=800):
                full_text += tok

            dec = json.JSONDecoder()
            start = full_text.index("{")
            result, _ = dec.raw_decode(full_text, start)

            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn2 = sqlite3.connect(str(db), timeout=10)
            try:
                conn2.execute(
                    "UPDATE buffett_winners SET ai_layer_rank=NULL, ai_layer_rank_at=NULL WHERE layer_rec=?",
                    (layer_num,)
                )
                for entry in result.get("ranked", []):
                    rank_val = entry.get("rank")
                    t = (entry.get("ticker") or "").strip()
                    if t and rank_val is not None:
                        conn2.execute(
                            "UPDATE buffett_winners SET ai_layer_rank=?, ai_layer_rank_at=? WHERE ticker=?",
                            (rank_val, now_str, t)
                        )
                conn2.commit()
            finally:
                conn2.close()
            print(f"[LayerAI] Layer {layer_num} ranked {n_stocks} stocks")
        except Exception as e:
            print(f"[LayerAI] Layer {layer_num} failed: {e}")


def _run_refresh_job(job_id: str) -> None:
    """Run send_newsletter_main.py --no-email + AI layer rankings + generate_dashboard.py."""
    import subprocess as _sp
    VENV_PY = PROJECT_DIR / "venv" / "bin" / "python3"
    try:
        for script, extra_args in [("send_newsletter_main.py", ["--no-email"])]:
            _job_update(job_id, progress="Fetching latest market data…")
            result = _sp.run(
                [str(VENV_PY), str(PROJECT_DIR / script)] + extra_args,
                cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                _job_update(job_id, status="error",
                            error=f"{script} failed: {result.stderr.strip()[-300:]}")
                return

        _job_update(job_id, progress="Rebuilding dashboard…")
        result = _sp.run(
            [str(VENV_PY), str(PROJECT_DIR / "generate_dashboard.py")],
            cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            _job_update(job_id, status="error",
                        error=f"generate_dashboard.py failed: {result.stderr.strip()[-300:]}")
            return

        _job_update(job_id, status="done", result={"ok": True})
    except Exception as e:
        _job_update(job_id, status="error", error=str(e))


def _run_buffett_ai_job(job_id: str, ticker: str) -> None:
    """Generate an AI investment thesis for a Buffett screener winner via Ollama."""
    try:
        if not ollama_client.available():
            _job_update(job_id, status="error",
                        error="Ollama not available — make sure ollama is running on the server")
            return

        db = PROJECT_DIR / "out" / "buffett.db"
        conn = sqlite3.connect(str(db), timeout=10)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM buffett_winners WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row is None:
            conn.close()
            _job_update(job_id, status="error",
                        error=f"{ticker} not found in Buffett winners — run the screener first")
            return
        w = dict(row)
        conn.close()

        import json as _json
        import csv as _csv
        div_pct = f"{w['dividend_yield']:.1f}%" if w.get("dividend_yield") else "None"
        mcap = w.get("market_cap") or 0
        mcap_fmt = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else (f"${mcap/1e6:.0f}M" if mcap else "N/A")
        trap_flags = []
        try:
            trap_flags = _json.loads(w.get("value_trap_flags") or "[]")
        except Exception:
            pass
        trap_flags_text = "; ".join(trap_flags) if trap_flags else "none"

        # Load holdings from CSV — no yfinance fetch needed; the AI knows these tickers
        holdings_lines = []
        holdings_path = PROJECT_DIR / "holdings.csv"
        _job_update(job_id, progress="Loading portfolio holdings…")
        if holdings_path.exists():
            try:
                with open(str(holdings_path), newline="") as hf:
                    for h in _csv.DictReader(hf):
                        hticker = (h.get("Stock") or "").strip()
                        hlayer = h.get("Layer", "?")
                        if hticker and hticker != ticker:
                            holdings_lines.append(f"  {hticker} (Layer {hlayer})")
            except Exception:
                pass

        holdings_block = ""
        redundancy_schema = ""
        if holdings_lines:
            holdings_block = f"""
Existing Portfolio Holdings (exclude {ticker} itself — it is the winner being analyzed):
{chr(10).join(holdings_lines)}

Using your knowledge of each ticker above, identify any that are REDUNDANT with {ticker}.
Redundant = same economic role, sector, business model, or risk exposure.
ETFs/funds: consider their dominant exposure (e.g. VTSAX = total US market, SCHD = US dividend).
"""
            redundancy_schema = """,
  "redundancy": [
    {
      "ticker": "<ticker of a redundant holding only — omit non-redundant ones>",
      "redundancy_reason": "<one sentence: what overlaps>",
      "winner_superior": <true|false>,
      "superiority_reason": "<one sentence: why winner is better, or why to keep the holding>"
    }
  ]"""

        prompt = f"""You are a stock analyst. Analyze this Buffett screener winner. Return ONLY valid JSON, no other text.

{w.get('company', ticker)} ({ticker}) — {w.get('sector', '?')} / {w.get('industry', '?')}
Price: ${w.get('price', 0):.2f} | Market Cap: {mcap_fmt} | Exchange: {w.get('exchange', '?')}
Layer assignment: {w.get('layer_rec', '?')} — {w.get('layer_reason', '?')}
Value Trap Risk: {w.get('value_trap_risk', 'unknown')}
Trap flags: {trap_flags_text}

Quality Metrics (passed Buffett screen):
  Gross Margin: {w.get('gross_margin', 0):.1f}%  | Net Income Margin: {w.get('net_income_margin', 0):.1f}%
  Interest/OpIncome: {w.get('interest_margin', 0):.1f}% | CapEx/NetIncome: {w.get('capex_margin', 0):.1f}%
  Quality Score: {w.get('quality_score', 'N/A')}/100

Valuation:
  P/E: {w.get('pe_ratio') or 'N/A'}x | P/FCF: {w.get('p_fcf') or 'N/A'}x | EV/EBITDA: {w.get('ev_ebitda') or 'N/A'}x
  Dividend Yield: {div_pct}
{holdings_block}
Return this JSON structure:
{{
  "thesis": "<2-sentence investment case for buying this stock now>",
  "moat_strength": "<strong|moderate|weakening>",
  "moat_note": "<one sentence on competitive advantage>",
  "valuation": "<cheap|fair|stretched>",
  "valuation_note": "<one sentence on P/E and FCF vs quality>",
  "top_risk": "<single most important risk to the thesis>",
  "conviction": <integer 1 to 5>,
  "layer_fit": "<one sentence on why this fits or does not fit layer {w.get('layer_rec', '?')}>"{ redundancy_schema }
}}"""

        _job_update(job_id, progress="Sending to AI…")
        full_text = ""
        num_predict = 2500 if holdings_lines else 700
        for tok in ollama_client.stream_generate(prompt, model=ollama_client.DEFAULT_MODEL, num_predict=num_predict):
            full_text += tok
            _job_update(job_id, progress=full_text)

        try:
            dec = json.JSONDecoder()
            start = full_text.index("{")
            analysis, _ = dec.raw_decode(full_text, start)
        except (ValueError, json.JSONDecodeError):
            _job_update(job_id, status="error",
                        error="AI returned malformed JSON — try again")
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn2 = sqlite3.connect(str(db), timeout=10)
        try:
            conn2.execute(
                "UPDATE buffett_winners SET ai_analysis=?, ai_analysis_at=? WHERE ticker=?",
                (json.dumps(analysis), now_str, ticker)
            )
            conn2.commit()
        finally:
            conn2.close()

        _job_update(job_id, status="done", result={"ok": True, "ticker": ticker, "analysis": analysis})
    except Exception as e:
        _job_update(job_id, status="error", error=str(e))


def _run_buffett_layer_compare_job(job_id: str, layer_num: int) -> None:
    """Ask Ollama to rank all Buffett winners in a given layer."""
    try:
        if not ollama_client.available():
            _job_update(job_id, status="error",
                        error="Ollama not available — make sure ollama is running on the server")
            return

        db = PROJECT_DIR / "out" / "buffett.db"
        conn = sqlite3.connect(str(db), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT ticker, company, sector, gross_margin, net_income_margin, "
            "pe_ratio, p_fcf, ev_ebitda, dividend_yield, quality_score, "
            "value_trap_risk, layer_reason "
            "FROM buffett_winners WHERE layer_rec=? AND value_trap_risk='low' "
            "ORDER BY quality_score DESC LIMIT 5",
            (layer_num,)
        )]
        conn.close()

        if not rows:
            _job_update(job_id, status="done",
                        result={"ok": True, "ranked": [], "summary": "No winners in this layer."})
            return

        layer_names = {1:"Structural Ballast", 2:"Cash-Flow Engine", 3:"Compounder",
                       4:"Convexity/Optionality", 5:"Shock Absorber"}
        layer_name = layer_names.get(layer_num, f"Layer {layer_num}")

        stock_lines = []
        for r in rows:
            div = f"{r['dividend_yield']*100:.1f}%" if r.get("dividend_yield") else "—"
            stock_lines.append(
                f"  {r['ticker']} ({r.get('company','?')}, {r.get('sector','?')}): "
                f"Score={r.get('quality_score','?')}/100, "
                f"GrossMargin={r.get('gross_margin',0):.0f}%, "
                f"NetIncome={r.get('net_income_margin',0):.0f}%, "
                f"P/E={r.get('pe_ratio') or 'N/A'}, "
                f"P/FCF={r.get('p_fcf') or 'N/A'}, "
                f"Div={div}, "
                f"TrapRisk={r.get('value_trap_risk','?')}"
            )

        n_stocks = len(rows)
        prompt = f"""You are a stock analyst. I am giving you exactly {n_stocks} stocks. Rank ONLY these {n_stocks} stocks from 1 (best) to {n_stocks} (worst) as Layer {layer_num} ({layer_name}) investments. Do not reference any other stocks.

Layer {layer_num} — {layer_name}. All passed Buffett 6-criteria screen (Gross≥40%, NetInc≥20%, etc.) and are low value-trap risk.

Stocks to rank:
{chr(10).join(stock_lines)}

Return ONLY valid JSON, no other text. Use rank 1 through {n_stocks} only:
{{
  "summary": "<2-sentence overview of this layer's opportunities>",
  "ranked": [
    {{"ticker": "BEST_TICKER", "rank": 1, "note": "<one sentence why>"}},
    {{"ticker": "NEXT_TICKER", "rank": 2, "note": "<one sentence why>"}},
    ... (exactly {n_stocks} entries, ranks 1 through {n_stocks})
  ]
}}"""

        _job_update(job_id, progress="Asking AI to rank…")
        full_text = ""
        for tok in ollama_client.stream_generate(prompt, model=ollama_client.DEFAULT_MODEL, num_predict=1200):
            full_text += tok
            _job_update(job_id, progress=full_text)

        try:
            dec = json.JSONDecoder()
            start = full_text.index("{")
            result, _ = dec.raw_decode(full_text, start)
        except (ValueError, json.JSONDecodeError):
            _job_update(job_id, status="error",
                        error="AI returned malformed JSON — try again")
            return

        # Persist AI ranks back to DB
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn3 = sqlite3.connect(str(db), timeout=10)
        try:
            # Clear previous ranks for this layer
            conn3.execute(
                "UPDATE buffett_winners SET ai_layer_rank=NULL, ai_layer_rank_at=NULL WHERE layer_rec=?",
                (layer_num,)
            )
            for entry in result.get("ranked", []):
                rank_val = entry.get("rank")
                t = entry.get("ticker", "").strip()
                if t and rank_val is not None:
                    conn3.execute(
                        "UPDATE buffett_winners SET ai_layer_rank=?, ai_layer_rank_at=? WHERE ticker=?",
                        (rank_val, now_str, t)
                    )
            conn3.commit()
        finally:
            conn3.close()

        _job_update(job_id, status="done", result={"ok": True, "layer": layer_num, **result})
    except Exception as e:
        _job_update(job_id, status="error", error=str(e))


# ── CC Chat helpers ───────────────────────────────────────────────────────────

def _fetch_ticker_names(tickers: list) -> dict:
    """Return {ticker: company_name} for a list of tickers via yfinance.
    Used to ground the AI chat so it cannot hallucinate company names."""
    import yfinance as _yf2
    result = {}
    for t in tickers:
        try:
            info = _yf2.Ticker(t).info or {}
            name = (info.get("longName") or info.get("shortName") or "").strip()
            if name:
                result[t] = name
        except Exception:
            pass
    return result


def _fetch_options_for_chat(ticker: str, expiry: str) -> str:
    """Fetch live option chain for a specific expiry and return a plain-text block for chat context."""
    try:
        import yfinance as yf
        from covered_call_rec import call_delta, _exec_premium, _liquidity_score, _safe_int
        from datetime import datetime as _dt
        stock = yf.Ticker(ticker)
        try:
            price = float(stock.fast_info.last_price or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            hist = stock.history(period="2d")
            price = float(hist["Close"].dropna().iloc[-1]) if not hist.empty else 0.0

        today = _dt.now().date()
        exp_date = _dt.strptime(expiry, "%Y-%m-%d").date()
        dte = (exp_date - today).days

        chain = stock.option_chain(expiry).calls
        rows = []
        for _, row in chain.iterrows():
            K   = float(row.get("strike", 0))
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            iv  = float(row.get("impliedVolatility", 0) or 0)
            oi  = _safe_int(row.get("openInterest", 0))
            vol = _safe_int(row.get("volume", 0))
            if K <= 0 or K > price * 1.50:
                continue
            if bid <= 0 and ask <= 0:
                continue
            exec_p = _exec_premium(bid, ask)
            if exec_p < 0.05:
                continue
            liq = _liquidity_score(bid, ask, vol, oi)
            T = dte / 365
            delta = call_delta(price, K, T, iv) if iv > 0.01 and T > 0 else None
            ann = exec_p / price * 100 * (365 / dte) if dte > 0 else None
            rows.append((K, bid, ask, exec_p, iv * 100, delta, ann, liq, oi))

        if not rows:
            return f"\nLIVE DATA — {expiry} ({dte} DTE): No tradable contracts found.\n"

        lines = [f"\nLIVE DATA (fetched on demand) — {expiry} ({dte} DTE) for {ticker} at ${price:.2f}:"]
        lines.append(f"  {'Strike':>7}  {'Bid':>5}  {'Ask':>5}  {'Exec':>5}  {'IV%':>5}  "
                     f"{'Delta':>5}  {'Ann%':>6}  {'Liq':>3}  {'OI':>6}")
        lines.append("  " + "-" * 70)
        for K, bid, ask, exec_p, iv_pct, delta, ann, liq, oi in rows:
            d_str = f"{delta*100:.0f}%" if delta is not None else "N/A"
            a_str = f"{ann:.1f}%" if ann is not None else "N/A"
            lines.append(f"  ${K:>6.2f}  ${bid:>4.2f}  ${ask:>4.2f}  ${exec_p:>4.2f}"
                         f"  {iv_pct:>5.1f}%  {d_str:>5}  {a_str:>6}  {liq:>3}  {oi:>6}")
        lines.append("  (These contracts may not meet the profit floor — weigh the trade-offs.)")
        return "\n".join(lines)
    except Exception as exc:
        return f"\nCould not fetch live data for {expiry}: {exc}\n"


def _detect_expiry_from_message(message: str, available_expirations: list) -> "str | None":
    """Return the best matching expiry date string based on month/date mentions in message."""
    import re
    from datetime import datetime as _dt
    msg = message.lower()
    month_map = {
        "january": 1, "jan": 1, "february": 2, "feb": 2,
        "march": 3, "mar": 3, "april": 4, "apr": 4,
        "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }
    found_month = None
    found_day = None
    for name, num in sorted(month_map.items(), key=lambda x: -len(x[0])):
        if re.search(rf'\b{re.escape(name)}\b', msg):
            found_month = num
            m = re.search(rf'\b{re.escape(name)}\s+(\d{{1,2}})\b', msg)
            if m:
                found_day = int(m.group(1))
            break
    if found_month is None:
        m = re.search(r'\b(\d{1,2})[/-](\d{1,2})\b', msg)
        if m:
            found_month = int(m.group(1))
            found_day = int(m.group(2))
    if found_month is None:
        return None

    now = _dt.now()
    year = now.year
    if found_month < now.month:
        year += 1
    candidates = [
        e for e in available_expirations
        if _dt.strptime(e, "%Y-%m-%d").month == found_month
        and _dt.strptime(e, "%Y-%m-%d").year == year
    ]
    if not candidates:
        return None
    if found_day:
        candidates.sort(key=lambda e: abs(_dt.strptime(e, "%Y-%m-%d").day - found_day))
    else:
        candidates.sort()
    return candidates[0]


# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/out/dashboard.html")
            self.end_headers()
            return
        if parsed.path == "/glossary":
            self._handle_glossary()
        elif parsed.path == "/api/covered-calls":
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
        elif parsed.path == "/api/buffett-analysis":
            self._handle_buffett_analysis(parse_qs(parsed.query))
        elif parsed.path == "/api/cc-ai-analysis":
            self._handle_cc_ai_analysis(parse_qs(parsed.query))
        elif parsed.path.startswith("/api/analysis-job/"):
            job_id = parsed.path.rstrip("/").split("/")[-1]
            self._handle_analysis_job_poll(job_id)
        elif parsed.path == "/api/cc-evaluate":
            self._handle_cc_evaluate()
        elif parsed.path == "/api/cc-positions":
            self._handle_cc_positions_get()
        elif parsed.path == "/api/lots":
            self._handle_lots_get(parse_qs(parsed.query).get("ticker", [None])[0])
        elif parsed.path == "/api/sells":
            self._handle_sells_get(parse_qs(parsed.query).get("ticker", [None])[0])
        elif parsed.path == "/api/tlh-analysis":
            self._handle_tlh_analysis()
        elif parsed.path == "/api/macro":
            self._handle_macro()
        elif parsed.path == "/api/ai/daily":
            self._handle_ai_daily(parse_qs(parsed.query))
        elif parsed.path == "/api/holding-news":
            self._handle_holding_news(parse_qs(parsed.query))
        elif parsed.path == "/api/news-summary":
            self._handle_news_summary(parse_qs(parsed.query))
        elif parsed.path == "/api/refresh-financials":
            self._handle_refresh_financials(parse_qs(parsed.query))
        else:
            # Restrict static file fallback to safe extensions only — prevents
            # serving .env, .py, .db, .csv, and other sensitive project files.
            _safe_exts = ('.html', '.ico', '.png', '.jpg', '.gif', '.svg', '.css', '.js', '.woff', '.woff2')
            if not any(parsed.path.lower().endswith(e) for e in _safe_exts):
                self.send_response(404)
                self.end_headers()
                return
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/cc-positions":
            self._handle_cc_add()
        elif parsed.path == "/api/cc-import":
            self._handle_cc_import()
        elif parsed.path == "/api/lots":
            self._handle_lot_add()
        elif parsed.path == "/api/sells":
            self._handle_sell_add()
        elif parsed.path == "/api/holdings":
            self._handle_holding_add()
        elif parsed.path == "/api/buffett-scan":
            self._handle_buffett_scan_trigger()
        elif parsed.path == "/api/buffett-ai-analyze":
            self._handle_buffett_ai_analyze()
        elif parsed.path == "/api/buffett-layer-compare":
            self._handle_buffett_layer_compare()
        elif parsed.path == "/api/analysis-job":
            self._handle_analysis_job_create()
        elif parsed.path == "/api/refresh-dashboard":
            self._handle_refresh_dashboard()
        elif parsed.path == "/api/invest-chat":
            self._handle_invest_chat()
        elif parsed.path == "/api/ai/chat":
            self._handle_portfolio_chat()
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
        elif len(parts) == 4 and parts[1] == "api" and parts[2] == "cc-positions" and parts[3].isdigit():
            self._handle_cc_delete(int(parts[3]))
        else:
            self.send_response(404)
            self.end_headers()

    def do_PATCH(self):
        parsed = urlparse(self.path)
        parts  = parsed.path.rstrip("/").split("/")
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "cc-positions" and parts[3].isdigit():
            self._handle_cc_update(int(parts[3]))
        elif len(parts) == 4 and parts[1] == "api" and parts[2] == "holdings":
            self._handle_holding_layer_update(parts[3].upper())
        else:
            self.send_response(404)
            self.end_headers()

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        return json.loads(self.rfile.read(length)) if length else {}

    # ── Holdings layer reassignment ───────────────────────────────────────────
    _LAYER_NAMES = {
        1: "Layer 1: L1 Structural Ballast",
        2: "Layer 2: L2 Cash-Flow Engines",
        3: "Layer 3: L3 Compounders",
        4: "Layer 4: L4 Convexity",
        5: "Layer 5: L5 Shock Absorbers",
    }

    def _handle_holding_layer_update(self, ticker: str):
        try:
            body      = self._read_body()
            layer_num = int(body.get("layer_num", 0))
            if layer_num not in self._LAYER_NAMES:
                return self._json_error(400, "layer_num must be 1–5")

            new_layer = self._LAYER_NAMES[layer_num]
            holdings_csv = PROJECT_DIR / "holdings.csv"

            # 1. Update holdings.csv ─────────────────────────────────────────
            rows, fieldnames, found = [], None, False
            with open(holdings_csv, newline="") as f:
                reader = _csv_mod.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    raw = str(row["Stock"]).strip().upper()
                    # Normalize BRK.B → BRK-B for comparison
                    norm = raw.replace(".", "-") if "." in raw else raw
                    if norm == ticker or raw == ticker:
                        row["Layer"] = str(layer_num)
                        found = True
                    rows.append(row)

            if not found:
                return self._json_error(404, f"{ticker} not found in holdings.csv")

            with open(holdings_csv, "w", newline="") as f:
                writer = _csv_mod.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            # 2. Rewrite DB history ──────────────────────────────────────────
            db = PROJECT_DIR / "out" / "investment.db"
            if db.exists():
                conn = sqlite3.connect(str(db), timeout=10)
                conn.row_factory = sqlite3.Row

                conn.execute(
                    "UPDATE holding_day SET layer = ? WHERE ticker = ?",
                    (new_layer, ticker)
                )

                # Fully recompute layer_day from holding_day
                hrows = conn.execute(
                    "SELECT day, layer, value, change_dollars FROM holding_day"
                ).fetchall()

                day_layer = collections.defaultdict(lambda: {"value": 0.0, "change": 0.0})
                day_total = collections.defaultdict(float)
                for r in hrows:
                    key = (r["day"], r["layer"])
                    day_layer[key]["value"]  += r["value"]
                    day_layer[key]["change"] += r["change_dollars"]
                    day_total[r["day"]]      += r["value"]

                conn.execute("DELETE FROM layer_day")
                for (day, layer), d in day_layer.items():
                    total    = day_total[day]
                    weight   = (d["value"] / total * 100) if total else 0.0
                    prev_val = d["value"] - d["change"]
                    chg_pct  = (d["change"] / prev_val * 100) if prev_val else 0.0
                    conn.execute(
                        "INSERT INTO layer_day (day, layer, value, change_dollars, change_pct, weight_pct) "
                        "VALUES (?,?,?,?,?,?)",
                        (day, layer, d["value"], d["change"], chg_pct, weight)
                    )
                conn.commit()
                conn.close()

            # 3. Regenerate dashboard HTML ────────────────────────────────────
            import subprocess
            subprocess.run(
                ["python3", "generate_dashboard.py"],
                cwd=str(PROJECT_DIR),
                capture_output=True,
                timeout=30,
            )

            self._json({"ok": True, "ticker": ticker, "new_layer": new_layer, "layer_num": layer_num})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_holding_add(self):
        """POST /api/holdings — add a new position to holdings.csv and seed today's DB row."""
        try:
            body      = self._read_body()
            raw_ticker = str(body.get("ticker", "")).strip().upper()
            # Normalize BRK.B → BRK-B
            ticker = raw_ticker.replace(".", "-") if "." in raw_ticker else raw_ticker
            shares    = float(body.get("shares", 0))
            avg_cost  = float(body.get("avg_cost", 0))
            layer_num = int(body.get("layer_num", 0))

            if not ticker:
                return self._json_error(400, "ticker is required")
            if shares <= 0:
                return self._json_error(400, "shares must be > 0")
            if avg_cost <= 0:
                return self._json_error(400, "avg_cost must be > 0")
            if layer_num not in self._LAYER_NAMES:
                return self._json_error(400, "layer_num must be 1–5")

            holdings_csv = PROJECT_DIR / "holdings.csv"
            layer_label  = self._LAYER_NAMES[layer_num]

            # Check for duplicate
            existing_tickers = set()
            rows, fieldnames = [], None
            if holdings_csv.exists():
                with open(holdings_csv, newline="") as f:
                    reader = _csv_mod.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        raw = str(row["Stock"]).strip().upper()
                        norm = raw.replace(".", "-") if "." in raw else raw
                        existing_tickers.add(norm)
                        rows.append(row)

            if ticker in existing_tickers:
                return self._json_error(409, f"{ticker} is already in your holdings. Use the Lots form to add shares.")

            # Append new row to CSV
            new_row = {
                "Stock":   ticker,
                "Shares":  str(shares),
                "AvgCost": str(avg_cost),
                "Layer":   str(layer_num),
            }
            rows.append(new_row)
            if not fieldnames:
                fieldnames = ["Stock", "Shares", "AvgCost", "Layer"]

            with open(holdings_csv, "w", newline="") as f:
                writer = _csv_mod.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            # Fetch current price from yfinance and seed holding_day for today
            price = None
            try:
                import yfinance as yf
                import warnings
                warnings.filterwarnings("ignore")
                # yfinance expects the original dot notation for some tickers (BRK-B → BRK-B is fine)
                tk = yf.Ticker(ticker)
                info = tk.fast_info
                price = float(info.get("last_price") or info.get("previous_close") or 0) or None
                if not price:
                    hist = tk.history(period="2d")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])
            except Exception:
                price = None

            if price and price > 0:
                today = datetime.date.today().isoformat()
                value = shares * price
                db    = PROJECT_DIR / "out" / "investment.db"
                if db.exists():
                    conn = sqlite3.connect(str(db), timeout=10)
                    conn.row_factory = sqlite3.Row

                    conn.execute(
                        "INSERT OR REPLACE INTO holding_day "
                        "(day, ticker, layer, shares, price, value, change_dollars, change_pct, weight_pct) "
                        "VALUES (?,?,?,?,?,?,0,0,0)",
                        (today, ticker, layer_label, shares, price, value)
                    )

                    # Recompute today's layer_day and portfolio_day weights
                    hrows = conn.execute(
                        "SELECT layer, value, change_dollars FROM holding_day WHERE day=?", (today,)
                    ).fetchall()

                    day_layer = collections.defaultdict(lambda: {"value": 0.0, "change": 0.0})
                    total_val = 0.0
                    for r in hrows:
                        day_layer[r["layer"]]["value"]  += r["value"]
                        day_layer[r["layer"]]["change"] += r["change_dollars"]
                        total_val += r["value"]

                    # Recompute weight_pct for every holding today in one SQL pass
                    if total_val:
                        conn.execute(
                            "UPDATE holding_day SET weight_pct=ROUND(value*100.0/?,4) WHERE day=?",
                            (total_val, today)
                        )

                    # Recompute layer_day for today
                    for layer, d in day_layer.items():
                        w        = (d["value"] / total_val * 100) if total_val else 0
                        prev_val = d["value"] - d["change"]
                        chg_pct  = (d["change"] / prev_val * 100) if prev_val else 0.0
                        conn.execute(
                            "INSERT OR REPLACE INTO layer_day "
                            "(day, layer, value, change_dollars, change_pct, weight_pct) VALUES (?,?,?,?,?,?)",
                            (today, layer, d["value"], d["change"], chg_pct, w)
                        )

                    conn.commit()
                    conn.close()

            # Seed opening lot in cost_lots
            db = PROJECT_DIR / "out" / "investment.db"
            if db.exists():
                today_str = datetime.date.today().isoformat()
                conn = sqlite3.connect(str(db), timeout=10)
                existing = conn.execute(
                    "SELECT COUNT(*) FROM cost_lots WHERE ticker=?", (ticker,)
                ).fetchone()[0]
                if existing == 0:
                    conn.execute(
                        "INSERT INTO cost_lots (ticker, shares, cost_per_share, purchase_date, notes) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (ticker, shares, avg_cost, today_str, "Opening lot (auto-created)")
                    )
                    conn.commit()
                conn.close()

            # Regenerate dashboard
            import subprocess
            subprocess.run(
                ["python3", "generate_dashboard.py"],
                cwd=str(PROJECT_DIR),
                capture_output=True,
                timeout=30,
            )

            self._json({
                "ok":        True,
                "ticker":    ticker,
                "layer":     layer_label,
                "price":     price,
                "value":     round(shares * price, 2) if price else None,
            })
        except Exception as e:
            self._json_error(500, str(e))

    # ── CC positions ──────────────────────────────────────────────────────────
    def _handle_cc_positions_get(self):
        try:
            db = PROJECT_DIR / "out" / "investment.db"
            if not db.exists():
                return self._json({"ok": True, "positions": []})
            conn = sqlite3.connect(str(db), timeout=10)
            conn.row_factory = sqlite3.Row

            # Auto-expire any open positions whose expiry date has passed.
            # Options expire at end of day on the expiry date, so we compare
            # strictly: expiry < today (i.e. the day after expiry has arrived).
            today = datetime.date.today().isoformat()
            past_open = conn.execute(
                "SELECT id, premium_per_contract, contracts, expiry "
                "FROM cc_positions WHERE status = 'open' AND expiry < ?",
                (today,)
            ).fetchall()
            for row in past_open:
                net = round(row["premium_per_contract"] * row["contracts"] * 100, 2)
                conn.execute(
                    "UPDATE cc_positions "
                    "SET status='expired', close_type='expired', "
                    "    closed_date=?, net_premium=? "
                    "WHERE id=?",
                    (row["expiry"], net, row["id"])
                )
            if past_open:
                conn.commit()

            positions = [dict(r) for r in conn.execute(
                "SELECT * FROM cc_positions ORDER BY opened_date DESC, id DESC"
            )]
            conn.close()
            # Compute mark-to-market P&L for open positions
            for p in positions:
                if p["status"] == "open" and p.get("current_mark") is not None:
                    mark  = p["current_mark"]
                    prev  = p.get("prev_mark")
                    c     = p["contracts"]
                    prem  = p["premium_per_contract"]
                    p["pnl_total"] = round((prem - mark) * c * 100, 2)
                    p["pnl_day"]   = round((prev - mark) * c * 100, 2) if prev is not None else None
                else:
                    p["pnl_total"] = None
                    p["pnl_day"]   = None
            auto_expired = [r["id"] for r in past_open]
            self._json({"ok": True, "positions": positions, "auto_expired": auto_expired})
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
            """, (_normalize_ticker(body["ticker"]), int(body["contracts"]), float(body["strike"]),
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
            conn.row_factory = sqlite3.Row
            updates = []
            values  = []
            for field in ["status", "closed_date", "closed_price", "close_type", "notes"]:
                if field in body:
                    updates.append(f"{field} = ?")
                    values.append(body[field])
            # Editable core fields (ticker typo fixes, etc.)
            if "ticker" in body:
                from covered_call_rec import normalize_ticker as _nt
                updates.append("ticker = ?")
                values.append(_nt(str(body["ticker"]).strip().upper()))
            if "contracts" in body:
                updates.append("contracts = ?")
                values.append(int(body["contracts"]))
            if "strike" in body:
                updates.append("strike = ?")
                values.append(float(body["strike"]))
            if "expiry" in body:
                updates.append("expiry = ?")
                values.append(str(body["expiry"]).strip())
            if "premium_per_contract" in body:
                updates.append("premium_per_contract = ?")
                values.append(float(body["premium_per_contract"]))
            if "opened_date" in body:
                updates.append("opened_date = ?")
                values.append(str(body["opened_date"]).strip())
            # Auto-compute net_premium whenever the position is being closed
            new_status = body.get("status", "")
            if new_status in ("closed", "expired", "assigned"):
                row = conn.execute(
                    "SELECT premium_per_contract, contracts FROM cc_positions WHERE id = ?",
                    (pos_id,)
                ).fetchone()
                if row:
                    buyback = float(body.get("closed_price") or 0)
                    net     = round((row["premium_per_contract"] - buyback) * row["contracts"] * 100, 2)
                    updates.append("net_premium = ?")
                    values.append(net)
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

    def _handle_cc_delete(self, pos_id: int):
        try:
            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            try:
                conn.execute("DELETE FROM cc_positions WHERE id = ?", (pos_id,))
                conn.commit()
            finally:
                conn.close()
            self._json({"ok": True})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_cc_import(self):
        """Import open positions from covered_calls.csv, skipping duplicates."""
        import csv as _csv
        csv_path = PROJECT_DIR / "covered_calls.csv"
        if not csv_path.exists():
            return self._json_error(404, "covered_calls.csv not found")
        db = PROJECT_DIR / "out" / "investment.db"
        conn = sqlite3.connect(str(db), timeout=10)
        conn.row_factory = sqlite3.Row
        added = skipped = 0
        try:
            with open(csv_path, newline="") as f:
                for row in _csv.DictReader(filter(lambda l: not l.strip().startswith("#"), f)):
                    ticker = _normalize_ticker(row.get("ticker") or "")
                    if not ticker:
                        continue
                    exists = conn.execute(
                        "SELECT id FROM cc_positions WHERE ticker=? AND strike=? AND expiry=? AND status='open'",
                        (ticker, float(row["strike"]), row["expiry"].strip())
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue
                    conn.execute(
                        "INSERT INTO cc_positions "
                        "(ticker,contracts,strike,expiry,premium_per_contract,opened_date,status,notes) "
                        "VALUES (?,?,?,?,?,?,'open',?)",
                        (ticker, int(row["contracts"]), float(row["strike"]),
                         row["expiry"].strip(), float(row["premium_per_contract"]),
                         row["opened_date"].strip(), (row.get("notes") or "").strip())
                    )
                    added += 1
            conn.commit()
        finally:
            conn.close()
        self._json({"ok": True, "added": added, "skipped": skipped})

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
            ticker     = body["ticker"].upper()
            new_shares = float(body["shares"])
            new_cost   = float(body["cost_per_share"])

            db   = PROJECT_DIR / "out" / "investment.db"
            conn = sqlite3.connect(str(db), timeout=10)
            cur  = conn.execute(
                "INSERT INTO cost_lots (ticker, shares, cost_per_share, purchase_date, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                (ticker, new_shares, new_cost, body["purchase_date"], body.get("notes", ""))
            )
            pos_id = cur.lastrowid

            # Recompute totals from all lots and sync to holdings.csv + holding_day
            lots = conn.execute(
                "SELECT shares, cost_per_share FROM cost_lots WHERE ticker=?", (ticker,)
            ).fetchall()
            total_shares = sum(r[0] for r in lots)
            avg_cost     = sum(r[0] * r[1] for r in lots) / total_shares if total_shares else new_cost

            conn.commit()
            conn.close()

            # Update holdings.csv — update existing row or insert if ticker absent
            holdings_csv = PROJECT_DIR / "holdings.csv"
            if holdings_csv.exists():
                rows, fieldnames, found = [], None, False
                with open(holdings_csv, newline="") as f:
                    reader = _csv_mod.DictReader(f)
                    fieldnames = reader.fieldnames
                    for row in reader:
                        if row["Stock"].strip().upper() == ticker:
                            row["Shares"]  = str(total_shares)
                            row["AvgCost"] = str(round(avg_cost, 4))
                            found = True
                        rows.append(row)
                if not found:
                    # Ticker was absent (e.g. closed then re-bought via lot form) — insert it
                    layer_row = conn_layer = None
                    try:
                        conn_layer = sqlite3.connect(str(db), timeout=10)
                        layer_row = conn_layer.execute(
                            "SELECT layer FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 1", (ticker,)
                        ).fetchone()
                    except Exception:
                        pass
                    finally:
                        if conn_layer:
                            conn_layer.close()
                    layer_num = 3  # default to Layer 3 (Core Compounders) if unknown
                    if layer_row:
                        # layer stored as "Layer N: ..." — extract N
                        import re as _re
                        m = _re.search(r"Layer (\d)", layer_row[0])
                        if m:
                            layer_num = int(m.group(1))
                    new_row = {"Stock": ticker, "Shares": str(total_shares),
                               "AvgCost": str(round(avg_cost, 4)), "Layer": str(layer_num)}
                    if fieldnames and "PurchaseDate" in fieldnames:
                        new_row["PurchaseDate"] = body.get("purchase_date", "")
                    rows.append(new_row)
                with open(holdings_csv, "w", newline="") as f:
                    writer = _csv_mod.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)

            # Update today's holding_day value (price unchanged, just more shares)
            db_conn = sqlite3.connect(str(db), timeout=10)
            today = datetime.date.today().isoformat()
            row = db_conn.execute(
                "SELECT price FROM holding_day WHERE ticker=? AND day=?", (ticker, today)
            ).fetchone()
            if row:
                price = row[0]
                new_value = total_shares * price
                db_conn.execute(
                    "UPDATE holding_day SET shares=?, value=? WHERE ticker=? AND day=?",
                    (total_shares, new_value, ticker, today)
                )
                # Recompute weight_pct for all holdings today
                total_val = db_conn.execute(
                    "SELECT SUM(value) FROM holding_day WHERE day=?", (today,)
                ).fetchone()[0] or 0
                if total_val:
                    db_conn.execute(
                        "UPDATE holding_day SET weight_pct=ROUND(value*100.0/?,4) WHERE day=?",
                        (total_val, today)
                    )
                db_conn.commit()
            db_conn.close()

            self._json({"ok": True, "id": pos_id, "total_shares": total_shares, "avg_cost": round(avg_cost, 4)})
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
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = 0
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

            h     = holdings[ticker]
            force = params.get("force", ["0"])[0] == "1"
            if force:
                with _cc_analyze_lock:
                    _cc_analyze_cache.pop(ticker, None)
            result = _cc_analyze_get(ticker)
            if result is None:
                result = analyze(ticker, h["avg_cost"], h["shares"])
                if result is not None:
                    _cc_analyze_set(ticker, result)

            if result is None:
                return self._json({"ok": False, "ticker": ticker,
                                   "error": "No qualifying contracts found in 21–60 DTE window."})

            # Open covered call positions on this ticker (to flag in the UI)
            open_calls = []
            cc_history = None
            try:
                db = PROJECT_DIR / "out" / "investment.db"
                conn = sqlite3.connect(str(db), timeout=5)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT strike, expiry FROM cc_positions WHERE ticker=? AND status='open'",
                    (ticker,)
                ).fetchall()
                open_calls = [{"strike": r["strike"], "expiry": r["expiry"]} for r in rows]
                hist = conn.execute(
                    """SELECT count(*) as cnt,
                              sum(net_premium) as total_net,
                              sum(case when close_type='assigned' then 1 else 0 end) as assigned_cnt
                       FROM cc_positions
                       WHERE ticker=? AND status IN ('closed','expired','assigned')
                         AND net_premium IS NOT NULL""",
                    (ticker,)
                ).fetchone()
                if hist and hist["cnt"] > 0:
                    cc_history = {
                        "count":          hist["cnt"],
                        "total_net":      round(hist["total_net"] or 0, 2),
                        "assigned_count": hist["assigned_cnt"] or 0,
                    }
                conn.close()
            except Exception:
                pass

            def _row_to_dict(row):
                return {
                    "expiration":       row["expiration"],
                    "strike":           float(row["strike"]),
                    "dte":              int(row["dte"]),
                    "bid":              float(row["bid"]),
                    "ask":              float(row["ask"]),
                    "mid":              float(row["mid"]),
                    "exec_premium":     round(_safe_float(row.get("exec_premium", row["mid"])), 2),
                    "premium_pct":      round(float(row["premium_pct"]), 2),
                    "annualized_ret":   round(float(row["annualized_ret"]), 1),
                    "profit_if_called": round(float(row["profit_if_called"]), 1),
                    "open_interest":    int(_safe_float(row.get("openInterest"))),
                    "volume":           int(_safe_float(row.get("volume"))),
                    "delta":            round(_safe_float(row.get("delta")), 3),
                    "itm_prob_real":    round(_safe_float(row.get("itm_prob_real", row.get("delta"))), 3),
                    "regret_prob":      round(_safe_float(row.get("regret_prob")), 3),
                    "regret_threshold": round(_safe_float(row.get("regret_threshold")), 2),
                    "cc_alpha":         round(_safe_float(row.get("cc_alpha")), 3),
                    "cc_alpha_pct":     round(_safe_float(row.get("cc_alpha_pct")), 5),
                    "iv_richness":      round(_safe_float(row.get("iv_richness")), 3),
                    "liquidity_score":  int(_safe_float(row.get("liquidity_score"))),
                    "score":            round(_safe_float(row.get("score")), 1),
                    "opp_score":        round(_safe_float(row.get("opp_score")), 1),
                    "risk_events":      list(row.get("risk_events") or []),
                    "has_avoid":        bool(row.get("has_avoid")),
                    "has_caution":      bool(row.get("has_caution")),
                    "passes_floor":     bool(row.get("passes_floor", True)),
                    "spread_width":     round(_safe_float(row.get("spread_width")), 2),
                }

            recs = [_row_to_dict(row) for _, row in result["recs"].iterrows()]
            tight_recs_df = result.get("tight_recs")
            tight_recs = (
                [_row_to_dict(row) for _, row in tight_recs_df.iterrows()]
                if tight_recs_df is not None and not tight_recs_df.empty
                else []
            )
            floor_fail_df = result.get("floor_fail_recs")
            floor_fail_recs = (
                [_row_to_dict(row) for _, row in floor_fail_df.iterrows()]
                if floor_fail_df is not None and not floor_fail_df.empty
                else []
            )

            vm = result.get("vol_model") or {}
            self._json({
                "ok":                True,
                "ticker":            result["ticker"],
                "shares":            h["shares"],
                "current_price":     round(result["current_price"], 2),
                "avg_cost":          round(result["avg_cost"], 2),
                "gain_pct":          round(result["gain_pct"], 2),
                "already_at_target": result["already_at_target"],
                "strike_floor":      round(result["strike_floor"], 2),
                "week52_high":       round(result["week52_high"], 2),
                "week52_high_dt":    result["week52_high_dt"],
                "hv_rank":           result.get("hv_rank"),
                "atm_iv":            result.get("atm_iv"),
                "hv_forecast":       round(vm.get("hv_forecast") or 0, 4) or None,
                "mu":                round(result.get("mu") or 0, 4) or None,
                "recs":              recs,
                "floor_fail_recs":   floor_fail_recs,
                "tight_recs":        tight_recs,
                "open_calls":        open_calls,
                "cc_history":        cc_history,
                "data_mode":         result.get("data_mode", "live"),
                "dte_extended":      result.get("dte_extended", False),
                "note":              result.get("note"),
            })

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_cc_ai_analysis(self, params):
        ticker = (params.get("ticker", [None])[0] or "").upper().strip()
        if not ticker:
            return self._json_error(400, "Missing ticker parameter")
        if not ollama_client.available():
            return self._json_error(503, "Ollama not available — make sure ollama is running on the server")

        def _sse(event, data):
            # Write as an HTTP/1.1 chunk so Tailscale Funnel forwards it immediately
            # instead of buffering the whole HTTP/1.0 response body.
            body = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
            chunk = f"{len(body):x}\r\n".encode() + body + b"\r\n"
            self.wfile.write(chunk)
            self.wfile.flush()

        def _to_str(v):
            if isinstance(v, str):   return v
            if isinstance(v, dict):  return " ".join(str(x) for x in v.values())
            if isinstance(v, list):  return "; ".join(str(x) for x in v)
            return str(v)

        try:
            from covered_call_rec import analyze, load_holdings, ai_context
            holdings = load_holdings()
            if ticker not in holdings:
                return self._json_error(404, f"{ticker} not found in holdings")
            h = holdings[ticker]

            # Check AI insight cache — send done event immediately if hit
            cached_ai = _cc_ai_get(ticker)
            if cached_ai:
                self.wfile.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/event-stream\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Transfer-Encoding: chunked\r\n"
                    b"X-Accel-Buffering: no\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
                self.wfile.flush()
                _sse("done", {"ok": True, "ticker": ticker,
                              "insight": cached_ai["insight"],
                              "model": cached_ai["model"],
                              "cached": True})
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
                return

            # Use cached analyze() result if available; otherwise fetch fresh
            result = _cc_analyze_get(ticker)
            if result is None:
                result = analyze(ticker, h["avg_cost"], h["shares"])
                if result is not None:
                    _cc_analyze_set(ticker, result)
            if result is None or result["recs"].empty:
                return self._json_error(422, "No qualifying option contracts found to analyze")
            # Write HTTP/1.1 SSE headers before any work that could raise,
            # so the error path can always send an SSE error event.
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Cache-Control: no-cache\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"X-Accel-Buffering: no\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            self.wfile.flush()
            prompt = ai_context(ticker, result, h["shares"], h.get("layer", "?"))
            _sse("status", {"message": "Sending to AI…"})

            # Ollama prompt evaluation can take 30-90s on CPU before the first
            # token. Run generation in a thread and send keepalive status chunks
            # every 10s so Tailscale Funnel doesn't drop the idle connection.
            import queue as _queue
            _tok_q = _queue.Queue()

            def _generate():
                try:
                    for tok in ollama_client.stream_generate(prompt):
                        _tok_q.put(("token", tok))
                    _tok_q.put(("done", None))
                except Exception as exc:
                    _tok_q.put(("error", str(exc)))

            threading.Thread(target=_generate, daemon=True).start()

            full_text = ""
            while True:
                try:
                    kind, val = _tok_q.get(timeout=10)
                except _queue.Empty:
                    _sse("status", {"message": "AI is thinking…"})
                    continue
                if kind == "token":
                    full_text += val
                    _sse("token", {"text": val})
                elif kind == "done":
                    break
                else:
                    raise Exception(val)

            # raw_decode finds the FIRST complete JSON object and stops —
            # the greedy r'\{.*\}' regex would grab everything up to the
            # LAST '}' and fail when the model outputs trailing text.
            try:
                _dec = json.JSONDecoder()
                _start = full_text.index('{')
                insight, _ = _dec.raw_decode(full_text, _start)
            except (ValueError, json.JSONDecodeError):
                _sse("error", {"message": "AI returned malformed JSON — try again"})
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
                return
            for field in ("iv_context", "roll_strategy", "timing_advice"):
                if field in insight:
                    insight[field] = _to_str(insight[field])

            # Overwrite strike/expiration from actual contract data — the model
            # often leaves the placeholder value (0.00) in the recommendation object.
            _rec = insight.get("recommendation", {})
            _rank = max(0, int(_rec.get("rank", 1)) - 1)
            if _rank < len(result["recs"]):
                _row = result["recs"].iloc[_rank]
                _rec["strike"]     = float(_row["strike"])
                _rec["expiration"] = str(_row["expiration"])
                insight["recommendation"] = _rec

            _cc_ai_set(ticker, insight, ollama_client.DEFAULT_MODEL)
            _sse("done", {"ok": True, "ticker": ticker, "insight": insight,
                          "model": ollama_client.DEFAULT_MODEL})
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except json.JSONDecodeError:
            try:
                _sse("error", {"message": "AI returned malformed JSON — try again"})
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass
        except Exception as e:
            try:
                _sse("error", {"message": str(e)})
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass

    # ── Conversational AI chat ────────────────────────────────────────────────

    def _build_chat_context_winner(self, ticker):
        import csv as _csv_m, json as _json_m
        db = PROJECT_DIR / "out" / "buffett.db"
        with sqlite3.connect(str(db), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM buffett_winners WHERE ticker = ?", (ticker,)
            ).fetchone()
        if row is None:
            raise ValueError(f"{ticker} not found in Buffett winners — run the screener first")
        w = dict(row)

        div_pct = f"{w['dividend_yield']:.1f}%" if w.get("dividend_yield") else "N/A"
        mcap = w.get("market_cap") or 0
        mcap_fmt = f"${mcap/1e9:.1f}B" if mcap >= 1e9 else (f"${mcap/1e6:.0f}M" if mcap else "N/A")
        trap_flags = []
        try:
            trap_flags = _json_m.loads(w.get("value_trap_flags") or "[]")
        except Exception:
            pass

        ai_block = ""
        if w.get("ai_analysis"):
            try:
                ai = _json_m.loads(w["ai_analysis"])
                ai_block = (
                    f"\nPrior AI Analysis:\n"
                    f"  Thesis: {ai.get('thesis', '?')}\n"
                    f"  Moat: {ai.get('moat_strength', '?')} — {ai.get('moat_note', '')}\n"
                    f"  Valuation: {ai.get('valuation', '?')} — {ai.get('valuation_note', '')}\n"
                    f"  Top Risk: {ai.get('top_risk', '?')}\n"
                    f"  Conviction: {ai.get('conviction', '?')}/5\n"
                    f"  Layer Fit: {ai.get('layer_fit', '')}"
                )
            except Exception:
                pass

        # Build a ticker→company name map from buffett_winners (fast, no network call)
        _ticker_names: dict = {}
        try:
            _db2 = PROJECT_DIR / "out" / "buffett.db"
            with sqlite3.connect(str(_db2), timeout=5) as _c2:
                for _row2 in _c2.execute("SELECT ticker, company FROM buffett_winners"):
                    if _row2[1]:
                        _ticker_names[_row2[0]] = _row2[1]
        except Exception:
            pass

        holdings_lines = []
        holdings_path = PROJECT_DIR / "holdings.csv"
        if holdings_path.exists():
            try:
                with open(str(holdings_path), newline="") as hf:
                    for h in _csv_m.DictReader(hf):
                        hticker = (h.get("Stock") or "").strip()
                        hlayer = h.get("Layer", "?")
                        if hticker and hticker != ticker:
                            hname = _ticker_names.get(hticker, "")
                            label = f"{hticker} — {hname}" if hname else hticker
                            holdings_lines.append(f"  {label} (Layer {hlayer})")
            except Exception:
                pass

        portfolio_block = ""
        if holdings_lines:
            portfolio_block = (
                "\nCurrent Portfolio Holdings (ticker — company name — layer):\n"
                + "\n".join(holdings_lines)
            )

        return (
            f"You are a knowledgeable investment advisor helping an investor understand a stock that "
            f"passed the Buffett quality screener. Answer conversationally in plain English — no "
            f"unexplained jargon. Be direct and specific; reference the data below when relevant.\n\n"
            f"STOCK: {w.get('company', ticker)} ({ticker})\n"
            f"Sector: {w.get('sector', '?')} / {w.get('industry', '?')}\n"
            f"Price: ${w.get('price', 0):.2f} | Market Cap: {mcap_fmt} | Exchange: {w.get('exchange', '?')}\n"
            f"Layer Assignment: {w.get('layer_rec', '?')} — {w.get('layer_reason', '?')}\n"
            f"Value Trap Risk: {w.get('value_trap_risk', '?')}\n"
            f"Trap Flags: {'; '.join(trap_flags) if trap_flags else 'none'}\n\n"
            f"Quality Metrics (all passed Buffett screen):\n"
            f"  Gross Margin: {w.get('gross_margin', 0):.1f}%\n"
            f"  Net Income Margin: {w.get('net_income_margin', 0):.1f}%\n"
            f"  Interest/OpIncome: {w.get('interest_margin', 0):.1f}%\n"
            f"  CapEx/NetIncome: {w.get('capex_margin', 0):.1f}%\n"
            f"  Quality Score: {w.get('quality_score', 'N/A')}/100\n\n"
            f"Valuation:\n"
            f"  P/E: {w.get('pe_ratio') or 'N/A'}x | P/FCF: {w.get('p_fcf') or 'N/A'}x | "
            f"EV/EBITDA: {w.get('ev_ebitda') or 'N/A'}x\n"
            f"  Dividend Yield: {div_pct}"
            f"{ai_block}"
            f"{portfolio_block}"
        )

    def _build_chat_context_cc(self, ticker):
        import yfinance as _yf
        from covered_call_rec import analyze, load_holdings
        holdings = load_holdings()
        if ticker not in holdings:
            raise ValueError(f"{ticker} not found in holdings")
        h = holdings[ticker]

        result = _cc_analyze_get(ticker)
        if result is None:
            result = analyze(ticker, h["avg_cost"], h["shares"])
            if result is not None:
                _cc_analyze_set(ticker, result)

        base = (
            f"You are a friendly covered call advisor helping an investor decide whether to sell "
            f"a covered call. Speak in plain English — explain any finance terms you use. "
            f"No Greek letters.\n\n"
            f"TICKER: {ticker}\n"
            f"Shares Held: {h['shares']:.0f}\n"
            f"Average Cost: ${h['avg_cost']:.2f}\n"
            f"Layer: {h['layer']}"
        )

        # Fetch all available expiry dates so the investor can ask about any month
        all_expirations = []
        try:
            all_expirations = list(_yf.Ticker(ticker).options or [])
        except Exception:
            pass

        if result is None or result["recs"].empty:
            avail = ", ".join(all_expirations[:20]) if all_expirations else "unknown"
            return base + (
                f"\n\nNote: No qualifying option contracts found in the standard 21–60 DTE window. "
                f"Answer general questions about covered call strategy for this position.\n"
                f"All available expiry dates for {ticker}: {avail}\n"
                f"(Contracts outside the qualifying window can be fetched on demand if the investor asks about a specific month.)"
            )

        price = result.get("current_price", 0)
        gain_pct = result.get("gain_pct", 0)
        base += (
            f"\nCurrent Price: ${price:.2f}\n"
            f"Unrealized Gain: {gain_pct:.1f}%\n"
            f"Strike Floor (profit threshold): ${result.get('strike_floor', 0):.2f}\n"
            f"52-Week High: ${result.get('week52_high', 0):.2f}\n"
            f"ATM IV: {result.get('atm_iv', 0):.1f}%  |  HV Rank: {result.get('hv_rank', 'N/A')}"
        )

        # Qualifying contracts (meet profit floor, standard DTE window)
        recs = result["recs"].head(5)
        contracts = []
        for i, (_, row) in enumerate(recs.iterrows(), 1):
            contracts.append(
                f"  #{i}: ${float(row['strike']):.2f} strike  "
                f"exp {row['expiration']}  ({int(row['dte'])} DTE)  "
                f"exec ${float(row.get('exec_premium', row.get('mid', 0))):.2f}/share  "
                f"({float(row.get('annualized_ret', 0)):.1f}% ann.)  "
                f"P(called away) {float(row.get('itm_prob_real', 0))*100:.0f}%  "
                f"regret P {float(row.get('regret_prob', 0))*100:.0f}%  "
                f"cc_alpha ${float(row.get('cc_alpha', 0)):.2f}"
            )
        base += "\n\nQualifying Contracts (meet profit floor):\n" + "\n".join(contracts)

        # Non-qualifying contracts — give the investor visibility even if they don't clear the floor
        floor_fail = result.get("floor_fail_recs")
        if floor_fail is not None and not floor_fail.empty:
            ff_lines = []
            for _, row in floor_fail.head(8).iterrows():
                ff_lines.append(
                    f"  ${float(row['strike']):.2f} strike  "
                    f"exp {row['expiration']}  ({int(row['dte'])} DTE)  "
                    f"exec ${float(row.get('exec_premium', row.get('mid', 0))):.2f}/share  "
                    f"({float(row.get('annualized_ret', 0)):.1f}% ann.)"
                )
            base += (
                f"\n\nContracts BELOW profit floor (don't clear cost+buffer, but tradeable if investor accepts lower return):\n"
                + "\n".join(ff_lines)
            )

        # List all available expiry dates so user can ask about any month
        if all_expirations:
            base += f"\n\nAll available expiry dates for {ticker}: {', '.join(all_expirations[:24])}"
            base += (
                f"\nIMPORTANT: You CANNOT fetch data yourself. Contracts outside the pre-analyzed "
                f"window are only available if a LIVE DATA block appears below in this prompt. "
                f"If no LIVE DATA block exists for a requested expiry, say you don't have it and "
                f"ask the investor to specify a date so live data can be loaded. NEVER invent, "
                f"estimate, or guess option prices, premiums, probabilities, or annualized returns."
            )

        cached_ai = _cc_ai_get(ticker)
        if cached_ai:
            ins = cached_ai.get("insight", {})
            rec = ins.get("recommendation", {})
            what_wrong = (ins.get("what_could_go_wrong") or "")[:300]
            base += (
                f"\n\nPrior AI Recommendation:\n"
                f"  Pick: #{rec.get('rank','?')} — {rec.get('expiration','?')} "
                f"${rec.get('strike','?')} call\n"
                f"  Summary: {rec.get('summary','?')}\n"
                f"  Main Risk: {what_wrong}"
            )

        return base

    def _build_chat_context(self, context_type, context_id):
        if context_type == "winner":
            return self._build_chat_context_winner(context_id)
        elif context_type == "cc":
            return self._build_chat_context_cc(context_id)
        raise ValueError(f"Unknown context_type: {context_type}")

    def _handle_invest_chat(self):
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")

        context_type = body.get("context_type", "")
        context_id   = (body.get("context_id") or "").upper().strip()
        messages     = body.get("messages", [])

        if context_type not in ("winner", "cc"):
            return self._json_error(400, "context_type must be 'winner' or 'cc'")
        if not context_id:
            return self._json_error(400, "context_id required")
        if not messages:
            return self._json_error(400, "messages array required")

        chat_key = f"{context_type}:{context_id}"
        if chat_key in _chat_active:
            return self._json_error(429, "already_streaming — close the other chat first")
        _chat_active.add(chat_key)

        # Write SSE headers immediately — before any blocking yfinance/AI calls —
        # so the browser doesn't see a hang waiting for the response to start.
        self.wfile.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"X-Accel-Buffering: no\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        self.wfile.flush()

        def _sse(data):
            body_bytes = f"data: {json.dumps(data)}\n\n".encode()
            chunk = f"{len(body_bytes):x}\r\n".encode() + body_bytes + b"\r\n"
            self.wfile.write(chunk)
            self.wfile.flush()

        try:
            _sse({"status": "thinking"})

            try:
                system_prompt = self._build_chat_context(context_type, context_id)
            except ValueError as e:
                _sse({"error": str(e)})
                return
            except Exception as e:
                _sse({"error": f"Context error: {e}"})
                return

            # For winner chats: detect ticker symbols mentioned across the conversation and
            # inject verified company names so the model cannot hallucinate what they are.
            if context_type == "winner":
                try:
                    import re as _re
                    all_text = " ".join(m.get("content", "") for m in messages)
                    # Match 2-5 uppercase letters (optionally with a hyphen suffix like BRK-B)
                    raw_tickers = _re.findall(r'\b([A-Z]{2,5}(?:-[A-Z])?)\b', all_text)
                    # Filter obvious non-tickers (common English words / units)
                    _skip = {"I", "A", "AN", "THE", "AND", "OR", "VS", "FOR", "TO",
                             "IN", "OF", "AT", "IS", "IT", "BE", "NO", "IF", "ON",
                             "AI", "DTE", "OTM", "ITM", "ATM", "IV", "HV", "PE",
                             "ETF", "FCF", "YTD", "SP", "SPY", "EPS", "USA", "US",
                             "CEO", "CFO", "IPO", "YOY", "QOQ", "TTM", "LT", "ST"}
                    candidate_tickers = [t for t in set(raw_tickers)
                                         if t not in _skip and t != context_id.upper()]
                    if candidate_tickers:
                        names = _fetch_ticker_names(candidate_tickers)
                        if names:
                            grounding = "\n\nVERIFIED COMPANY NAMES (from live data — use these exactly, do not substitute):\n"
                            grounding += "\n".join(f"  {t}: {n}" for t, n in names.items())
                            system_prompt += grounding
                except Exception:
                    pass

            # For CC chats: fetch live option chain data for expiries the user asks about.
            # Reuse the expiration list already embedded in the system prompt to avoid a
            # duplicate yfinance network call.
            if context_type == "cc":
                try:
                    import re as _re2
                    from datetime import datetime as _dt2, timedelta as _td2
                    last_user_msg = next(
                        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                        ""
                    )
                    _exp_m = _re2.search(
                        r'All available expiry dates for \S+: ([0-9,\- ]+)', system_prompt
                    )
                    all_exps = (
                        [x.strip() for x in _exp_m.group(1).split(',') if x.strip()]
                        if _exp_m else []
                    )

                    def _already_has(exp):
                        return (f"exp {exp}" in system_prompt or f"— {exp} (" in system_prompt)

                    # Detect "shorter duration / near term / next N weeks" requests —
                    # fetch all expiries within the implied window that aren't already loaded.
                    msg_lower = last_user_msg.lower()
                    _near_term_words = ("shorter", "short duration", "near term", "near-term",
                                        "near expir", "next few", "next 1", "next 2", "next 3",
                                        "next 4", "1 week", "2 week", "3 week", "4 week",
                                        "this week", "coming week")
                    is_near_term_req = any(w in msg_lower for w in _near_term_words)

                    # Also detect "next N weeks" / "next N days" for a specific window
                    _window_days = 0
                    _wk_m = _re2.search(r'next\s+(\d+)\s+week', msg_lower)
                    _dy_m = _re2.search(r'next\s+(\d+)\s+day', msg_lower)
                    if _wk_m:
                        _window_days = int(_wk_m.group(1)) * 7
                    elif _dy_m:
                        _window_days = int(_dy_m.group(1))
                    elif is_near_term_req:
                        _window_days = 35  # default: ~5 weeks for generic "shorter" requests

                    if _window_days > 0 and all_exps:
                        cutoff = _dt2.now().date() + _td2(days=_window_days)
                        to_fetch = [
                            e for e in all_exps
                            if _dt2.strptime(e, "%Y-%m-%d").date() <= cutoff and not _already_has(e)
                        ]
                        for exp in to_fetch[:6]:  # cap at 6 expiries to avoid huge prompts
                            system_prompt += _fetch_options_for_chat(context_id, exp)
                    else:
                        # Fall back to single-expiry detection by month name / date mention
                        target_exp = _detect_expiry_from_message(last_user_msg, all_exps)
                        if target_exp and not _already_has(target_exp):
                            system_prompt += _fetch_options_for_chat(context_id, target_exp)
                except Exception:
                    pass

            import queue as _queue
            _tok_q = _queue.Queue()
            full_messages = [{"role": "system", "content": system_prompt}] + messages

            def _generate():
                try:
                    for tok in ollama_client.stream_chat(full_messages, model=ollama_client.DEFAULT_MODEL):
                        _tok_q.put(("token", tok))
                    _tok_q.put(("done", None))
                except Exception as exc:
                    _tok_q.put(("error", str(exc)))

            threading.Thread(target=_generate, daemon=True).start()

            while True:
                try:
                    kind, val = _tok_q.get(timeout=10)
                except _queue.Empty:
                    _sse({"status": "thinking"})
                    continue
                if kind == "token":
                    _sse({"token": val})
                elif kind == "done":
                    _sse({"done": True})
                    break
                else:
                    _sse({"error": val})
                    break
        except Exception:
            pass
        finally:
            _chat_active.discard(chat_key)
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass

    def _handle_cc_evaluate(self):
        try:
            from covered_call_rec import evaluate_open_position
            db_path = Path(__file__).parent / "out" / "investment.db"
            with sqlite3.connect(db_path) as con:
                rows = con.execute(
                    "SELECT id, ticker, contracts, strike, expiry, "
                    "premium_per_contract, current_mark FROM cc_positions "
                    "WHERE status='open' ORDER BY expiry"
                ).fetchall()

            if not rows:
                return self._json({"ok": True, "evaluations": []})

            evaluations = []
            for (pos_id, ticker, contracts, strike, expiry,
                 premium_per_contract, current_mark) in rows:
                try:
                    ev = evaluate_open_position(
                        ticker=ticker,
                        strike=float(strike),
                        expiry=expiry,
                        original_premium=float(premium_per_contract),
                        current_mark=float(current_mark) if current_mark is not None else None,
                    )
                    ev["id"]        = pos_id
                    ev["ticker"]    = ticker
                    ev["contracts"] = contracts
                    ev["strike"]    = float(strike)
                    ev["expiry"]    = expiry
                    ev["premium"]   = float(premium_per_contract)
                    evaluations.append(ev)
                except Exception as e:
                    evaluations.append({
                        "id": pos_id, "ticker": ticker, "contracts": contracts,
                        "strike": float(strike), "expiry": expiry,
                        "premium": float(premium_per_contract),
                        "error": str(e),
                        "recommendation": "unknown", "reason": str(e),
                    })

            self._json({"ok": True, "evaluations": evaluations})
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
                        freq      = (12 if avg_days < 45 else
                                     6 if avg_days < 75 else
                                     4 if avg_days < 130 else
                                     2 if avg_days < 250 else 1)
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
            # Discard pay dates that are in the past or before the ex-div date
            if pay_date:
                try:
                    pay_dt = datetime.strptime(pay_date, "%Y-%m-%d").date()
                    ex_dt  = datetime.strptime(ex_date,  "%Y-%m-%d").date() if ex_date else None
                    if pay_dt < today or (ex_dt and pay_dt < ex_dt):
                        pay_date = None
                except Exception:
                    pay_date = None
            # Prefer stockanalysis.com pay date over yfinance (Yahoo is often 1 day early)
            if ex_date:
                try:
                    from datetime import timedelta as _td
                    sa_map = _fetch_sa_pay_date(ticker)
                    candidate = _sa_lookup_pay_date(sa_map, ex_date)
                    if candidate:
                        ex_dt  = datetime.strptime(ex_date, "%Y-%m-%d").date()
                        pay_dt = datetime.strptime(candidate, "%Y-%m-%d").date()
                        if ex_dt <= pay_dt <= ex_dt + _td(days=90):
                            pay_date = candidate
                except Exception:
                    pass

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
                    # Discard pay dates that are before the ex-div date (impossible)
                    # or more than 90 days after ex-div (yfinance returns wrong-cycle
                    # annual dates for WMT/GRMN etc). Past pay dates are kept for
                    # LAST KNOWN rows where they correctly show when payment occurred.
                    pay_date_estimated = False
                    if pay_date:
                        try:
                            from datetime import timedelta as _td
                            pay_dt = datetime.strptime(pay_date, "%Y-%m-%d").date()
                            ex_dt  = datetime.strptime(ex_date,  "%Y-%m-%d").date() if ex_date else None
                            if ((ex_dt and pay_dt < ex_dt)
                                    or (ex_dt and pay_dt > ex_dt + _td(days=90))):
                                pay_date = None
                        except Exception:
                            pay_date = None

                    # Supplemental pay date lookup — always prefer stockanalysis.com
                    # over yfinance when SA has data for this ex-date, since Yahoo
                    # Finance consistently returns pay dates that are 1 day early.
                    if ex_date:
                        from datetime import timedelta as _td
                        ex_dt = datetime.strptime(ex_date, "%Y-%m-%d").date()
                        if ticker in _MUTUAL_FUND_TICKERS:
                            if not pay_date:
                                # Vanguard/Fidelity funds pay on or 1 business day after ex-div
                                pay_date = _next_business_day(ex_dt, 1).strftime("%Y-%m-%d")
                                pay_date_estimated = True
                        else:
                            # Try stockanalysis.com (stocks + ETFs) — overrides yfinance when found
                            try:
                                sa_map = _fetch_sa_pay_date(ticker)
                                candidate = _sa_lookup_pay_date(sa_map, ex_date)
                                if candidate:
                                    pay_dt = datetime.strptime(candidate, "%Y-%m-%d").date()
                                    if ex_dt <= pay_dt <= ex_dt + _td(days=90):
                                        pay_date = candidate
                                        pay_date_estimated = False
                            except Exception:
                                pass

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
                    pay_pending = (
                        not is_upcoming
                        and pay_date is not None
                        and datetime.strptime(pay_date, "%Y-%m-%d").date() >= today
                    )

                    # Compute qualifying shares: only lots purchased on or before
                    # the ex-div date receive the payout.  Lots with no purchase
                    # date are assumed to qualify (owned before any tracked ex-div).
                    lots = meta.get("lots") or [(meta["shares"], meta.get("purchase_date"))]
                    if ex_date:
                        try:
                            qualifying_shares = sum(
                                lot_sh for lot_sh, lot_pd in lots
                                if not lot_pd or lot_pd <= ex_date
                            )
                        except Exception:
                            qualifying_shares = shares
                    else:
                        qualifying_shares = shares

                    # If no shares qualify for this cycle, suppress upcoming/pending flags.
                    if qualifying_shares <= 0:
                        pay_pending = False
                        is_upcoming = False
                        days_to_ex  = None

                    row.update({
                        "ex_div_date":        ex_date,
                        "pay_date":           pay_date,
                        "pay_date_estimated": pay_date_estimated,
                        "declared_amount":    last_amount,
                        "annual_rate":        annual_rate,
                        "div_yield":          div_yield,
                        "yield_on_cost":      yoc,
                        "last_amount":        last_amount,
                        "last_date":          last_date,
                        "total_payout":       round(last_amount * qualifying_shares, 2) if (last_amount and (is_upcoming or pay_pending) and qualifying_shares > 0) else None,
                        "annual_income":      round(annual_rate * shares, 2) if annual_rate else None,
                        "days_to_ex":         days_to_ex,
                        "declared":           is_upcoming,
                        "pay_pending":        pay_pending,
                        "tax_type":           tax_type,
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

            def _div_sort_key(r):
                group = 0 if r.get("declared") else (1 if r.get("pay_pending") else 2)
                dtex  = r.get("days_to_ex") if r.get("days_to_ex") is not None else 9999
                # UPCOMING/PAY DUE: ascending (soonest first)
                # LAST KNOWN: descending (most recent first) — negate the negative days_to_ex
                if group == 2:
                    dtex = -dtex
                return (group, dtex, r["ticker"])

            results.sort(key=_div_sort_key)

            payload = {"ok": True, "results": results, "as_of": today.isoformat()}
            _cache_set(_div_cache, payload)
            self._json(payload)

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_analysis_job_create(self):
        """POST /api/analysis-job  body: {type, ticker, [mode]}"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            return self._json_error(400, "Invalid JSON body")
        kind   = body.get("type", "")
        ticker = (body.get("ticker") or "").upper().strip()
        if not ticker:
            return self._json_error(400, "ticker required")
        if kind == "buffett":
            mode   = (body.get("mode") or "annual").lower()
            job_id = _job_create("buffett")
            threading.Thread(target=_run_buffett_job, args=(job_id, ticker, mode), daemon=True).start()
        elif kind == "cc-ai":
            job_id = _job_create("cc-ai")
            threading.Thread(target=_run_cc_ai_job, args=(job_id, ticker), daemon=True).start()
        else:
            return self._json_error(400, f"Unknown analysis type: {kind!r}")
        self._json({"ok": True, "job_id": job_id})

    def _handle_analysis_job_poll(self, job_id):
        """GET /api/analysis-job/<id>"""
        job = _job_get(job_id)
        if job is None:
            return self._json_error(404, "Job not found or expired")
        self._json({
            "ok":       True,
            "status":   job["status"],
            "kind":     job["kind"],
            "progress": job["progress"],
            "result":   job["result"],
            "error":    job["error"],
        })

    def _handle_buffett_analysis(self, params):
        ticker_symbol = (params.get("ticker", [None])[0] or "").upper().strip()
        mode = (params.get("mode", ["annual"])[0] or "annual").lower()
        if not ticker_symbol:
            self._json({"ok": False, "error": "ticker required"})
            return
        try:
            import yfinance as yf
            import pandas as pd

            stock = yf.Ticker(ticker_symbol)

            if mode == "ttm":
                income_stmt   = stock.quarterly_financials
                balance_sheet = stock.quarterly_balance_sheet
                cash_flow     = stock.quarterly_cashflow
            else:
                income_stmt   = stock.financials
                balance_sheet = stock.balance_sheet
                cash_flow     = stock.cashflow

            if income_stmt.empty:
                self._json({"ok": False, "error": f"No financial data found for {ticker_symbol}"})
                return

            def get_val(df, keys, col=0):
                if isinstance(keys, str):
                    keys = [keys]
                for key in keys:
                    if key in df.index:
                        try:
                            if col < df.shape[1]:
                                v = df.iloc[df.index.get_loc(key), col]
                                if not pd.isna(v):
                                    return float(v)
                        except Exception:
                            pass
                return 0.0

            def get_flow(df, keys):
                """Annual: col 0. TTM: sum last 4 quarters."""
                if mode != "ttm":
                    return get_val(df, keys, 0)
                if isinstance(keys, str):
                    keys = [keys]
                for key in keys:
                    if key in df.index:
                        try:
                            n = min(4, df.shape[1])
                            vals = [float(df.iloc[df.index.get_loc(key), i])
                                    for i in range(n)
                                    if not pd.isna(df.iloc[df.index.get_loc(key), i])]
                            if vals:
                                return sum(vals)
                        except Exception:
                            pass
                return 0.0

            # For growth comparisons in TTM mode: compare most recent quarter (col 0)
            # vs same quarter last year (col 4); fall back to col 1 if < 5 cols available
            def prior_col(df):
                if mode == "ttm":
                    return 4 if df.shape[1] > 4 else (1 if df.shape[1] > 1 else 0)
                return 1

            revenue         = get_flow(income_stmt, ["Total Revenue", "Revenue"])
            gross_profit    = get_flow(income_stmt, ["Gross Profit", "Net Interest Income"])
            sga             = get_flow(income_stmt, ["Selling General And Administration", "Operating Expense"])
            rnd             = get_flow(income_stmt, "Research And Development")
            depreciation    = get_flow(cash_flow,  ["DepreciationAndAmortization", "Depreciation"])
            if depreciation == 0:
                depreciation = get_flow(income_stmt, "Reconciled Depreciation")
            interest_exp    = get_flow(income_stmt, ["Interest Expense", "Interest Expense Non Operating"])
            op_income       = get_flow(income_stmt, ["Operating Income", "Operating Profit"])
            net_income      = get_flow(income_stmt, ["Net Income", "Net Income Common Stockholders"])
            eps_current     = get_val(income_stmt,   "Basic EPS", 0)
            eps_prev        = get_val(income_stmt,   "Basic EPS", prior_col(income_stmt))
            cash            = get_val(balance_sheet, ["Cash And Cash Equivalents", "Cash Financial"])
            total_debt      = get_val(balance_sheet, ["Total Debt", "Long Term Debt"])
            equity          = get_val(balance_sheet, ["Stockholders Equity", "Total Equity Gross Minority Interest"])
            treasury_stock  = get_val(balance_sheet, "Treasury Stock")
            preferred_stock = get_val(balance_sheet, "Preferred Stock")
            re_cur          = get_val(balance_sheet, "Retained Earnings", 0)
            re_1            = get_val(balance_sheet, "Retained Earnings", prior_col(balance_sheet))
            capex           = abs(get_flow(cash_flow, ["Capital Expenditure", "Capital Expenditures"]))

            is_financial = (gross_profit == 0 and revenue > 0)
            results = []

            def check(metric, value_str, criteria, passed, note=""):
                results.append({"Metric": metric, "Value": value_str, "Criteria": criteria,
                                 "Result": "PASS" if passed else "FAIL", "Note": note})

            # 1. Gross Margin
            gm = (gross_profit / revenue) if revenue else 0
            if is_financial:
                results.append({"Metric": "Gross Margin", "Value": "N/A", "Criteria": "> 40%",
                                 "Result": "N/A", "Note": "Bank / Insurer"})
                gp_valid = False
            else:
                check("Gross Margin", f"{gm:.1%}", "> 40%", gm > 0.40)
                gp_valid = gross_profit > 0

            # 2-4. Expense margins
            if gp_valid:
                check("SG&A Margin",         f"{sga/gross_profit:.1%}",         "< 30%", sga/gross_profit < 0.30)
                check("R&D Margin",          f"{rnd/gross_profit:.1%}",         "< 30%", rnd/gross_profit < 0.30)
                check("Depreciation Margin", f"{depreciation/gross_profit:.1%}","< 10%", depreciation/gross_profit < 0.10)
            else:
                for m in ["SG&A Margin", "R&D Margin", "Depreciation Margin"]:
                    check(m, "Neg/Zero GP", m.split()[0], False)

            # 5. Interest margin
            if op_income > 0:
                check("Interest Margin", f"{interest_exp/op_income:.1%}", "< 15%", interest_exp/op_income < 0.15)
            else:
                check("Interest Margin", "Neg Op Inc", "< 15%", False, "Op Income negative")

            # 6. Net income margin
            nm = (net_income / revenue) if revenue else 0
            check("Net Income Margin", f"{nm:.1%}", "> 20%", nm > 0.20)

            # 7. EPS growth
            check("EPS Growth", f"${eps_current:.2f} vs ${eps_prev:.2f}", "Trend Up", eps_current > eps_prev)

            # 8. Retained earnings
            check("Retained Earnings", "Trending up" if re_cur > re_1 else "Declining",
                  "Growth", re_cur > re_1)

            # 9. Cash vs debt
            check("Cash vs Debt",
                  f"${cash/1e9:.2f}B vs ${total_debt/1e9:.2f}B", "Cash > Debt", cash > total_debt)

            # 10. Debt / equity
            if equity > 0:
                de = total_debt / equity
                check("Debt / Equity", f"{de:.2f}", "< 0.80", de < 0.80)
            else:
                check("Debt / Equity", "Neg Equity", "< 0.80", False)

            # 11. Preferred stock
            check("Preferred Stock", f"${preferred_stock/1e6:.1f}M" if preferred_stock else "$0",
                  "None", preferred_stock == 0)

            # 12. Buybacks
            check("Share Buybacks", f"${treasury_stock/1e6:.1f}M" if treasury_stock else "$0",
                  "Present", treasury_stock != 0)

            # 13. CapEx margin
            if net_income > 0:
                cm = capex / net_income
                check("CapEx / Net Income", f"{cm:.1%}", "< 25%", cm < 0.25)
            else:
                check("CapEx / Net Income", "Neg Net Inc", "< 25%", False, "Net income negative")

            try:
                price = float(stock.history(period="1d")["Close"].iloc[-1])
            except Exception:
                price = 0.0

            score = sum(1 for r in results if r["Result"] == "PASS")

            # Derive a human-readable period label from the most recent filing date.
            period_label = None
            try:
                col = income_stmt.columns[0]
                col_dt = pd.Timestamp(col)
                yr = col_dt.year
                mo = col_dt.strftime("%b")
                day = col_dt.strftime("%d").lstrip("0")
                if mode == "ttm":
                    qtr = (col_dt.month - 1) // 3 + 1
                    period_label = f"TTM as of Q{qtr} {yr} (ended {mo} {day}, {yr})"
                    n_q = len(income_stmt.columns)
                    quarters_used = min(4, n_q)
                    period_label += f" · {quarters_used}Q summed"
                else:
                    if col_dt.month == 12:
                        period_label = f"FY {yr} annual (Dec {day}, {yr})"
                    else:
                        period_label = f"FY {yr} annual (fiscal year ended {mo} {day}, {yr})"
                    n_years = len(income_stmt.columns)
                    if n_years > 1:
                        period_label += f" · most recent of {n_years} available"
            except Exception:
                period_label = None

            self._json({"ok": True, "ticker": ticker_symbol, "price": price,
                        "score": score, "max_score": len(results), "results": results,
                        "period_label": period_label})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_buffett_winners(self):
        try:
            from datetime import datetime as _dt
            db = PROJECT_DIR / "out" / "buffett.db"
            if not db.exists():
                return self._json({"ok": True, "winners": [], "meta": {},
                                   "cache_count": 0, "scan_running": False,
                                   "eta_seconds": None, "scan_duration": None,
                                   "log_tail": []})

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

            # Exclude tickers already owned — they'll reappear if sold
            try:
                from covered_call_rec import load_holdings as _lh
                _owned = set(_lh().keys())
            except Exception:
                _owned = set()
            winners = [w for w in winners if w["ticker"] not in _owned]

            for w in winners:
                w["first_seen"] = first_seen.get(w["ticker"])
                if w.get("ai_analysis"):
                    try:
                        w["ai_analysis"] = json.loads(w["ai_analysis"])
                    except (ValueError, json.JSONDecodeError):
                        w["ai_analysis"] = None

            scan_running = False
            lock = PROJECT_DIR / "out" / "buffett_screener.lock"
            if lock.exists():
                try:
                    pid = int(lock.read_text().strip())
                    os.kill(pid, 0)
                    scan_running = True
                except (ProcessLookupError, ValueError, OSError):
                    pass
            # Grace window: subprocess is still starting up (no lock file yet)
            if not scan_running and time.time() < _scan_launching_until:
                scan_running = True

            eta_seconds = None
            tickers_scanned = int(meta.get("tickers_scanned") or 0)
            total_tickers   = int(meta.get("total_tickers") or 2348)
            if scan_running and tickers_scanned > 0 and meta.get("scan_started"):
                try:
                    started = _dt.strptime(meta["scan_started"], "%Y-%m-%d %H:%M:%S")
                    elapsed = max((_dt.now() - started).total_seconds(), 5.0)
                    rate    = tickers_scanned / elapsed
                    if rate > 0:
                        eta_seconds = int((total_tickers - tickers_scanned) / rate)
                except Exception:
                    pass

            # Duration of last completed scan
            scan_duration = None
            if meta.get("scan_started") and meta.get("last_scan"):
                try:
                    s = _dt.strptime(meta["scan_started"], "%Y-%m-%d %H:%M:%S")
                    e = _dt.strptime(meta["last_scan"],    "%Y-%m-%d %H:%M:%S")
                    d = int((e - s).total_seconds())
                    if 0 < d < 7200:
                        scan_duration = d
                except Exception:
                    pass

            # Last 20 lines of screener log for the UI error/status panel.
            # Strip Python traceback lines to avoid leaking file paths to the browser.
            log_tail = []
            try:
                log_path = PROJECT_DIR / "out" / "screener.log"
                if log_path.exists():
                    _tb_prefixes = ("Traceback (", "  File ", "    ", "During handling")
                    all_lines = log_path.read_text(errors="replace").splitlines()
                    log_tail = [
                        ln for ln in all_lines[-40:]
                        if not any(ln.startswith(p) for p in _tb_prefixes)
                    ][-20:]
            except Exception:
                pass

            self._json({"ok": True, "winners": winners, "meta": meta,
                        "cache_count": cache_count, "scan_running": scan_running,
                        "eta_seconds": eta_seconds, "scan_duration": scan_duration,
                        "log_tail": log_tail})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_buffett_scan_trigger(self):
        """POST /api/buffett-scan — start a manual scan if one isn't already running."""
        global _scan_launching_until
        import subprocess, threading
        lock = PROJECT_DIR / "out" / "buffett_screener.lock"
        if lock.exists():
            try:
                pid = int(lock.read_text().strip())
                os.kill(pid, 0)
                return self._json({"ok": False, "reason": "already_running", "pid": pid})
            except (ProcessLookupError, ValueError, OSError):
                lock.unlink(missing_ok=True)
        # If we're still in the launch window from a previous trigger, don't double-fire
        if time.time() < _scan_launching_until:
            return self._json({"ok": False, "reason": "already_running"})

        # Set a 90-second grace window so the winners API reports scan_running=True
        # immediately, before the subprocess has had time to write the lock file.
        _scan_launching_until = time.time() + 90

        VENV_PY = PROJECT_DIR / "venv" / "bin" / "python3"
        LOG     = PROJECT_DIR / "out" / "screener.log"

        def _bg():
            global _scan_launching_until
            try:
                with open(LOG, "a") as lf:
                    lf.write(f"\n=== MANUAL SCAN {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                    subprocess.run(
                        [str(VENV_PY), str(PROJECT_DIR / "buffett_screener.py")],
                        cwd=str(PROJECT_DIR), stdout=lf, stderr=lf
                    )
            finally:
                # Once the subprocess exits (success or crash), clear the grace
                # window so the UI immediately stops showing "Scanning".
                _scan_launching_until = 0.0

        threading.Thread(target=_bg, daemon=True).start()
        self._json({"ok": True, "started": True})

    def _handle_buffett_ai_analyze(self):
        """POST /api/buffett-ai-analyze  body: {"ticker": "AAPL"}"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            return self._json_error(400, "Invalid JSON body")
        ticker = (body.get("ticker") or "").upper().strip()
        if not ticker:
            return self._json_error(400, "ticker required")

        # Return cached analysis if it's fresh (within 7 days)
        db = PROJECT_DIR / "out" / "buffett.db"
        if db.exists():
            try:
                conn = sqlite3.connect(str(db), timeout=5)
                row = conn.execute(
                    "SELECT ai_analysis, ai_analysis_at FROM buffett_winners "
                    "WHERE ticker=? AND ai_analysis IS NOT NULL "
                    "AND ai_analysis_at >= date('now', '-7 days')",
                    (ticker,)
                ).fetchone()
                conn.close()
                if row:
                    try:
                        analysis = json.loads(row[0])
                        # Only use cache if it has the redundancy field (analyses before
                        # holdings were wired in lack it and need to be re-run)
                        if "redundancy" in analysis:
                            return self._json({"ok": True, "cached": True,
                                               "ticker": ticker, "analysis": analysis})
                    except Exception:
                        pass
            except Exception:
                pass

        job_id = _job_create("buffett-ai")
        threading.Thread(target=_run_buffett_ai_job, args=(job_id, ticker), daemon=True).start()
        self._json({"ok": True, "job_id": job_id})

    def _handle_buffett_layer_compare(self):
        """POST /api/buffett-layer-compare  body: {"layer": 2}"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            return self._json_error(400, "Invalid JSON body")
        layer_num = body.get("layer")
        if layer_num is None:
            return self._json_error(400, "layer required")
        try:
            layer_num = int(layer_num)
        except (ValueError, TypeError):
            return self._json_error(400, "layer must be an integer")
        if layer_num not in (1, 2, 3, 4, 5):
            return self._json_error(400, "layer must be 1–5")

        job_id = _job_create("buffett-layer-compare")
        threading.Thread(target=_run_buffett_layer_compare_job,
                         args=(job_id, layer_num), daemon=True).start()
        self._json({"ok": True, "job_id": job_id})

    def _handle_tlh_analysis(self):
        """GET /api/tlh-analysis — unrealized P&L per lot for tax-loss harvesting."""
        import yfinance as yf
        from datetime import date, datetime

        db = PROJECT_DIR / "out" / "investment.db"
        conn = sqlite3.connect(str(db), timeout=10)
        conn.row_factory = sqlite3.Row
        lots = conn.execute(
            "SELECT id, ticker, shares, cost_per_share, purchase_date, notes FROM cost_lots ORDER BY ticker, purchase_date"
        ).fetchall()
        conn.close()

        if not lots:
            self._json({"positions": []})
            return

        tickers = sorted(set(r[1] for r in lots))
        today = date.today()

        # fetch current prices
        prices = {}
        for t in tickers:
            try:
                fi = yf.Ticker(t).fast_info
                p = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
                if p:
                    prices[t] = float(p)
            except Exception:
                pass

        # build lot-level data, aggregate per ticker
        positions = {}
        for lot_id, ticker, shares, cost_per_share, purchase_date, notes in lots:
            price = prices.get(ticker)
            if price is None:
                continue

            acquired = datetime.strptime(purchase_date, "%Y-%m-%d").date()
            days_held = (today - acquired).days
            is_lt = days_held > 365

            cost_basis = shares * cost_per_share
            mkt_value  = shares * price
            pnl        = mkt_value - cost_basis

            lot = {
                "id": lot_id,
                "shares": shares,
                "cost_per_share": round(cost_per_share, 4),
                "purchase_date": purchase_date,
                "days_held": days_held,
                "is_lt": is_lt,
                "cost_basis": round(cost_basis, 2),
                "mkt_value": round(mkt_value, 2),
                "pnl": round(pnl, 2),
                "notes": notes or "",
            }

            if ticker not in positions:
                positions[ticker] = {
                    "ticker": ticker,
                    "price": round(price, 4),
                    "total_shares": 0.0,
                    "total_cost": 0.0,
                    "total_value": 0.0,
                    "total_pnl": 0.0,
                    "st_pnl": 0.0,
                    "lt_pnl": 0.0,
                    "lots": [],
                }

            p = positions[ticker]
            p["lots"].append(lot)
            p["total_shares"] += shares
            p["total_cost"]   += cost_basis
            p["total_value"]  += mkt_value
            p["total_pnl"]    += pnl
            if is_lt:
                p["lt_pnl"] += pnl
            else:
                p["st_pnl"] += pnl

        # round aggregates
        result = []
        for p in positions.values():
            p["total_shares"] = round(p["total_shares"], 4)
            p["total_cost"]   = round(p["total_cost"], 2)
            p["total_value"]  = round(p["total_value"], 2)
            p["total_pnl"]    = round(p["total_pnl"], 2)
            p["st_pnl"]       = round(p["st_pnl"], 2)
            p["lt_pnl"]       = round(p["lt_pnl"], 2)
            p["avg_cost"]     = round(p["total_cost"] / p["total_shares"], 4) if p["total_shares"] else 0
            result.append(p)

        result.sort(key=lambda x: x["total_pnl"])  # losers first
        self._json({"positions": result})

    def _handle_refresh_dashboard(self):
        """POST /api/refresh-dashboard — fetch fresh prices, update DB, regenerate dashboard (no email).
        Returns a job_id immediately so the browser can poll rather than holding the connection open."""
        job_id = _job_create("refresh")
        threading.Thread(target=_run_refresh_job, args=(job_id,), daemon=True).start()
        self._json({"ok": True, "job_id": job_id})

    # ── Macro + Portfolio AI endpoints ────────────────────────────────────────

    def _handle_macro(self):
        """GET /api/macro — return cached macro context JSON (fetches if stale)."""
        try:
            import macro_context
            ctx = macro_context.fetch()
            # Strip internal fields before sending
            public = {k: v for k, v in ctx.items() if not k.startswith("_")}
            self._json({"ok": True, "macro": public})
        except Exception as e:
            self._json_error(500, f"Macro fetch failed: {e}")

    def _handle_holding_news(self, qs: dict):
        """GET /api/holding-news — news articles mentioning portfolio holdings."""
        try:
            import csv as _csv
            holdings_path = PROJECT_DIR / "holdings.csv"
            tickers = []
            if holdings_path.exists():
                with open(holdings_path, newline="") as f:
                    for row in _csv.DictReader(f):
                        t = str(row.get("Stock", "")).strip().upper()
                        if t:
                            tickers.append(t)
            tickers = list(dict.fromkeys(tickers))  # deduplicate, preserve order

            import news_fetcher
            force = qs.get("force", ["0"])[0] == "1"
            result = news_fetcher.fetch(tickers, force=force)
            self._json({"ok": True,
                        "by_ticker": result.get("by_ticker", {}),
                        "fetched_at": result.get("_fetched_at", 0)})
        except Exception as e:
            self._json_error(500, f"News fetch failed: {e}")

    def _handle_news_summary(self, qs: dict):
        """GET /api/news-summary — AI-generated per-ticker news summaries + macro angle.
        ?force=1 triggers regeneration. Returns status='generating' while running."""
        global _news_summary_generating
        import portfolio_ai

        force = qs.get("force", ["0"])[0] == "1"
        today = __import__("datetime").date.today().isoformat()

        if force:
            with _news_summary_lock:
                already = _news_summary_generating
                if not already:
                    _news_summary_generating = True
            if not already:
                def _run():
                    global _news_summary_generating
                    try:
                        portfolio_ai.generate_news_summaries(force=True)
                    except Exception as e:
                        print(f"[news-summary] generation failed: {e}")
                    finally:
                        with _news_summary_lock:
                            _news_summary_generating = False
                threading.Thread(target=_run, daemon=True).start()
            self._json({"ok": True, "status": "generating", "date": today})
            return

        with _news_summary_lock:
            generating = _news_summary_generating
        if generating:
            self._json({"ok": True, "status": "generating", "date": today})
            return

        cached, generated_at = portfolio_ai.get_cached_news_summaries_today()
        if cached is not None:
            if cached.get("_failed"):
                self._json({"ok": False, "error": cached.get("_error", "Generation failed"), "date": today})
                return
            self._json({"ok": True, "summaries": cached, "date": today, "generated_at": generated_at})
            return

        # No cache — kick off background generation
        with _news_summary_lock:
            already = _news_summary_generating
            if not already:
                _news_summary_generating = True
        if not already:
            def _run_bg():
                global _news_summary_generating
                try:
                    portfolio_ai.generate_news_summaries(force=False)
                except Exception as e:
                    print(f"[news-summary] background generation failed: {e}")
                finally:
                    with _news_summary_lock:
                        _news_summary_generating = False
            threading.Thread(target=_run_bg, daemon=True).start()
        self._json({"ok": True, "status": "generating", "date": today})

    def _handle_refresh_financials(self, qs: dict):
        """GET /api/refresh-financials — trigger a background financials fetch for all holdings."""
        import csv as _csv
        force = qs.get("force", ["0"])[0] == "1"

        def _run():
            try:
                import financials_fetcher
                holdings_path = PROJECT_DIR / "holdings.csv"
                tickers = []
                with open(holdings_path, newline="") as f:
                    for row in _csv.DictReader(f):
                        t = row.get("Stock", "").strip().upper()
                        if t:
                            tickers.append(t)
                tickers = list(dict.fromkeys(tickers))
                financials_fetcher.fetch_all(tickers, force=force)
                print("[Financials] API-triggered refresh complete.")
            except Exception as e:
                print(f"[Financials] API refresh failed: {e}")

        threading.Thread(target=_run, daemon=True).start()
        self._json({"ok": True, "status": "refreshing", "force": force})

    def _handle_ai_daily(self, qs: dict):
        """GET /api/ai/daily — return today's AI portfolio insight.
        ?force=1 kicks off background regeneration and returns immediately with
        status='generating'; client should poll /api/ai/daily (no force) until
        a real insight arrives."""
        global _ai_insight_generating
        import portfolio_ai

        force = qs.get("force", ["0"])[0] == "1"
        today = __import__("datetime").date.today().isoformat()

        if force:
            with _ai_insight_lock:
                already_running = _ai_insight_generating
                if not already_running:
                    _ai_insight_generating = True

            if not already_running:
                def _run():
                    global _ai_insight_generating
                    try:
                        portfolio_ai.generate_daily_insight(force=True)
                    except Exception as e:
                        print(f"[AI daily] background generation failed: {e}")
                    finally:
                        with _ai_insight_lock:
                            _ai_insight_generating = False
                threading.Thread(target=_run, daemon=True).start()

            self._json({"ok": True, "status": "generating", "date": today})
            return

        # Non-force: serve from cache if available; otherwise kick off background
        # generation and return status=generating so the client can poll.
        with _ai_insight_lock:
            generating = _ai_insight_generating

        if generating:
            self._json({"ok": True, "status": "generating", "date": today})
            return

        cached, generated_at = portfolio_ai.get_cached_insight_today()
        if cached:
            self._json({"ok": True, "insight": cached, "date": today, "generated_at": generated_at})
            return

        # No cache and not already running — start background generation
        with _ai_insight_lock:
            already_running = _ai_insight_generating
            if not already_running:
                _ai_insight_generating = True

        if not already_running:
            def _run_bg():
                global _ai_insight_generating
                try:
                    portfolio_ai.generate_daily_insight(force=False)
                except Exception as e:
                    print(f"[AI daily] background generation failed: {e}")
                finally:
                    with _ai_insight_lock:
                        _ai_insight_generating = False
            threading.Thread(target=_run_bg, daemon=True).start()

        self._json({"ok": True, "status": "generating", "date": today})

    def _handle_portfolio_chat(self):
        """POST /api/ai/chat — SSE streaming chat with portfolio + macro context as system prompt.
        Body: {"messages": [{"role": "user", "content": "..."}]}"""
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")

        messages = body.get("messages", [])
        if not messages:
            return self._json_error(400, "messages array required")

        chat_key = "portfolio:global"
        if chat_key in _chat_active:
            return self._json_error(429, "already_streaming — close the other chat first")
        _chat_active.add(chat_key)

        try:
            import portfolio_ai
            system_prompt = portfolio_ai.build_portfolio_system_prompt()
        except Exception as e:
            _chat_active.discard(chat_key)
            return self._json_error(500, f"Context build failed: {e}")

        import queue as _queue
        _tok_q = _queue.Queue()
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        def _sse(data):
            payload = f"data: {json.dumps(data)}\n\n".encode()
            chunk = f"{len(payload):x}\r\n".encode() + payload + b"\r\n"
            self.wfile.write(chunk)
            self.wfile.flush()

        def _generate():
            try:
                for tok in ollama_client.stream_chat(
                    full_messages, model=ollama_client.DEFAULT_MODEL,
                    temperature=0.4, num_predict=3500
                ):
                    _tok_q.put(("token", tok))
                _tok_q.put(("done", None))
            except Exception as exc:
                _tok_q.put(("error", str(exc)))

        try:
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Cache-Control: no-cache\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"X-Accel-Buffering: no\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            self.wfile.flush()
            threading.Thread(target=_generate, daemon=True).start()
            while True:
                try:
                    kind, val = _tok_q.get(timeout=10)
                except _queue.Empty:
                    _sse({"status": "thinking"})
                    continue
                if kind == "token":
                    _sse({"token": val})
                elif kind == "done":
                    _sse({"status": "done"})
                    break
                elif kind == "error":
                    _sse({"error": val})
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            _chat_active.discard(chat_key)
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass

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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def _handle_glossary(self):
        html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Investment Dashboard — Glossary</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f4f6f9; color: #1a2340; line-height: 1.6; }
  header { background: #1a2340; color: #fff; padding: 18px 32px;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.3rem; font-weight: 700; }
  header a { color: #a0aec0; font-size: 13px; text-decoration: none; }
  header a:hover { color: #fff; }
  .container { max-width: 900px; margin: 32px auto; padding: 0 20px 60px; }
  .intro { background: #fff; border-radius: 10px; padding: 20px 24px;
           margin-bottom: 28px; border: 1px solid #e8ecf0;
           font-size: 14px; color: #555; }
  h2 { font-size: 1rem; font-weight: 700; color: #1a2340; margin: 32px 0 14px;
       padding-bottom: 6px; border-bottom: 2px solid #e8ecf0; text-transform: uppercase;
       letter-spacing: 0.05em; }
  h2.new { border-bottom-color: #6c5ce7; color: #6c5ce7; }
  .term { background: #fff; border-radius: 8px; border: 1px solid #e8ecf0;
          padding: 14px 18px; margin-bottom: 10px; }
  .term.new { border-left: 3px solid #6c5ce7; }
  .term-name { font-weight: 700; font-size: 14px; color: #1a2340; }
  .term-name .tag { font-size: 10px; font-weight: 600; background: #6c5ce7;
                    color: #fff; padding: 1px 6px; border-radius: 3px;
                    margin-left: 8px; vertical-align: middle; }
  .term-formula { font-family: "SF Mono", "Fira Code", monospace; font-size: 12px;
                  background: #f4f6f9; border-radius: 4px; padding: 4px 10px;
                  margin: 6px 0; display: inline-block; color: #2d3a55; }
  .term-body { font-size: 13px; color: #444; margin-top: 5px; }
  .term-body b { color: #1a2340; }
</style>
</head>
<body>
<header>
  <h1>📖 Glossary</h1>
  <a href="/out/dashboard.html">← Back to Dashboard</a>
</header>
<div class="container">

<div class="intro">
  Definitions for every metric and term used in the Investment Dashboard.
  Terms marked <span style="background:#6c5ce7;color:#fff;font-size:10px;font-weight:600;
  padding:1px 6px;border-radius:3px;">NEW</span> were added in the V2 covered call engine.
</div>

<!-- ── OPTIONS & COVERED CALLS ────────────────────────────────── -->
<h2>Options &amp; Covered Calls — Core Mechanics</h2>

<div class="term">
  <div class="term-name">Covered Call (Buy-Write)</div>
  <div class="term-body">Selling a call option against shares you already own. You collect the
  premium immediately; in exchange you agree to sell your shares at the strike price if the buyer
  exercises. The strategy trades upside potential for income.</div>
</div>

<div class="term">
  <div class="term-name">Strike Price (K)</div>
  <div class="term-body">The price at which your shares would be <b>called away</b> (sold) if the
  option is exercised. You choose a strike above the current price to stay out-of-the-money.</div>
</div>

<div class="term">
  <div class="term-name">DTE — Days to Expiration</div>
  <div class="term-body">Calendar days until the option contract expires. The dashboard filters
  21–60 DTE by default (enough time value without excessive event risk).</div>
</div>

<div class="term">
  <div class="term-name">Bid / Ask / Mid</div>
  <div class="term-body"><b>Bid</b> — highest price a buyer will pay right now.
  <b>Ask</b> — lowest price a seller will accept. <b>Mid</b> — the mathematical midpoint.
  Wide bid-ask spreads indicate an illiquid market; the mid is rarely the actual fill price.</div>
</div>

<div class="term new">
  <div class="term-name">Exec Premium <span class="tag">NEW</span></div>
  <div class="term-formula">Exec = Bid + 0.25 × (Ask − Bid)</div>
  <div class="term-body">Estimated fill price — more realistic than mid for thinly traded options.
  Uses 25% of the spread above bid, reflecting typical retail execution. All profit, yield, and
  alpha calculations use Exec Premium, not Mid.</div>
</div>

<div class="term">
  <div class="term-name">Premium % (Prem%)</div>
  <div class="term-formula">Prem% = Exec Premium / Stock Price</div>
  <div class="term-body">The option income as a percentage of the stock's current value.
  Useful for comparing contracts across different price stocks.</div>
</div>

<div class="term">
  <div class="term-name">Annualized Return (Ann%)</div>
  <div class="term-formula">Ann% = Prem% × (365 / DTE)</div>
  <div class="term-body">Premium yield scaled to a full year. <b>Used for comparison only</b> —
  it assumes you can continuously roll at the same premium, which is unrealistic.
  The V2 engine ranks by Score, not Ann%, to avoid systematically favouring short-DTE contracts.</div>
</div>

<div class="term">
  <div class="term-name">P/L if Called</div>
  <div class="term-formula">(Strike + Exec Premium − Avg Cost) / Avg Cost</div>
  <div class="term-body">Your total return on the original investment <b>if assigned</b>.
  This is the number that matters for profit-floor filtering; premium counts toward the return.
  <b>Floor policy</b>: the engine uses your position-level average cost (not individual tax-lot
  basis). In a FIFO scenario where you hold lots at varying prices, a high-cost lot could be
  assigned at a loss even when the average-cost floor is satisfied — the dashboard does not
  model this per-lot edge case.</div>
</div>

<div class="term">
  <div class="term-name">Assignment</div>
  <div class="term-body">The option buyer exercises their right to buy your shares at the strike
  price. For covered calls this typically happens at expiration when the stock closes above the
  strike, though early assignment is possible for deep ITM contracts near ex-dividend dates.</div>
</div>

<div class="term">
  <div class="term-name">ITM / ATM / OTM</div>
  <div class="term-body"><b>In The Money (ITM)</b> — strike &lt; current price; intrinsic value
  exists, assignment more likely. <b>At The Money (ATM)</b> — strike ≈ current price; maximum
  time value. <b>Out of The Money (OTM)</b> — strike &gt; current price; all value is extrinsic;
  lower assignment risk, lower premium.</div>
</div>

<div class="term">
  <div class="term-name">Intrinsic Value</div>
  <div class="term-formula">max(Stock Price − Strike, 0)</div>
  <div class="term-body">The in-the-money amount of the option. An OTM call has zero intrinsic
  value — its entire price is time/extrinsic value.</div>
</div>

<div class="term">
  <div class="term-name">Extrinsic Value (Time Value)</div>
  <div class="term-formula">Option Price − Intrinsic Value</div>
  <div class="term-body">The portion of the option's price beyond intrinsic value. Decays toward
  zero at expiration. Relevant for early assignment risk: a holder generally won't exercise early
  if doing so forfeits meaningful extrinsic value.</div>
</div>

<div class="term">
  <div class="term-name">Open Interest (OI)</div>
  <div class="term-body">Total number of outstanding contracts at this strike/expiry. Higher OI
  means tighter spreads and easier fills. The dashboard's liquidity score weights OI at 30 points
  out of 100.</div>
</div>

<div class="term">
  <div class="term-name">Roll / Roll Up / Roll Out</div>
  <div class="term-body"><b>Roll</b> — buy back the current call and sell a new one simultaneously.
  <b>Roll out</b> — same strike, later expiry (collects more time value).
  <b>Roll up</b> — higher strike, same or later expiry (raises your cap, often a debit or smaller
  credit). A roll is evaluated as a new trade: it should only be done when the net position beats
  both holding and closing outright.</div>
</div>

<!-- ── V2 ANALYSIS METRICS ────────────────────────────────────── -->
<h2 class="new">V2 Analysis Metrics</h2>

<div class="term new">
  <div class="term-name">CC Alpha $ <span class="tag">NEW</span></div>
  <div class="term-formula">CC Alpha ≈ P − E[(S<sub>T</sub> − K)<sup>+</sup>]<br>
  where E[(S<sub>T</sub> − K)<sup>+</sup>] = S·e<sup>(μ−q)T</sup>·N(d<sub>1,μ</sub>) − K·N(d<sub>2,μ</sub>)<br>
  d<sub>1,μ</sub> = d<sub>2,μ</sub> + σ√T &nbsp;·&nbsp; σ = eff_IV</div>
  <div class="term-body">The <b>expected gain from selling the call versus simply continuing to
  hold the stock</b>. The expected upside surrender is computed under the real-world lognormal
  model with drift μ — not the risk-neutral rate. The premium P is collected today; the
  surrender term occurs at expiration. The formula implicitly assumes r = 0 (i.e., no time-value
  adjustment to P). For typical 21–60 DTE contracts and a 4–5% risk-free rate the error is
  &lt;$0.03 on a $3 premium — immaterial in practice.<br><br>
  <b>Positive</b> (green) — selling the call adds expected value vs holding.<br>
  <b>Negative</b> (red) — holding outright has higher expected return; consider doing nothing.</div>
</div>

<div class="term new">
  <div class="term-name">Regret % <span class="tag">NEW</span></div>
  <div class="term-formula">Regret % = N(d<sub>2,μ</sub>(B)) &nbsp; where B = K + P<br>
  d<sub>2,μ</sub>(B) = [ln(S/B) + (μ − q − 0.5σ²)T] / (σ√T)</div>
  <div class="term-body">Probability that the stock closes above the <b>regret threshold</b>
  B = K + P at expiration — the price above which selling the call leaves you worse off than
  simply holding. Uses the same physical distribution as Estimated Expiry ITM% and CC Alpha
  (identical μ, q, σ = eff_IV); regret_prob = itm_prob_real(S, K+P, T, σ, μ, q).
  <b>This is lower than the expiry-ITM probability</b>: the stock can finish above the strike
  and you still win, as long as it doesn't run past K + P.</div>
</div>

<div class="term new">
  <div class="term-name">Regret Threshold <span class="tag">NEW</span></div>
  <div class="term-formula">Regret Threshold = Strike + Exec Premium</div>
  <div class="term-body">The stock price above which the covered call <b>underperforms a pure
  hold</b>. Below this level, even if assigned, you captured more value than you gave up.</div>
</div>

<div class="term new">
  <div class="term-name">Score (Multi-Factor) <span class="tag">NEW</span></div>
  <div class="term-formula">Score = 100 × (0.25·A + 0.15·Y + 0.15·V + 0.15·L + 0.15·U + 0.15·R)</div>
  <div class="term-body">0–100 composite for <b>within-ticker contract selection</b>. Uses percentile
  ranks computed across all contracts for this ticker and expiration set, so a 30-DTE 87 and a
  55-DTE 87 for the same stock are genuinely comparable. All inputs ∈ [0,1] before weighting:
  <br><b>A</b> — CC Alpha (25%) — percentile rank; higher alpha = better
  <br><b>Y</b> — Premium yield (15%) — percentile rank
  <br><b>V</b> — IV richness (15%) — percentile rank (clipped at −1 before ranking)
  <br><b>L</b> — Liquidity score (15%) — <em>absolute</em> normalised (Liq/100), not a percentile
  <br><b>U</b> — Upside room (15%) — percentile rank of vol-normalised distance to strike
  <br><b>R</b> — 1 − PctRank(Regret%) (15%) — <em>inverse</em> percentile rank so lower regret = higher score
  <br><br><b>Limitation:</b> because ranks are within-ticker, every stock will produce a contract near 90.
  Do not compare Score across different tickers. Use <b>Opp Score</b> for cross-ticker comparison.</div>
</div>

<div class="term new">
  <div class="term-name">Opp Score (Opportunity Score) <span class="tag">NEW</span></div>
  <div class="term-formula">OppScore = 100 × (0.30·A + 0.20·Y + 0.20·V + 0.15·L + 0.15·R)<br>
  using fixed reference scales, not percentile ranks</div>
  <div class="term-body">Cross-ticker comparable score — MSFT 72 and RIVN 72 represent
  similar opportunity levels. Uses absolute inputs with fixed reference scales so the score
  doesn't inflate just because a contract ranks well within a bad option chain:
  <br><b>A</b> — CC Alpha / S; reference 0–2.5% per contract
  <br><b>Y</b> — Annualized yield; reference 0–20%/yr
  <br><b>V</b> — IV richness; reference −50% to +100%
  <br><b>L</b> — Liquidity score / 100 (absolute)
  <br><b>R</b> — 1 − (Regret% / 40%); 0–40% regret range
  <br><br>Pair with Score: <b>Score</b> answers "which contract is best for this stock?";
  <b>Opp Score</b> answers "which stock currently offers the best covered-call opportunity?"</div>
</div>

<div class="term new">
  <div class="term-name">Liquidity Score <span class="tag">NEW</span></div>
  <div class="term-body">0–100 composite measuring how tradeable the contract is:
  50 pts for bid-ask spread quality (&lt;5% of mid = max points), 30 pts for open interest,
  20 pts for daily volume. Affects the Score ranking. The Exec Premium formula
  (Bid + 0.25 × spread) is fixed — liquidity does not change the λ coefficient.</div>
</div>

<!-- ── PROBABILITY & GREEKS ───────────────────────────────────── -->
<h2>Probability &amp; Greeks</h2>

<div class="term">
  <div class="term-name">Delta (Δ)</div>
  <div class="term-formula">Δ = e<sup>−qT</sup> · N(d<sub>1</sub>)</div>
  <div class="term-body">Rate of change of the option's price per $1 move in the stock.
  Delta is displayed in the table (e.g., 0.26) as a Greeks measure. It is sometimes cited as
  a rough assignment-probability estimate ("25-delta call"), but this is an approximation for
  two reasons: (1) the true risk-neutral ITM probability is N(d<sub>2</sub>), which is somewhat
  lower than delta for low-dividend equities; (2) neither delta nor N(d<sub>2</sub>) accounts for
  real-world stock drift. The table shows delta separately from <b>eITM%</b> (the real-world
  model's ITM estimate) and <b>Regret %</b> for a cleaner probability picture.</div>
</div>

<div class="term new">
  <div class="term-name">Estimated Expiry ITM % <span class="tag">NEW</span></div>
  <div class="term-formula">P(S<sub>T</sub> &gt; K) = N(d<sub>2,μ</sub>)<br>d<sub>2,μ</sub> = [ln(S/K) + (μ − q − 0.5σ²)T] / (σ√T),&nbsp; σ = eff_IV (contract IV if &gt; 1%, else HV forecast)</div>
  <div class="term-body">Estimated probability that the stock price closes <em>above the strike</em>
  at expiration under the real-world drift model. This is <b>not the same as assignment
  probability</b>: American equity calls can be exercised early (particularly around dividends),
  and an ITM finish doesn't guarantee assignment in all scenarios. Use this as a directional
  estimate of how likely the strike is breached at expiry. If μ &lt; r, this will be lower than
  the risk-neutral N(d<sub>2</sub>); for a strong-momentum stock it will be higher.</div>
</div>

<div class="term new">
  <div class="term-name">μ — Real-World Drift <span class="tag">NEW</span></div>
  <div class="term-formula">μ = 0.50·μ<sub>60d</sub> + 0.25·μ<sub>252d</sub> + 0.25·μ<sub>market</sub></div>
  <div class="term-body">Blended estimate of the stock's <b>total-return drift</b>, estimated from
  yfinance dividend-adjusted Close prices (auto_adjust=True). Weights recent 60-day momentum
  most heavily, blends in 1-year trend and a 10% long-run market assumption, then caps at ±50%
  to prevent extreme momentum from dominating. In d<sub>2,μ</sub> the dividend yield q is
  subtracted separately so the formula captures price drift only. Displayed as <b>μ +X.X%/yr</b>.</div>
</div>

<div class="term">
  <div class="term-name">Gamma (Γ)</div>
  <div class="term-formula">Γ = e<sup>−qT</sup> · φ(d<sub>1</sub>) / (S · σ · √T)</div>
  <div class="term-body">Rate of change of delta per $1 move in the stock. High gamma (near
  expiry and near the strike) means delta can shift dramatically on a small stock move.
  Used in the open position evaluator to flag accelerating assignment risk: a 1% stock move
  changes delta by approximately Γ × 0.01 × S.</div>
</div>

<!-- ── VOLATILITY & PRICING ───────────────────────────────────── -->
<h2>Volatility &amp; Pricing</h2>

<div class="term">
  <div class="term-name">IV — Implied Volatility</div>
  <div class="term-body">The market's expectation of future volatility, backed out from current
  option prices using Black-Scholes. Higher IV = more expensive options = more premium income for
  sellers. Shown as ATM IV (at-the-money, nearest expiry).</div>
</div>

<div class="term">
  <div class="term-name">HV — Historical (Realised) Volatility</div>
  <div class="term-body">Actual volatility the stock has exhibited, measured from daily price
  returns and annualised. The dashboard computes HV20 (20-day), HV60 (60-day), HV120 (120-day),
  and an EWMA variant (exponentially weighted, λ=0.94, weights recent moves more heavily).</div>
</div>

<div class="term new">
  <div class="term-name">HV_forecast <span class="tag">NEW</span></div>
  <div class="term-formula">HV_fc = 0.40·HV20 + 0.35·HV<sub>EWMA</sub> + 0.25·HV60</div>
  <div class="term-body">Blended forward-looking volatility estimate used as the denominator in
  IV Richness. Weights recent realised vol more heavily than longer windows.</div>
</div>

<div class="term">
  <div class="term-name">HV Percentile</div>
  <div class="term-body">Percentile of today's 21-day realised volatility within its own 1-year
  distribution. <b>HV Pct 70%</b> means today's vol is higher than 70% of the past year's
  readings — a better environment for selling premium. Note: this is a <em>percentile</em>
  (fraction of observations below current), not a conventional <em>rank</em>
  (HV<sub>curr</sub> − HV<sub>min</sub>) / (HV<sub>max</sub> − HV<sub>min</sub>), which
  can differ substantially when the historical distribution has outliers.</div>
</div>

<div class="term new">
  <div class="term-name">IV Richness <span class="tag">NEW</span></div>
  <div class="term-formula">IV Richness<sub>K,T</sub> = IV<sub>K,T</sub> / HV_forecast − 1</div>
  <div class="term-body">Whether the option is <b>expensive or cheap relative to the model's
  expected realised volatility</b>. Each contract uses its own implied volatility (not the ATM
  IV from the nearest expiry shown in the header), so a contract can appear rich due to
  strike-specific skew rather than a broadly elevated vol environment.
  <br><b>Positive (green, "rich")</b> — market IV exceeds the model's expected realized vol,
  which is generally more favorable for premium sellers, all else equal. Part of any premium
  can reflect compensation for jump risk, gap risk, or other tail risks not captured in
  historical vol.
  <br><b>Negative (red, "cheap")</b> — options are priced below expected realized vol; a
  less favorable environment for selling.
  <br>Distinct from HV Percentile, which measures realized vol vs. its own history.</div>
</div>

<div class="term new">
  <div class="term-name">Expected Move <span class="tag">NEW</span></div>
  <div class="term-formula">Expected Move = S × IV × √T</div>
  <div class="term-body">Approximate one-standard-deviation move in the stock over the option's
  life, in dollar terms (S × IV × √T). This is the standard trader approximation; strictly,
  volatility applies to log-returns, so the formula slightly understates the true sigma move.
  A strike 1.0× the expected move above spot is roughly 1-sigma OTM. Used to normalise strike
  distance across stocks with very different volatilities.</div>
</div>

<!-- ── PORTFOLIO & TAX ────────────────────────────────────────── -->
<h2>Portfolio &amp; Tax</h2>

<div class="term">
  <div class="term-name">Layers (L1–L5)</div>
  <div class="term-body">Portfolio architecture classification:
  <b>L1 Structural Ballast</b> (index funds, BRK.B) ·
  <b>L2 Cash-Flow Engines</b> (dividend payers ≥3% yield) ·
  <b>L3 Compounders</b> (quality growth) ·
  <b>L4 Convexity / Optionality</b> (high upside, high risk — Taleb barbell 10–15%) ·
  <b>L5 Shock Absorbers</b> (low-correlation hedges).</div>
</div>

<div class="term">
  <div class="term-name">TWR — Time-Weighted Return</div>
  <div class="term-body">A return calculation that eliminates the distorting effect of cash flows
  (new money added, positions sold). Each day's return is computed independently and then
  chain-multiplied. This makes the portfolio chart comparable to SPY regardless of when capital
  was deployed.</div>
</div>

<div class="term">
  <div class="term-name">FIFO — First In, First Out</div>
  <div class="term-body">When selling shares, the oldest lot (lowest purchase date) is consumed
  first. IRS default cost basis method. Affects whether a sale is short-term or long-term and
  which cost basis applies to the gain/loss calculation.</div>
</div>

<div class="term">
  <div class="term-name">Tax Lot</div>
  <div class="term-body">A specific purchase tranche: a date, share count, and cost/share. Each
  lot ages independently toward long-term status (held more than one year, per IRS rules).
  The Lots modal shows all lots per holding with their ST/LT badge, unrealized G/L, and days
  until LT conversion.</div>
</div>

<div class="term">
  <div class="term-name">ST / LT — Short-Term / Long-Term Gains</div>
  <div class="term-body"><b>Short-term</b> — held ≤1 year; taxed as ordinary income (up to 37%
  federal). <b>Long-term</b> — held <em>more than</em> 1 year (IRS rule: the holding period begins
  the day <em>after</em> acquisition; sale must occur on a date strictly later than the one-year
  anniversary); taxed at lower capital gains rates (0%, 15%, or 20% depending on income).<br><br>
  <b>Written equity call tax treatment depends on how the position closes (IRS Pub. 550):</b>
  If the call <b>expires</b> or is <b>closed (bought back)</b>, the option gain/loss is generally
  short-term capital gain/loss regardless of how long it was open. If the call is
  <b>exercised</b>, the premium is added to the proceeds from selling the underlying shares,
  and the resulting stock gain/loss generally follows the <em>stock's</em> holding period
  (short- or long-term). Note: qualified-covered-call and straddle rules (IRC §1092) can
  alter the holding-period treatment of the underlying shares. Consult a tax advisor for
  your specific situation.</div>
</div>

<div class="term">
  <div class="term-name">NIIT — Net Investment Income Tax</div>
  <div class="term-body">3.8% federal surtax on investment income (dividends, capital gains,
  net option gains) for taxpayers above $200k (single) / $250k (MFJ) MAGI. NIIT applies to
  <b>net option gains</b>, not the gross premium collected — losses and offsetting positions
  reduce the NII base. Per IRS rules, NIIT applies to the <b>lesser of</b>: (a) total net
  investment income (NII) or (b) the excess of MAGI over the applicable threshold.
  Formula: 0.038 × min(NII, max(0, MAGI − Threshold)).
  The dashboard applies this lesser-of formula using the representative MAGI for your selected
  bracket. Toggle in the Tax Harvesting modal.</div>
</div>

<div class="term">
  <div class="term-name">Yield on Cost</div>
  <div class="term-formula">Yield on Cost = Annual Dividend per Share / Avg Cost per Share</div>
  <div class="term-body">Dividend yield relative to what <em>you</em> paid, not the current market
  price. A position bought cheaply years ago may show a much higher yield on cost than the
  current quoted yield.</div>
</div>

<div class="term">
  <div class="term-name">Ex-Dividend Date</div>
  <div class="term-body">The date you must own shares <b>before</b> to receive the next dividend.
  Buy on or after this date and you miss the payout. For covered calls, an ex-div date inside
  the option window creates early assignment risk: a call holder may exercise early to capture
  the dividend if the dividend exceeds the option's extrinsic value.</div>
</div>

<!-- ── BUFFETT SCREENER ───────────────────────────────────────── -->
<h2>Buffett Screener</h2>

<div class="term">
  <div class="term-name">Gross Margin</div>
  <div class="term-formula">(Revenue − Cost of Goods Sold) / Revenue</div>
  <div class="term-body">How much of each revenue dollar remains after direct production costs.
  Buffett threshold: ≥40%. High gross margins indicate pricing power and durable competitive
  advantage.</div>
</div>

<div class="term">
  <div class="term-name">SG&amp;A / Gross Profit</div>
  <div class="term-body">Selling, General &amp; Administrative expenses as a fraction of gross
  profit. Buffett threshold: ≤30%. Companies spending less to maintain revenue tend to have
  stronger moats.</div>
</div>

<div class="term">
  <div class="term-name">Interest / Operating Income</div>
  <div class="term-body">Debt service burden relative to operating earnings. Buffett threshold:
  ≤15%. Low ratio = company can service debt comfortably even in a downturn.</div>
</div>

<div class="term">
  <div class="term-name">CapEx / Net Income</div>
  <div class="term-body">Capital expenditure intensity. Buffett threshold: ≤25% (screener uses
  ≤50% for a wider net). Capital-light businesses generate free cash flow without heavy
  reinvestment, enabling buybacks and dividends.</div>
</div>

<div class="term">
  <div class="term-name">EV / EBITDA</div>
  <div class="term-body">Enterprise Value divided by Earnings Before Interest, Taxes, Depreciation
  and Amortisation. Capital-structure neutral valuation multiple. Used in the Buffett Deep-Dive
  and Recommended Purchases valuation scoring.</div>
</div>

<div class="term">
  <div class="term-name">P / FCF</div>
  <div class="term-body">Price divided by Free Cash Flow per share. FCF = operating cash flow
  minus capital expenditures — the actual cash the business generates after maintaining its asset
  base. Often more reliable than P/E for capital-intensive industries.</div>
</div>

</div><!-- .container -->
</body>
</html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)


server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)

# Regenerate dashboard on startup so changes to generate_dashboard.py take
# effect immediately after a deploy + service restart.
def _startup_regen():
    try:
        import subprocess as _sp
        dashboard = PROJECT_DIR / "out" / "dashboard.html"
        gen_script = PROJECT_DIR / "generate_dashboard.py"
        if (not dashboard.exists()
                or gen_script.stat().st_mtime > dashboard.stat().st_mtime):
            print("[Startup] generate_dashboard.py is newer than dashboard — regenerating…")
            _venv_py = PROJECT_DIR / "venv" / "bin" / "python3"
            r = _sp.run([str(_venv_py), str(gen_script)], capture_output=True, text=True)
            if r.returncode != 0:
                print(f"[Startup] Dashboard regen failed: {r.stderr.strip()[-200:]}")
            else:
                print("[Startup] Dashboard regenerated.")
    except Exception as _e:
        print(f"[Startup] Dashboard regen error: {_e}")

threading.Thread(target=_startup_regen, daemon=True).start()

url = f"http://localhost:{PORT}/out/dashboard.html"
if sys.stdout.isatty():
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Investment Dashboard → {url}")
    print("Press Ctrl+C to stop.\n")

try:
    server.serve_forever()
except KeyboardInterrupt:
    server.shutdown()
