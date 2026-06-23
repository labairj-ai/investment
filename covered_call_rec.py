#!/usr/bin/env python3
"""
Covered call recommendation engine.

Usage:
  python3 covered_call_rec.py EW          # single ticker
  python3 covered_call_rec.py EW GRMN     # multiple tickers
  python3 covered_call_rec.py             # all covered-call-eligible holdings

Strike selection logic:
  - Base minimum: strike >= avg_cost * 1.10  (10% profit if called away)
  - If stock already up >= 10% from cost:    strike >= current_price * 1.10
                                             (protect existing gain + another 10%)

Premium collected is added to effective profit calculation.
"""

import csv
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

RISK_FREE_RATE = 0.045  # approximate US 10-yr treasury


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def call_delta(S: float, K: float, T: float, sigma: float, r: float = RISK_FREE_RATE) -> float:
    """Black-Scholes delta for a European call. Returns 0 if inputs are invalid."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return _norm_cdf(d1)
    except (ValueError, ZeroDivisionError):
        return 0.0

PROJECT_DIR = Path(__file__).parent
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"

MIN_DTE = 21
MAX_DTE = 60
TOP_N  = 5
MIN_BID = 0.10   # ignore illiquid contracts with no real bid


# ── helpers ──────────────────────────────────────────────────────────────────

def normalize_ticker(t: str) -> str:
    t = str(t).strip().upper().lstrip("$")
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            t = f"{left}-{right}"
    return t


def load_holdings() -> dict:
    result = {}
    with open(HOLDINGS_CSV) as f:
        for row in csv.DictReader(f):
            t = normalize_ticker(row["Stock"])
            result[t] = {
                "shares":   float(row["Shares"]),
                "avg_cost": float(row["AvgCost"]),
                "layer":    int(row["Layer"]),
            }
    return result


def min_strike(current_price: float, avg_cost: float) -> float:
    base = avg_cost * 1.10
    if current_price >= base:
        return current_price * 1.10
    return base


def get_risk_events(stock: yf.Ticker, today, exp_date) -> list:
    """
    Returns risk events that fall within [today, exp_date]:
      - AVOID  (earnings): option spans an earnings report
      - CAUTION (ex-div):  ex-dividend before expiry → early assignment risk
    """
    events = []
    try:
        cal = stock.calendar or {}

        # ── earnings ──────────────────────────────────────────────────────────
        raw_earnings = cal.get("Earnings Date", [])
        if not isinstance(raw_earnings, list):
            raw_earnings = [raw_earnings]
        for ed in raw_earnings:
            if ed is None:
                continue
            ed_date = ed if hasattr(ed, "year") else datetime.strptime(str(ed), "%Y-%m-%d").date()
            if today < ed_date <= exp_date:
                days_to_earn = (ed_date - today).days
                days_before_exp = (exp_date - ed_date).days
                events.append({
                    "type":     "earnings",
                    "severity": "avoid",
                    "date":     str(ed_date),
                    "label":    f"📵 AVOID — earnings {str(ed_date)} ({days_to_earn}d away, {days_before_exp}d before expiry)",
                })

        # ── ex-dividend ───────────────────────────────────────────────────────
        raw_ex = cal.get("Ex-Dividend Date")
        if raw_ex and hasattr(raw_ex, "year"):
            if today < raw_ex <= exp_date:
                days_to_ex = (raw_ex - today).days
                events.append({
                    "type":     "ex_div",
                    "severity": "caution",
                    "date":     str(raw_ex),
                    "label":    f"⚠️  CAUTION — ex-div {str(raw_ex)} ({days_to_ex}d away, early assignment risk)",
                })
    except Exception:
        pass

    return events


def analyze(ticker: str, avg_cost: float, shares: float):
    stock = yf.Ticker(ticker)

    # Current price: short fetch so it's always today's data
    price_hist = stock.history(period="2d")
    if price_hist.empty:
        print(f"  [{ticker}] No price data — skipping.")
        return None
    current_price = float(price_hist["Close"].dropna().iloc[-1])

    # 52-week high: separate full-year fetch
    hist = stock.history(period="52wk")
    if hist.empty:
        week52_high    = current_price
        week52_high_dt = "n/a"
    else:
        week52_high    = float(hist["High"].max())
        week52_high_dt = hist["High"].idxmax().strftime("%Y-%m-%d")

    strike_floor = min_strike(current_price, avg_cost)
    gain_pct = (current_price - avg_cost) / avg_cost * 100
    already_at_target = current_price >= avg_cost * 1.10

    today = datetime.now().date()
    min_exp = today + timedelta(days=MIN_DTE)
    max_exp = today + timedelta(days=MAX_DTE)

    try:
        expirations = [
            e for e in stock.options
            if min_exp <= datetime.strptime(e, "%Y-%m-%d").date() <= max_exp
        ]
    except Exception:
        print(f"  [{ticker}] Could not fetch option expirations — skipping.")
        return None

    if not expirations:
        print(f"  [{ticker}] No expirations in {MIN_DTE}–{MAX_DTE} DTE window.")
        return None

    rows = []
    for exp in expirations:
        exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
        dte      = (exp_date - today).days
        try:
            calls = stock.option_chain(exp).calls
        except Exception:
            continue

        calls = calls[calls["strike"] >= strike_floor].copy()
        calls = calls[calls["bid"] >= MIN_BID].copy()
        if calls.empty:
            continue

        calls["mid"]              = (calls["bid"] + calls["ask"]) / 2
        calls["dte"]              = dte
        calls["expiration"]       = exp
        calls["premium_pct"]      = calls["mid"] / current_price * 100
        calls["annualized_ret"]   = calls["premium_pct"] * (365 / dte)
        calls["profit_if_called"] = (
            (calls["strike"] - avg_cost + calls["mid"]) / avg_cost * 100
        )
        T = dte / 365
        calls["delta"] = calls.apply(
            lambda r: call_delta(current_price, r["strike"], T,
                                 float(r["impliedVolatility"]) if r["impliedVolatility"] > 0 else 0.0),
            axis=1
        )

        risk = get_risk_events(stock, today, exp_date)
        calls["risk_events"]  = [risk] * len(calls)
        calls["has_avoid"]    = any(e["severity"] == "avoid"   for e in risk)
        calls["has_caution"]  = any(e["severity"] == "caution" for e in risk)

        rows.append(calls)

    if not rows:
        print(f"  [{ticker}] No qualifying contracts found above ${strike_floor:.2f}.")
        return None

    import pandas as pd
    all_calls = pd.concat(rows, ignore_index=True)
    all_calls = all_calls.sort_values("annualized_ret", ascending=False).head(TOP_N)

    return {
        "ticker":            ticker,
        "current_price":     current_price,
        "avg_cost":          avg_cost,
        "shares":            shares,
        "gain_pct":          gain_pct,
        "already_at_target": already_at_target,
        "strike_floor":      strike_floor,
        "week52_high":       week52_high,
        "week52_high_dt":    week52_high_dt,
        "recs":              all_calls,
    }


def print_report(r: dict) -> None:
    t     = r["ticker"]
    price = r["current_price"]
    cost  = r["avg_cost"]
    gain  = r["gain_pct"]
    floor = r["strike_floor"]

    w52  = r["week52_high"]
    w52d = r["week52_high_dt"]
    print()
    print("=" * 64)
    print(f"  {t}  —  current ${price:.2f}  |  avg cost ${cost:.2f}  |  "
          f"gain {gain:+.1f}%  |  52w high ${w52:.2f} ({w52d})")

    if r["already_at_target"]:
        print(f"  ✓ Already up ≥10% — floor set to current × 1.10 = ${floor:.2f}")
    else:
        pct_to_go = (cost * 1.10 - price) / cost * 100
        print(f"  ○ Not yet at +10% target — min strike = ${floor:.2f}  "
              f"({pct_to_go:.1f}% to go)")

    print(f"  Top {len(r['recs'])} contracts  (DTE {MIN_DTE}–{MAX_DTE}, "
          f"bid ≥ ${MIN_BID})\n")

    print(f"  {'Expiry':<12} {'Strike':>7} {'DTE':>4} {'Bid':>6} {'Ask':>6} "
          f"{'Mid':>6} {'Prem%':>6} {'Ann%':>7} {'P/L if called':>14} {'Prob Called':>12}")
    print("  " + "-" * 95)

    for _, row in r["recs"].iterrows():
        avoid_tag   = " 📵AVOID"   if row.get("has_avoid")   else ""
        caution_tag = " ⚠️ CAUTION" if row.get("has_caution") else ""
        print(
            f"  {row['expiration']:<12} "
            f"${row['strike']:>6.2f} "
            f"{int(row['dte']):>4}d "
            f"${row['bid']:>5.2f} "
            f"${row['ask']:>5.2f} "
            f"${row['mid']:>5.2f} "
            f"{row['premium_pct']:>5.1f}% "
            f"{row['annualized_ret']:>6.1f}% "
            f"  {row['profit_if_called']:>+.1f}% vs cost"
            f"  {row['delta']*100:>5.1f}%"
            f"{avoid_tag}{caution_tag}"
        )
        for event in (row.get("risk_events") or []):
            print(f"    {event['label']}")
    print()


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    holdings = load_holdings()

    tickers = [t.upper() for t in sys.argv[1:]]
    if not tickers:
        tickers = list(holdings.keys())

    print(f"\nCovered Call Recommendations  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Criteria: strike ≥ cost×1.10 (or current×1.10 if already up ≥10%)")

    found = False
    for ticker in tickers:
        if ticker not in holdings:
            print(f"\n  [{ticker}] Not in holdings.csv — skipping.")
            continue
        h = holdings[ticker]
        print(f"\nAnalyzing {ticker}...")
        result = analyze(ticker, h["avg_cost"], h["shares"])
        if result:
            print_report(result)
            found = True

    if not found:
        print("\nNo recommendations generated.\n")


if __name__ == "__main__":
    main()
