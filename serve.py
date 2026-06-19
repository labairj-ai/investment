#!/usr/bin/env python3
"""
Investment dashboard server.
Serves static files at http://localhost:5001 and handles:
  GET /api/covered-calls?ticker=EW  → option chain recommendations (JSON)
"""

import json
import http.server
import os
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 5001
PROJECT_DIR = Path(__file__).parent
os.chdir(PROJECT_DIR)


class Handler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/covered-calls":
            self._handle_covered_calls(parse_qs(parsed.query))
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
