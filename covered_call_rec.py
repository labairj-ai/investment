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
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

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


def analyze(ticker: str, avg_cost: float, shares: float):
    stock = yf.Ticker(ticker)

    hist = stock.history(period="5d")
    if hist.empty:
        print(f"  [{ticker}] No price data — skipping.")
        return None
    current_price = float(hist["Close"].dropna().iloc[-1])

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
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
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
        "recs":              all_calls,
    }


def print_report(r: dict) -> None:
    t     = r["ticker"]
    price = r["current_price"]
    cost  = r["avg_cost"]
    gain  = r["gain_pct"]
    floor = r["strike_floor"]

    print()
    print("=" * 64)
    print(f"  {t}  —  current ${price:.2f}  |  cost basis ${cost:.2f}  |  "
          f"gain {gain:+.1f}%")

    if r["already_at_target"]:
        print(f"  ✓ Already up ≥10% — floor set to current × 1.10 = ${floor:.2f}")
    else:
        pct_to_go = (cost * 1.10 - price) / cost * 100
        print(f"  ○ Not yet at +10% target — min strike = ${floor:.2f}  "
              f"({pct_to_go:.1f}% to go)")

    print(f"  Top {len(r['recs'])} contracts  (DTE {MIN_DTE}–{MAX_DTE}, "
          f"bid ≥ ${MIN_BID})\n")

    print(f"  {'Expiry':<12} {'Strike':>7} {'DTE':>4} {'Bid':>6} {'Ask':>6} "
          f"{'Mid':>6} {'Prem%':>6} {'Ann%':>7} {'P/L if called':>14}")
    print("  " + "-" * 80)

    for _, row in r["recs"].iterrows():
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
        )
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
