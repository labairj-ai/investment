#!/usr/bin/env python3
from __future__ import annotations
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
import hmac
import json
from time_utils import now_utc, now_utc_iso, now_utc_space, now_eastern, today_eastern, epoch_to_utc, parse_timestamp, to_eastern, format_eastern
# Logging contract (0674): machine/audit log timestamps are UTC (see now_utc_space()).
# Human-readable operational output may include Eastern context if needed.
# Log ordering must use UTC values, never Eastern-formatted strings.
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
import strategy_config  # validates config/strategy.json at import; raises ConfigurationError on bad config
import agent_db

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
        return cache.get("date") == today_eastern().isoformat()


def _cache_set(cache, data):
    with _data_cache_lock:
        cache["data"] = data
        cache["ts"]   = time.time()
        cache["date"] = today_eastern().isoformat()


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

_thesis_jobs: dict = {}    # job_id -> {status, draft?, error?} for async thesis drafting

_chat_active: set = set()  # tracks in-flight chat streams by "context_type:ticker"
_ai_insight_lock = threading.Lock()
_ai_insight_generating = False  # True while background generation is running

_news_summary_lock = threading.Lock()
_news_summary_generating = False

_comparison_cache: dict | None = None      # cached score_for_comparison result
_comparison_cache_at: float = 0.0          # monotonic time of last cache fill
_COMPARISON_CACHE_TTL = 900.0              # 15 minutes — LLM result is stable


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

# Per-account execution locks — prevents concurrent cycle runs in ThreadingHTTPServer (0310).


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


def _render_urgent_email(rec: dict) -> str:
    action  = rec.get("action", "ACTION")
    ticker  = rec.get("ticker", "—")
    why_now = rec.get("why_now") or ""
    rat     = rec.get("rationale") or ""
    score   = rec.get("recommendation_score", "—")
    return f"""<html><body style="font-family:sans-serif;background:#0d1117;color:#e2e8f0;padding:24px;">
<div style="max-width:560px;margin:0 auto;background:#1a2340;border-radius:10px;padding:24px;border:2px solid #e53e3e;">
  <div style="font-size:11px;font-weight:700;letter-spacing:.1em;color:#fc8181;text-transform:uppercase;margin-bottom:8px;">⚡ Urgent Action Required</div>
  <div style="font-size:22px;font-weight:700;color:#fff;margin-bottom:4px;">{action} — {ticker}</div>
  <div style="font-size:12px;color:#718096;margin-bottom:16px;">Recommendation score: {score}</div>
  {f'<p style="font-size:14px;color:#a0aec0;margin-bottom:12px;">{why_now}</p>' if why_now else ""}
  {f'<p style="font-size:13px;color:#90cdf4;">{rat}</p>' if rat else ""}
  <hr style="border-color:#2d3748;margin:20px 0;">
  <div style="font-size:11px;color:#718096;">Log in to the Investment Dashboard to act on this recommendation.</div>
</div></body></html>"""


