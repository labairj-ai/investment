#!/usr/bin/env python3
"""
Covered call recommendation engine — V2

Central question: does selling this call provide positive expected value versus
simply continuing to own the stock?  Every contract is ranked by covered-call
alpha (E[premium - upside surrendered]) rather than raw annualized yield.

Key metrics
-----------
cc_alpha          : exec_premium - E[max(S_T-K, 0)] under blended real-world drift
regret_threshold  : K + exec_premium  (stock price where CC starts trailing hold)
regret_prob       : P(S_T > K + exec_premium) under real-world model
itm_prob_rn       : N(d2)  risk-neutral probability of expiring ITM
itm_prob_real     : estimated probability of expiring ITM under real-world price drift (mu)
expected_move     : S × IV × sqrt(T)  1-sigma move over option life
z_strike          : ln(K/S) / (IV×sqrt(T))  vol-normalised distance to strike
iv_richness       : IV / HV_forecast - 1  (>0 means IV rich vs expected realised)
exec_premium      : bid + 0.25×(ask-bid)  estimated fill price
liquidity_score   : 0-100 composite (spread, OI, volume)

Profit floor (per-contract, premium counts toward floor):
  K + exec_premium >= max(C × (1 + R_MIN), S × (1 + R_FORWARD))

Usage:
  python3 covered_call_rec.py EW
  python3 covered_call_rec.py EW GRMN
  python3 covered_call_rec.py           # all holdings
"""

import csv
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

from strategy_config import (
    CC_MIN_DTE as MIN_DTE,
    CC_MAX_DTE as MAX_DTE,
    CC_MAX_DTE_EXTENDED as MAX_DTE_EXTENDED,
    CC_R_MIN as R_MIN,
    CC_R_FORWARD as R_FORWARD,
    CC_EXEC_LAMBDA as EXEC_LAMBDA,
    CC_MIN_BID as MIN_BID,
    CC_TOP_N as TOP_N,
    CC_MAX_STRIKE_MULTIPLIER as MAX_STRIKE_MULTIPLIER,
)

# ── Settings ──────────────────────────────────────────────────────────────────

RISK_FREE_RATE = 0.045

# Drift model
DRIFT_WEIGHT_60D   = 0.50
DRIFT_WEIGHT_252D  = 0.25
DRIFT_WEIGHT_MKT   = 0.25
DRIFT_MKT_LONG_RUN = 0.10
DRIFT_CAP          = 0.50

PROJECT_DIR  = Path(__file__).parent
HOLDINGS_CSV = PROJECT_DIR / "holdings.csv"


# ── Retry helper ──────────────────────────────────────────────────────────────

def _yf_retry(fn, retries=2, delay=2.0):
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception:
            if attempt < retries:
                time.sleep(delay)
            else:
                raise


# ── Math ─────────────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def _bs_d1d2(S, K, T, sigma, r=RISK_FREE_RATE, q=0.0):
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / sq
    return d1, d1 - sq


