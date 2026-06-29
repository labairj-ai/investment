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


def bs_call_price(S: float, K: float, T: float, sigma: float, r: float = RISK_FREE_RATE) -> float:
    """Black-Scholes fair value for a European call. Returns 0 if inputs are invalid."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    except (ValueError, ZeroDivisionError):
        return 0.0

PROJECT_DIR = Path(__file__).parent
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"

MIN_DTE = 21
MAX_DTE = 60
MAX_DTE_EXTENDED = 180  # fallback when standard window is dry
TOP_N   = 5
MIN_BID = 0.05   # minimum bid for a "live" market
# Covered calls beyond 50% above current price have negligible premium;
# also filters out legacy pre-split contracts with unadjusted strikes
MAX_STRIKE_MULTIPLIER = 1.50


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

    # 52-week high + historical volatility from the same fetch
    hist = stock.history(period="52wk")
    if hist.empty:
        week52_high    = current_price
        week52_high_dt = "n/a"
        hist_vol       = 0.40   # conservative default
    else:
        week52_high    = float(hist["High"].max())
        week52_high_dt = hist["High"].idxmax().strftime("%Y-%m-%d")
        _ret = hist["Close"].pct_change().dropna()
        hist_vol = float(_ret.std() * math.sqrt(252)) if len(_ret) >= 20 else 0.40

    strike_floor = min_strike(current_price, avg_cost)
    gain_pct = (current_price - avg_cost) / avg_cost * 100
    already_at_target = current_price >= avg_cost * 1.10

    today = datetime.now().date()

    try:
        all_options = stock.options
    except Exception:
        print(f"  [{ticker}] Could not fetch option expirations — skipping.")
        return None

    def _get_expirations(max_dte):
        min_exp = today + timedelta(days=MIN_DTE)
        max_exp = today + timedelta(days=max_dte)
        return [
            e for e in all_options
            if min_exp <= datetime.strptime(e, "%Y-%m-%d").date() <= max_exp
        ]

    def _build_rows(expirations, mid_mode):
        """
        mid_mode controls how mid price is computed when bids are zero:
          "live"        – bid >= MIN_BID required
          "ask_proxy"   – bid=0 ok; use ask * 0.5 as conservative mid
          "theoretical" – bid=ask=0 ok; use Black-Scholes from IV
        Returns (rows, note_fragment)
        """
        import pandas as pd
        rows = []
        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            try:
                calls = stock.option_chain(exp).calls
            except Exception:
                continue

            max_strike = current_price * MAX_STRIKE_MULTIPLIER
            calls = calls[calls["strike"] >= strike_floor].copy()
            calls = calls[calls["strike"] <= max_strike].copy()

            if mid_mode == "live":
                calls = calls[calls["bid"] >= MIN_BID].copy()
                if calls.empty:
                    continue
                calls["mid"] = (calls["bid"] + calls["ask"]) / 2

            elif mid_mode == "ask_proxy":
                # bid=0 but ask>0: use ask * 0.5 as conservative estimate
                calls = calls[calls["ask"] >= MIN_BID * 2].copy()
                if calls.empty:
                    continue
                calls["mid"] = calls.apply(
                    lambda r: (r["bid"] + r["ask"]) / 2 if r["bid"] >= MIN_BID
                              else r["ask"] * 0.50,
                    axis=1,
                )

            elif mid_mode == "theoretical":
                # bid=ask=0: use Black-Scholes with historical vol as IV floor.
                # yfinance often returns stale/rounded IVs (e.g. 6.25%) when
                # markets are closed; hist_vol provides a realistic fallback.
                T_yr = dte / 365
                def _eff_iv(chain_iv):
                    iv = float(chain_iv) if chain_iv and float(chain_iv) > 0.01 else 0.0
                    return max(iv, hist_vol * 0.80)   # never go below 80% of hist vol

                calls["bs_mid"] = calls.apply(
                    lambda r: bs_call_price(
                        current_price, r["strike"], T_yr, _eff_iv(r["impliedVolatility"])
                    ),
                    axis=1,
                )
                calls = calls[calls["bs_mid"] >= MIN_BID].copy()
                if calls.empty:
                    continue
                calls["mid"] = calls["bs_mid"]

            if calls.empty:
                continue

            T = dte / 365
            calls["dte"]       = dte
            calls["expiration"] = exp
            calls["premium_pct"]      = calls["mid"] / current_price * 100
            calls["annualized_ret"]   = calls["premium_pct"] * (365 / dte)
            calls["profit_if_called"] = (
                (calls["strike"] - avg_cost + calls["mid"]) / avg_cost * 100
            )
            calls["delta"] = calls.apply(
                lambda r: call_delta(current_price, r["strike"], T,
                                     float(r["impliedVolatility"]) if r["impliedVolatility"] > 0 else 0.0),
                axis=1,
            )

            risk = get_risk_events(stock, today, exp_date)
            calls["risk_events"] = [risk] * len(calls)
            calls["has_avoid"]   = any(e["severity"] == "avoid"   for e in risk)
            calls["has_caution"] = any(e["severity"] == "caution" for e in risk)
            rows.append(calls)
        return rows

    # ── Tier 1: standard 21–60 DTE, live bids ─────────────────────────────
    exps = _get_expirations(MAX_DTE)
    note = None
    data_mode = "live"
    dte_extended = False

    rows = _build_rows(exps, "live") if exps else []

    # ── Tier 2: same window, ask-proxy mid (market closed / illiquid) ──────
    if not rows and exps:
        rows = _build_rows(exps, "ask_proxy")
        if rows:
            data_mode = "ask_proxy"
            note = ("⚠️ No live bids found — market may be closed or options are illiquid. "
                    "Premiums are estimated at 50% of the ask. Verify before trading.")

    # ── Tier 3: ask-proxy exhausted, try IV-based theoretical prices ───────
    if not rows and exps:
        rows = _build_rows(exps, "theoretical")
        if rows:
            data_mode = "theoretical"
            note = ("⚠️ No market quotes found (bid=ask=0). Premiums are Black-Scholes "
                    "estimates from implied volatility — for reference only. "
                    "Verify with your broker when the market opens.")

    # ── Tier 4: widen DTE window to 21–90 and retry ────────────────────────
    if not rows:
        exps_ext = _get_expirations(MAX_DTE_EXTENDED)
        new_exps = [e for e in exps_ext if e not in exps]
        if new_exps:
            for mode in ("live", "ask_proxy", "theoretical"):
                rows = _build_rows(new_exps, mode)
                if rows:
                    data_mode = mode
                    dte_extended = True
                    suffix = {
                        "live":        "",
                        "ask_proxy":   " Premiums estimated at 50% of ask.",
                        "theoretical": " Premiums are Black-Scholes estimates from IV.",
                    }[mode]
                    note = (f"No contracts found in standard 21–60 DTE window — "
                            f"showing 61–{MAX_DTE_EXTENDED} DTE instead.{suffix}")
                    break

    if not exps and not _get_expirations(MAX_DTE_EXTENDED):
        print(f"  [{ticker}] No expirations in {MIN_DTE}–{MAX_DTE_EXTENDED} DTE window.")
        return None

    if not rows:
        print(f"  [{ticker}] No qualifying contracts found above ${strike_floor:.2f} "
              f"(tried live, ask-proxy, and theoretical modes).")
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
        "data_mode":         data_mode,
        "dte_extended":      dte_extended,
        "note":              note,
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