def _dispatch_urgent_notifications() -> None:
    """Send email for URGENT open recommendations not yet notified. Idempotent."""
    try:
        conn = agent_db._connect()
        urgent = conn.execute(
            """SELECT r.id, r.ticker, r.action, r.why_now, r.rationale, r.recommendation_score
               FROM recommendations r
               WHERE r.status='open' AND r.urgency_level='URGENT'
                 AND NOT EXISTS (
                     SELECT 1 FROM notification_events ne
                     WHERE ne.recommendation_id = r.id AND ne.level='URGENT'
                 )
               ORDER BY r.created_at DESC""",
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[Notifications] DB query failed: {e}")
        return

    if not urgent:
        return

    email_from, app_pw, email_to = _load_email_creds()
    if not all([email_from, app_pw, email_to]):
        print(f"[Notifications] {len(urgent)} URGENT rec(s) found but email not configured")
        return

    for row in urgent:
        rec = dict(row)
        try:
            subject = f"[URGENT] {rec['action']} — {rec['ticker']}"
            _send_email(email_from, app_pw, email_to, subject, _render_urgent_email(rec))
            agent_db.record_notification_event(rec["id"], "URGENT")
            print(f"[Notifications] URGENT email sent for rec {rec['id']} ({rec['ticker']})")
        except Exception as e:
            print(f"[Notifications] email failed for rec {rec['id']}: {e}")


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
agent_db.migrate()

# Mark any agent_runs left in 'running' state as failed — they were killed by a
# previous service restart and will never complete on their own.
def _cleanup_stale_runs() -> None:
    import time as _t
    conn = agent_db._connect()
    cur = conn.execute(
        "UPDATE agent_runs SET status='error', error='Process killed (service restart)', "
        "finished_at=? WHERE status='running'",
        (_t.time(),),
    )
    if cur.rowcount:
        print(f"[Startup] Cleaned up {cur.rowcount} stale agent_run(s) left in 'running' state.")
    conn.commit()
    conn.close()

_cleanup_stale_runs()


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
        from tax_utils import is_long_term as _is_lt
        purchase_dt = _date.fromisoformat(lot["purchase_date"])
        days_held   = (sell_dt - purchase_dt).days
        term        = "LT" if _is_lt(purchase_dt, sell_dt) else "ST"
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
        raise FileNotFoundError(script)
    import subprocess
    result = subprocess.run(
        [str(PROJECT_DIR / "venv/bin/python"), str(PROJECT_DIR / "scripts/watchdog_job.py"),
         "backup", "--", "bash", str(script)],
        cwd=str(PROJECT_DIR),
        capture_output=True, text=True, timeout=120
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0:
        raise RuntimeError(f"Backup failed (exit {result.returncode}); success flag not advanced")


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
    BACKUP_FLAG       = PROJECT_DIR / "out" / "last_backup_date.txt"
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

    def already_backed_up(today):
        try:
            return BACKUP_FLAG.read_text().strip() == today
        except Exception:
            return False

    def do_backup(today):
        try:
            _backup_data()
            BACKUP_FLAG.write_text(today)
        except Exception as exc:
            print(f"[Backup] Exception: {exc}")

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
            lf.write("[PortfolioAI] Running macro scores…\n")
            try:
                _pai._init_ai_tables()
                _pai.generate_holding_macro_scores(force=False)
                lf.write("[PortfolioAI] Macro scores done.\n")
            except Exception as _e:
                lf.write(f"[PortfolioAI] Macro scores error: {_e}\n")
            # Daily insight is generated by the briefing agent in the pipeline below.
            result = subprocess.run(
                [str(VENV_PY), str(PROJECT_DIR / "generate_dashboard.py")],
                cwd=str(PROJECT_DIR),
                capture_output=True, text=True, timeout=300
            )
            lf.write(result.stdout or "")
            if result.returncode != 0:
                lf.write(f"ERROR (generate_dashboard.py): {result.stderr}\n")
            lf.write("[DepChecker] Checking recommendation dependencies…\n")
            try:
                from agents.dependency_checker import check_all_dependencies
                n = check_all_dependencies()
                lf.write(f"[DepChecker] {n} recommendation(s) superseded.\n")
            except Exception as _e:
                lf.write(f"[DepChecker] Error: {_e}\n")
            # Agent pipeline runs after dashboard is rebuilt so values are
            # immediately visible without waiting for LLM inference.
            lf.write("[triggers] Running agent pipeline…\n")
            try:
                _run_agent_pipeline(log_path=LOG)
            except Exception as _ae:
                lf.write(f"[triggers] Agent pipeline error: {_ae}\n")
        return True

    while True:
        now   = _dt.now(TZ)
        today = now.date().isoformat()
        if now.weekday() == 5 and now.hour >= 7 and not already_ran(today):
            print(f"[Scheduler] Running newsletter for {today}…")
            if run(send_email=False):
                print(f"[Scheduler] Done for {today}.")
                do_backup(today)
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
                do_backup(today)
            else:
                print(f"[Scheduler] 5 PM refresh failed — will retry in 30 min.")
        elif already_ran(today) and now.hour >= 21 and now.minute >= 30 and not already_refreshed(today):
            print(f"[Scheduler] Running 9:30 PM OTC price refresh for {today}…")
            if run(send_email=False):
                REFRESH_FLAG.write_text(today)
                print(f"[Scheduler] 9:30 PM refresh done for {today}.")
                do_backup(today)
            else:
                print(f"[Scheduler] 9:30 PM refresh failed — will retry in 30 min.")
        # Daily backup — runs once per day at 8 PM ET regardless of newsletter/refresh
        # Catches weekday data changes (manual lot edits, thesis saves, etc.)
        if now.hour >= 20 and not already_backed_up(today):
            do_backup(today)
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
    from agents.news.brief import read_json, atomic_json
    slot_path = PROJECT_DIR / 'out/news_brief_slot.json'
    last_slot = read_json(slot_path)
    if last_slot.get('day') and last_slot.get('slot'):
        _done.add((last_slot['day'], last_slot['slot']))

    def _do_refresh(label, today):
        global _news_summary_generating
        LOG.parent.mkdir(exist_ok=True)
        print(f"[NewsRefresh] {label}:00 ET refresh starting for {today}…")
        try:
            import csv as _csv
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

            # One worker owns both evidence collection and synthesis.
            with _news_summary_lock:
                already = _news_summary_generating
                if not already:
                    _news_summary_generating = True

            if already:
                print(f"[NewsRefresh] {label}: summary already generating, skipping AI step.")
                return
            else:
                try:
                    result = _pai.generate_news_summaries(force=True)
                    if not result.get('ok'):
                        raise RuntimeError(result.get('error', 'News refresh failed'))
                    if result.get('status') != 'ready':
                        print(f'[NewsRefresh] {label}: another process owns the refresh.')
                        return
                except Exception as e:
                    print(f"[NewsRefresh] {label} summary error: {e}")
                    with open(LOG, "a") as lf:
                        lf.write(f"[{_dt.now(TZ)}] {label}:00 summary FAILED: {e}\n")
                    return
                finally:
                    with _news_summary_lock:
                        _news_summary_generating = False

            # Daily insight is generated by the briefing agent in the pipeline.

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
            due = [(label, hour) for label, hour in SLOTS if now.hour >= hour]
            for label, target_hour in due[-1:]:
                key = (today, label)
                if key not in _done and now.hour >= target_hour:
                    _done.add(key)
                    atomic_json(slot_path, {'day': today, 'slot': label})
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

    cutoff = (now_utc() - datetime.timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
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

            now_str = now_utc_space()
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
            last = _date.fromisoformat(FLAG.read_text().strip())
            # Consider "this week" = within 6 days
            return (today_eastern() - last).days < 6
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


# ── Weekly outcome evaluator (Sunday 2 AM ET) ────────────────────────────────

def _run_outcome_evaluator():
    """Evaluate matured recommendations once a week on Sunday at 2 AM ET."""
    import socket
    if socket.gethostname() != "optiplex":
        return
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ   = ZoneInfo("America/New_York")
    FLAG = PROJECT_DIR / "out" / "last_outcome_eval.txt"

    def already_ran_this_week():
        try:
            from datetime import date as _date
            last = _date.fromisoformat(FLAG.read_text().strip())
            return (today_eastern() - last).days < 6
        except Exception:
            return False

    while True:
        now = _dt.now(TZ)
        if now.weekday() == 6 and now.hour == 2 and not already_ran_this_week():
            try:
                from agents.outcome_evaluator import evaluate_matured_recommendations
                n = evaluate_matured_recommendations()
                FLAG.write_text(_dt.now(TZ).date().isoformat())
                print(f"[OutcomeEval] Evaluated {n} matured recommendation(s).")
            except Exception as e:
                print(f"[OutcomeEval] Failed: {e}")
        time.sleep(1800)


threading.Thread(target=_run_outcome_evaluator, daemon=True).start()


# ── Agent pipeline helpers ────────────────────────────────────────────────────

def build_portfolio_snapshot():
    from agents.snapshot import build_portfolio_snapshot as _build
    return _build()


def _run_agent_pipeline(log_path=None) -> None:
    """Build snapshot → detect triggers → run agents → dispatch notifications.

    Writes [triggers] and [Orchestrator] lines to stdout and optionally to
    log_path (a Path or str) so they appear in newsletter.log.
    Non-fatal: exceptions are caught and logged; caller continues normally.
    """
    from operational_watchdog import receipt
    _watchdog_record = receipt('agent_pipeline')
    def _log(msg):
        print(msg)
        if log_path:
            try:
                with open(log_path, "a") as _lf:
                    _lf.write(msg + "\n")
            except Exception:
                pass

    try:
        snapshot = build_portfolio_snapshot()
        n_holdings = len(snapshot.holdings)
        n_priced = sum(1 for h in snapshot.holdings if h.current_price > 0)
        _log(
            f"[triggers] Snapshot: {n_holdings} holdings, {n_priced} priced, "
            f"total_value={snapshot.total_value:.0f}"
        )

        from agents.triggers import detect_triggers
        events = detect_triggers(snapshot)
        _run_ids = []
        triggered = list({e.agent_type for e in events})
        _log(f"[triggers] {len(events)} events → agents: {triggered}")

        if events:
            from agents.orchestrator import run_agents
            recs, _run_ids = run_agents(snapshot, events)
            _log(f"[Orchestrator] {len(recs)} recommendation(s) generated.")
        else:
            _log("[Orchestrator] No agents triggered.")

        import agent_db as _watchdog_adb
        with _watchdog_adb._connect() as _watchdog_conn:
            _watchdog_runs = [dict(r) for r in _watchdog_conn.execute(
                "SELECT id,agent_type,status FROM agent_runs WHERE id IN (" +
                ','.join('?' for _ in _run_ids) + ")", _run_ids)] if _run_ids else []
        _watchdog_conn.close()
        receipt('agent_pipeline', _watchdog_record,
                'FAILED' if any(r['status'] != 'done' for r in _watchdog_runs) else 'COMPLETE',
                {'opportunity_expected': any(e.agent_type == 'opportunity_hunter' for e in events),
                 'opportunity_run_ids': [r['id'] for r in _watchdog_runs if r['agent_type'] == 'opportunity_hunter']})

        try:
            _dispatch_urgent_notifications()
        except Exception as _ne:
            _log(f"[Notifications] dispatch failed: {_ne}")
    except Exception as _e:
        receipt('agent_pipeline', _watchdog_record, 'FAILED', {'error': type(_e).__name__})
        _log(f"[AgentPipeline] Failed: {_e}")


# ── Weekly thesis monitor (Saturday 7 AM ET) ──────────────────────────────────

def _run_saturday_sweep():
    """Run thesis monitor + tax agent for all holdings on Saturday at 7 AM ET."""
    import socket
    if socket.gethostname() != "optiplex":
        return
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    TZ   = ZoneInfo("America/New_York")
    FLAG = PROJECT_DIR / "out" / "last_saturday_sweep.txt"

    def _already_ran():
        try:
            from datetime import date as _date
            last = _date.fromisoformat(FLAG.read_text().strip())
            return (today_eastern() - last).days < 6
        except Exception:
            return False

    while True:
        now = _dt.now(TZ)
        if now.weekday() == 5 and now.hour == 7 and not _already_ran():
            try:
                # Guard: ensure today's prices are loaded before running agents.
                # send_newsletter_main.py (kicked off by _run_daily at the same time)
                # writes holding_day rows; if they aren't there yet, skip and retry
                # at the next 30-minute tick (still hour==7).
                today_str = _dt.now(TZ).date().isoformat()
                _gc = sqlite3.connect(
                    str(PROJECT_DIR / "out" / "investment.db"), timeout=5
                )
                _has = _gc.execute(
                    "SELECT 1 FROM holding_day WHERE day=? LIMIT 1", (today_str,)
                ).fetchone()
                _gc.close()
                if not _has:
                    print("[SaturdaySweep] No holding_day data for today yet — will retry.")
                    time.sleep(1800)
                    continue

                _run_agent_pipeline()

                try:
                    from agents.dependency_checker import check_all_dependencies
                    check_all_dependencies()
                except Exception as e:
                    print(f"[SaturdaySweep] dep checker failed: {e}")

                FLAG.write_text(today_str)
                print("[SaturdaySweep] Weekly sweep complete.")
            except Exception as e:
                print(f"[SaturdaySweep] Scheduled run failed: {e}")
        time.sleep(1800)


threading.Thread(target=_run_saturday_sweep, daemon=True).start()


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
        for tok in ollama_client.stream_generate(prompt, content_only=True, num_predict=1500):
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

            now_str = now_utc_space()
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

        # Agent pipeline runs after dashboard is rebuilt so holdings values
        # are immediately visible without waiting for LLM inference.
        try:
            _run_agent_pipeline()
        except Exception as _ape:
            print(f"[RefreshJob] agent pipeline error: {_ape}")
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

        now_str = now_utc_space()
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
        now_str = now_utc_space()
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

        today = today_eastern()
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

    now = now_eastern()
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


from execution_validation import validate_execution_body as _validate_execution_body


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
        elif parsed.path == "/api/candidates/comparison":
            self._handle_candidates_comparison()
        elif parsed.path == "/api/candidates":
            self._handle_candidates_get()
        elif parsed.path.startswith("/api/candidates/"):
            parts = parsed.path.rstrip("/").split("/")
            if len(parts) == 5 and parts[4] == "history":
                self._handle_candidate_history(parts[3].upper())
            else:
                self.send_response(404); self.end_headers()
        elif parsed.path == "/api/agent-status":
            self._handle_agent_status()
        elif parsed.path == "/api/recommendations":
            self._handle_recommendations_get()
        elif parsed.path == "/api/preferences":
            self._handle_preferences_get()
        elif parsed.path == "/api/strategy-config":
            self._handle_strategy_config_get()
        elif parsed.path.startswith("/api/agents/"):
            self._handle_agents_get(parsed)
        elif parsed.path.startswith("/api/theses/"):
            parts = parsed.path.rstrip("/").split("/")
            if len(parts) == 4:                               # /api/theses/<ticker>
                self._handle_thesis_get(parts[3].upper())
            elif len(parts) == 5 and parts[4] == "job":     # /api/theses/<ticker>/job?id=...
                job_id = parse_qs(parsed.query).get("id", [None])[0]
                self._handle_thesis_job_poll(job_id or "")
            elif len(parts) == 5 and parts[4] == "history": # /api/theses/<ticker>/history
                self._handle_thesis_history(parts[3].upper())
            elif len(parts) == 5 and parts[4] == "health":  # /api/theses/<ticker>/health
                self._handle_thesis_health(parts[3].upper())
            else:
                self.send_response(404)
                self.end_headers()
        # ── 0198 Shadow account endpoints ─────────────────────────────────────
        elif parsed.path == "/api/shadow/account":
            self._handle_shadow_account()
        elif parsed.path == "/api/shadow/intents":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
            self._handle_shadow_intents(limit)
        elif parsed.path == "/api/shadow/fills":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
            self._handle_shadow_fills(limit)
        elif parsed.path == "/api/shadow/runs":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
            self._handle_shadow_runs(limit)
        elif parsed.path.startswith("/api/shadow/risk/"):
            intent_id = parsed.path.split("/api/shadow/risk/", 1)[1]
            self._handle_shadow_risk(intent_id)
        elif parsed.path == "/api/learning/stats":
            _valid_horizons = {"1w", "1m", "3m", "6m", "12m"}
            _h = parse_qs(parsed.query).get("horizon", ["3m"])[0]
            _horizon = _h if _h in _valid_horizons else "3m"
            self._handle_learning_stats(_horizon)
        elif parsed.path == "/api/watchdog/heartbeat":
            try:
                import sqlite3 as _watchdog_sqlite
                with _watchdog_sqlite.connect(f'file:{PROJECT_DIR}/out/investment.db?mode=ro', uri=True, timeout=3) as _wd:
                    _wd.execute('SELECT 1 FROM agent_runs LIMIT 1').fetchone()
                _wd.close()
                self._json({"ok": True})
            except Exception:
                self._json_error(503, "Database unavailable")
        elif parsed.path == "/api/watchdog":
            from operational_watchdog import report
            self._json({"ok": True, "report": report()})
        elif parsed.path == "/api/learning/readiness":
            self._handle_learning_readiness()
        elif parsed.path == "/api/learning/champion-challenger":
            self._handle_champion_challenger()
        # ── Alpaca paper account endpoints ────────────────────────────────────
        elif parsed.path == "/api/alpaca/account":
            self._handle_alpaca_account()
        elif parsed.path == "/api/alpaca/intents":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
            self._handle_alpaca_intents(limit)
        elif parsed.path == "/api/alpaca/fills":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
            self._handle_alpaca_fills(limit)
        elif parsed.path == "/api/alpaca/runs":
            limit = int(parse_qs(parsed.query).get("limit", ["20"])[0])
            self._handle_alpaca_runs(limit)
        elif parsed.path.startswith("/api/alpaca/risk/"):
            intent_id = parsed.path.split("/api/alpaca/risk/", 1)[1]
            self._handle_alpaca_risk(intent_id)
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
        elif parsed.path == "/api/trade-engine/run":
            self._handle_trade_engine_run()
        elif parsed.path == "/api/trade-engine/run-alpaca":
            self._handle_trade_engine_run_alpaca()
        elif parsed.path == "/api/invest-chat":
            self._handle_invest_chat()
        elif parsed.path == "/api/ai/chat":
            self._handle_portfolio_chat()
        elif parsed.path == "/api/brief/respond":
            self._handle_brief_respond()
        elif parsed.path == "/api/candidates":
            self._handle_candidates_post()
        elif parsed.path.startswith("/api/candidates/"):
            parts = parsed.path.rstrip("/").split("/")          # ['','api','candidates',ticker,action or 'history']
            if len(parts) == 5 and parts[4] == "history":
                self._handle_candidate_history(parts[3].upper())
            elif len(parts) == 5 and parts[4] == "reject":
                self._handle_candidate_action(parts[3].upper(), "rejected")
            elif len(parts) == 5 and parts[4] == "watch":
                self._handle_candidate_action(parts[3].upper(), "watch")
            else:
                self.send_response(404); self.end_headers()
        elif parsed.path.startswith("/api/preferences/"):
            parts = parsed.path.rstrip("/").split("/")
            if len(parts) == 5 and parts[4] == "feedback" and parts[3].isdigit():
                self._handle_preference_feedback(int(parts[3]))
            else:
                self.send_response(404); self.end_headers()
        elif parsed.path.startswith("/api/agents/"):
            self._handle_agents_post(parsed)
        elif parsed.path.startswith("/api/theses/"):
            parts = parsed.path.rstrip("/").split("/")
            if len(parts) == 5 and parts[4] == "draft":     # /api/theses/<t>/draft
                self._handle_thesis_draft_post(parts[3].upper())
            elif len(parts) == 5 and parts[4] == "approve": # /api/theses/<t>/approve
                self._handle_thesis_approve(parts[3].upper())
            elif len(parts) == 5 and parts[4] == "accept-proposal":
                self._handle_thesis_accept_proposal()
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/theses/"):
            parts = parsed.path.rstrip("/").split("/")
            if len(parts) == 5 and parts[4] == "draft":     # PUT /api/theses/<t>/draft
                self._handle_thesis_draft_put(parts[3].upper())
            else:
                self.send_response(404)
                self.end_headers()
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
        elif len(parts) == 5 and parts[1] == "api" and parts[2] == "agents" and parts[3] == "journal" and parts[4].isdigit():
            self._handle_journal_edit(int(parts[4]))
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
                today = today_eastern().isoformat()
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
                today_str = today_eastern().isoformat()
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
            conn = sqlite3.connect(str(db), timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                # Auto-expire any open positions whose expiry date has passed.
                # Options expire at end of day on the expiry date, so we compare
                # strictly: expiry < today (i.e. the day after expiry has arrived).
                today = today_eastern().isoformat()
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
            finally:
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
            conn = sqlite3.connect(str(db), timeout=30)
            try:
                cur  = conn.execute("""
                    INSERT INTO cc_positions
                    (ticker, contracts, strike, expiry, premium_per_contract, opened_date, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
                """, (_normalize_ticker(body["ticker"]), int(body["contracts"]), float(body["strike"]),
                      body["expiry"], float(body["premium_per_contract"]),
                      body["opened_date"], body.get("notes", "")))
                conn.commit()
                pos_id = cur.lastrowid
            finally:
                conn.close()
            self._json({"ok": True, "id": pos_id})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_journal_edit(self, rec_id: int):
        try:
            body        = self._read_body()
            notes       = body.get("notes")       # None = don't change
            reason_code = body.get("reason_code") # None = don't change
            ok = agent_db.update_journal_entry(rec_id, notes, reason_code)
            if ok:
                self._json({"ok": True})
            else:
                self._json_error(404, "No user_decision row for that recommendation")
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_cc_update(self, pos_id: int):
        try:
            body    = self._read_body()
            db      = PROJECT_DIR / "out" / "investment.db"
            conn    = sqlite3.connect(str(db), timeout=30)
            conn.row_factory = sqlite3.Row
            try:
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
                    return self._json_error(400, "No updatable fields provided")
                values.append(pos_id)
                conn.execute(f"UPDATE cc_positions SET {', '.join(updates)} WHERE id = ?", values)
                conn.commit()
            finally:
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
            today = today_eastern().isoformat()
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

            # If all lots for this ticker are gone, remove it from holdings.csv
            remaining_lots = [
                a for a in allocs
                if round(a["original_shares"] - a["shares"], 6) >= 1e-4
            ]
            if not remaining_lots:
                holdings_csv = PROJECT_DIR / "holdings.csv"
                if holdings_csv.exists():
                    import csv as _csv_sell
                    rows, fieldnames = [], None
                    with open(holdings_csv, newline="") as f:
                        reader = _csv_sell.DictReader(f)
                        fieldnames = reader.fieldnames
                        for row in reader:
                            raw = str(row.get("Stock", "")).strip().upper()
                            norm = raw.replace(".", "-") if "." in raw else raw
                            if norm != ticker and raw != ticker:
                                rows.append(row)
                    with open(holdings_csv, "w", newline="") as f:
                        writer = _csv_sell.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)

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
                    for tok in ollama_client.stream_generate(prompt, content_only=True, num_predict=1500):
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
                        cutoff = today_eastern() + _td2(days=_window_days)
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
                        contracts=int(contracts) if contracts else 1,
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
            today      = today_eastern()
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
            today    = today_eastern()

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

            today = today_eastern()
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
            today    = today_eastern()

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
                                ex_date = epoch_to_utc(ts).strftime("%Y-%m-%d")
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
                    started = parse_timestamp(meta["scan_started"])
                    elapsed = max((now_utc() - started).total_seconds(), 5.0)
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
                    lf.write(f"\n=== MANUAL SCAN {now_utc_space()} UTC ===\n")
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
        today = today_eastern()

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
        """One refresh job; serve last-good synthesis during work or failures."""
        global _news_summary_generating
        import portfolio_ai
        from agents.news.brief import latest, read_json, VERSION
        force = qs.get("force", ["0"])[0] == "1"
        cached, generated_at = latest(portfolio_ai.DB_PATH)
        state = read_json(PROJECT_DIR / "out/news_brief_state.json")
        # Process state survives reloads/restarts, but abandoned jobs expire.
        external_running = (state.get("status") == "generating" and
                            time.time() - state.get("started_epoch", 0) < 90)
        cooling_down = (state.get("status") == "error" and
                        time.time() - state.get("finished_epoch", 0) < 120)
        fresh = bool(cached and cached.get("_brief_version") == VERSION and
                     cached.get("_day") == today_eastern().isoformat())
        if fresh and generated_at:
            try:
                fresh = ((now_utc() - parse_timestamp(generated_at)).total_seconds() < 1800 or
                         (state.get('status') == 'ready' and time.time()-state.get('finished_epoch', 0) < 1800))
            except Exception:
                fresh = False
        # A portfolio change invalidates the brief even within its freshness window.
        holdings = portfolio_ai._load_holdings_csv()
        current_tickers = sorted({str(h['Stock']).strip().upper() for h in holdings if h.get('Stock')})
        import hashlib
        portfolio_key = hashlib.sha256(json.dumps(holdings, sort_keys=True).encode()).hexdigest()
        fresh = fresh and cached.get('_holdings') == current_tickers and cached.get('_portfolio_key') == portfolio_key
        with _news_summary_lock:
            generating = _news_summary_generating or external_running
            if (force or (not fresh and not cooling_down)) and not generating:
                _news_summary_generating = generating = True
                def _run():
                    global _news_summary_generating
                    try:
                        result = portfolio_ai.generate_news_summaries(force=force)
                        if not result.get('ok'):
                            print(f"[news-summary] {result.get('error', 'Refresh failed')}")
                    finally:
                        with _news_summary_lock:
                            _news_summary_generating = False
                threading.Thread(target=_run, daemon=True).start()
        status = 'generating' if generating else ('error' if state.get('status') == 'error' else 'ready')
        raw = read_json(PROJECT_DIR / 'out/news_brief_articles.json')
        self._json({
            'ok': bool(cached) or status != 'error', 'status': status,
            'summaries': cached, 'events': (cached or {}).get('_events', {}),
            'themes': (cached or {}).get('_themes', []),
            'by_ticker': (cached or {}).get('_by_ticker', {}) or raw.get('by_ticker', {}),
            'generated_at': generated_at,
            'generated_at_et': format_eastern(parse_timestamp(generated_at)) if generated_at else None,
            'stale': not fresh or status != 'ready', 'error': state.get('error') if status == 'error' else None,
            'elapsed_seconds': state.get('elapsed_seconds'),
        })

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
        today = today_eastern().isoformat()

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
            # Attach brief_id + deterministic items from provenance snapshot.
            # The LLM output (cached) has headline/what_changed/key_question/portfolio_state.
            # needs_attention, opportunities, watch come from the brief_state snapshot
            # so they carry stable item keys regardless of LLM output.
            brief_id = None
            freshness_data = None
            evidence_data = None
            try:
                import sqlite3 as _sql, json as _json
                bc = _sql.connect(str(portfolio_ai.DB_PATH), timeout=5)
                bc.row_factory = _sql.Row
                br = bc.execute(
                    "SELECT brief_id, brief_snapshot_json FROM portfolio_brief_provenance"
                    " ORDER BY captured_at DESC LIMIT 1"
                ).fetchone()
                bc.close()
                if br:
                    brief_id = br["brief_id"]
                    snap = _json.loads(br["brief_snapshot_json"] or "{}")
                    freshness_data = snap.get("freshness")
                    cs = snap.get("critic_summary", {})
                    evidence_data = {
                        "agent_count": len(snap.get("thesis_deltas", [])),
                        "rec_count": len(snap.get("open_decisions", [])),
                        "news_count": len(snap.get("news_signals", [])),
                        "critic_approved": cs.get("APPROVE", 0) + cs.get("APPROVE_WITH_CAUTION", 0),
                    }
                    # Merge deterministic items from brief_state snapshot into the response.
                    # This gives items stable keys (guardian:X, rec:Y, news:Z, thesis:T)
                    # rather than relying on LLM regeneration.
                    if isinstance(cached, dict):
                        cached = dict(cached)
                        # Sort previously_dismissed to bottom
                        def _sort_items(items):
                            return (
                                [i for i in items if not i.get("previously_dismissed")]
                                + [i for i in items if i.get("previously_dismissed")]
                            )
                        cached["needs_attention"] = _sort_items(snap.get("attention_items", []))
                        cached["opportunities"] = _sort_items(snap.get("opportunities", []))
                        cached["watch"] = snap.get("watch_items", [])
            except Exception:
                pass
            if isinstance(cached, dict) and freshness_data:
                cached = {**cached, "_freshness": freshness_data, "_evidence": evidence_data}
            generated_at_et = None
            if generated_at:
                try:
                    generated_at_et = format_eastern(parse_timestamp(generated_at))
                except Exception:
                    pass
            self._json({"ok": True, "insight": cached, "date": today,
                        "generated_at": generated_at,
                        "generated_at_et": generated_at_et,
                        "brief_id": brief_id})
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

    def _handle_brief_respond(self):
        """POST /api/brief/respond — record REVIEW/DISMISS/DEFER on a brief item.
        Body: {"brief_id": "...", "item_key": "...", "action": "REVIEW|DISMISS|DEFER", "note": "..."}
        """
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")

        brief_id = body.get("brief_id", "")
        item_key = body.get("item_key", "")
        action = body.get("action", "")
        note = body.get("note", "") or ""

        if not brief_id or not item_key or action not in ("REVIEW", "DISMISS", "DEFER"):
            return self._json_error(400, "brief_id, item_key, and action (REVIEW|DISMISS|DEFER) required")

        try:
            import portfolio_ai
            import sqlite3 as _sql
            portfolio_ai._init_ai_tables()
            conn = _sql.connect(str(portfolio_ai.DB_PATH), timeout=10)
            conn.row_factory = _sql.Row
            status_code, result = portfolio_ai.apply_brief_response(conn, brief_id, item_key, action, note)
            if status_code == 200:
                conn.commit()  # apply_brief_response no longer owns the connection
            conn.close()
            if status_code == 200:
                self._json(result)
            else:
                self._json_error(status_code, result.get("error", ""))
        except Exception as e:
            self._json_error(500, f"Could not record response: {e}")

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

    # ── Candidate universe endpoints ─────────────────────────────────────────

    def _handle_candidates_get(self):
        try:
            import csv as _csv
            candidates = agent_db.get_candidates(include_rejected=False)
            # Sync owned status from holdings.csv in a background thread so the
            # GET response is not blocked by write-lock contention on the DB.
            def _sync_bg():
                try:
                    held = []
                    csv_path = PROJECT_DIR / "holdings.csv"
                    if csv_path.exists():
                        with open(csv_path, newline="") as f:
                            for row in _csv.DictReader(f):
                                t = str(row.get("Stock", "")).strip().upper()
                                if t:
                                    held.append(t)
                    agent_db.sync_owned_candidates(held)
                except Exception:
                    pass
            threading.Thread(target=_sync_bg, daemon=True).start()
            self._json({"ok": True, "candidates": candidates})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_candidates_comparison(self):
        """GET /api/candidates/comparison — score and rank active candidates (cached 15 min)."""
        global _comparison_cache, _comparison_cache_at
        import time as _time
        try:
            now = _time.monotonic()
            if _comparison_cache is not None and (now - _comparison_cache_at) < _COMPARISON_CACHE_TTL:
                return self._json({"ok": True, "cached": True, **_comparison_cache})
            from agents.opportunity_agent import score_for_comparison
            candidates = agent_db.get_candidates(include_rejected=False)
            result = score_for_comparison(candidates)
            _comparison_cache = result
            _comparison_cache_at = _time.monotonic()
            self._json({"ok": True, **result})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_candidates_post(self):
        """Add a manual candidate and kick off the analysis pipeline async."""
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))
            ))
        except Exception:
            return self._json_error(400, "invalid JSON body")

        ticker = str(body.get("ticker", "")).strip().upper()
        notes  = body.get("notes") or None
        if not ticker:
            return self._json_error(400, "ticker required")

        agent_db.upsert_candidate(ticker=ticker, source="MANUAL", notes=notes, actor="user", reason="manual add")

        def _bg():
            try:
                import financials_fetcher
                financials_fetcher.fetch_all([ticker], force=True)
            except Exception as e:
                print(f"[Candidates] financials fetch failed for {ticker}: {e}")
            # Kick opportunity hunter if registered (no-ops if not yet built)
            try:
                import agents.orchestrator as orch
                from agents.triggers import TriggerEvent
                snapshot = build_portfolio_snapshot()
                orch.run_agents(snapshot, [TriggerEvent(trigger_type="on_demand", agent_type="opportunity_hunter", ticker=ticker)])  # returns (recs, run_ids)
                agent_db.mark_candidate_evaluated(ticker)
            except Exception:
                pass

        import threading
        threading.Thread(target=_bg, daemon=True).start()
        self._json({"ok": True, "ticker": ticker, "status": "active"})

    def _handle_candidate_action(self, ticker: str, new_status: str):
        try:
            body   = self._read_body()
            reason = body.get("reason") or None
            notes  = body.get("notes") or None
            agent_db.set_candidate_status(ticker, new_status, notes=notes, actor="user", reason=reason)
            self._json({"ok": True, "ticker": ticker, "status": new_status})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_candidate_history(self, ticker: str):
        try:
            history = agent_db.get_candidate_history(ticker)
            self._json({"ok": True, "ticker": ticker, "history": history})
        except Exception as e:
            self._json_error(500, str(e))

    # ── Agent status endpoint ─────────────────────────────────────────────────

    def _handle_agent_status(self):
        """GET /api/agent-status — running agents + last completed sweep timestamp."""
        try:
            conn = agent_db._connect()
            cutoff = time.time() - 7200  # ignore stale "running" rows older than 2 h
            running_rows = conn.execute(
                "SELECT DISTINCT agent_type FROM agent_runs "
                "WHERE status='running' AND started_at >= ? ORDER BY id DESC",
                (cutoff,),
            ).fetchall()
            last_row = conn.execute(
                "SELECT MAX(finished_at) AS ts FROM agent_runs WHERE status='done'"
            ).fetchone()

            running_since = None
            avg_durations = {}
            if running_rows:
                rs = conn.execute(
                    "SELECT MIN(started_at) AS ts FROM agent_runs "
                    "WHERE status='running' AND started_at >= ?",
                    (cutoff,),
                ).fetchone()
                running_since = rs["ts"] if rs else None

                agent_types = [r["agent_type"] for r in running_rows]
                placeholders = ",".join("?" * len(agent_types))
                dur_rows = conn.execute(
                    f"SELECT agent_type, AVG(finished_at - started_at) AS avg_dur "
                    f"FROM agent_runs WHERE status='done' AND agent_type IN ({placeholders}) "
                    f"GROUP BY agent_type",
                    agent_types,
                ).fetchall()
                avg_durations = {
                    r["agent_type"]: round(r["avg_dur"])
                    for r in dur_rows if r["avg_dur"]
                }

            conn.close()
            self._json({
                "running": len(running_rows) > 0,
                "agents": [r["agent_type"] for r in running_rows],
                "running_since": running_since,
                "avg_durations": avg_durations,
                "last_completed_at": last_row["ts"] if last_row else None,
            })
        except Exception as e:
            self._json({"running": False, "agents": [], "running_since": None,
                        "avg_durations": {}, "last_completed_at": None})

    # ── Decision Queue endpoint ───────────────────────────────────────────────

    def _handle_recommendations_get(self):
        """Return open recommendations with critic verdicts attached."""
        try:
            recs = agent_db.list_recommendations(status="open")
            self._json({"ok": True, "recommendations": recs})
        except Exception as e:
            self._json_error(500, str(e))

    # ── Thesis intake endpoints ───────────────────────────────────────────────

    def _handle_thesis_get(self, ticker: str):
        try:
            thesis = agent_db.get_thesis_full(ticker)
            if thesis:
                # Surface open change proposals for this ticker
                recs = agent_db.get_open_recommendations(ticker)
                proposals = [r for r in recs if r.get("action") == "THESIS_CHANGE_PROPOSAL"]
                thesis["open_proposals"] = proposals
            self._json({"ok": True, "thesis": thesis})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_thesis_health(self, ticker: str):
        """Return thesis health summary: composite score, per-pillar breakdown."""
        try:
            t = agent_db.get_thesis(ticker)
            if not t or t.get("status") != "ACTIVE":
                self._json({"ok": True, "thesis": None})
                return
            pillars = t.get("pillars", [])
            last_evaluated = max(
                (p["last_evaluated_at"] for p in pillars if p.get("last_evaluated_at")),
                default=None,
            )
            self._json({
                "ok": True,
                "thesis": {
                    "ticker": ticker,
                    "thesis_status": t.get("status"),
                    "health_score": t.get("health_score"),
                    "has_critical_violation": t.get("has_critical_violation", False),
                    "last_evaluated_at": last_evaluated,
                    "pillars": [
                        {
                            "name": p.get("name"),
                            "importance": p.get("importance"),
                            "status": p.get("status"),
                            "score": p.get("score"),
                            "reason": p.get("reason"),
                            "critical": bool(p.get("critical")),
                        }
                        for p in pillars
                    ],
                },
            })
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_thesis_draft_post(self, ticker: str):
        """Trigger AI drafting from the user's intake form data."""
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")
        intake = body.get("intake")
        if not intake:
            return self._json_error(400, "intake field required")

        def _run():
            try:
                import thesis_engine
                draft = thesis_engine.draft_thesis(ticker, intake)
                import agent_db as _adb
                _adb.save_thesis_draft(
                    ticker=ticker,
                    intake_json=json.dumps(intake),
                    draft_json=json.dumps(draft),
                )
                return {"ok": True, "draft": draft}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        # Run in background thread; respond with job token
        import threading, uuid
        job_id = str(uuid.uuid4())
        _thesis_jobs[job_id] = {"status": "running", "ticker": ticker}

        def _worker():
            result = _run()
            _thesis_jobs[job_id].update({"status": "done", **result})

        threading.Thread(target=_worker, daemon=True).start()
        self._json({"ok": True, "job_id": job_id})

    def _handle_thesis_draft_put(self, ticker: str):
        """Save the user-edited draft (before approval)."""
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")
        intake = body.get("intake", {})
        draft  = body.get("draft", {})
        if not draft:
            return self._json_error(400, "draft field required")
        try:
            agent_db.save_thesis_draft(
                ticker=ticker,
                intake_json=json.dumps(intake),
                draft_json=json.dumps(draft),
            )
            self._json({"ok": True})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_thesis_approve(self, ticker: str):
        """Activate the current draft as the authoritative thesis."""
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")
        draft = body.get("draft")
        if draft is None:
            thesis = agent_db.get_thesis_full(ticker)
            if not thesis or thesis.get("status") != "DRAFT":
                return self._json_error(400, "No DRAFT thesis found for this ticker")
            raw_draft = thesis.get("draft_json") or {}
            final_draft_json = json.dumps(raw_draft) if isinstance(raw_draft, dict) else str(raw_draft or "{}")
        else:
            final_draft_json = json.dumps(draft) if isinstance(draft, dict) else str(draft)
        try:
            thesis_id = agent_db.approve_thesis(ticker, final_draft_json)
        except ValueError as e:
            return self._json_error(400, str(e))
        except Exception as e:
            return self._json_error(500, str(e))

        # Write metadata columns and supplementary tables
        try:
            active = agent_db.get_thesis_full(ticker)
            intake = (active.get("intake_json") or {}) if active else {}
            if isinstance(intake, str):
                intake = json.loads(intake) if intake else {}
            agent_db.update_thesis_metadata(thesis_id, intake)

            import re as _re
            def _infer_direction(key):
                return "LOWER_IS_BETTER" if any(x in str(key).lower() for x in ["debt","expense","loss","churn","burn"]) else "HIGHER_IS_BETTER"
            def _parse_persistence(s):
                m2 = _re.search(r'\d+', str(s or "1"))
                return int(m2.group()) if m2 else 1
            draft_dict = json.loads(final_draft_json) if isinstance(final_draft_json, str) else final_draft_json
            # Support both new pillars format and legacy claims format
            pillars_src = draft_dict.get("pillars") or []
            if not pillars_src:
                for claim in (draft_dict.get("claims") or []):
                    text = claim.get("claim", "")
                    name = text[:70].rstrip()
                    if len(text) > 70 and " " in name:
                        name = name[:name.rfind(" ")]
                    pillars_src.append({
                        "name": name,
                        "description": text,
                        "importance": claim.get("importance", 20),
                        "critical": False,
                        "metrics": [
                            {
                                "metric_key": m.get("metric", ""),
                                "direction": _infer_direction(m.get("metric", "")),
                                "healthy_rule_json": m.get("healthy", ""),
                                "warning_rule_json": m.get("warning", ""),
                                "violation_rule_json": m.get("violation", ""),
                                "persistence_periods": _parse_persistence(m.get("persistence", "1")),
                            }
                            for m in (claim.get("measurements") or []) if m.get("metric")
                        ],
                    })
            for pillar in pillars_src:
                pid = agent_db.insert_thesis_pillar(
                    thesis_id, pillar.get("name", ""),
                    float(pillar.get("importance", 0)),
                    description=pillar.get("description"),
                    critical=bool(pillar.get("critical", False)),
                )
                for m in (pillar.get("metrics") or []):
                    agent_db.insert_thesis_metric(
                        pid, m.get("metric_key", ""), m.get("direction", "HIGHER_IS_BETTER"),
                        healthy_rule_json=m.get("healthy_rule_json"),
                        warning_rule_json=m.get("warning_rule_json"),
                        violation_rule_json=m.get("violation_rule_json"),
                        persistence_periods=int(m.get("persistence_periods", 1)),
                    )
            for rule in (draft_dict.get("rules") or []):
                agent_db.insert_thesis_rule(
                    thesis_id, rule.get("rule_type", ""), rule.get("rule_json", "{}")
                )
            for risk in (draft_dict.get("key_risks") or []):
                if isinstance(risk, str):
                    agent_db.insert_thesis_risk(thesis_id, risk)
                elif isinstance(risk, dict) and risk.get("description"):
                    agent_db.insert_thesis_risk(
                        thesis_id, risk["description"],
                        severity=risk.get("severity", "MEDIUM"),
                        time_horizon=risk.get("time_horizon"),
                    )
            for catalyst in (draft_dict.get("catalysts") or []):
                if isinstance(catalyst, str):
                    agent_db.insert_thesis_catalyst(thesis_id, catalyst)
                elif isinstance(catalyst, dict) and catalyst.get("description"):
                    agent_db.insert_thesis_catalyst(
                        thesis_id, catalyst["description"],
                        importance=catalyst.get("importance", "MEDIUM"),
                        time_horizon=catalyst.get("time_horizon"),
                    )
            for sig in (draft_dict.get("qualitative_signals") or []):
                if isinstance(sig, dict) and sig.get("description"):
                    agent_db.insert_thesis_rule(
                        thesis_id, "QUALITATIVE_SIGNAL",
                        json.dumps({
                            "signal_name": sig.get("description", "")[:60],
                            "description": sig.get("description", ""),
                            "source": sig.get("source", ""),
                            "direction": sig.get("direction", "positive"),
                        }),
                    )
            review_triggers = draft_dict.get("review_triggers") or []
            val_framework   = draft_dict.get("valuation_framework")
            _conn = agent_db._connect()
            if review_triggers:
                _conn.execute(
                    "UPDATE investment_theses SET review_triggers=? WHERE id=?",
                    (json.dumps(review_triggers), thesis_id),
                )
            if val_framework:
                _conn.execute(
                    "UPDATE investment_theses SET valuation_framework=? WHERE id=?",
                    (json.dumps(val_framework) if isinstance(val_framework, dict) else val_framework, thesis_id),
                )
            _conn.commit()
            _conn.close()
        except Exception as e:
            print(f"[thesis_approve] post-approval writes failed for {ticker}: {e}")

        self._json({"ok": True, "thesis_id": thesis_id})

    def _handle_thesis_history(self, ticker: str):
        try:
            history = agent_db.get_thesis_history(ticker)
            self._json({"ok": True, "history": history})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_thesis_accept_proposal(self):
        """Accept a THESIS_CHANGE_PROPOSAL recommendation."""
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")
        rec_id = body.get("recommendation_id")
        if not rec_id:
            return self._json_error(400, "recommendation_id required")
        try:
            ok = agent_db.accept_thesis_change_proposal(int(rec_id))
            self._json({"ok": ok})
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_thesis_job_poll(self, job_id: str):
        """Poll status of an async thesis draft job."""
        result = _thesis_jobs.get(job_id)
        if result is None:
            return self._json_error(404, "job not found")
        self._json(result)

    # ── /api/agents/* ─────────────────────────────────────────────────────────

    def _handle_preferences_get(self):
        """GET /api/preferences — return all learned soft preferences."""
        prefs = agent_db.get_learned_preferences()
        return self._json({"ok": True, "preferences": prefs, "count": len(prefs)})

    def _handle_preference_feedback(self, pref_id: int):
        """POST /api/preferences/{id}/feedback — record user feedback on a learned preference."""
        body = self._read_body()
        outcome   = body.get("outcome")    # "confirmed" | "rejected" | None
        suppressed = bool(body.get("suppressed", False))
        if not outcome and not suppressed:
            return self._json_error(400, "Provide 'outcome' or 'suppressed'")
        try:
            agent_db.record_preference_feedback(pref_id, outcome, suppressed)
        except Exception as e:
            return self._json_error(500, str(e))
        return self._json({"ok": True, "pref_id": pref_id, "outcome": outcome, "suppressed": suppressed})

    def _handle_strategy_config_get(self):
        """GET /api/strategy-config — return key hard-rule constants for the Investor Model page."""
        cfg = {
            "layers": {
                str(n): {"name": strategy_config.LAYER_NAMES[n], "target_pct": strategy_config.LAYER_TARGETS[n]}
                for n in sorted(strategy_config.LAYER_TARGETS)
            },
            "covered_calls": {
                "min_dte": strategy_config.CC_MIN_DTE,
                "max_dte": strategy_config.CC_MAX_DTE,
                "extended_max_dte": strategy_config.CC_MAX_DTE_EXTENDED,
                "min_bid": strategy_config.CC_MIN_BID,
                "r_min": strategy_config.CC_R_MIN,
                "top_n": strategy_config.CC_TOP_N,
            },
            "risk": {
                "drift_threshold_pct": strategy_config.DRIFT_THRESHOLD,
                "layer_gross_dom_pct": strategy_config.LAYER_GROSS_DOM,
                "holding_gross_dom_pct": strategy_config.HOLDING_GROSS_DOM,
            },
            "triggers": {
                "price_move_z": strategy_config.TRIGGER_PRICE_MOVE_Z,
                "nav_impact_pct": strategy_config.TRIGGER_NAV_IMPACT_PCT,
                "macro_score_change": strategy_config.TRIGGER_MACRO_SCORE_CHANGE,
                "cc_mgmt_dte": strategy_config.TRIGGER_CC_MGMT_DTE,
                "tax_lt_window_min": strategy_config.TRIGGER_TAX_LT_WINDOW_MIN,
                "tax_lt_window_max": strategy_config.TRIGGER_TAX_LT_WINDOW_MAX,
                "tax_loss_min": strategy_config.TRIGGER_TAX_LOSS_MIN,
                "st_tax_rate": strategy_config.TAX_ST_RATE,
            },
        }
        return self._json({"ok": True, "config": cfg})

    def _handle_agents_get(self, parsed):
        """Route GET /api/agents/* requests."""
        from urllib.parse import parse_qs
        parts = parsed.path.rstrip("/").split("/")
        # /api/agents/recommendations
        if len(parts) == 4 and parts[3] == "recommendations":
            qs = parse_qs(parsed.query)
            status = qs.get("status", ["open"])[0]
            recs = agent_db.list_recommendations(status=status)
            return self._json({"ok": True, "recommendations": recs})
        # /api/agents/recommendations/{ticker}/lineage
        if (len(parts) == 6 and parts[3] == "recommendations"
                and parts[5] == "lineage"):
            data = agent_db.get_lineage(parts[4])
            return self._json({"ok": True, **data})
        # /api/agents/recommendations/{id}
        if len(parts) == 5 and parts[3] == "recommendations" and parts[4].isdigit():
            rec = agent_db.get_recommendation_full(int(parts[4]))
            if not rec:
                return self._json_error(404, "Recommendation not found")
            return self._json({"ok": True, "recommendation": rec})
        # /api/agents/journal
        if len(parts) == 4 and parts[3] == "journal":
            entries = agent_db.list_journal_entries()
            summary = agent_db.journal_summary()
            return self._json({"ok": True, "entries": entries, "summary": summary})
        # /api/agents/runs
        if len(parts) == 4 and parts[3] == "runs":
            qs = parse_qs(parsed.query)
            agent_type = qs.get("agent_type", [None])[0]
            limit = int(qs.get("limit", ["20"])[0])
            runs = agent_db.list_runs(agent_type=agent_type, limit=limit)
            return self._json({"ok": True, "runs": runs})
        # /api/agents/runs/{id}
        if len(parts) == 5 and parts[3] == "runs" and parts[4].isdigit():
            run = agent_db.get_run_full(int(parts[4]))
            if not run:
                return self._json_error(404, "Run not found")
            return self._json({"ok": True, "run": run})
        # /api/agents/coverage
        if len(parts) == 4 and parts[3] == "coverage":
            return self._json({"ok": True, **agent_db.get_coverage()})
        # /api/agents/learning/health — 0370: data health dashboard
        if len(parts) == 5 and parts[3] == "learning" and parts[4] == "health":
            try:
                from agents.learning.calibration import compute_data_health
                conn = agent_db._connect()
                try:
                    health = compute_data_health(conn)
                finally:
                    conn.close()
                return self._json({"ok": True, **health})
            except Exception as e:
                return self._json_error(500, f"health check failed: {e}")
        self._json_error(404, "Not found")

    def _handle_agents_post(self, parsed):
        """Route POST /api/agents/* requests."""
        parts = parsed.path.rstrip("/").split("/")
        # /api/agents/recommendations/{id}/decision
        if (len(parts) == 6 and parts[3] == "recommendations"
                and parts[4].isdigit() and parts[5] == "decision"):
            return self._handle_agent_decision(int(parts[4]))
        # /api/agents/recommendations/{id}/execute
        if (len(parts) == 6 and parts[3] == "recommendations"
                and parts[4].isdigit() and parts[5] == "execute"):
            return self._handle_agent_execute(int(parts[4]))
        # /api/agents/run
        if len(parts) == 4 and parts[3] == "run":
            return self._handle_agent_run_trigger()
        self._json_error(404, "Not found")

    # 0077 — valid decision values
    _VALID_DECISIONS = frozenset({"accepted", "rejected", "deferred"})

    def _handle_agent_decision(self, rec_id: int):
        """POST /api/agents/recommendations/{id}/decision"""
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")
        decision = body.get("decision", "").lower().strip()
        # 0077: validate decision value
        if decision not in self._VALID_DECISIONS:
            return self._send_json(
                {"ok": False, "error": f"Invalid decision. Must be one of: {sorted(self._VALID_DECISIONS)}"},
                status=400,
            )

        # 0077: check recommendation exists and is open
        rec_check = agent_db.get_recommendation_by_id(rec_id)
        if not rec_check or rec_check.get("status") != "open":
            return self._send_json(
                {"ok": False, "error": "Recommendation not found or already closed"},
                status=400,
            )

        reason_code = body.get("reason_code", "OTHER")
        notes = body.get("notes")

        # Write user decision record
        try:
            agent_db.insert_user_decision(
                recommendation_id=rec_id,
                decision=decision,
                reason_code=reason_code,
                notes=notes,
            )
        except Exception as e:
            return self._json_error(500, str(e))

        # Record notification engagement outcome
        try:
            agent_db.close_notification_event(rec_id, outcome="acted_on", decided_at=time.time())
        except Exception:
            pass

        # Recalculate soft preferences in background (non-blocking)
        def _run_learner():
            try:
                from agents.preference_learner import run_preference_learner
                run_preference_learner()
            except Exception as _e:
                print(f"[PrefLearner] error: {_e}")
        threading.Thread(target=_run_learner, daemon=True).start()

        # Flip recommendation status to the decision value
        found = agent_db.close_recommendation(rec_id, status=decision)
        if not found:
            return self._json_error(404, "Recommendation not found")

        rec = agent_db.get_recommendation_full(rec_id)
        self._json({"ok": True, "recommendation": rec})

    def _handle_agent_execute(self, rec_id: int):
        """POST /api/agents/recommendations/{id}/execute — record that a recommendation was executed.

        0076: ticker and action are derived from the recommendation row; body values are ignored.
        0072: accepts position_shares_before, position_shares_after, execution_fraction.
        0092: action-specific field validation + fill_id idempotency key.
        """
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")

        rec = agent_db.get_recommendation_by_id(rec_id)
        if not rec:
            return self._send_json({"ok": False, "error": "recommendation not found"}, status=404)

        if rec.get("status") != "accepted":
            return self._send_json(
                {"ok": False, "error": f"recommendation status is '{rec.get('status')}'; must be 'accepted'"},
                status=409,
            )

        ticker = rec["ticker"]
        action = rec["action"]

        # 0107: load canonical position size server-side for coverage validation
        from datetime import date as _date
        from portfolio_positions import load_positions as _load_positions
        _positions = _load_positions(PROJECT_DIR / "holdings.csv")
        _pos = _positions.get(ticker.upper())
        if _pos is None:
            # Normalize ticker (BRK-B → BRK.B lookup) — try without dashes
            _pos = _positions.get(ticker.replace("-", ".").upper())
        server_pos_before: float | None = _pos.shares if _pos else None

        # For SELL_CC: if ticker not in holdings, reject with 422
        if action in ("EXIT", "TRIM", "SELL_CC") and server_pos_before is None:
            return self._json_error(422, f"{ticker} not found in holdings.csv — cannot verify position size")

        err = _validate_execution_body(action, body, rec, today_eastern(),
                                       server_pos_before=server_pos_before)
        if err:
            code, msg = err
            return self._json_error(code, msg)

        fill_id = (body.get("fill_id") or "").strip() or None
        if fill_id:
            existing = agent_db.get_executed_action_by_fill_id(fill_id)
            if existing:
                return self._send_json(
                    {"ok": True, "executed_action_id": existing["id"],
                     "recommendation_id": rec_id, "duplicate": True},
                    status=409,
                )

        exec_date = body.get("execution_date", "").strip()

        # 0107: inject canonical position_shares_before so transaction uses server-side value
        if server_pos_before is not None:
            body = {**body, "position_shares_before": server_pos_before}

        # 0104: all writes (executed_actions + cc_positions + group linking) in one transaction
        try:
            tx = agent_db.record_execution_transaction(
                rec_id=rec_id, ticker=ticker, action=action,
                exec_date=exec_date, body=body, fill_id=fill_id,
            )
        except Exception as e:
            return self._json_error(500, str(e))

        exec_id = tx["exec_id"]
        if tx.get("cc_pos_id") is None and action == "SELL_CC":
            print(f"[Execute] SELL_CC {ticker}: duplicate open cc_position — position insert skipped")

        self._json({
            "ok": True,
            "executed_action_id": exec_id,
            "recommendation_id": rec_id,
            "ticker": ticker,
            "action": action,
        })

    def _handle_agent_run_trigger(self):
        """POST /api/agents/run — start an on-demand agent run in a background thread.

        0079: orchestrator owns run IDs; this endpoint no longer pre-creates a
        wrapper agent_runs row. The run_ids returned by run_agents() are used directly.
        """
        try:
            body = self._read_body()
        except Exception:
            return self._json_error(400, "Invalid JSON body")
        agent_type = body.get("agent_type", "").strip()
        if not agent_type:
            return self._json_error(400, "agent_type field required")
        ticker = body.get("ticker")

        # Shared result container for the background thread
        _result: dict = {}

        def _worker():
            try:
                import agents.orchestrator as orch
                from agents.triggers import TriggerEvent

                snapshot = build_portfolio_snapshot()
                recs, run_ids = orch.run_agents(
                    snapshot,
                    [TriggerEvent(trigger_type="on_demand", agent_type=agent_type, ticker=ticker)],
                )
                _result["run_ids"] = run_ids
                _result["recommendation_count"] = len(recs)
            except Exception as e:
                _result["error"] = str(e)
                print(f"[AgentRun] on-demand {agent_type} failed: {e}")

        import threading
        threading.Thread(target=_worker, daemon=True).start()
        self._json({"ok": True, "status": "started", "agent_type": agent_type, "ticker": ticker})

    # ── 0198 Shadow account handlers ──────────────────────────────────────────

    def _shadow_conn(self):
        import sqlite3 as _sqlite3
        from pathlib import Path as _Path
        _db = _Path(__file__).resolve().parent / "out" / "investment.db"
        conn = _sqlite3.connect(str(_db), timeout=5)
        conn.row_factory = _sqlite3.Row
        return conn

    def _handle_shadow_account(self):
        try:
            conn = self._shadow_conn()
            row = conn.execute(
                "SELECT * FROM trading_accounts WHERE account_id='AGENTIC_SHADOW_01'"
            ).fetchone()
            if not row:
                return self._send_json({"ok": False, "error": "shadow account not found"}, 404)
            positions = conn.execute(
                "SELECT symbol, qty, avg_cost, instrument_type FROM position_snapshots WHERE account_id='AGENTIC_SHADOW_01'"
            ).fetchall()
            pos_value = sum(float(r["qty"] or 0) * float(r["avg_cost"] or 0) for r in positions)
            nav = float(row["current_cash"] or 0) + pos_value
            conn.close()
            self._json({
                "ok": True,
                "account_id": row["account_id"],
                "name": row["name"],
                "mode": row["mode"],
                "starting_capital": float(row["starting_capital"] or 0),
                "current_cash": float(row["current_cash"] or 0),
                "nav": round(nav, 2),
                "position_count": len(positions),
                "trading_enabled": bool(row["trading_enabled"]),
                "policy_version": row["policy_version"],
                "positions": [
                    {"symbol": r["symbol"], "qty": float(r["qty"] or 0),
                     "avg_cost": float(r["avg_cost"] or 0),
                     "value": round(float(r["qty"] or 0) * float(r["avg_cost"] or 0), 2)}
                    for r in positions
                ],
            })
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_shadow_intents(self, limit: int = 20):
        try:
            conn = self._shadow_conn()
            rows = conn.execute(
                """SELECT ti.intent_id, ti.symbol, ti.side, ti.quantity, ti.limit_price,
                          ti.status, ti.created_at, ti.valid_until,
                          rd.decision, rd.checks_json
                   FROM trade_intents ti
                   LEFT JOIN risk_decisions rd ON rd.intent_id=ti.intent_id
                   WHERE ti.account_id='AGENTIC_SHADOW_01'
                   ORDER BY ti.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            import json as _json
            intents = []
            for r in rows:
                checks = []
                if r["checks_json"]:
                    try:
                        checks = _json.loads(r["checks_json"])
                    except Exception:
                        pass
                failed = [c for c in checks if c.get("result") == "FAIL"]
                passed_count = sum(1 for c in checks if c.get("result") == "PASS")
                intents.append({
                    "intent_id": r["intent_id"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "quantity": r["quantity"],
                    "limit_price": r["limit_price"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "risk_decision": r["decision"],
                    "checks_passed": passed_count,
                    "checks_failed": len(failed),
                    "fail_reason": failed[0].get("reason") if failed else None,
                })
            conn.close()
            self._json({"ok": True, "intents": intents})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_shadow_fills(self, limit: int = 20):
        try:
            conn = self._shadow_conn()
            rows = conn.execute(
                """SELECT f.fill_id, f.symbol, f.side, f.qty, f.price, f.fee,
                          f.fill_source, f.filled_at, ti.recommendation_id
                   FROM fills f
                   JOIN orders o ON f.order_id=o.order_id
                   JOIN trade_intents ti ON o.intent_id=ti.intent_id
                   WHERE f.account_id='AGENTIC_SHADOW_01'
                   ORDER BY f.filled_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            conn.close()
            self._json({
                "ok": True,
                "fills": [
                    {
                        "fill_id": r["fill_id"],
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "qty": r["qty"],
                        "price": r["price"],
                        "fee": r["fee"],
                        "fill_source": r["fill_source"],
                        "filled_at": r["filled_at"],
                        "recommendation_id": r["recommendation_id"],
                    }
                    for r in rows
                ],
            })
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_shadow_risk(self, intent_id: str):
        try:
            conn = self._shadow_conn()
            row = conn.execute(
                "SELECT * FROM risk_decisions WHERE intent_id=? ORDER BY decision_id DESC LIMIT 1",
                (intent_id,),
            ).fetchone()
            conn.close()
            if not row:
                return self._send_json({"ok": False, "error": "no risk decision found"}, 404)
            import json as _json
            checks = []
            if row["checks_json"]:
                try:
                    checks = _json.loads(row["checks_json"])
                except Exception:
                    pass
            self._json({
                "ok": True,
                "intent_id": row["intent_id"],
                "decision": row["decision"],
                "evaluated_at": row["evaluated_at"],
                "checks": checks,
            })
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_shadow_runs(self, limit: int = 20):
        try:
            conn = self._shadow_conn()
            rows = conn.execute(
                """SELECT run_at, execution_state, halt_reason, duration_seconds,
                          new_intents_processed, risk_rejections, orders_submitted,
                          fills_applied, duplicate_fills_skipped, broker_api_errors,
                          cash_delta_vs_broker, position_delta_vs_broker,
                          oldest_unresolved_order_age_minutes
                   FROM cycle_runs ORDER BY run_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            conn.close()
            self._json({
                "ok": True,
                "runs": [dict(r) for r in rows],
            })
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_learning_stats(self, horizon: str = "3m"):
        """GET /api/learning/stats?horizon=3m — strategy learning calibration data (0329, 0333).

        horizon param: 1w|1m|3m (diagnostic)|6m|12m — defaults to 3m.
        1w and 1m are flagged diagnostic_only in the response.
        """
        try:
            conn = agent_db._connect()
            horizon = horizon or "3m"
            diagnostic_only = horizon in ("1w", "1m")

            # Overview counts
            overview = conn.execute("""
                SELECT
                    COUNT(DISTINCT e.episode_id)                                   AS total_episodes,
                    COUNT(DISTINCT o.episode_id)                                   AS labeled_episodes,
                    SUM(CASE WHEN e.selected=1 THEN 1 ELSE 0 END)                 AS selected_episodes,
                    MIN(DATE(e.captured_at, 'unixepoch'))                          AS earliest_date,
                    MAX(DATE(e.captured_at, 'unixepoch'))                          AS latest_date
                FROM decision_episodes e
                LEFT JOIN episode_outcomes o ON e.episode_id = o.episode_id
                  AND o.horizon = ?
            """, (horizon,)).fetchone()
            overview = dict(overview) if overview else {}

            # Score calibration: mean alpha by composite_score bucket
            cal_rows = conn.execute("""
                SELECT
                    CASE
                        WHEN e.composite_score < 55 THEN '45-54'
                        WHEN e.composite_score < 65 THEN '55-64'
                        WHEN e.composite_score < 75 THEN '65-74'
                        WHEN e.composite_score < 85 THEN '75-84'
                        ELSE '85+'
                    END                   AS bucket,
                    COUNT(*)              AS n,
                    ROUND(AVG(o.alpha)*100, 2)        AS mean_alpha_pct,
                    ROUND(AVG(o.ticker_return)*100, 2) AS mean_return_pct,
                    ROUND(AVG(o.spy_return)*100, 2)   AS mean_spy_pct
                FROM decision_episodes e
                JOIN episode_outcomes o ON e.episode_id = o.episode_id
                WHERE o.horizon = ?
                GROUP BY bucket
                ORDER BY bucket
            """, (horizon,)).fetchall()
            score_calibration = [dict(r) for r in cal_rows]

            # Feature attribution: mean alpha by component buckets
            def _feature_buckets(component_col: str) -> list[dict]:
                rows = conn.execute(f"""
                    SELECT
                        CASE
                            WHEN e.{component_col} IS NULL THEN 'N/A'
                            WHEN e.{component_col} < 50    THEN '<50'
                            WHEN e.{component_col} < 65    THEN '50-64'
                            WHEN e.{component_col} < 80    THEN '65-79'
                            ELSE '80+'
                        END              AS bucket,
                        COUNT(*)         AS n,
                        ROUND(AVG(o.alpha)*100, 2) AS mean_alpha_pct
                    FROM decision_episodes e
                    JOIN episode_outcomes o ON e.episode_id = o.episode_id
                    WHERE o.horizon = ?
                    GROUP BY bucket ORDER BY bucket
                """, (horizon,)).fetchall()
                return [dict(r) for r in rows]

            feature_attribution = {
                "Q":  _feature_buckets("q_score"),
                "V":  _feature_buckets("v_score"),
                "PF": _feature_buckets("pf_score"),
                "C":  _feature_buckets("c_score"),
                "EC": _feature_buckets("ec_score"),
            }

            # LLM calibration: by conviction stars (NULL until conviction data arrives)
            llm_rows = conn.execute("""
                SELECT
                    COALESCE(e.llm_conviction, -1) AS stars,
                    COUNT(*)                        AS n,
                    ROUND(AVG(o.alpha)*100, 2)      AS mean_alpha_pct,
                    ROUND(SUM(CASE WHEN o.alpha > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                                                    AS hit_rate_pct
                FROM decision_episodes e
                JOIN episode_outcomes o ON e.episode_id = o.episode_id
                WHERE o.horizon = ? AND e.selected = 1
                GROUP BY stars ORDER BY stars
            """, (horizon,)).fetchall()
            llm_calibration = [dict(r) for r in llm_rows]

            # Risk gate audit: counterfactual outcomes by reject_rule (0347: use decision_alpha)
            cf_horizon = horizon if horizon in ("1w", "1m", "3m") else "3m"
            risk_rows = conn.execute("""
                SELECT
                    COALESCE(reject_rule, 'unknown') AS rule,
                    COUNT(*)                          AS n_blocked,
                    SUM(CASE WHEN COALESCE(decision_alpha, alpha) < 0 THEN 1 ELSE 0 END) AS losses_avoided,
                    SUM(CASE WHEN COALESCE(decision_alpha, alpha) > 0 THEN 1 ELSE 0 END) AS alpha_missed,
                    ROUND(AVG(alpha)*100, 2)          AS mean_alpha_pct,
                    ROUND(AVG(decision_alpha)*100, 2) AS mean_decision_alpha_pct
                FROM risk_counterfactual_outcomes
                WHERE horizon = ? AND alpha IS NOT NULL
                GROUP BY rule ORDER BY n_blocked DESC
            """, (cf_horizon,)).fetchall()
            risk_audit = [dict(r) for r in risk_rows]

            # Active model card with uncertainty bands (0343)
            active_model_row = conn.execute(
                """SELECT model_version, lifecycle_state, training_n, unique_tickers,
                          unique_decision_dates, created_at, validation_metrics
                   FROM learning_models
                   WHERE lifecycle_state = 'PAPER_ACTIVE'
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
            active_model_card = None
            if active_model_row:
                import json as _json
                vm = _json.loads(active_model_row["validation_metrics"] or "{}")
                active_model_card = {
                    "model_version": active_model_row["model_version"],
                    "lifecycle_state": active_model_row["lifecycle_state"],
                    "training_n": active_model_row["training_n"],
                    "unique_tickers": active_model_row["unique_tickers"],
                    "unique_decision_dates": active_model_row["unique_decision_dates"],
                    "cv_folds": vm.get("cv_folds"),
                    "beats_baseline": vm.get("beats_baseline"),
                    "top_vs_bottom_quintile_alpha": vm.get("top_vs_bottom_quintile_alpha"),
                    # 0347: renamed from alpha_ci_* / alpha_reliability
                    "ranking_spread_ci_low":  vm.get("ranking_spread_ci_low"),
                    "ranking_spread_ci_high": vm.get("ranking_spread_ci_high"),
                    "alpha_precision":        vm.get("alpha_precision"),
                    "alpha_edge_evidence":    vm.get("alpha_edge_evidence"),
                }

            conn.close()
            self._json({
                "ok": True,
                "horizon": horizon,
                "diagnostic_only": diagnostic_only,
                "overview": overview,
                "score_calibration": score_calibration,
                "feature_attribution": feature_attribution,
                "llm_calibration": llm_calibration,
                "risk_audit": risk_audit,
                "active_model_card": active_model_card,
            })
        except Exception as e:
            self._json_error(500, str(e))

    def _handle_trade_engine_run(self):
        """POST /api/trade-engine/run — full execution cycle for AGENTIC_SHADOW_01 (0216, 0244, 0254)."""
        conn = None
        try:
            from trade_engine.execution_engine import ExecutionSession, SessionNotReadyError
            conn = self._shadow_conn()
            session = ExecutionSession("AGENTIC_SHADOW_01", conn)
            session.initialize()  # raises SessionNotReadyError if not TRADING_READY
            summary = session.run_cycle()
            execution_state = summary.get("execution_state", "OK")
            if execution_state == "HALTED":
                self._send_json({
                    "ok": False,
                    "execution_state": "HALTED",
                    "halt_reason": summary.get("halt_reason", "unknown"),
                    "new_intents_processed": summary.get("new_intents_processed", 0),
                    "results": summary.get("results", []),
                }, 409)
            else:
                self._json({
                    "ok": True,
                    "execution_state": execution_state,
                    "new_intents_processed": summary["new_intents_processed"],
                    "new_intents_blocked": summary.get("new_intents_blocked", False),
                    "stale_symbols": summary.get("stale_symbols", []),
                    "new_orders_created": summary.get("new_orders_created", 0),
                    "fills_on_submission": summary.get("fills_on_submission", 0),
                    "risk_rejections": summary.get("risk_rejections", 0),
                    "working_orders_checked": summary.get("working_orders_checked", 0),
                    "fills_on_retry": summary.get("fills_on_retry", 0),
                    "total_fills": summary.get("total_fills", 0),
                    "orders_expired": summary.get("orders_expired", 0),
                    "results": summary.get("results", []),
                })
        except SessionNotReadyError as e:
            self._send_json({"ok": False, "error": str(e), "halt_reason": "NOT_TRADING_READY"}, 503)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)
        finally:
            if conn is not None:
                conn.close()

    # ── Learning Readiness Report (0385) ─────────────────────────────────────

    def _handle_learning_readiness(self):
        """GET /api/learning/readiness — consolidated learning loop readiness report (0385)."""
        import agent_db
        conn = None
        try:
            from agents.learning.calibration import learning_readiness_report
            conn = agent_db._connect()
            report = learning_readiness_report(conn)
            # 0442: attach experiment baseline snapshot if it exists
            _cfg = Path(__file__).resolve().parent / "config"
            _baseline_path = _cfg / "experiment_baseline.json"
            if _baseline_path.exists():
                try:
                    report["experiment_baseline"] = json.loads(_baseline_path.read_text())
                except Exception:
                    report["experiment_baseline"] = None
            else:
                report["experiment_baseline"] = None
            # attach operational integrity record if it exists
            _ir_path = _cfg / "experiment_integrity_record.json"
            try:
                report["integrity_record"] = json.loads(_ir_path.read_text()) if _ir_path.exists() else None
            except Exception:
                report["integrity_record"] = None
            # attach acceptance canary artifacts if they exist
            for _key, _fname in (
                ("shadow_canary", "experiment_shadow_canary_001.json"),
                ("paper_canary",  "experiment_paper_canary_001.json"),
            ):
                _p = _cfg / _fname
                try:
                    report[_key] = json.loads(_p.read_text()) if _p.exists() else None
                except Exception:
                    report[_key] = None
            # attach episode accumulation stats
            try:
                _ep = conn.execute(
                    """SELECT COUNT(*) AS total,
                              COUNT(DISTINCT ticker) AS tickers,
                              MIN(captured_at) AS first_at,
                              MAX(captured_at) AS last_at
                       FROM decision_episodes"""
                ).fetchone()
                report["episode_stats"] = dict(_ep) if _ep else None
            except Exception:
                report["episode_stats"] = None
            # 0554: accepted-era macro effectiveness, observe-only
            try:
                from agents.learning.macro_experiment import evaluate as _macro_eval
                report["macro_experiment"] = _macro_eval(conn)
            except Exception as _macro_exc:
                report["macro_experiment"] = {"evidence_state": "UNAVAILABLE", "error": str(_macro_exc), "observe_only": True}
            # 0443: attach latest model activation snapshot from model_promotion_log
            try:
                _mv = report.get("model_version")
                if _mv:
                    _promo = conn.execute(
                        """SELECT from_state, to_state, promoted_by, promoted_at,
                                  promotion_reason, promotion_metrics_snapshot
                           FROM model_promotion_log
                           WHERE model_version=? AND to_state IN ('OBSERVE','PAPER_ACTIVE')
                           ORDER BY promoted_at DESC LIMIT 1""",
                        (_mv,),
                    ).fetchone()
                    if _promo:
                        _snap = {}
                        try:
                            _snap = json.loads(_promo["promotion_metrics_snapshot"] or "{}")
                        except Exception:
                            pass
                        report["latest_activation_snapshot"] = {
                            "from_state": _promo["from_state"],
                            "to_state": _promo["to_state"],
                            "promoted_by": _promo["promoted_by"],
                            "promoted_at": _promo["promoted_at"],
                            "promotion_reason": _promo["promotion_reason"],
                            "git_commit_sha": _snap.get("git_commit_sha"),
                            "strategy_hash": _snap.get("strategy_hash"),
                            "policy_hash": _snap.get("policy_hash"),
                            "evidence_contract_version": _snap.get("evidence_contract_version"),
                        }
                    else:
                        report["latest_activation_snapshot"] = None
                else:
                    report["latest_activation_snapshot"] = None
            except Exception:
                report["latest_activation_snapshot"] = None
            body = json.dumps({"ok": True, "report": report}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            if conn is not None:
                conn.close()

    # ── Champion/Challenger comparison handler ────────────────────────────────

    def _handle_champion_challenger(self):
        """GET /api/learning/champion-challenger — side-by-side champion vs challenger stats (0336/0340)."""
        try:
            conn = self._shadow_conn()
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            try:
                def _stats(rows):
                    if not rows:
                        return {"n": 0, "alpha_mean": None, "hit_rate": None, "mae_mean": None, "mfe_mean": None}
                    alphas = [r["alpha_3m"] for r in rows if r.get("alpha_3m") is not None]
                    maes = [r["mae_pct"] for r in rows if r.get("mae_pct") is not None]
                    mfes = [r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]
                    returns = [r["return_3m"] for r in rows if r.get("return_3m") is not None]
                    d_returns = [r["decision_return_3m"] for r in rows if r.get("decision_return_3m") is not None]
                    is_vals = [r["implementation_shortfall"] for r in rows if r.get("implementation_shortfall") is not None]
                    return {
                        "n": len(rows),
                        "n_labeled": len(alphas),
                        "alpha_mean": sum(alphas) / len(alphas) if alphas else None,
                        "hit_rate": sum(1 for a in alphas if a > 0) / len(alphas) if alphas else None,
                        "mae_mean": sum(maes) / len(maes) if maes else None,
                        "mfe_mean": sum(mfes) / len(mfes) if mfes else None,
                        "return_mean": sum(returns) / len(returns) if returns else None,
                        "decision_return_mean": sum(d_returns) / len(d_returns) if d_returns else None,
                        "impl_shortfall_mean": sum(is_vals) / len(is_vals) if is_vals else None,
                    }

                def _book_portfolio_stats(book_id):
                    """Portfolio-level stats from virtual_book_nav (MTM) or virtual_fills fallback (0340/0359)."""
                    book = conn.execute(
                        "SELECT starting_cash, current_cash, as_of FROM virtual_books WHERE book_id=?",
                        (book_id,),
                    ).fetchone()
                    if not book:
                        return {"book_id": book_id, "available": False}

                    starting_cash = float(book["starting_cash"])
                    current_cash  = float(book["current_cash"])

                    # 0359: use MTM ledger when available — it's the authoritative source
                    try:
                        nav_rows = conn.execute(
                            """SELECT date, total_nav, spy_nav, daily_return
                               FROM virtual_book_nav
                               WHERE book_id=? AND is_complete=1
                               ORDER BY date""",
                            (book_id,),
                        ).fetchall()
                    except Exception:
                        # is_complete column may not exist on older DBs
                        try:
                            nav_rows = conn.execute(
                                """SELECT date, total_nav, spy_nav, daily_return
                                   FROM virtual_book_nav WHERE book_id=? ORDER BY date""",
                                (book_id,),
                            ).fetchall()
                        except Exception:
                            nav_rows = []

                    if nav_rows:
                        import math as _math
                        navs = [float(r["total_nav"]) for r in nav_rows]
                        spy_navs = [float(r["spy_nav"]) for r in nav_rows if r["spy_nav"] is not None]
                        daily_rets = [float(r["daily_return"]) for r in nav_rows if r["daily_return"] is not None]
                        nav_series = [{"date": r["date"], "nav": round(float(r["total_nav"]), 2)} for r in nav_rows]

                        # 0367: use starting_cash as the inception NAV, not navs[0]
                        # navs[0] is the first MTM row, which may be after cash was deployed;
                        # starting from navs[0] silently drops the return earned between
                        # inception and the first MTM run
                        starting = starting_cash
                        cum_return = (navs[-1] - starting) / starting if starting else 0.0
                        spy_cum = (spy_navs[-1] - spy_navs[0]) / spy_navs[0] if len(spy_navs) >= 2 else None

                        peak = starting
                        max_dd = 0.0
                        for n in navs:
                            peak = max(peak, n)
                            dd = (peak - n) / peak if peak else 0.0
                            max_dd = max(max_dd, dd)

                        vol = None
                        if len(daily_rets) >= 2:
                            mean = sum(daily_rets) / len(daily_rets)
                            var = sum((r - mean) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
                            vol = _math.sqrt(var) * _math.sqrt(252)

                        fill_row = conn.execute(
                            "SELECT COUNT(*) as n FROM virtual_fills WHERE book_id=? AND action='BUY'",
                            (book_id,),
                        ).fetchone()
                        trade_count = fill_row["n"] if fill_row else 0

                        return {
                            "book_id": book_id,
                            "available": True,
                            "source": "mtm",
                            "trade_count": trade_count,
                            "starting_cash": starting_cash,
                            "current_cash": current_cash,
                            "cumulative_return": round(cum_return, 6),
                            "spy_cumulative_return": round(spy_cum, 6) if spy_cum is not None else None,
                            "max_drawdown": round(max_dd, 6),
                            "annualized_volatility": round(vol, 6) if vol is not None else None,
                            "nav_series": nav_series[-90:],
                            "as_of": book["as_of"],
                        }

                    # Fallback: cost-basis reconstruction from fills
                    fills = conn.execute(
                        """SELECT ticker, action, price, qty, filled_at, decision_origin
                           FROM virtual_fills WHERE book_id=? ORDER BY filled_at""",
                        (book_id,),
                    ).fetchall()

                    if not fills:
                        return {
                            "book_id": book_id, "available": True, "source": "cost_basis",
                            "trade_count": 0,
                            "starting_cash": starting_cash, "current_cash": current_cash,
                            "deployed_pct": 0.0, "cumulative_return_cost_basis": 0.0,
                        }

                    positions = {}  # ticker → (qty, avg_cost)
                    trade_returns = []
                    total_notional = 0.0
                    nav_series = []  # {date, nav} — cost-basis NAV (no mark-to-market)
                    running_cash = starting_cash
                    peak_nav = starting_cash
                    max_drawdown = 0.0

                    for fill in fills:
                        ticker = fill["ticker"]
                        action = (fill["action"] or "BUY").upper()
                        price  = float(fill["price"])
                        qty    = float(fill["qty"])
                        total_notional += price * qty
                        fill_date = (fill["filled_at"] or "")[:10]

                        if action == "BUY":
                            prev_qty, prev_cost = positions.get(ticker, (0.0, 0.0))
                            new_qty = prev_qty + qty
                            new_cost = (prev_cost * prev_qty + price * qty) / new_qty if new_qty else price
                            positions[ticker] = (new_qty, new_cost)
                            running_cash -= price * qty
                        elif action in ("SELL", "EXIT", "TRIM"):
                            prev_qty, prev_cost = positions.get(ticker, (qty, price))
                            if prev_cost:
                                trade_returns.append(price / prev_cost - 1)
                            new_qty = max(0.0, prev_qty - qty)
                            positions[ticker] = (new_qty, prev_cost) if new_qty > 0 else (0.0, 0.0)
                            running_cash += price * qty

                        # NAV at cost basis: cash + sum(qty * avg_cost) for open positions
                        pos_value = sum(q * c for (q, c) in positions.values() if q > 0)
                        nav = running_cash + pos_value
                        if fill_date:
                            nav_series.append({"date": fill_date, "nav": round(nav, 2)})

                        peak_nav = max(peak_nav, nav)
                        dd = (peak_nav - nav) / peak_nav if peak_nav > 0 else 0.0
                        max_drawdown = max(max_drawdown, dd)

                    # Final cost-basis NAV
                    pos_value = sum(q * c for (q, c) in positions.values() if q > 0)
                    final_nav = current_cash + pos_value
                    cum_return = (final_nav - starting_cash) / starting_cash if starting_cash else 0.0
                    avg_nav = (starting_cash + final_nav) / 2
                    turnover = total_notional / avg_nav if avg_nav > 0 else 0.0

                    winners = [r for r in trade_returns if r > 0]
                    losers  = [r for r in trade_returns if r <= 0]
                    win_rate = len(winners) / len(trade_returns) if trade_returns else None
                    gross_loss = abs(sum(losers)) if losers else 0.0
                    profit_factor = (sum(winners) / gross_loss) if gross_loss > 0 else None
                    open_positions = sum(1 for (q, _) in positions.values() if q > 0)
                    deployed_pct = pos_value / final_nav * 100 if final_nav > 0 else 0.0

                    return {
                        "book_id": book_id,
                        "available": True,
                        "source": "cost_basis",
                        "trade_count": len(fills),
                        "starting_cash": starting_cash,
                        "current_cash": current_cash,
                        "deployed_pct": round(deployed_pct, 2),
                        "cumulative_return_cost_basis": round(cum_return, 6),
                        "max_drawdown": round(max_drawdown, 6),
                        "turnover": round(turnover, 4),
                        "win_rate": round(win_rate, 4) if win_rate is not None else None,
                        "avg_winner": round(sum(winners) / len(winners), 6) if winners else None,
                        "avg_loser": round(sum(losers) / len(losers), 6) if losers else None,
                        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
                        "open_positions": open_positions,
                        "as_of": book["as_of"],
                        "nav_series": nav_series[-90:],  # last 90 data points for chart
                    }

                champ_rows = conn.execute(
                    """SELECT to2.alpha_3m, to2.mae_pct, to2.mfe_pct, to2.return_3m,
                              to2.decision_return_3m, to2.implementation_shortfall
                       FROM trade_outcomes to2
                       JOIN trade_intents ti ON to2.intent_id = ti.intent_id
                       WHERE ti.decision_origin = 'CHAMPION'
                       ORDER BY to2.created_at DESC LIMIT 500"""
                ).fetchall()

                chal_rows = conn.execute(
                    """SELECT to2.alpha_3m, to2.mae_pct, to2.mfe_pct, to2.return_3m,
                              to2.decision_return_3m, to2.implementation_shortfall
                       FROM trade_outcomes to2
                       JOIN trade_intents ti ON to2.intent_id = ti.intent_id
                       WHERE ti.decision_origin = 'PAPER_CHALLENGER'
                       ORDER BY to2.created_at DESC LIMIT 500"""
                ).fetchall()

                variant_count = conn.execute(
                    "SELECT COUNT(*) as n FROM decision_variants"
                ).fetchone()["n"]

                would_have_diverged = conn.execute(
                    "SELECT COUNT(*) as n FROM decision_variants WHERE would_have_selected=1"
                ).fetchone()["n"]

                # 0354: experiment divergence = challenger vs base-score champion (not LLM rec)
                experiment_diverged = conn.execute(
                    """SELECT COUNT(*) as n FROM decision_variants
                       WHERE experiment_champion_ticker IS NOT NULL
                         AND experiment_champion_ticker != variant_ticker"""
                ).fetchone()["n"]

                active_model = conn.execute(
                    """SELECT model_version, lifecycle_state, training_n, unique_tickers,
                              unique_decision_dates, created_at
                       FROM learning_models
                       WHERE lifecycle_state = 'PAPER_ACTIVE'
                       ORDER BY created_at DESC LIMIT 1"""
                ).fetchone()

                # Execution quality: mean IS and limit_variance by action (0350)
                is_by_action = {}
                try:
                    is_rows = conn.execute(
                        """SELECT COALESCE(ti.side, 'BUY') as action,
                                  AVG(to2.implementation_shortfall) as mean_is,
                                  AVG(to2.limit_variance) as mean_limit_variance,
                                  AVG(ti.decision_spread_bps) as mean_spread_bps,
                                  COUNT(*) as n
                           FROM trade_outcomes to2
                           JOIN trade_intents ti ON to2.intent_id = ti.intent_id
                           WHERE to2.implementation_shortfall IS NOT NULL
                              OR to2.limit_variance IS NOT NULL
                           GROUP BY COALESCE(ti.side, 'BUY')"""
                    ).fetchall()
                    is_by_action = {r["action"]: {"mean_is": r["mean_is"], "mean_limit_variance": r["mean_limit_variance"], "mean_spread_bps": r["mean_spread_bps"], "n": r["n"]} for r in is_rows}
                except Exception:
                    pass

                champ_stats = _book_portfolio_stats("CHAMPION_BOOK")
                chal_stats  = _book_portfolio_stats("CHALLENGER_BOOK")

                # 0359: mtm_nav_available only True when stats actually came from MTM ledger
                mtm_nav_available = (
                    champ_stats.get("source") == "mtm" or chal_stats.get("source") == "mtm"
                )

                self._json({
                    "champion": _stats(champ_rows),
                    "challenger": _stats(chal_rows),
                    "champion_book": champ_stats,
                    "challenger_book": chal_stats,
                    "variants_recorded": variant_count,
                    "variants_would_diverge": would_have_diverged,
                    "variants_experiment_diverge": experiment_diverged,
                    "active_model": active_model,
                    "execution_quality": is_by_action,
                    "mtm_nav_available": mtm_nav_available,
                })
            finally:
                conn.close()
        except Exception as e:
            self._json_error(500, str(e))

    # ── Alpaca paper account handlers ─────────────────────────────────────────

    def _handle_alpaca_account(self):
        try:
            conn = self._shadow_conn()
            row = conn.execute(
                "SELECT * FROM trading_accounts WHERE account_id='AGENTIC_ALPACA_01'"
            ).fetchone()
            if not row:
                return self._restricted_send_json({"ok": False, "error": "alpaca account not found"}, 404)
            positions = conn.execute(
                "SELECT symbol, qty, avg_cost, instrument_type, market_price, market_value "
                "FROM position_snapshots WHERE account_id='AGENTIC_ALPACA_01'"
            ).fetchall()
            pos_value = sum(
                float(r["market_value"]) if r["market_value"] is not None
                else float(r["qty"] or 0) * float(r["avg_cost"] or 0)
                for r in positions
            )
            nav = float(row["current_cash"] or 0) + pos_value
            conn.close()
            self._restricted_json({
                "ok": True,
                "account_id": row["account_id"],
                "name": row["name"],
                "mode": row["mode"],
                "broker": row["broker"],
                "starting_capital": float(row["starting_capital"] or 0),
                "current_cash": float(row["current_cash"] or 0),
                "nav": round(nav, 2),
                "position_count": len(positions),
                "trading_enabled": bool(row["trading_enabled"]),
                "policy_version": row["policy_version"],
                "positions": [
                    {
                        "symbol": r["symbol"],
                        "qty": float(r["qty"] or 0),
                        "avg_cost": float(r["avg_cost"] or 0),
                        "market_price": float(r["market_price"]) if r["market_price"] is not None else None,
                        "value": round(
                            float(r["market_value"]) if r["market_value"] is not None
                            else float(r["qty"] or 0) * float(r["avg_cost"] or 0), 2
                        ),
                    }
                    for r in positions
                ],
            })
        except Exception as e:
            self._restricted_send_json({"ok": False, "error": str(e)}, 500)

    def _handle_alpaca_intents(self, limit: int = 20):
        try:
            conn = self._shadow_conn()
            rows = conn.execute(
                """SELECT ti.intent_id, ti.symbol, ti.side, ti.quantity, ti.limit_price,
                          ti.status, ti.created_at, ti.valid_until,
                          rd.decision, rd.checks_json
                   FROM trade_intents ti
                   LEFT JOIN risk_decisions rd ON rd.intent_id=ti.intent_id
                   WHERE ti.account_id='AGENTIC_ALPACA_01'
                   ORDER BY ti.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            intents = []
            for r in rows:
                checks = []
                if r["checks_json"]:
                    try:
                        checks = json.loads(r["checks_json"])
                    except Exception:
                        pass
                failed = [c for c in checks if c.get("result") == "FAIL"]
                passed_count = sum(1 for c in checks if c.get("result") == "PASS")
                intents.append({
                    "intent_id": r["intent_id"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "quantity": r["quantity"],
                    "limit_price": r["limit_price"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "risk_decision": r["decision"],
                    "checks_passed": passed_count,
                    "checks_failed": len(failed),
                    "fail_reason": failed[0].get("reason") if failed else None,
                })
            conn.close()
            self._restricted_json({"ok": True, "intents": intents})
        except Exception as e:
            self._restricted_send_json({"ok": False, "error": str(e)}, 500)

    def _handle_alpaca_fills(self, limit: int = 20):
        try:
            conn = self._shadow_conn()
            rows = conn.execute(
                """SELECT f.fill_id, f.symbol, f.side, f.qty, f.price, f.fee,
                          f.fill_source, f.filled_at, f.origin,
                          ti.recommendation_id, o.broker_order_id
                   FROM fills f
                   LEFT JOIN orders o ON f.order_id=o.order_id
                   LEFT JOIN trade_intents ti ON o.intent_id=ti.intent_id
                   WHERE f.account_id='AGENTIC_ALPACA_01'
                   ORDER BY f.filled_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            conn.close()
            self._restricted_json({
                "ok": True,
                "fills": [
                    {
                        "fill_id": r["fill_id"],
                        "symbol": r["symbol"],
                        "side": r["side"],
                        "qty": r["qty"],
                        "price": r["price"],
                        "fee": r["fee"],
                        "fill_source": r["fill_source"],
                        "filled_at": r["filled_at"],
                        "origin": r["origin"],
                        "recommendation_id": r["recommendation_id"],
                        "broker_order_id": r["broker_order_id"],
                    }
                    for r in rows
                ],
            })
        except Exception as e:
            self._restricted_send_json({"ok": False, "error": str(e)}, 500)

    def _handle_alpaca_runs(self, limit: int = 20):
        try:
            conn = self._shadow_conn()
            rows = conn.execute(
                """SELECT run_at, execution_state, halt_reason, duration_seconds,
                          new_intents_processed, risk_rejections, orders_submitted,
                          fills_applied, duplicate_fills_skipped, broker_api_errors,
                          cash_delta_vs_broker, position_delta_vs_broker,
                          oldest_unresolved_order_age_minutes,
                          broker_fills_observed, broker_fills_new,
                          broker_fills_duplicate, external_fills_observed
                   FROM cycle_runs
                   WHERE account_id='AGENTIC_ALPACA_01'
                   ORDER BY run_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            conn.close()
            self._restricted_json({"ok": True, "runs": [dict(r) for r in rows]})
        except Exception as e:
            self._restricted_send_json({"ok": False, "error": str(e)}, 500)

    def _handle_alpaca_risk(self, intent_id: str):
        try:
            conn = self._shadow_conn()
            row = conn.execute(
                "SELECT * FROM risk_decisions WHERE intent_id=? ORDER BY decision_id DESC LIMIT 1",
                (intent_id,),
            ).fetchone()
            conn.close()
            if not row:
                return self._restricted_send_json({"ok": False, "error": "no risk decision found"}, 404)
            checks = []
            if row["checks_json"]:
                try:
                    checks = json.loads(row["checks_json"])
                except Exception:
                    pass
            self._restricted_json({
                "ok": True,
                "intent_id": row["intent_id"],
                "decision": row["decision"],
                "evaluated_at": row["evaluated_at"],
                "checks": checks,
            })
        except Exception as e:
            self._restricted_send_json({"ok": False, "error": str(e)}, 500)

    def _handle_trade_engine_run_alpaca(self):
        """POST /api/trade-engine/run-alpaca — execution cycle for AGENTIC_ALPACA_01 (0308-0312)."""
        # ── Auth (0308) ────────────────────────────────────────────────────────
        expected_token = os.environ.get("TRADE_ENGINE_API_TOKEN", "")
        provided_token = self.headers.get("X-Trade-Engine-Token", "")
        if not expected_token or not hmac.compare_digest(
            expected_token.encode(), provided_token.encode()
        ):
            return self._restricted_send_json({"ok": False, "error": "unauthorized"}, 401)

        # ── Submission feature flag (0310) ─────────────────────────────────────
        if os.environ.get("ALPACA_PAPER_SUBMISSION_ENABLED") != "1":
            return self._restricted_send_json(
                {"ok": False, "error": "ALPACA_PAPER_SUBMISSION_ENABLED is not set to '1'"}, 503
            )

        # ── Cross-process single-flight execution lease (0317) ────────────────
        from agent_db import acquire_execution_lease, release_execution_lease
        import socket as _socket
        _lease_holder = f"http:{_socket.gethostname()}:{os.getpid()}"
        _lease_conn = self._shadow_conn()
        if not acquire_execution_lease(_lease_conn, "AGENTIC_ALPACA_01", _lease_holder, ttl_seconds=1800):
            _lease_conn.close()
            return self._restricted_send_json(
                {"ok": False, "error": "execution cycle already running for AGENTIC_ALPACA_01"}, 409
            )

        conn = None
        try:
            from trade_engine.execution_engine import ExecutionSession, SessionNotReadyError
            from trade_engine.alpaca_adapter import AlpacaAdapter, _ALPACA_PAPER_URL, _ALPACA_DATA_URL

            api_key = os.environ.get("ALPACA_API_KEY", "")
            api_secret = os.environ.get("ALPACA_API_SECRET", "")
            if not api_key or not api_secret:
                return self._restricted_send_json(
                    {"ok": False, "error": "ALPACA_API_KEY / ALPACA_API_SECRET not configured"}, 503
                )

            # ── Account binding (0309) ─────────────────────────────────────────
            expected_account_id = os.environ.get("ALPACA_PAPER_ACCOUNT_ID") or None
            if not expected_account_id:
                return self._restricted_send_json(
                    {"ok": False, "error": "ALPACA_PAPER_ACCOUNT_ID not configured — account binding cannot be verified"},
                    503,
                )

            adapter = AlpacaAdapter(
                api_key=api_key,
                api_secret=api_secret,
                base_url=_ALPACA_PAPER_URL,
                data_url=_ALPACA_DATA_URL,
                submission_enabled=True,
                expected_account_id=expected_account_id,
            )
            conn = self._shadow_conn()
            session = ExecutionSession("AGENTIC_ALPACA_01", conn, broker=adapter)
            session.initialize()
            summary = session.run_cycle()

            # ── Surface HALTED accurately (0312) ──────────────────────────────
            exec_state = summary.get("execution_state", "OK")
            halt_reason = summary.get("halt_reason")
            response = {
                "ok": exec_state != "HALTED",
                "execution_state": exec_state,
                "halt_reason": halt_reason,
                "new_intents_processed": summary["new_intents_processed"],
                "new_intents_blocked": summary.get("new_intents_blocked", False),
                "stale_symbols": summary.get("stale_symbols", []),
                "new_orders_created": summary.get("new_orders_created", 0),
                "fills_on_submission": summary.get("fills_on_submission", 0),
                "risk_rejections": summary.get("risk_rejections", 0),
                "working_orders_checked": summary.get("working_orders_checked", 0),
                "fills_on_retry": summary.get("fills_on_retry", 0),
                "total_fills": summary.get("total_fills", 0),
                "orders_expired": summary.get("orders_expired", 0),
                "results": summary.get("results", []),
            }
            if exec_state == "HALTED":
                self._restricted_send_json(response, 409)
            else:
                self._restricted_json(response)
        except SessionNotReadyError as e:
            self._restricted_send_json(
                {"ok": False, "error": str(e), "execution_state": "HALTED",
                 "halt_reason": "NOT_TRADING_READY"}, 503
            )
        except Exception as e:
            self._restricted_send_json({"ok": False, "error": str(e)}, 500)
        finally:
            release_execution_lease(_lease_conn, "AGENTIC_ALPACA_01", _lease_holder)
            _lease_conn.close()
            if conn is not None:
                conn.close()

    def _restricted_json(self, data):
        """Send 200 JSON with no CORS header — for execution/sensitive endpoints (0308)."""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _restricted_send_json(self, data, status: int = 200):
        """Send JSON with custom status and no CORS header — for execution/sensitive endpoints (0308)."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status: int = 200):
        """Send JSON response with a custom HTTP status code."""
        body = json.dumps(data).encode()
        self.send_response(status)
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
        from site_help import glossary_page
        html = glossary_page()
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