def call_delta(S: float, K: float, T: float, sigma: float,
               r: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1, _ = _bs_d1d2(S, K, T, sigma, r, q)
        return math.exp(-q * T) * _norm_cdf(d1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def call_gamma(S: float, K: float, T: float, sigma: float,
               r: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d1, _ = _bs_d1d2(S, K, T, sigma, r, q)
        return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError):
        return 0.0


def bs_call_price(S: float, K: float, T: float, sigma: float,
                  r: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    try:
        d1, d2 = _bs_d1d2(S, K, T, sigma, r, q)
        return (S * math.exp(-q * T) * _norm_cdf(d1)
                - K * math.exp(-r * T) * _norm_cdf(d2))
    except (ValueError, ZeroDivisionError):
        return 0.0


def call_extrinsic(S: float, K: float, option_price: float) -> float:
    return max(0.0, option_price - max(0.0, S - K))


def itm_prob_rn(S: float, K: float, T: float, sigma: float,
                r: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    """Risk-neutral probability of expiring ITM: N(d2). Lower than delta (N(d1))."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if S > K else 0.0
    try:
        _, d2 = _bs_d1d2(S, K, T, sigma, r, q)
        return _norm_cdf(d2)
    except (ValueError, ZeroDivisionError):
        return 0.0


def itm_prob_real(S: float, K: float, T: float, sigma: float,
                  mu: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    """Estimated probability of expiring ITM under real-world price-return drift mu."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if S > K else 0.0
    try:
        d2_real = (math.log(S / K) + (mu - q - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return _norm_cdf(d2_real)
    except (ValueError, ZeroDivisionError):
        return 0.0


def expected_upside_lost(S: float, K: float, T: float, sigma: float,
                          mu: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    """E[max(S_T - K, 0)] under real-world lognormal with drift mu."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, S - K)
    try:
        sq = sigma * math.sqrt(T)
        d1 = (math.log(S / K) + (mu - q + 0.5 * sigma ** 2) * T) / sq
        d2 = d1 - sq
        return S * math.exp((mu - q) * T) * _norm_cdf(d1) - K * _norm_cdf(d2)
    except (ValueError, ZeroDivisionError):
        return max(0.0, S - K)


def regret_prob(S: float, K: float, P: float, T: float, sigma: float,
                mu: float = RISK_FREE_RATE, q: float = 0.0) -> float:
    """P(S_T > K + P): probability CC underperforms simply holding the stock."""
    return itm_prob_real(S, K + P, T, sigma, mu, q)


# ── Volatility model ──────────────────────────────────────────────────────────

def _estimate_drift(ret) -> float:
    """Blended real-world annualised drift from dividend-adjusted Close.pct_change().
    yfinance auto_adjust=True (default) means returns are total-return drift.
    Caller must subtract q (annual dividend yield) when computing real-world d2."""
    n = len(ret)
    values, weights = [], []
    if n >= 60:
        values.append(float(ret.iloc[-60:].mean()  * 252)); weights.append(DRIFT_WEIGHT_60D)
    if n >= 252:
        values.append(float(ret.iloc[-252:].mean() * 252)); weights.append(DRIFT_WEIGHT_252D)
    values.append(DRIFT_MKT_LONG_RUN); weights.append(DRIFT_WEIGHT_MKT)
    total_w = sum(weights)
    mu = sum(v * w for v, w in zip(values, weights)) / total_w
    return max(-DRIFT_CAP, min(DRIFT_CAP, mu))


def compute_vol_model(hist_df) -> dict:
    """HV20/60/120, EWMA, blended forecast, and real-world drift."""
    ret = hist_df["Close"].pct_change().dropna()
    n   = len(ret)

    def hv_n(days):
        return float(ret.iloc[-days:].std() * math.sqrt(252)) if n >= days else None

    hv20  = hv_n(20)
    hv60  = hv_n(60)
    hv120 = hv_n(120)

    lam, var = 0.94, float(ret.iloc[0] ** 2) if n > 0 else 0.04
    for r in ret.iloc[1:]:
        var = lam * var + (1 - lam) * r ** 2
    hv_ewma = math.sqrt(var * 252)

    components = [x for x in [hv20, hv_ewma, hv60] if x is not None]
    w_raw      = [0.40, 0.35, 0.25][:len(components)]
    total_w    = sum(w_raw)
    hv_forecast = sum(c * w for c, w in zip(components, w_raw)) / total_w if total_w else 0.30

    return {
        "hv20":        hv20,
        "hv60":        hv60,
        "hv120":       hv120,
        "hv_ewma":     round(hv_ewma, 4),
        "hv_forecast": round(hv_forecast, 4),
        "mu":          _estimate_drift(ret),
    }


# ── Pricing / liquidity model ─────────────────────────────────────────────────

def _exec_premium(bid: float, ask: float) -> float:
    if bid <= 0 and ask <= 0:
        return 0.0
    if bid < MIN_BID:
        return ask * 0.50
    return bid + EXEC_LAMBDA * (ask - bid)


def _spread_pct(bid: float, ask: float) -> float:
    mid = (bid + ask) / 2
    return (ask - bid) / mid if mid > 0 else 1.0


def _safe_int(v, default=0) -> int:
    try:
        f = float(v)
        return int(f) if not math.isnan(f) else default
    except (TypeError, ValueError):
        return default


def _liquidity_score(bid: float, ask: float, volume: int, open_interest: int) -> int:
    score = 0
    sp = _spread_pct(bid, ask)
    if sp < 0.05:   score += 50
    elif sp < 0.10: score += 40
    elif sp < 0.20: score += 30
    elif sp < 0.40: score += 15
    oi = open_interest or 0
    if oi >= 1000:  score += 30
    elif oi >= 500: score += 25
    elif oi >= 100: score += 20
    elif oi >= 50:  score += 15
    elif oi >= 10:  score += 10
    vol = volume or 0
    if vol >= 500:  score += 20
    elif vol >= 100: score += 15
    elif vol >= 50:  score += 10
    elif vol >= 10:  score += 5
    return score


def _clears_profit_floor(K: float, exec_prem: float,
                          avg_cost: float, current_price: float) -> bool:
    """Premium now participates in the floor: K + P >= max(C×(1+R_MIN), S×(1+R_FORWARD))."""
    total = K + exec_prem
    return total >= max(avg_cost * (1 + R_MIN), current_price * (1 + R_FORWARD))


# ── Event model ───────────────────────────────────────────────────────────────

def _expiry_implied_move(stock, current_price: float, today) -> float:
    """ATM straddle cost as a fraction of spot for the nearest short-dated expiry.
    Reflects the market's implied move over the full expiry period, not just earnings."""
    try:
        for exp in (stock.options or []):
            ed = datetime.strptime(exp, "%Y-%m-%d").date()
            dte_this = (ed - today).days
            if not (7 <= dte_this <= 35):
                continue
            chain = stock.option_chain(exp)
            calls, puts = chain.calls, chain.puts
            atm_c = calls.iloc[(calls["strike"] - current_price).abs().argsort()[:1]]
            atm_p = puts.iloc[(puts["strike"] - current_price).abs().argsort()[:1]]
            c_mid = (float(atm_c["bid"].values[0]) + float(atm_c["ask"].values[0])) / 2
            p_mid = (float(atm_p["bid"].values[0]) + float(atm_p["ask"].values[0])) / 2
            straddle = c_mid + p_mid
            if straddle > 0.50:
                return straddle / current_price
    except Exception:
        pass
    return None


def get_risk_events(stock, current_price: float, today, exp_date,
                    strike=None,
                    option_price=None) -> list:
    """
    Returns risk events within [today, exp_date].
    Ex-div uses extrinsic/dividend economics instead of blanket avoidance.
    Earnings uses straddle-implied move vs strike distance when available.
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
            if not (today < ed_date <= exp_date):
                continue
            days_to_earn = (ed_date - today).days
            implied_move = _expiry_implied_move(stock, current_price, today)
            if implied_move and strike:
                strike_dist = (strike - current_price) / current_price
                coverage = strike_dist / implied_move if implied_move > 0 else float("inf")
                move_note = (f" | strike covers {coverage:.0%} of "
                             f"expiry-implied ±{implied_move:.0%} move")
            else:
                move_note = ""
            events.append({
                "type":     "earnings",
                "severity": "avoid",
                "date":     str(ed_date),
                "label":    f"📵 AVOID — earnings {ed_date} ({days_to_earn}d){move_note}",
            })

        # ── ex-dividend ───────────────────────────────────────────────────────
        raw_ex = cal.get("Ex-Dividend Date")
        if raw_ex and hasattr(raw_ex, "year") and today < raw_ex <= exp_date:
            days_to_ex = (raw_ex - today).days
            div_amount = None
            try:
                div_amount = float(stock.info.get("lastDividendValue") or 0)
            except Exception:
                pass

            itm = strike is not None and current_price > strike
            if itm and option_price and div_amount and div_amount > 0:
                extrinsic = call_extrinsic(current_price, strike, option_price)
                ratio = div_amount / extrinsic if extrinsic > 0.01 else float("inf")
                if ratio >= 1.0:
                    severity = "avoid"
                    label = (f"📵 AVOID — ex-div {raw_ex} ({days_to_ex}d) "
                             f"div ${div_amount:.2f} ≥ extrinsic ${extrinsic:.2f} "
                             f"— early assignment very likely")
                elif ratio >= 0.50:
                    severity = "caution"
                    label = (f"⚠️ CAUTION — ex-div {raw_ex} ({days_to_ex}d) "
                             f"div ${div_amount:.2f} vs extrinsic ${extrinsic:.2f} "
                             f"({ratio:.0%}) — moderate assignment risk")
                else:
                    severity = "caution"
                    label = (f"ℹ️  ex-div {raw_ex} ({days_to_ex}d) "
                             f"div ${div_amount:.2f} vs extrinsic ${extrinsic:.2f} — low risk")
            else:
                severity = "caution"
                label = f"⚠️ ex-div {raw_ex} ({days_to_ex}d) in window"
                if div_amount:
                    label += f" (div ${div_amount:.2f})"

            events.append({
                "type":     "ex_div",
                "severity": severity,
                "date":     str(raw_ex),
                "label":    label,
            })
    except Exception:
        pass
    return events


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_ticker(t: str) -> str:
    t = str(t).strip().upper().lstrip("$")
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            t = f"{left}-{right}"
    return t


def load_holdings() -> dict:
    """Load holdings from CSV, merging multiple rows for the same ticker into one entry.

    Multiple rows per ticker are supported for tracking add-on purchases with
    different PurchaseDates (e.g., shares added after an ex-dividend date).
    Shares and cost basis are aggregated; individual lots are preserved in
    the 'lots' list as [(shares, purchase_date)] for dividend qualification logic.
    """
    raw: dict = {}
    with open(HOLDINGS_CSV) as f:
        for row in csv.DictReader(f):
            t = normalize_ticker(row["Stock"])
            raw.setdefault(t, []).append({
                "shares":        float(row["Shares"]),
                "avg_cost":      float(row["AvgCost"]),
                "layer":         int(row["Layer"]),
                "purchase_date": (row.get("PurchaseDate") or "").strip() or None,
            })
    result = {}
    for t, lots in raw.items():
        total_shares = sum(l["shares"] for l in lots)
        avg_cost     = (sum(l["shares"] * l["avg_cost"] for l in lots) / total_shares
                        if total_shares else 0.0)
        result[t] = {
            "shares":        total_shares,
            "avg_cost":      avg_cost,
            "layer":         lots[0]["layer"],
            "purchase_date": lots[0]["purchase_date"],   # kept for back-compat
            "lots":          [(l["shares"], l["purchase_date"]) for l in lots],
        }
    return result


def _market_price(stock) -> float:
    try:
        p = float(stock.fast_info.last_price or 0)
        if p > 0:
            return p
    except Exception:
        pass
    return None


# ── Multi-factor scoring ──────────────────────────────────────────────────────

def _compute_opp_score(df) -> "pd.Series":
    """Cross-ticker comparable opportunity score using fixed absolute reference scales.

    Unlike Score (within-ticker percentile ranks), OppScore means the same thing
    across different tickers — MSFT 72 vs RIVN 72 are comparable opportunities.

    All inputs mapped to [0,1] before weighting:
      A  CCα% = cc_alpha / S            0–2.5% per contract → [0,1]
      Y  Annualized yield               0–20%/yr            → [0,1]
      V  IV richness                    −50% to +100%       → [0,1]
      L  Liquidity score                0–100               → [0,1]
      R  1 − regret_prob / 0.40         0–40% regret        → [0,1]

    Weights: A 30%, Y 20%, V 20%, L 15%, R 15%
    """
    A = (df["cc_alpha_pct"] / 0.025).clip(0, 1)
    Y = (df["annualized_ret"] / 20.0).clip(0, 1)
    V = ((df["iv_richness"].clip(-0.5, 1.0) + 0.5) / 1.5)
    L = df["liquidity_score"] / 100.0
    R = (1.0 - df["regret_prob"] / 0.40).clip(0, 1)
    return (100 * (0.30*A + 0.20*Y + 0.20*V + 0.15*L + 0.15*R)).round(1)


def _compute_scores(df):
    """Add 'score' (within-ticker) and 'opp_score' (cross-ticker) columns."""
    n = len(df)
    if n == 0:
        return df

    def pct_rank(series):
        return series.rank(pct=True, method="average")

    A = pct_rank(df["cc_alpha"])                          # 25% — core metric
    Y = pct_rank(df["premium_pct"])                       # 15% — yield
    V = pct_rank(df["iv_richness"].clip(lower=-1))        # 15% — IV richness
    L = df["liquidity_score"] / 100.0                     # 15% — liquidity (absolute)
    U = pct_rank(df["z_strike"])                          # 15% — upside room
    R = 1 - pct_rank(df["regret_prob"])                   # 15% — low regret risk

    df = df.copy()
    df["score"]     = 100 * (0.25*A + 0.15*Y + 0.15*V + 0.15*L + 0.15*U + 0.15*R)
    df["opp_score"] = _compute_opp_score(df)
    return df


# ── Core analyzer ─────────────────────────────────────────────────────────────

def analyze(ticker: str, avg_cost: float, shares: float):
    stock = yf.Ticker(ticker)

    current_price = _market_price(stock)
    if current_price is None:
        price_hist = _yf_retry(lambda: stock.history(period="2d"))
        if price_hist.empty:
            print(f"  [{ticker}] No price data — skipping.")
            return None
        current_price = float(price_hist["Close"].dropna().iloc[-1])

    hist = _yf_retry(lambda: stock.history(period="2y"))
    if hist.empty:
        week52_high    = current_price
        week52_high_dt = "n/a"
        vol_model      = {"hv20": None, "hv60": None, "hv120": None,
                          "hv_ewma": 0.40, "hv_forecast": 0.40, "mu": 0.10}
        hv_rank        = None
    else:
        hist52 = hist.iloc[-252:] if len(hist) >= 252 else hist
        week52_high    = float(hist52["High"].max())
        week52_high_dt = hist52["High"].idxmax().strftime("%Y-%m-%d")
        vol_model      = compute_vol_model(hist)
        _ret = hist["Close"].pct_change().dropna()
        hv_rank = None
        if len(_ret) >= 42:
            rolling_hv     = _ret.rolling(21).std().dropna() * math.sqrt(252)
            current_21d_hv = float(rolling_hv.iloc[-1])
            hv_rank        = round(float((rolling_hv < current_21d_hv).mean() * 100), 1)

    hist_vol = vol_model["hv_forecast"]
    mu       = vol_model["mu"]
    try:
        q = float(stock.info.get("dividendYield") or 0.0)
    except Exception:
        q = 0.0
    gain_pct = (current_price - avg_cost) / avg_cost * 100
    already_at_target = current_price >= avg_cost * (1 + R_MIN)
    strike_floor      = avg_cost * (1 + R_MIN)   # kept for UI context

    today = datetime.now().date()

    try:
        all_options = _yf_retry(lambda: stock.options)
    except Exception:
        print(f"  [{ticker}] Could not fetch option expirations — skipping.")
        return None

    # ATM IV from nearest expiry
    atm_iv = None
    try:
        for _exp in all_options[:3]:
            _chain = stock.option_chain(_exp).calls
            _atm   = _chain.iloc[(_chain["strike"] - current_price).abs().argsort()[:1]]
            _iv    = float(_atm["impliedVolatility"].values[0])
            if _iv > 0.01:
                atm_iv = round(_iv * 100, 1)
                break
    except Exception:
        pass

    def _get_expirations(max_dte):
        min_exp = today + timedelta(days=MIN_DTE)
        max_exp = today + timedelta(days=max_dte)
        return [e for e in all_options
                if min_exp <= datetime.strptime(e, "%Y-%m-%d").date() <= max_exp]

    def _build_rows(expirations, mid_mode):
        import pandas as pd
        rows = []
        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            try:
                calls = _yf_retry(lambda: stock.option_chain(exp).calls)
            except Exception:
                continue

            T = dte / 365

            if mid_mode == "live":
                calls = calls[calls["bid"] >= MIN_BID].copy()
                if calls.empty:
                    continue
                calls["mid"] = (calls["bid"] + calls["ask"]) / 2

            elif mid_mode == "ask_proxy":
                calls = calls[calls["ask"] >= MIN_BID * 2].copy()
                if calls.empty:
                    continue
                calls["mid"] = calls.apply(
                    lambda r: (r["bid"] + r["ask"]) / 2 if r["bid"] >= MIN_BID
                              else r["ask"] * 0.50, axis=1)

            elif mid_mode == "theoretical":
                def _eff_iv_bs(chain_iv):
                    iv = float(chain_iv) if chain_iv and float(chain_iv) > 0.01 else 0.0
                    return max(iv, hist_vol * 0.80)
                calls["bs_mid"] = calls.apply(
                    lambda r: bs_call_price(current_price, r["strike"], T,
                                            _eff_iv_bs(r["impliedVolatility"])), axis=1)
                calls = calls[calls["bs_mid"] >= MIN_BID].copy()
                if calls.empty:
                    continue
                calls["mid"] = calls["bs_mid"]

            if calls.empty:
                continue

            calls = calls[calls["strike"] >  current_price].copy()  # OTM only
            calls = calls[calls["strike"] <= current_price * MAX_STRIKE_MULTIPLIER].copy()
            # Fetch calendar/earnings data once per expiry (not per contract).
            risk_for_exp = get_risk_events(stock, current_price, today, exp_date)
            metrics = []
            for _, row in calls.iterrows():
                K   = float(row["strike"])
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                mid = float(row["mid"])
                iv  = float(row.get("impliedVolatility", 0) or 0)
                oi  = _safe_int(row.get("openInterest", 0))
                vol = _safe_int(row.get("volume", 0))

                eff_iv    = iv if iv > 0.01 else hist_vol
                exec_prem = _exec_premium(bid, ask) if mid_mode != "theoretical" else mid

                passes    = _clears_profit_floor(K, exec_prem, avg_cost, current_price)

                delta_val = call_delta(current_price, K, T, eff_iv)
                gamma_val = call_gamma(current_price, K, T, eff_iv)
                itm_rn    = itm_prob_rn(current_price, K, T, eff_iv)
                itm_real  = itm_prob_real(current_price, K, T, eff_iv, mu, q)
                reg_p     = regret_prob(current_price, K, exec_prem, T, eff_iv, mu, q)
                up_lost   = expected_upside_lost(current_price, K, T, eff_iv, mu, q)
                cc_alpha  = exec_prem - up_lost
                exp_move  = current_price * eff_iv * math.sqrt(T)
                z_k       = (math.log(K / current_price) / (eff_iv * math.sqrt(T))
                             if eff_iv > 0 and T > 0 else 0.0)
                iv_rich   = (eff_iv / hist_vol - 1) if hist_vol > 0 else 0.0
                liq       = _liquidity_score(bid, ask, vol, oi)
                risk      = risk_for_exp

                metrics.append({
                    "expiration":        exp,
                    "strike":            K,
                    "dte":               dte,
                    "bid":               bid,
                    "ask":               ask,
                    "mid":               mid,
                    "exec_premium":      round(exec_prem, 2),
                    "premium_pct":       exec_prem / current_price * 100,
                    "annualized_ret":    exec_prem / current_price * 100 * (365 / dte),
                    "profit_if_called":  (K + exec_prem - avg_cost) / avg_cost * 100,
                    "delta":             round(delta_val, 3),
                    "gamma":             round(gamma_val, 4),
                    "itm_prob_rn":       round(itm_rn, 3),
                    "itm_prob_real":     round(itm_real, 3),
                    "regret_prob":       round(reg_p, 3),
                    "regret_threshold":  round(K + exec_prem, 2),
                    "cc_alpha":          round(cc_alpha, 3),
                    "cc_alpha_pct":      round(cc_alpha / current_price, 6),
                    "upside_lost":       round(up_lost, 3),
                    "expected_move":     round(exp_move, 2),
                    "z_strike":          round(z_k, 2),
                    "iv_richness":       round(iv_rich, 3),
                    "liquidity_score":   liq,
                    "openInterest":      oi,
                    "volume":            vol,
                    "impliedVolatility": eff_iv,
                    "risk_events":       risk,
                    "has_avoid":         any(e["severity"] == "avoid"   for e in risk),
                    "has_caution":       any(e["severity"] == "caution" for e in risk),
                    "passes_floor":      passes,
                    "spread_width":      round(ask - bid, 2),
                })

            if metrics:
                rows.append(pd.DataFrame(metrics))
        return rows

    # ── Tiered data collection ─────────────────────────────────────────────────
    exps      = _get_expirations(MAX_DTE)
    note      = None
    data_mode = "live"
    dte_extended = False

    rows = _build_rows(exps, "live") if exps else []

    if not rows and exps:
        rows = _build_rows(exps, "ask_proxy")
        if rows:
            data_mode = "ask_proxy"
            note = ("⚠️  No live bids — market may be closed or options illiquid. "
                    "Exec premiums estimated at 50% of ask. Verify before trading.")

    if not rows and exps:
        rows = _build_rows(exps, "theoretical")
        if rows:
            data_mode = "theoretical"
            note = ("⚠️  No market quotes (bid=ask=0). Premiums are Black-Scholes "
                    "estimates from IV — reference only. Verify when market opens.")

    if not rows:
        exps_ext = _get_expirations(MAX_DTE_EXTENDED)
        new_exps = [e for e in exps_ext if e not in exps]
        if new_exps:
            for mode in ("live", "ask_proxy", "theoretical"):
                rows = _build_rows(new_exps, mode)
                if rows:
                    data_mode    = mode
                    dte_extended = True
                    suffix = {"live": "", "ask_proxy": " Premiums at 50% of ask.",
                              "theoretical": " Premiums are BS estimates."}[mode]
                    note = (f"No contracts in standard 21–60 DTE window — "
                            f"showing 61–{MAX_DTE_EXTENDED} DTE.{suffix}")
                    break

    if not exps and not _get_expirations(MAX_DTE_EXTENDED):
        print(f"  [{ticker}] No expirations in {MIN_DTE}–{MAX_DTE_EXTENDED} DTE window.")
        return None

    if not rows:
        print(f"  [{ticker}] No option contracts found "
              f"(tried live, ask-proxy, and theoretical modes).")
        return None

    import pandas as pd
    all_calls = pd.concat(rows, ignore_index=True)
    all_calls = _compute_scores(all_calls)

    # Floor-passing contracts ranked by within-ticker score (shown in "All" view)
    recs_df  = all_calls[all_calls["passes_floor"]].sort_values(
                    "score", ascending=False).head(20)
    # Floor-failing contracts (below-floor accordion in "All" view)
    floor_fail_df = all_calls[~all_calls["passes_floor"]].sort_values(
                    "score", ascending=False).head(10)
    # Tight-spread contracts ranked by cross-ticker OppScore (shown in "Tight" view)
    # Includes floor-failing contracts so the user sees what's available regardless
    tight_df = all_calls[all_calls["spread_width"] <= 0.25].sort_values(
                    "opp_score", ascending=False)

    if recs_df.empty:
        print(f"  [{ticker}] No contracts meet profit floor — "
              f"{len(tight_df)} tight-spread contract(s) available in filtered view.")

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
        "recs":              recs_df,
        "floor_fail_recs":   floor_fail_df,
        "tight_recs":        tight_df,
        "data_mode":         data_mode,
        "dte_extended":      dte_extended,
        "note":              note,
        "hv_rank":           hv_rank,
        "atm_iv":            atm_iv,
        "vol_model":         vol_model,
        "mu":                mu,
    }


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(r: dict) -> None:
    t     = r["ticker"]
    price = r["current_price"]
    cost  = r["avg_cost"]
    gain  = r["gain_pct"]
    floor = r["strike_floor"]
    w52   = r["week52_high"]
    w52d  = r["week52_high_dt"]
    mu    = r.get("mu", RISK_FREE_RATE)
    vm    = r.get("vol_model", {})

    print()
    print("=" * 76)
    print(f"  {t}  —  current ${price:.2f}  |  avg cost ${cost:.2f}  |  "
          f"gain {gain:+.1f}%  |  52w high ${w52:.2f} ({w52d})")

    hv_rank = r.get("hv_rank")
    atm_iv  = r.get("atm_iv")
    hv20    = vm.get("hv20")
    hv_fc   = vm.get("hv_forecast")
    if atm_iv and hv_fc:
        iv_rich_pct = (atm_iv / 100 / hv_fc - 1) * 100
        rich_label  = ("rich" if iv_rich_pct > 10 else
                       "fair" if iv_rich_pct > -5 else "cheap")
        print(f"  IV {atm_iv:.1f}%  |  HV20 {hv20*100:.1f}%  |  HV_fc {hv_fc*100:.1f}%  "
              f"|  IV richness {iv_rich_pct:+.1f}% ({rich_label})"
              + (f"  |  HV rank {hv_rank:.0f}th pct" if hv_rank is not None else ""))
    elif hv_rank is not None:
        print(f"  HV rank: {hv_rank:.0f}th percentile"
              + (f"  |  ATM IV: {atm_iv:.1f}%" if atm_iv else ""))

    print(f"  Drift (blended real-world μ): {mu*100:+.1f}%/yr  "
          f"|  Floor: K + exec_prem ≥ max(cost×{1+R_MIN:.2f}, price×{1+R_FORWARD:.2f})")
    print(f"  Best call competes against: DO NOTHING (cc_alpha=0)\n")

    print(f"  {'Expiry':<12} {'Strike':>7} {'DTE':>4} {'Bid':>5} {'Ask':>5} {'Exec':>5} "
          f"{'Prem%':>6} {'Ann%':>6} {'P/L':>6} {'Delta':>6} {'eITM%':>6} "
          f"{'Rgrt%':>6} {'CCα$':>6} {'Liq':>4} {'Scr':>4}")
    print("  " + "-" * 110)

    for _, row in r["recs"].iterrows():
        avoid_tag   = " 📵" if row.get("has_avoid")   else ""
        caution_tag = " ⚠️" if row.get("has_caution") else ""
        cc_alpha    = float(row.get("cc_alpha", 0))
        alpha_str   = f"{cc_alpha:+.2f}"
        print(
            f"  {row['expiration']:<12}"
            f"${row['strike']:>6.2f} "
            f"{int(row['dte']):>4}d"
            f" ${float(row['bid']):>4.2f}"
            f" ${float(row['ask']):>4.2f}"
            f" ${float(row.get('exec_premium', row['mid'])):>4.2f}"
            f" {float(row['premium_pct']):>5.1f}%"
            f" {float(row['annualized_ret']):>5.1f}%"
            f" {float(row['profit_if_called']):>+5.1f}%"
            f"  {float(row['delta'])*100:>4.1f}%"
            f"  {float(row.get('itm_prob_real', row['delta']))*100:>4.1f}%"
            f"  {float(row.get('regret_prob', 0))*100:>5.1f}%"
            f"  {alpha_str:>6}"
            f"  {int(row.get('liquidity_score', 0)):>3}"
            f" {float(row.get('score', 0)):>4.0f}"
            f"{avoid_tag}{caution_tag}"
        )
        for event in (row.get("risk_events") or []):
            print(f"    {event['label']}")

    # NO CALL comparison
    best_alpha = float(r["recs"].iloc[0].get("cc_alpha", 0)) if len(r["recs"]) else 0
    best_exp   = r["recs"].iloc[0].get("expected_move", None) if len(r["recs"]) else None
    if best_alpha < 0:
        print(f"\n  *** Best contract has cc_alpha={best_alpha:+.2f}  "
              f"→  DO NOTHING may be the better choice ***")
    print()


# ── Open position evaluator ───────────────────────────────────────────────────

def _eval_open_economics(delta, dte, pct_captured, has_avoid, current_price,
                          strike, original_premium, live_mark, risk_events,
                          gamma=None):
    """
    Economic comparison: hold vs close vs roll.
    Returns (recommendation, reason).
    """
    # Priority 1: risk event → close to remove it
    if has_avoid:
        label = next((e["label"] for e in risk_events if e["severity"] == "avoid"), "risk event")
        return "buy_back", f"Close to remove event risk: {label.replace('📵 AVOID — ', '')}"

    # Remaining annualised yield — use extrinsic value only.
    # For OTM calls extrinsic ≈ live_mark; for ITM calls the intrinsic portion
    # has no time value left to decay, so counting it inflates the yield metric.
    remaining_ann = None
    if live_mark is not None and live_mark > 0 and dte and dte > 0:
        intrinsic_val  = max(current_price - strike, 0.0)
        extrinsic_val  = max(live_mark - intrinsic_val, 0.0)
        remaining_ann  = (extrinsic_val / current_price) * (365 / dte) * 100

    # Priority 2: most of premium captured AND remaining yield is low
    if pct_captured is not None and pct_captured >= 80:
        if remaining_ann is None or remaining_ann < 5:
            remaining_str = f"{remaining_ann:.1f}%" if remaining_ann is not None else "N/A"
            return "buy_back", (f"{pct_captured:.0f}% captured, remaining annualised yield "
                                f"{remaining_str} — cost to close is minimal")

    # Priority 3: gamma-aware assignment risk near expiry
    if dte is not None and dte <= 21:
        gamma_delta_1pct = (gamma or 0) * current_price * 0.01
        if delta is not None and delta >= 0.30:
            detail = (f", Γ×1%move≈{gamma_delta_1pct:.3f} delta acceleration"
                      if gamma else "")
            return "roll", (f"{dte}d left, delta {delta*100:.0f}%{detail} "
                            f"— assignment risk accelerating, roll out")

    # Priority 4: deep ITM
    if current_price >= strike:
        return "roll", f"Stock ${current_price:.2f} above strike ${strike:.2f} — roll up and out"
    if current_price >= strike * 0.97:
        return "roll", f"Stock within 3% of strike — roll to protect position"

    # Priority 5: delta too high
    if delta is not None and delta >= 0.50:
        return "roll", f"Delta {delta*100:.0f}% — high expiry-ITM probability, roll up or out"

    # Priority 6: short DTE, decent capture
    if dte is not None and dte <= 5 and pct_captured is not None and pct_captured >= 60:
        return "buy_back", f"{dte}d left, {pct_captured:.0f}% captured — close and redeploy"

    parts = []
    if delta is not None:
        parts.append(f"delta {delta*100:.0f}%")
    if dte is not None:
        parts.append(f"{dte}d remaining")
    if pct_captured is not None:
        parts.append(f"{pct_captured:.0f}% captured")
    if remaining_ann is not None:
        parts.append(f"remaining yield {remaining_ann:.1f}%/yr")
    return "hold", ("No action needed — " + ", ".join(parts)) if parts else "Hold position"


def _suggest_next_call(stock, min_strike: float, current_price: float) -> dict:
    today = datetime.now().date()
    best  = None
    try:
        expirations = _yf_retry(lambda: stock.options)
        for exp in expirations:
            exp_date     = datetime.strptime(exp, "%Y-%m-%d").date()
            dte_candidate = (exp_date - today).days
            if dte_candidate < 14 or dte_candidate > 75:
                continue
            try:
                calls = _yf_retry(lambda: stock.option_chain(exp).calls)
                calls = calls[calls["strike"] >= min_strike]
                calls = calls[(calls["bid"] > 0) & (calls["ask"] > 0)]
                if calls.empty:
                    continue
                for _, row in calls.iterrows():
                    s   = float(row["strike"])
                    bid = float(row["bid"])
                    ask = float(row["ask"])
                    iv  = float(row.get("impliedVolatility", 0) or 0)
                    d   = None
                    if iv > 0.01 and dte_candidate > 0:
                        d = call_delta(current_price, s, dte_candidate / 365, iv)
                    if d is None or not (0.15 <= d <= 0.40):
                        continue
                    exec_prem = _exec_premium(bid, ask)
                    if exec_prem < 0.20:
                        continue
                    score = exec_prem / s * 100
                    if best is None or score > best["_score"]:
                        best = {
                            "expiry":      exp,
                            "strike":      round(s, 2),
                            "dte":         dte_candidate,
                            "mid":         round((bid + ask) / 2, 2),
                            "exec":        round(exec_prem, 2),
                            "delta":       round(d, 3),
                            "premium_pct": round(score, 2),
                            "_score":      score,
                        }
            except Exception:
                continue
    except Exception:
        pass
    if best:
        best.pop("_score")
    return best


def evaluate_open_position(ticker: str, strike: float, expiry: str,
                            original_premium: float, current_mark) -> dict:
    """
    Evaluate an open covered call using economic comparisons rather than
    rule-based priority ladders.
    Returns metrics + recommendation: 'hold' | 'roll' | 'buy_back'.
    """
    stock = yf.Ticker(ticker)

    live_price = _market_price(stock)
    if live_price is None:
        price_hist = _yf_retry(lambda: stock.history(period="2d"))
        if price_hist.empty:
            raise ValueError(f"No price data for {ticker}")
        live_price = float(price_hist["Close"].dropna().iloc[-1])
    current_price = live_price

    today    = datetime.now().date()
    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    dte      = (exp_date - today).days

    delta     = None
    gamma     = None
    live_mark = current_mark
    try:
        chain = _yf_retry(lambda: stock.option_chain(expiry).calls)
        exact = chain[abs(chain["strike"] - strike) < 0.01]
        row   = exact if not exact.empty else chain.iloc[(chain["strike"] - strike).abs().argsort()[:1]]
        if not row.empty:
            bid = float(row["bid"].values[0])
            ask = float(row["ask"].values[0])
            if bid > 0 or ask > 0:
                live_mark = (bid + ask) / 2
            iv = float(row["impliedVolatility"].values[0])
            if iv > 0.01 and dte > 0:
                T     = dte / 365
                delta = call_delta(current_price, strike, T, iv)
                gamma = call_gamma(current_price, strike, T, iv)
    except Exception:
        pass

    risk_events = get_risk_events(stock, current_price, today, exp_date, strike, live_mark)
    has_avoid   = any(e["severity"] == "avoid" for e in risk_events)

    pct_captured = None
    if live_mark is not None and original_premium > 0:
        pct_captured = max(0.0, (original_premium - live_mark) / original_premium * 100)

    # Extrinsic value remaining — only this portion has time-decay value.
    # Intrinsic (S - K for ITM calls) contributes nothing to decay-based yield.
    remaining_intrinsic     = max(current_price - strike, 0.0)
    remaining_extrinsic     = max(live_mark - remaining_intrinsic, 0.0) if live_mark is not None else None
    remaining_extrinsic_yield     = (remaining_extrinsic / current_price * 100
                                     if remaining_extrinsic is not None and current_price > 0
                                     else None)
    remaining_extrinsic_ann_yield = (remaining_extrinsic_yield * 365 / dte
                                     if remaining_extrinsic_yield is not None and dte > 0
                                     else None)

    rec, reason = _eval_open_economics(
        delta=delta, dte=dte, pct_captured=pct_captured,
        has_avoid=has_avoid, current_price=current_price,
        strike=strike, original_premium=original_premium,
        live_mark=live_mark, risk_events=risk_events, gamma=gamma,
    )

    next_contract = None
    if rec == "roll":
        min_s = max(strike, current_price * 1.01)
        next_contract = _suggest_next_call(stock, min_s, current_price)
    elif rec == "buy_back":
        next_contract = _suggest_next_call(stock, current_price * 1.03, current_price)

    return {
        "current_price":              round(current_price, 2),
        "current_mark":               round(live_mark, 2) if live_mark is not None else None,
        "delta":                      round(delta, 3) if delta is not None else None,
        "gamma":                      round(gamma, 4) if gamma is not None else None,
        "dte":                        dte,
        "pct_captured":               round(pct_captured, 1) if pct_captured is not None else None,
        "remaining_extrinsic":        round(remaining_extrinsic, 2) if remaining_extrinsic is not None else None,
        "remaining_extrinsic_yield":  round(remaining_extrinsic_yield, 2) if remaining_extrinsic_yield is not None else None,
        "remaining_extrinsic_ann_yield": round(remaining_extrinsic_ann_yield, 1) if remaining_extrinsic_ann_yield is not None else None,
        "risk_events":                risk_events,
        "has_avoid":                  has_avoid,
        "recommendation":             rec,
        "reason":                     reason,
        "next_contract":              next_contract,
    }


# ── Ollama AI context builder ─────────────────────────────────────────────────

def ai_context(ticker, result, shares, layer):
    contracts_available = int(shares // 100)
    vm    = result.get("vol_model", {})
    mu    = result.get("mu", RISK_FREE_RATE)
    hv_fc = vm.get("hv_forecast", 0)
    hv20  = vm.get("hv20")
    hv60  = vm.get("hv60")
    hv_rank = result.get("hv_rank")
    atm_iv  = result.get("atm_iv")
    price   = result["current_price"]
    cost    = result["avg_cost"]

    # Pre-translate volatility context into plain English
    if atm_iv is not None and hv_fc > 0:
        iv_rich_pct = (atm_iv / 100 / hv_fc - 1) * 100
        if iv_rich_pct > 10:
            vol_env = f"options are pricing in {atm_iv:.1f}% volatility but the stock has only been moving at {hv_fc*100:.1f}% — options are expensive right now, which favors selling"
        elif iv_rich_pct < -10:
            vol_env = f"options are pricing in {atm_iv:.1f}% volatility but the stock has been moving at {hv_fc*100:.1f}% — options are cheap, sellers are getting squeezed"
        else:
            vol_env = f"options are priced at {atm_iv:.1f}% implied volatility, roughly in line with the stock's recent {hv_fc*100:.1f}% realized movement — fair premium environment"
    elif hv_fc > 0:
        vol_env = f"stock has been moving at about {hv_fc*100:.1f}% annualized volatility"
        if hv20 and hv60:
            vol_env += f" (20-day: {hv20*100:.1f}%, 60-day: {hv60*100:.1f}%)"
    else:
        vol_env = "volatility data unavailable"

    if hv_rank is not None:
        if hv_rank >= 70:
            vol_env += f"; volatility is at the {hv_rank:.0f}th percentile of its 1-year range — an elevated reading, historically a good time to sell premium"
        elif hv_rank <= 30:
            vol_env += f"; volatility is at the {hv_rank:.0f}th percentile of its 1-year range — compressed, premiums are thin"
        else:
            vol_env += f"; volatility is at the {hv_rank:.0f}th percentile of its 1-year range — moderate"

    layer_desc = {1: "core long-term hold", 2: "growth/compounder", 3: "speculative/trading"}.get(layer, f"layer {layer}")

    lines = [
        "You are a knowledgeable friend helping an investor decide whether to sell a covered call. "
        "Write in plain, conversational English — no Greek letters, no math symbols, no jargon. "
        "Translate every concept into real-money terms. "
        "'There is a 20% chance the stock closes above the strike' not 'eITM 0.20'. "
        "Every sentence must include specific dollar amounts or percentages from the data below. "
        "CRITICAL — option contract math: 1 contract = 100 shares. "
        "The 'income per contract' figure below is already the TOTAL cash collected (exec_price × 100). "
        "Never multiply it by 100 again. Never say 'or $X for 100 shares' after stating the contract income — "
        "the contract income IS the income for 100 shares. "
        "Respond with ONLY a JSON object — no markdown fences, no text outside the braces.\n",

        f"STOCK: {ticker} at ${price:.2f} | you own {shares:.0f} shares (avg cost ${cost:.2f}, "
        f"{result['gain_pct']:+.1f}% unrealized gain) | can sell {contracts_available} contract(s)",
        f"This is a {layer_desc}. 52-week high: ${result['week52_high']:.2f} ({result.get('week52_high_dt','')}).",
        f"Minimum acceptable strike: ${result['strike_floor']:.2f} (combined strike + premium must cover your cost with a small buffer).",
        f"",
        f"MARKET CONDITIONS: {vol_env}.",
        f"Stock's estimated trend: {mu*100:+.1f}%/yr (blended from recent price history).",
        f"",
    ]

    if result.get("note"):
        lines.append(f"NOTE: {result['note']}")
        lines.append("")

    lines.append("TOP OPTION CONTRACTS to consider (pre-filtered and ranked by our scoring system):")
    for i, (_, row) in enumerate(result["recs"].head(3).iterrows()):
        exec_p      = float(row.get("exec_premium", row["mid"]))
        spread      = float(row["ask"]) - float(row["bid"])
        itm_pct     = float(row.get("itm_prob_real", 0)) * 100
        regret_pct  = float(row.get("regret_prob", 0)) * 100
        regret_k    = float(row["strike"]) + exec_p
        alpha       = float(row.get("cc_alpha", 0))
        exp_move    = float(row.get("expected_move", 0))
        liq         = int(row.get("liquidity_score", 0))
        ann         = float(row["annualized_ret"])
        income_per_contract = exec_p * 100

        flags = []
        for e in (row.get("risk_events") or []):
            if e["type"] == "earnings":
                flags.append("earnings report falls within this window")
            elif e["type"] == "ex_div":
                flags.append(f"ex-dividend date in window ({e['severity']} risk of early assignment)")
        if spread > exec_p * 0.30:
            flags.append(f"wide bid-ask spread (${spread:.2f}) — use a limit order")
        if liq < 40:
            flags.append(f"thin liquidity (score {liq}/100) — be patient filling this")

        alpha_desc = (f"selling nets you ${alpha:+.2f}/share more than the expected cost of capping your upside"
                      if alpha > 0
                      else f"${abs(alpha):.2f}/share of upside you'd be giving up exceeds the premium")

        lines.append(
            f"\n  Contract #{i+1}: Sell the {row['expiration']} ${float(row['strike']):.2f} call — {int(row['dte'])} days out"
            f"\n    Collect: ${income_per_contract:.0f} total per contract (${exec_p:.2f}/share × 100 shares) — {ann:.1f}%/yr annualized"
            f"\n    Chance stock closes above strike and you get called away: ~{itm_pct:.0f}%"
            f"\n    Chance this trade leaves you worse off than just holding: ~{regret_pct:.0f}% (stock would need to close above ${regret_k:.2f})"
            f"\n    Net edge vs just holding: {alpha_desc}"
            f"\n    Expected stock move over this window: ~${exp_move:.2f}"
            f"\n    Bid ${float(row['bid']):.2f} / Ask ${float(row['ask']):.2f} — expected fill ~${exec_p:.2f} | Liquidity: {liq}/100"
            + (f"\n    FLAGS: {'; '.join(flags)}" if flags else "")
        )

    lines.append(f"""

Respond with ONLY this JSON (no markdown, no text outside the braces).
Write every field in plain English as if explaining to a smart friend — no Greek symbols, no math notation:
{{
  "recommendation": {{
    "rank": 1,
    "strike": 0.00,
    "expiration": "YYYY-MM-DD",
    "summary": "One or two sentences: which contract you'd pick and the single most important reason why, in plain dollars and cents."
  }},
  "the_trade": "Explain exactly what the investor is agreeing to: what they collect (state the total contract income once — do NOT re-multiply by 100), what they're giving up, and what has to happen for this to work out well. 2-3 sentences.",
  "market_conditions": "Is this a good or bad time to be selling options on this stock right now? Explain in terms of what the market is paying and whether that's generous or stingy. 2 sentences.",
  "what_could_go_wrong": "What is the scenario where this trade leaves the investor worse off than just holding? Give the exact stock price that flips the outcome, and your honest read on how likely that is. 2-3 sentences.",
  "risks": [
    "One specific, plain-English risk with a dollar amount or percentage",
    "A second specific risk with a dollar amount or percentage"
  ],
  "what_to_watch": "What should the investor monitor during the trade? When should they consider buying back the option early or rolling to a new strike? Give a specific price level or time trigger. 2-3 sentences."
}}""")
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    holdings = load_holdings()
    tickers  = [t.upper() for t in sys.argv[1:]] or list(holdings.keys())

    print(f"\nCovered Call Recommendations  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Ranked by: multi-factor score (25% cc_alpha, 15% each yield/IV/liquidity/upside/regret)")
    print(f"Floor: K + exec_prem >= cost×{1+R_MIN:.2f}  |  exec = bid + {EXEC_LAMBDA:.0%}×spread")

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
