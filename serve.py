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
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 5001


def _safe_float(v, default=0.0):
    """Convert v to float, returning default for None/NaN/inf."""
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default
PROJECT_DIR = Path(__file__).parent
os.chdir(PROJECT_DIR)


class Handler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/covered-calls":
            self._handle_covered_calls(parse_qs(parsed.query))
        elif parsed.path == "/api/dividends":
            self._handle_dividends()
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
                })

            self._json({
                "ok":               True,
                "ticker":           result["ticker"],
                "current_price":    round(result["current_price"], 2),
                "avg_cost":         round(result["avg_cost"], 2),
                "gain_pct":         round(result["gain_pct"], 2),
                "already_at_target": result["already_at_target"],
                "strike_floor":     round(result["strike_floor"], 2),
                "recs":             recs,
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
            holdings = load_holdings()

            today = date.today()
            results = []

            for ticker, meta in sorted(holdings.items()):
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
                        continue

                    # ── upcoming declared dates from calendar ─────────────────
                    ex_date = pay_date = None
                    try:
                        cal = tk.calendar or {}
                        raw_ex  = cal.get("Ex-Dividend Date")
                        raw_pay = cal.get("Dividend Date")
                        if hasattr(raw_ex, "strftime"):
                            ex_str = raw_ex.strftime("%Y-%m-%d")
                            # Only use if it's in the future
                            if datetime.strptime(ex_str, "%Y-%m-%d").date() >= today:
                                ex_date = ex_str
                        if hasattr(raw_pay, "strftime"):
                            pay_str = raw_pay.strftime("%Y-%m-%d")
                            if datetime.strptime(pay_str, "%Y-%m-%d").date() >= today:
                                pay_date = pay_str
                    except Exception:
                        pass

                    # Fall back to info exDividendDate if calendar missing
                    if not ex_date:
                        try:
                            info = tk.info or {}
                            ts = info.get("exDividendDate")
                            if ts:
                                d = datetime.utcfromtimestamp(ts).date()
                                if d >= today:
                                    ex_date = d.strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    # ── compute yields from rate + price (not yfinance yield) ─
                    div_yield = round(annual_rate / price * 100, 2) if annual_rate and price else None
                    yoc       = round(annual_rate / avg_cost * 100, 2) if annual_rate and avg_cost else None

                    # ── days until ex-div ─────────────────────────────────────
                    days_to_ex = None
                    if ex_date:
                        days_to_ex = (datetime.strptime(ex_date, "%Y-%m-%d").date() - today).days

                    declared_amount = last_amount  # best estimate for next payout

                    row.update({
                        "ex_div_date":     ex_date,
                        "pay_date":        pay_date,
                        "declared_amount": declared_amount,
                        "annual_rate":     annual_rate,
                        "div_yield":       div_yield,
                        "yield_on_cost":   yoc,
                        "last_amount":     last_amount,
                        "last_date":       last_date,
                        "total_payout":    round(declared_amount * shares, 2) if declared_amount else None,
                        "annual_income":   round(annual_rate * shares, 2) if annual_rate else None,
                        "days_to_ex":      days_to_ex,
                        "declared":        bool(ex_date),
                    })
                    results.append(row)

                except Exception as e:
                    row["error"] = str(e)
                    results.append(row)

            # Sort: upcoming declared first by days_to_ex, then last-paid by ticker
            results.sort(key=lambda r: (
                0 if r.get("declared") else 1,
                r.get("days_to_ex") if r.get("days_to_ex") is not None else 9999,
                r["ticker"]
            ))

            self._json({"ok": True, "results": results, "as_of": today.isoformat()})

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
