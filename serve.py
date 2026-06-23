#!/usr/bin/env python3
"""
Investment dashboard server.
Serves static files at http://localhost:5001 and handles:
  GET /api/covered-calls?ticker=EW  → option chain recommendations (JSON)
  GET /api/dividends                → upcoming/recent dividend info for all holdings
"""

import json
import math
import http.server
import os
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_div_cache      = {"data": None, "ts": 0}
_earn_cache     = {"data": None, "ts": 0}
_timeline_cache = {"data": None, "ts": 0}
_DIV_CACHE_TTL      = 3600
_EARN_CACHE_TTL     = 3600
_TIMELINE_CACHE_TTL = 3600

PORT = 5001


def _classify_div_type(info, ticker):
    """Return 'qualified', 'ordinary', or 'tax_exempt' for a holding."""
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
    """Convert v to float, returning default for None/NaN/inf."""
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default
PROJECT_DIR = Path(__file__).parent
os.chdir(PROJECT_DIR)


# ── Daily newsletter scheduler ────────────────────────────────────────────────
def _run_daily():
    """
    Background thread: runs the newsletter + dashboard once per day.
    Fires immediately if it's ≥ 8 AM ET and hasn't run today.
    Rechecks every 30 minutes to catch the 8 AM window if the server
    was already running beforehand.
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
            else:
                print(f"[Scheduler] Failed — will retry in 30 min.")
        time.sleep(1800)


threading.Thread(target=_run_daily, daemon=True).start()


class Handler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
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
        else:
            super().do_GET()

    def _handle_covered_calls(self, params):
        ticker = (params.get("ticker", [None])[0] or "").upper().strip()
        if not ticker:
            return self._json_error(400, "Missing ticker parameter")

        try:
            from covered_call_rec import analyze, load_holdings
            holdings = load_holdings()

            if ticker not in holdings:
                return self._json_error(404, f"{ticker} not found in holdings")

            h = holdings[ticker]
            result = analyze(ticker, h["avg_cost"], h["shares"])

            if result is None:
                return self._json({"ok": False, "ticker": ticker,
                                   "error": "No qualifying contracts found in 21–60 DTE window."})

            recs = []
            for _, row in result["recs"].iterrows():
                recs.append({
                    "expiration":     row["expiration"],
                    "strike":         float(row["strike"]),
                    "dte":            int(row["dte"]),
                    "bid":            float(row["bid"]),
                    "ask":            float(row["ask"]),
                    "mid":            float(row["mid"]),
                    "premium_pct":    round(float(row["premium_pct"]), 2),
                    "annualized_ret": round(float(row["annualized_ret"]), 1),
                    "profit_if_called": round(float(row["profit_if_called"]), 1),
                    "open_interest":  int(row.get("openInterest") or 0),
                    "volume":         int(row.get("volume") or 0),
                    "delta":          round(_safe_float(row.get("delta")), 3),
                    "risk_events":    list(row.get("risk_events") or []),
                    "has_avoid":      bool(row.get("has_avoid")),
                    "has_caution":    bool(row.get("has_caution")),
                })

            self._json({
                "ok":               True,
                "ticker":           result["ticker"],
                "current_price":    round(result["current_price"], 2),
                "avg_cost":         round(result["avg_cost"], 2),
                "gain_pct":         round(result["gain_pct"], 2),
                "already_at_target": result["already_at_target"],
                "strike_floor":     round(result["strike_floor"], 2),
                "week52_high":      round(result["week52_high"], 2),
                "week52_high_dt":   result["week52_high_dt"],
                "recs":             recs,
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

            if _timeline_cache["data"] and (time.time() - _timeline_cache["ts"]) < _TIMELINE_CACHE_TTL:
                return self._json(_timeline_cache["data"])

            holdings   = load_holdings()
            today      = date.today()
            this_year  = today.year
            this_month = today.strftime("%Y-%m")

            # Always Jan–Dec of the current year
            months = [date(this_year, m, 1).strftime("%Y-%m") for m in range(1, 13)]

            received = defaultdict(float)
            expected = defaultdict(float)

            def fetch_one(ticker, meta):
                shares = meta["shares"]
                r_local = defaultdict(float)
                e_local = defaultdict(float)
                try:
                    tk   = yf.Ticker(ticker)
                    divs = tk.dividends
                    if divs.empty:
                        return r_local, e_local

                    # ── historical received ───────────────────────────────────
                    for ts, amount in divs.items():
                        d = ts.date() if hasattr(ts, "date") else ts
                        mk = d.strftime("%Y-%m")
                        if mk in months:
                            if d < today:
                                r_local[mk] += float(amount) * shares

                    # ── estimate future ───────────────────────────────────────
                    if len(divs) >= 2:
                        recent = divs.tail(4)
                        intervals = [(recent.index[i] - recent.index[i-1]).days
                                     for i in range(1, len(recent))]
                        avg_days  = sum(intervals) / len(intervals)
                        freq_days = int(round(avg_days))

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

            items = list(holdings.items())
            with ThreadPoolExecutor(max_workers=10) as pool:
                for r_local, e_local in pool.map(lambda kv: fetch_one(kv[0], kv[1]), items):
                    for mk, v in r_local.items():
                        received[mk] += v
                    for mk, v in e_local.items():
                        expected[mk] += v

            received_series = [round(received.get(mk, 0), 2) for mk in months]
            expected_series = [round(expected.get(mk, 0), 2) for mk in months]
            this_idx        = months.index(this_month) if this_month in months else None

            payload = {
                "ok":           True,
                "months":       months,
                "received":     received_series,
                "expected":     expected_series,
                "this_month":   this_month,
                "this_month_idx": this_idx,
            }
            _timeline_cache["data"] = payload
            _timeline_cache["ts"]   = time.time()
            self._json(payload)

        except Exception as e:
            self._json_error(500, str(e))

    def _handle_earnings(self):
        try:
            import yfinance as yf
            import warnings
            from datetime import date, datetime
            warnings.filterwarnings("ignore")

            from covered_call_rec import load_holdings

            if _earn_cache["data"] and (time.time() - _earn_cache["ts"]) < _EARN_CACHE_TTL:
                return self._json(_earn_cache["data"])

            holdings  = load_holdings()
            today     = date.today()

            LAYER_NAMES = {
                1: "Layer 1: Structural Ballast",
                2: "Layer 2: Cash-Flow Engines",
                3: "Layer 3: Compounders",
                4: "Layer 4: Convexity / Optionality",
                5: "Layer 5: Shock Absorbers / Regime Hedges",
            }

            def fetch_one(ticker, meta):
                row = {"ticker": ticker, "layer_num": meta["layer"],
                       "layer": LAYER_NAMES.get(meta["layer"], f"Layer {meta['layer']}")}
                try:
                    tk = yf.Ticker(ticker)

                    # ── 1. check calendar for declared upcoming date ──────────
                    upcoming = []
                    past     = []
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

                    # ── 2. fall back to earnings_dates history ────────────────
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
                        return row  # no earnings data anywhere

                    days = (target - today).days
                    row.update({
                        "earnings_date": str(target),
                        "is_upcoming":   is_upcoming,
                        "days_to_earn":  days,
                    })
                except Exception:
                    pass
                return row

            items       = list(holdings.items())
            results_raw = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for r in pool.map(lambda kv: fetch_one(kv[0], kv[1]), items):
                    if r.get("earnings_date"):
                        results_raw.append(r)

            # Deduplicate
            seen, results = set(), []
            for r in results_raw:
                if r["ticker"] not in seen:
                    seen.add(r["ticker"])
                    results.append(r)

            # Sort: upcoming first by days_to_earn, then past by days descending
            results.sort(key=lambda r: (
                0 if r.get("is_upcoming") else 1,
                r.get("days_to_earn", 9999)
            ))

            payload = {"ok": True, "results": results, "as_of": today.isoformat()}
            _earn_cache["data"] = payload
            _earn_cache["ts"]   = time.time()
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

            # Price
            price = None
            try:
                hist  = tk.history(period="2d")
                price = _safe_float(hist["Close"].dropna().iloc[-1]) if not hist.empty else None
            except Exception:
                pass

            if price is None:
                return self._json({"ok": False, "error": f"Could not fetch price for {ticker}"})

            # Name
            name = ticker
            try:
                info = tk.info or {}
                name = info.get("longName") or info.get("shortName") or ticker
            except Exception:
                info = {}

            # Dividend history
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

            # Upcoming dates
            ex_date = pay_date = None
            try:
                cal = tk.calendar or {}
                raw_ex  = cal.get("Ex-Dividend Date")
                raw_pay = cal.get("Dividend Date")
                if hasattr(raw_ex, "strftime"):
                    ex_date  = raw_ex.strftime("%Y-%m-%d")
                if hasattr(raw_pay, "strftime"):
                    pay_date = raw_pay.strftime("%Y-%m-%d")
            except Exception:
                pass
            if not ex_date and last_date:
                ex_date = last_date

            days_to_ex  = (datetime.strptime(ex_date, "%Y-%m-%d").date() - today).days if ex_date else None
            is_upcoming = days_to_ex is not None and days_to_ex >= 0

            # Tax type
            try:
                tax_type = _classify_div_type(info, ticker)
            except Exception:
                tax_type = "qualified"

            div_yield   = round(annual_rate / price * 100, 2) if annual_rate and price else None
            total_payout  = round(last_amount * shares, 2)   if last_amount and shares else None
            annual_income = round(annual_rate * shares, 2)    if annual_rate and shares else None

            self._json({
                "ok":           True,
                "ticker":       ticker,
                "name":         name,
                "price":        round(price, 2) if price else None,
                "shares":       shares,
                "ex_div_date":  ex_date,
                "pay_date":     pay_date,
                "declared_amount": last_amount,
                "last_date":    last_date,
                "annual_rate":  annual_rate,
                "div_yield":    div_yield,
                "total_payout": total_payout,
                "annual_income":annual_income,
                "days_to_ex":   days_to_ex,
                "declared":     is_upcoming,
                "tax_type":     tax_type,
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

            # ── serve from cache if fresh ────────────────────────────────────
            if _div_cache["data"] and (time.time() - _div_cache["ts"]) < _DIV_CACHE_TTL:
                return self._json(_div_cache["data"])

            holdings = load_holdings()
            today = date.today()

            def fetch_one(ticker, meta):
                shares   = meta["shares"]
                avg_cost = meta["avg_cost"]
                row = {"ticker": ticker, "shares": shares}
                try:
                    tk = yf.Ticker(ticker)

                    # ── current price ─────────────────────────────────────────
                    price = None
                    try:
                        hist  = tk.history(period="2d")
                        price = _safe_float(hist["Close"].dropna().iloc[-1]) if not hist.empty else None
                    except Exception:
                        pass
                    row["price"] = price

                    # ── dividend history (most reliable source) ───────────────
                    last_amount = last_date = annual_rate = None
                    try:
                        divs = tk.dividends
                        if not divs.empty:
                            last_amount = round(float(divs.iloc[-1]), 4)
                            last_date   = divs.index[-1].strftime("%Y-%m-%d")
                            # Estimate annual rate from payment frequency
                            if len(divs) >= 2:
                                intervals = [(divs.index[i] - divs.index[i-1]).days
                                             for i in range(max(1, len(divs)-4), len(divs))]
                                avg_days  = sum(intervals) / len(intervals)
                                freq = 4 if avg_days < 100 else (2 if avg_days < 250 else 1)
                                annual_rate = round(float(divs.iloc[-1]) * freq, 4)
                    except Exception:
                        pass

                    # Skip tickers with no dividend history at all
                    if not last_amount:
                        return row

                    # ── declared dates from calendar (keep even if past) ──────
                    ex_date = pay_date = None
                    try:
                        cal = tk.calendar or {}
                        raw_ex  = cal.get("Ex-Dividend Date")
                        raw_pay = cal.get("Dividend Date")
                        if hasattr(raw_ex, "strftime"):
                            ex_date  = raw_ex.strftime("%Y-%m-%d")
                        if hasattr(raw_pay, "strftime"):
                            pay_date = raw_pay.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                    # Fall back to info exDividendDate (unix timestamp)
                    if not ex_date:
                        try:
                            info = tk.info or {}
                            ts = info.get("exDividendDate")
                            if ts:
                                ex_date = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    # Fall back to last dividend date from history
                    if not ex_date and last_date:
                        ex_date = last_date

                    # ── classify dividend tax type ────────────────────────────
                    tax_type = "qualified"  # default
                    try:
                        info     = tk.info or {}
                        tax_type = _classify_div_type(info, ticker)
                    except Exception:
                        pass

                    # ── compute yields from rate + price (not yfinance yield) ─
                    div_yield = round(annual_rate / price * 100, 2) if annual_rate and price else None
                    yoc       = round(annual_rate / avg_cost * 100, 2) if annual_rate and avg_cost else None

                    # ── days until ex-div (negative = already past) ───────────
                    days_to_ex = None
                    if ex_date:
                        days_to_ex = (datetime.strptime(ex_date, "%Y-%m-%d").date() - today).days

                    # declared = confirmed future date; otherwise showing most recent known
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
                    results.append(row)

                except Exception as e:
                    row["error"] = str(e)
                return row

            # ── fetch all tickers in parallel ────────────────────────────────
            items   = list(holdings.items())
            results_raw = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for row in pool.map(lambda kv: fetch_one(kv[0], kv[1]), items):
                    if row and row.get("last_amount"):
                        results_raw.append(row)

            # Deduplicate (yfinance occasionally triggers double fetches in threads)
            seen, results = set(), []
            for r in results_raw:
                if r["ticker"] not in seen:
                    seen.add(r["ticker"])
                    results.append(r)

            # Sort: upcoming declared first by days_to_ex, then last-paid by ticker
            results.sort(key=lambda r: (
                0 if r.get("declared") else 1,
                r.get("days_to_ex") if r.get("days_to_ex") is not None else 9999,
                r["ticker"]
            ))

            payload = {"ok": True, "results": results, "as_of": today.isoformat()}
            _div_cache["data"] = payload
            _div_cache["ts"]   = time.time()
            self._json(payload)

        except Exception as e:
            self._json_error(500, str(e))

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, code, msg):
        body = json.dumps({"ok": False, "error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
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
