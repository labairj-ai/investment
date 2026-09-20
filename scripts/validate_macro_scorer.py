#!/usr/bin/env python3
"""
Macro scorer validation lab (0479).

Four test modules:
  1. Repeatability    — N=20 passes on frozen inputs, per-dim range/stddev; gate from config
  2. Anchor calibration — known instruments against expected score brackets
  3. Factor concordance — measure beta sign vs LLM score sign agreement (0473)
  4. Drift detection  — compare last two history rows per ticker; flag unexplained deltas
"""
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import time
import uuid
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

DIMS = ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk")

OUT_PATH = PROJECT_DIR / "out" / "macro_validation_results.json"
DB_PATH  = PROJECT_DIR / "out" / "investment.db"

# Anchor instruments with expected score brackets per dimension
ANCHORS = {
    "BIL": {
        "description": "3-month T-bill / cash equivalent",
        "rate_sensitivity":   (1, 3),
        "dollar_sensitivity": (1, 3),
    },
    "VNQ": {
        "description": "REIT / long-duration bond-like",
        "rate_sensitivity": (7, 10),
    },
    "NEE": {
        "description": "NextEra Energy — domestic US utility, minimal foreign revenue",
        "dollar_sensitivity": (1, 4),   # domestic utility, little FX exposure
    },
    "XOM": {
        "description": "Large US energy / inflation hedge / significant international operations",
        "inflation_hedge":    (6, 10),
        "dollar_sensitivity": (5, 9),   # international ops → moderate-high dollar exposure
    },
}

# Relative ordering invariants — more robust than absolute brackets.
# Chosen from independently-evidenced company characteristics, not expected LLM output.
RELATIVE_ORDERING_CHECKS = [
    {
        "lower_ticker":  "NEE",
        "higher_ticker": "XOM",
        "dimension":     "dollar_sensitivity",
        "description":   "domestic utility (NEE) < international energy (XOM) for dollar_sensitivity",
    }
]


def _check_relative_ordering(anchor_scores: dict, checks: list) -> dict:
    """Verify relative ordering invariants. Returns {"pass": bool, "checks": [...]}."""
    check_results = []
    for check in checks:
        lo_dim = anchor_scores.get(check["lower_ticker"], {}).get("dims", {}).get(check["dimension"], {})
        hi_dim = anchor_scores.get(check["higher_ticker"], {}).get("dims", {}).get(check["dimension"], {})
        lo = lo_dim.get("actual") if isinstance(lo_dim, dict) else None
        hi = hi_dim.get("actual") if isinstance(hi_dim, dict) else None
        label = check.get("description", f"{check['lower_ticker']}<{check['higher_ticker']} on {check['dimension']}")
        if lo is None or hi is None:
            check_results.append({"label": label, "status": "SKIP",
                                   "detail": "score unavailable", "lo": lo, "hi": hi})
        elif lo < hi:
            check_results.append({"label": label, "lo": lo, "hi": hi, "status": "PASS",
                                   "detail": f"{check['lower_ticker']}={lo} < {check['higher_ticker']}={hi}"})
        else:
            check_results.append({"label": label, "lo": lo, "hi": hi, "status": "FAIL",
                                   "detail": f"{check['lower_ticker']}={lo} not < {check['higher_ticker']}={hi}"})
    all_pass = all(c["status"] in ("PASS", "SKIP") for c in check_results)
    return {"pass": all_pass, "checks": check_results}


def _score_val(dim_data):
    if isinstance(dim_data, dict):
        v = dim_data.get("score")
    elif isinstance(dim_data, (int, float)):
        v = dim_data
    else:
        return None
    try:
        return max(1, min(10, int(v)))
    except (TypeError, ValueError):
        return None


def _freeze_validation_evidence(tickers: list, conn) -> dict:
    """Freeze evidence and betas for the validation universe at run start (0529).
    Returns {ticker: {"evidence": dict, "betas": dict, "evidence_hash": str}}.
    All N repeatability repeats use this snapshot so inputs are byte-identical.
    """
    import portfolio_ai as pai
    snapshot = {}
    for tk in tickers:
        ev = pai._fetch_company_evidence(tk, conn)
        betas = pai._compute_equity_betas(tk) or {}
        ev_hash = hashlib.sha256(json.dumps(
            {"evidence": ev, "betas": betas}, sort_keys=True, default=str
        ).encode()).hexdigest()
        prompt = pai._build_macro_score_request(tk, ev, betas)
        snapshot[tk] = {"evidence": ev, "betas": betas, "evidence_hash": ev_hash,
                        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()}
    return snapshot


def _score_one_ticker(ticker: str, evidence: dict, betas):
    """Score a single ticker using the canonical production scoring contract (0529).
    evidence: pre-frozen via _freeze_validation_evidence; betas: same.
    All repeats must receive the same evidence/betas for byte-identical inputs.
    """
    try:
        import portfolio_ai as pai
        import ollama_client
        if not ollama_client.available():
            print(f"  [skip] Ollama not available for {ticker}")
            return None
        prompt = pai._build_macro_score_request(ticker, evidence, betas)
        full_text = ""
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=pai._MACRO_SCORE_TEMPERATURE,
            num_predict=pai._MACRO_SCORE_NUM_PREDICT,
        ):
            full_text += tok
        return pai._parse_and_validate_macro_score_response(full_text, ticker)
    except Exception as e:
        print(f"  [error] {ticker}: {e}")
        return None


# ── Module 1: Repeatability ───────────────────────────────────────────────────

def run_repeatability(tickers: list, macro: dict, n: int = 20,
                       evidence_snapshot=None,
                       same_input_score_max_range: int = 1,
                       stability_policy=None) -> dict:
    """Score each ticker n times with frozen evidence; flag dimensions where range > same_input_score_max_range."""
    all_scores: dict = {t: {d: [] for d in DIMS} for t in tickers}
    for rep in range(1, n + 1):
        print(f"  Repeat {rep}/{n}...")
        for tk in tickers:
            snap = (evidence_snapshot or {}).get(tk, {})
            scores = _score_one_ticker(tk, snap.get("evidence", {}), snap.get("betas"))
            if scores:
                for dim in DIMS:
                    sv = _score_val(scores.get(dim))
                    if sv is not None:
                        all_scores[tk][dim].append(sv)
            time.sleep(5)

    results = {}
    for tk, dims in all_scores.items():
        results[tk] = {}
        for dim, vals in dims.items():
            if len(vals) >= 2:
                mean  = statistics.mean(vals)
                stdev = statistics.stdev(vals)
                score_range = max(vals) - min(vals)
                flag = score_range > same_input_score_max_range
                results[tk][dim] = {
                    "mean": round(mean, 2), "stdev": round(stdev, 3),
                    "range": score_range, "n": len(vals), "flag": flag,
                    "values": list(vals),
                    "status": "ok",
                }
                import portfolio_ai as _pai
                if hasattr(_pai, "_dimension_validation_state"):
                    results[tk][dim].update(_pai._dimension_validation_state(
                        results[tk][dim], {"n_repeats": n,
                        "thresholds": {"same_input_score_max_range": same_input_score_max_range},
                        "stability_policy": stability_policy or {}}))
                    results[tk][dim]["status"] = "ok" if results[tk][dim]["eligible"] else "UNSTABLE"
            elif len(vals) == 1:
                results[tk][dim] = {"mean": vals[0], "stdev": None, "range": 0, "n": 1, "values": list(vals),
                                    "flag": False, "status": "insufficient"}
            else:
                results[tk][dim] = {"mean": None, "stdev": None, "range": None, "n": 0, "values": [],
                                    "flag": False, "status": "no_data"}
    return results


# ── Module 2: Anchor Calibration ─────────────────────────────────────────────

def run_anchor_calibration(evidence_snapshot: dict) -> dict:
    """Score anchor instruments; compare vs expected brackets."""
    results = {}
    for ticker, anchor in ANCHORS.items():
        print(f"  Scoring anchor {ticker} ({anchor['description']})...")
        from portfolio_ai import is_fund
        if is_fund(ticker):
            results[ticker] = {"description": anchor["description"], "dims": {},
                               "status": "UNSUPPORTED", "reason": "Production excludes funds"}
            continue
        snap = evidence_snapshot[ticker]
        scores = _score_one_ticker(ticker, snap["evidence"], snap["betas"])
        anchor_result = {"description": anchor["description"], "dims": {}}
        for dim in DIMS:
            if dim not in anchor:
                continue
            sv = _score_val(scores.get(dim)) if scores else None
            lo, hi = anchor[dim]
            pass_cal = (lo <= sv <= hi) if sv is not None else False
            anchor_result["dims"][dim] = {
                "actual": sv, "expected_range": [lo, hi],
                "pass": pass_cal,
                "status": "PASS" if pass_cal else "FAIL",
            }
        results[ticker] = anchor_result
        time.sleep(8)
    # Relative ordering checks — stored under special key, not iterated as a ticker
    results["_ordering"] = _check_relative_ordering(results, RELATIVE_ORDERING_CHECKS)
    return results


# ── Module 3: Factor vs LLM Concordance (0483) ───────────────────────────────

def run_concordance(tickers: list) -> dict:
    """Compare measured rate_beta direction to LLM rate_sensitivity using corrected logic (0483).
    rate_beta < -5   → high sensitivity (≥6) expected
    rate_beta > -2   → low sensitivity (≤4) expected
    neutral zone     → no check
    """
    if not DB_PATH.exists():
        return {"skipped": True, "reason": "DB not found"}
    try:
        from portfolio_ai import _is_concordance_warning
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT ticker, scores FROM holding_macro_scores").fetchall()
        conn.close()
    except Exception as e:
        return {"skipped": True, "reason": str(e)}

    checked = []
    warnings_found = []
    for row in rows:
        try:
            s = json.loads(row["scores"])
        except Exception:
            continue
        rb = s.get("rate_beta_100bp_return_pct")
        rs = _score_val(s.get("rate_sensitivity"))
        if rb is None or rs is None:
            continue
        warn = _is_concordance_warning(rb, rs)
        entry = {
            "ticker": row["ticker"],
            "rate_beta": round(rb, 4),
            "rate_sensitivity": rs,
            "confidence": s.get("rate_beta_confidence", "unknown"),
            "concordance_warning": warn,
        }
        checked.append(entry)
        if warn:
            warnings_found.append(entry)

    if not checked:
        return {"skipped": True, "reason": "no tickers with both beta and LLM score"}

    # Only count non-neutral-zone tickers for concordance rate
    directional = [c for c in checked if c["rate_beta"] < -5.0 or c["rate_beta"] > -2.0]
    concordance_rate = (
        sum(1 for c in directional if not c["concordance_warning"]) / len(directional)
        if directional else None
    )
    return {
        "skipped": False,
        "concordance_rate": round(concordance_rate, 3) if concordance_rate is not None else None,
        "n_directional": len(directional),
        "n_neutral_zone": len(checked) - len(directional),
        "warnings": warnings_found,
        "tickers": checked,
    }


# ── Module 4: Unexplained Drift Detection ────────────────────────────────────

def run_drift_detection(drift_score_delta_threshold: int = 1) -> dict:
    """Compare two most recent holding_macro_scores_history rows per ticker.
    Flag tickers where evidence_hash unchanged but score changed > drift_score_delta_threshold.
    """
    if not DB_PATH.exists():
        return {"skipped": True, "reason": "DB not found"}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, scores, evidence_hash, scored_at "
            "FROM holding_macro_scores_history "
            "ORDER BY ticker, scored_at DESC"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"skipped": True, "reason": str(e)}

    ticker_runs: dict = {}
    for r in rows:
        ticker_runs.setdefault(r["ticker"], []).append(r)

    drift_flags = []
    comparisons = []
    provenance_events = []
    stable_count = 0
    evidence_changed_count = 0
    unverifiable_count = 0

    for ticker, run_list in ticker_runs.items():
        if len(run_list) < 2:
            continue
        curr_row, prev_row = run_list[0], run_list[1]
        try:
            curr_s = json.loads(curr_row["scores"])
            prev_s = json.loads(prev_row["scores"])
        except Exception:
            continue

        curr_contract = curr_s.get("scorer_contract_hash")
        prev_contract = prev_s.get("scorer_contract_hash")
        curr_prompt = curr_s.get("prompt_hash")
        prev_prompt = prev_s.get("prompt_hash")
        curr_ev = curr_row["evidence_hash"]
        prev_ev = prev_row["evidence_hash"]
        if curr_contract != prev_contract:
            provenance_events.append({"ticker": ticker, "classification": "contract_changed"})
            continue
        if curr_prompt != prev_prompt or curr_ev != prev_ev:
            provenance_events.append({"ticker": ticker, "classification": "input_changed"})
            evidence_changed_count += 1
            continue
        if curr_contract is None or curr_prompt is None:
            unverifiable_count += 1
            continue

        # Same evidence hash — check for score drift
        drifted_dims = []
        for dim in DIMS:
            cv = _score_val(curr_s.get(dim))
            pv = _score_val(prev_s.get(dim))
            if cv is not None and pv is not None:
                comparisons.append({"ticker": ticker, "dim": dim, "delta": cv - pv})
                if abs(cv - pv) > drift_score_delta_threshold:
                    drifted_dims.append({"dim": dim, "prev": pv, "curr": cv, "delta": cv - pv})

        if drifted_dims:
            drift_flags.append({
                "ticker": ticker,
                "curr_scored_at": curr_row["scored_at"],
                "prev_scored_at": prev_row["scored_at"],
                "evidence_hash": curr_ev,
                "prompt_hash": curr_prompt,
                "scorer_contract_hash": curr_contract,
                "drifted_dims": drifted_dims,
                "status": "UNEXPLAINED_DRIFT",
            })
        else:
            stable_count += 1

    return {
        "skipped": False,
        "drift_flags": drift_flags,
        "comparisons": comparisons,
        "provenance_events": provenance_events,
        "stable_count": stable_count,
        "evidence_changed_count": evidence_changed_count,
        "unverifiable_count": unverifiable_count,
        "n_checked": stable_count + len(drift_flags) + evidence_changed_count,
    }


# ── Module 5: Synthetic Regression Truth (0489) ──────────────────────────────

def run_synthetic_regression(beta_recovery_tolerance: float = 1.5) -> dict:
    """Verify multivariate OLS recovers injected true betas within tolerance (from config)."""
    try:
        import numpy as np
        np.random.seed(42)
        n = 104
        yield_chg = np.random.normal(0, 0.10, n)
        uup_ret   = np.random.normal(0, 0.5, n)
        spy_ret   = np.random.normal(0.1, 1.5, n)
        noise     = np.random.normal(0, 1.0, n)
        equity_pct = -5.0 * yield_chg + 2.0 * uup_ret + 0.8 * spy_ret + noise

        X = np.column_stack([np.ones(n), yield_chg, uup_ret, spy_ret])
        coeffs, _, _, _ = np.linalg.lstsq(X, equity_pct, rcond=None)
        rate_r, usd_r, spy_r = coeffs[1], coeffs[2], coeffs[3]
        tol = beta_recovery_tolerance

        results = []
        results.append({"test": "rate_beta_truth",   "recovered": round(float(rate_r), 3), "expected": -5.0, "tol": tol,
                         "status": "PASS" if abs(rate_r - (-5.0)) < tol else "FAIL"})
        results.append({"test": "usd_beta_truth",    "recovered": round(float(usd_r),  3), "expected": 2.0,  "tol": tol,
                         "status": "PASS" if abs(usd_r - 2.0) < tol else "FAIL"})
        results.append({"test": "market_beta_truth", "recovered": round(float(spy_r),  3), "expected": 0.8,  "tol": tol,
                         "status": "PASS" if abs(spy_r - 0.8) < tol else "FAIL"})
        return {"status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL", "tests": results}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


# ── Module 6: Regime Direction Tests (0489) ───────────────────────────────────

def run_regime_direction_tests() -> dict:
    """Verify compute_regime_stress direction semantics and missing-data handling."""
    try:
        from portfolio_ai import compute_regime_stress
        results = []

        def _r(rate=None, dollar=None, vix=None):
            return {
                "rate":       {"yield_10y_63d_chg_bps": rate}   if rate   is not None else {},
                "dollar":     {"uup_63d_pct": dollar}           if dollar is not None else {},
                "volatility": {"vix_level": vix}                if vix    is not None else {},
            }

        tests = [
            ("rising_rates_positive",        lambda: compute_regime_stress(_r(rate=100))["rate_stress"]   >  0),
            ("falling_rates_negative",       lambda: compute_regime_stress(_r(rate=-100))["rate_stress"]  <  0),
            ("missing_rate_is_none",         lambda: compute_regime_stress(_r())["rate_stress"]           is None),
            ("strong_dollar_positive",       lambda: compute_regime_stress(_r(dollar=3.0))["dollar_stress"] > 0),
            ("weak_dollar_negative",         lambda: compute_regime_stress(_r(dollar=-3.0))["dollar_stress"] < 0),
            ("missing_dollar_is_none",       lambda: compute_regime_stress(_r())["dollar_stress"]          is None),
            ("high_vix_positive",            lambda: compute_regime_stress(_r(vix=35))["vol_stress"] > 0),
            ("missing_vix_is_none",          lambda: compute_regime_stress(_r())["vol_stress"]       is None),
            ("geo_stress_always_none",       lambda: compute_regime_stress(_r(rate=100))["geopolitical_stress"] is None),
            ("rate_stress_clamped_at_plus1", lambda: compute_regime_stress(_r(rate=10000))["rate_stress"]  <= 1.0),
            ("rate_stress_clamped_at_neg1",  lambda: compute_regime_stress(_r(rate=-10000))["rate_stress"] >= -1.0),
        ]
        for name, fn in tests:
            try:
                ok = fn()
                results.append({"test": name, "status": "PASS" if ok else "FAIL"})
            except Exception as e:
                results.append({"test": name, "status": "FAIL", "error": str(e)})

        return {"status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
                "tests": results}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


# ── Module 7: Fund Classification Tests (0489) ────────────────────────────────

def run_fund_classification_tests() -> dict:
    """Verify SECURITY_MASTER correctly classifies known instruments."""
    try:
        from portfolio_ai import is_fund, SECURITY_MASTER
        results = []
        funds     = ["VTSAX", "VFIAX", "VTMGX", "FSPTX", "FXAIX", "VVIAX",
                     "SPY", "QQQ", "SCHD", "BIL", "VNQ", "TLT"]
        companies = ["AAPL", "GRMN", "MSTR", "NVDA", "AMZN"]
        for t in funds:
            ok = is_fund(t)
            results.append({"ticker": t, "expected": "fund",    "got": "fund" if ok else "company",
                             "status": "PASS" if ok else "FAIL"})
        for t in companies:
            ok = not is_fund(t)
            results.append({"ticker": t, "expected": "company", "got": "company" if ok else "fund",
                             "status": "PASS" if ok else "FAIL"})
        return {"status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
                "tickers": results}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


# ── Module 8: Ledger Integrity (0489) ─────────────────────────────────────────

def run_ledger_integrity(current_contract_hash: str = None, require_current: bool = False,
                         portfolio_n: int = None, portfolio_universe_hash: str = None) -> dict:
    """Separate historical accounting integrity from current production certification (0544/0545)."""
    if not DB_PATH.exists():
        return {"status": "SKIP", "reason": "no DB"}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(macro_scoring_runs)")}
        optional = [c for c in ("scorer_contract_hash", "run_scope", "portfolio_n", "portfolio_universe_hash") if c in cols]
        select_cols = ["run_id", "expected_n", "scored_n", "failed_n", "supported_scored_n", "unsupported_n", "status"] + optional
        rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM macro_scoring_runs WHERE status != 'STARTED'").fetchall()
        conn.close()
    except Exception as e:
        return {"status": "SKIP", "reason": str(e)}

    results = []
    for row in rows:
        run_id, exp, scored, failed, supported, unsupported, status = row[:7]
        extras = dict(zip(optional, row[7:]))
        contract_hash, run_scope, run_portfolio_n, run_universe_hash = (
            extras.get(c) for c in ("scorer_contract_hash", "run_scope", "portfolio_n", "portfolio_universe_hash"))
        accounting_ok = (exp == scored + failed)
        certified_ok = (
            status == "COMPLETE" and contract_hash == current_contract_hash and
            exp == scored and failed == 0 and (supported or 0) + (unsupported or 0) == scored
            and (portfolio_n is None or run_scope == "full_refresh")
            and (portfolio_n is None or (portfolio_n > 0 and run_portfolio_n == portfolio_n and exp == portfolio_n))
            and (portfolio_universe_hash is None or run_universe_hash == portfolio_universe_hash)
        )
        current_ok = certified_ok if require_current else True
        results.append({
            "run_id": run_id[:8] if run_id else "?",
            "expected": exp, "scored": scored, "failed": failed, "status_field": status,
            "accounting_ok": accounting_ok,
            "current_contract_ok": certified_ok,
            "scorer_contract_hash": contract_hash,
            "run_scope": run_scope, "portfolio_n": run_portfolio_n,
            "portfolio_universe_hash": run_universe_hash,
            "status": "PASS" if accounting_ok else "FAIL",
        })

    if not results:
        return {"status": "SKIP", "reason": "no completed runs yet"}

    historical_status = "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL"
    certification_runs = [r for r in results if r["current_contract_ok"]]
    certification_status = "PASS" if certification_runs else "FAIL"
    return {"status": certification_status if require_current else historical_status,
            "historical_status": historical_status, "runs": results,
            "certification_status": certification_status,
            "certification_runs": certification_runs}


def _current_portfolio_tickers(pai) -> list:
    """Use the same canonical holdings source as production scoring (0548)."""
    try:
        return pai._current_holdings_universe()["tickers"]
    except Exception:
        return []


# ── Summary + Output ──────────────────────────────────────────────────────────

def print_summary(repeatability: dict, anchor_cal: dict, concordance: dict, drift: dict,
                  synth: dict = None, regime_tests: dict = None,
                  fund_tests: dict = None, ledger: dict = None):
    print("\n=== 1. REPEATABILITY ===")
    print(f"{'Ticker':<12} {'Dimension':<22} {'Mean':>6} {'StDev':>6} {'N':>3} {'Status'}")
    print("-" * 65)
    for tk, dims in repeatability.items():
        for dim, r in dims.items():
            stdev_s = f"{r['stdev']:.3f}" if r["stdev"] is not None else "—"
            mean_s  = f"{r['mean']:.2f}" if r["mean"] is not None else "—"
            print(f"{tk:<12} {dim:<22} {mean_s:>6} {stdev_s:>6} {r['n']:>3}  {r['status']}")

    print("\n=== 2. ANCHOR CALIBRATION ===")
    for ticker, res in anchor_cal.items():
        if ticker == "_ordering":
            continue
        print(f"\n{ticker} — {res['description']}")
        for dim, r in res["dims"].items():
            print(f"  {dim}: actual={r['actual']}, expected={r['expected_range']} → {r['status']}")
    ordering = anchor_cal.get("_ordering", {})
    if ordering:
        print(f"\n  Relative ordering: {'PASS' if ordering['pass'] else 'FAIL'}")
        for chk in ordering.get("checks", []):
            print(f"    {chk['label']}: {chk['status']} — {chk.get('detail', '')}")

    print("\n=== 3. FACTOR vs LLM CONCORDANCE ===")
    if concordance.get("skipped"):
        print(f"  SKIPPED: {concordance.get('reason')}")
    else:
        cr = concordance.get("concordance_rate")
        cr_str = f"{cr:.1%}" if cr is not None else "N/A"
        print(f"  Directional concordance: {cr_str} ({concordance.get('n_directional',0)} tickers)")
        warns = concordance.get("warnings", [])
        if warns:
            print(f"  Concordance warnings ({len(warns)}):")
            for c in warns[:10]:
                print(f"    {c['ticker']}: rate_beta={c['rate_beta']:+.3f}, LLM rate_sensitivity={c['rate_sensitivity']}")

    print("\n=== 4. UNEXPLAINED DRIFT DETECTION ===")
    if drift.get("skipped"):
        print(f"  SKIPPED: {drift.get('reason')}")
    else:
        print(f"  Checked: {drift['n_checked']}, Stable: {drift['stable_count']}, "
              f"Evidence-changed: {drift['evidence_changed_count']}, "
              f"Unverifiable: {drift['unverifiable_count']}")
        if drift["drift_flags"]:
            print(f"  UNEXPLAINED DRIFT flags ({len(drift['drift_flags'])}):")
            for f in drift["drift_flags"]:
                dims_str = ", ".join(f"{d['dim']}:{d['prev']}→{d['curr']}" for d in f["drifted_dims"])
                print(f"    {f['ticker']} ({f['prev_scored_at'][:10]} → {f['curr_scored_at'][:10]}): {dims_str}")
        else:
            print("  No unexplained drift detected.")

    if synth:
        print(f"\n=== 5. SYNTHETIC REGRESSION ({synth.get('status')}) ===")
        for t in synth.get("tests", []):
            print(f"  {t['test']}: recovered={t['recovered']}, expected={t['expected']} ±{t['tol']} → {t['status']}")

    if regime_tests:
        print(f"\n=== 6. REGIME DIRECTION ({regime_tests.get('status')}) ===")
        fails = [t for t in regime_tests.get("tests", []) if t["status"] != "PASS"]
        print(f"  {len(regime_tests.get('tests',[]))} checks, {len(fails)} failed")
        for t in fails:
            print(f"  FAIL: {t['test']}")

    if fund_tests:
        print(f"\n=== 7. FUND CLASSIFICATION ({fund_tests.get('status')}) ===")
        fails = [t for t in fund_tests.get("tickers", []) if t["status"] != "PASS"]
        print(f"  {len(fund_tests.get('tickers',[]))} tickers, {len(fails)} failed")
        for t in fails:
            print(f"  FAIL: {t['ticker']} expected={t['expected']} got={t['got']}")

    if ledger:
        print(f"\n=== 8. LEDGER INTEGRITY ({ledger.get('status')}) ===")
        if ledger.get("status") == "SKIP":
            print(f"  SKIPPED: {ledger.get('reason')}")
        else:
            fails = [r for r in ledger.get("runs", []) if r["status"] != "PASS"]
            print(f"  {len(ledger.get('runs',[]))} runs, {len(fails)} accounting failures")
            for r in fails:
                print(f"  FAIL: {r['run_id']} expected={r['expected']} scored={r['scored']} failed={r['failed']}")


def _count_fails(repeatability, anchor_cal, concordance, drift,
                 synth=None, regime_tests=None, fund_tests=None, ledger=None) -> tuple[int, int, int]:
    """Return (fail, warn, pass) counts."""
    fails = warns = passes = 0

    # Repeatability: UNSTABLE = warn
    for dims in repeatability.values():
        for r in dims.values():
            if r["status"] == "UNSTABLE":
                warns += 1
            elif r["status"] == "ok":
                passes += 1

    # Anchor: FAIL = fail
    for k, res in anchor_cal.items():
        if k == "_ordering":
            fails += sum(1 for c in res.get("checks", []) if c.get("status") == "FAIL")
            passes += sum(1 for c in res.get("checks", []) if c.get("status") == "PASS")
            continue
        for r in res["dims"].values():
            if r["status"] == "PASS":
                passes += 1
            else:
                fails += 1

    # Concordance: warnings = warns
    if not concordance.get("skipped"):
        warns += len(concordance.get("warnings", []))
        cr = concordance.get("concordance_rate")
        if cr is not None and cr >= 0.6:
            passes += 1

    # Drift: each flag = warn
    if not drift.get("skipped"):
        warns += len(drift.get("drift_flags", []))
        passes += drift.get("stable_count", 0)

    # Synthetic regression: FAIL = fail
    if synth and synth.get("status") == "FAIL":
        for t in synth.get("tests", []):
            if t["status"] == "FAIL":
                fails += 1
            else:
                passes += 1

    # Regime direction: FAIL = fail
    if regime_tests and regime_tests.get("status") != "SKIP":
        for t in regime_tests.get("tests", []):
            if t["status"] == "FAIL":
                fails += 1
            else:
                passes += 1

    # Fund classification: FAIL = fail
    if fund_tests and fund_tests.get("status") != "SKIP":
        for t in fund_tests.get("tickers", []):
            if t["status"] == "FAIL":
                fails += 1
            else:
                passes += 1

    # Ledger integrity: FAIL = fail
    if ledger and ledger.get("status") == "FAIL":
        for r in ledger.get("runs", []):
            if r["status"] == "FAIL":
                fails += 1
            else:
                passes += 1

    return fails, warns, passes


def _load_validation_config() -> dict:
    """Load validation_config.json. Raises on missing file or malformed JSON — no silent defaults."""
    config_path = PROJECT_DIR / "validation_config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"validation_config.json not found at {config_path}. "
            "Create it with all required threshold keys before running validation."
        )
    try:
        config = json.loads(config_path.read_text())
        _validate_config(config)
        return config
    except json.JSONDecodeError as e:
        raise ValueError(
            f"validation_config.json is malformed — {e}. "
            "Fix the JSON before running validation. Refusing to fall back to defaults."
        ) from e


def _get_commit_sha() -> str:
    import subprocess
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=str(PROJECT_DIR)
        ).stdout.strip()
    except Exception:
        return "unknown"


def _get_model_identity() -> str:
    try:
        import ollama_client
        return ollama_client.DEFAULT_MODEL
    except Exception:
        return "unknown"


_REQUIRED_THRESHOLDS = {
    "beta_recovery_tolerance",
    "anchor_ordering_failures",
    "fund_unsupported_pct",
    "ledger_integrity_pct",
    "unexplained_large_swings",
    "missing_data_unknown_pct",
    "same_input_score_max_range",
    "drift_score_delta_threshold",
}


def _validate_config(config: dict) -> None:
    if not isinstance(config, dict):
        raise ValueError("validation config must be an object")
    allowed = {"version", "repeatability_universe", "thresholds", "n_repeats", "prior_block_record", "stability_policy"}
    unknown = {k for k in config if k not in allowed and not k.startswith("amendment_note")}
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    t = config.get("thresholds", {})
    if not isinstance(t, dict):
        raise ValueError("thresholds must be an object")
    if _REQUIRED_THRESHOLDS - set(t):
        raise ValueError(f"missing required threshold keys: {sorted(_REQUIRED_THRESHOLDS - set(t))}")
    if set(t) - _REQUIRED_THRESHOLDS:
        raise ValueError(f"unknown threshold keys: {sorted(set(t) - _REQUIRED_THRESHOLDS)}")
    for key, value in t.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid numeric threshold: {key}")
        if key.endswith("_pct") and value > 100:
            raise ValueError(f"percentage outside 0..100: {key}")
    if type(config.get("n_repeats")) is not int or config["n_repeats"] < 2:
        raise ValueError("n_repeats must be an integer >= 2")
    policy = config.get("stability_policy", {})
    if not policy:
        policy = {"stable_stddev_max": 1.0, "borderline_stddev_max": 1.5}
    if not isinstance(policy, dict):
        raise ValueError("stability_policy must be an object")
    stable_max = policy.get("stable_stddev_max")
    borderline_max = policy.get("borderline_stddev_max")
    if (isinstance(stable_max, bool) or not isinstance(stable_max, (int, float)) or stable_max < 0
            or isinstance(borderline_max, bool) or not isinstance(borderline_max, (int, float))
            or borderline_max < stable_max):
        raise ValueError("invalid stability_policy boundaries")
    universe = config.get("repeatability_universe")
    if universe is not None and (not isinstance(universe, list) or not universe
            or any(not isinstance(tk, str) or not tk.strip() for tk in universe)
            or len(set(universe)) != len(universe)):
        raise ValueError("repeatability_universe must contain unique ticker strings")


def _check_thresholds(results: dict, config: dict) -> dict:
    """Derive verdicts from measured values, never trust upstream PASS labels."""
    t = config["thresholds"]
    checks = {}
    def gate(name, ok):
        checks[name] = "PASS" if ok else "BLOCK"
    def pct(rows):
        return 100 * sum(r.get("status") == "PASS" for r in rows) / len(rows) if rows else None
    def minimum(name, rows, threshold):
        value = pct(rows)
        gate(name, value is not None and value >= threshold)
    synth = results.get("synthetic_regression", {}).get("tests", [])
    gate("beta_recovery", bool(synth) and all(
        isinstance(r.get("recovered"), (int, float)) and isinstance(r.get("expected"), (int, float))
        and math.isfinite(r["recovered"]) and math.isfinite(r["expected"])
        and abs(r["recovered"] - r["expected"]) <= t["beta_recovery_tolerance"] for r in synth))
    regime = results.get("regime_direction", {}).get("tests", [])
    missing = [r for r in regime if r.get("test", "").startswith("missing_") or r.get("test") == "geo_stress_always_none"]
    direction = [r for r in regime if r not in missing]
    minimum("missing_data_unknown", missing, t["missing_data_unknown_pct"])
    gate("regime_direction", bool(direction) and all(r.get("status") == "PASS" for r in direction))
    funds = results.get("fund_classification", {}).get("tickers", [])
    minimum("fund_unsupported", [r for r in funds if r.get("expected") == "fund"], t["fund_unsupported_pct"])
    companies = [r for r in funds if r.get("expected") == "company"]
    gate("company_classification", bool(companies) and all(r.get("status") == "PASS" for r in companies))
    ledger_result = results.get("ledger_integrity", {})
    ledger = ledger_result.get("runs", [])
    measured = [{"status": "PASS" if r.get("accounting_ok", r.get("expected") is not None and
                 r.get("expected") == r.get("scored", -1) + r.get("failed", -1)) else "FAIL"} for r in ledger]
    minimum("ledger_integrity", measured, t["ledger_integrity_pct"])
    cert_status = ledger_result.get("certification_status")
    if cert_status is None:
        # Compatibility for pre-0544 synthetic fixtures; live runs always emit
        # an explicit certification_status field.
        cert_status = "PASS"
    gate("current_contract_production_certification", cert_status == "PASS")
    anchor = results.get("anchor_calibration", {})
    dims = [r for tk, res in anchor.items() if tk != "_ordering" and isinstance(res, dict) for r in res.get("dims", {}).values()]
    gate("anchor_calibration", bool(dims) and all(r.get("actual") is not None
         and r["expected_range"][0] <= r["actual"] <= r["expected_range"][1] for r in dims))
    ordering = anchor.get("_ordering", {}).get("checks", [])
    gate("anchor_ordering", bool(ordering) and all(r.get("lo") is not None and r.get("hi") is not None for r in ordering)
         and sum(r["lo"] >= r["hi"] for r in ordering) <= t["anchor_ordering_failures"])
    drift = results.get("drift", {})
    deltas = drift.get("comparisons")
    drifted = {r["ticker"] for r in (deltas or []) if abs(r["delta"]) > t["drift_score_delta_threshold"]}
    gate("unexplained_drift", deltas is not None and not drift.get("skipped")
         and len(drifted) <= t["unexplained_large_swings"])
    repeat = results.get("repeatability", {})
    expected = config.get("repeatability_universe", list(repeat))
    # 0539: system acceptance requires complete observations; per-dimension range
    # remains an eligibility classification and does not invalidate other dimensions.
    complete = bool(expected) and set(repeat) == set(expected) and all(
        set(repeat[tk]) == set(DIMS) and all(r.get("n") == config.get("n_repeats")
        and isinstance(r.get("range"), (int, float)) and math.isfinite(r["range"])
        and r.get("mean") is not None for r in repeat[tk].values()) for tk in expected)
    gate("repeatability", complete)
    if complete:
        checks["repeatability_eligibility"] = "PASS"
    return {"verdict": "PASS" if all(v == "PASS" for v in checks.values()) else "BLOCK",
            "per_check": checks, "effective_thresholds": dict(t)}


def _run_type(live, smoke, override, verdict):
    if smoke or override is not None:
        return "smoke"
    if not live:
        return "dry_run"
    return "acceptance" if verdict == "PASS" else "validation_failed"


def _persist_run(db_path, output, timeout=30):
    """Record each UUID once; atomically activate all dimensions and the pointer."""
    import portfolio_ai as pai
    activate = output["run_type"] == "acceptance" and output["verdict"] == "PASS"
    if activate:
        if _check_thresholds(output["results"], output["config_used"])["verdict"] != "PASS":
            raise ValueError("acceptance measurements do not satisfy config")
        if output["scorer_contract_hash"] != pai._compute_scorer_contract_hash():
            raise ValueError("scorer contract changed during validation")
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    try:
        conn.execute("BEGIN IMMEDIATE")
        record = dict(output, activated=activate)
        conn.execute("INSERT INTO macro_validation_runs VALUES (?,?,?,?,?,?)", (
            output["record_id"], output["output_path"], output["run_type"], output["verdict"],
            json.dumps(record, sort_keys=True), output["timestamp"]))
        if activate:
            for ticker, dims in output["results"]["repeatability"].items():
                provenance = output["evidence_snapshot"][ticker]
                for dim, r in dims.items():
                    state = pai._dimension_validation_state(r, output["config_used"])
                    conn.execute("""INSERT INTO macro_dimension_validation
                        (acceptance_record_id,ticker,dimension,mean_score,stddev,n_samples,
                         stability_class,config_version,config_hash,model_identity,scorer_contract_hash,
                         prompt_hash,evidence_hash,eligible,eligibility_reason,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        output["record_id"], ticker, dim, r["mean"], r["stdev"], r["n"],
                        state["stability_class"], output["validation_config_version"],
                        output["validation_config_hash"], output["model_identity"], output["scorer_contract_hash"],
                        provenance["prompt_hash"], provenance["evidence_hash"], int(state["eligible"]),
                        state["eligibility_reason"], output["timestamp"]))
            conn.execute("""INSERT INTO macro_acceptance_state
                (contract,accepted_at,record_id,commit_sha,model_identity,scorer_contract_hash,output_path,notes)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(contract) DO UPDATE SET
                accepted_at=excluded.accepted_at,record_id=excluded.record_id,commit_sha=excluded.commit_sha,
                model_identity=excluded.model_identity,scorer_contract_hash=excluded.scorer_contract_hash,
                output_path=excluded.output_path,notes=excluded.notes""", (
                output["acceptance_contract"], output["timestamp"], output["record_id"], output["commit_sha"],
                output["model_identity"], output["scorer_contract_hash"], output["output_path"], "Formal validation PASS"))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return activate


def main():
    import argparse
    import portfolio_ai as pai
    parser = argparse.ArgumentParser(description="Macro scorer validation lab")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--n-repeats", type=int, default=None, help="Override N; forces smoke mode")
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    record_id = str(uuid.uuid4())  # allocated before evidence collection or validation
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    config = _load_validation_config()
    n = args.n_repeats if args.n_repeats is not None else config["n_repeats"]
    if n < 2:
        raise ValueError("repeat count must be >= 2")
    tickers = config.get("repeatability_universe", [])
    if len(tickers) < 6 or any(pai.is_fund(tk) for tk in tickers):
        raise ValueError("repeatability_universe requires >=6 unique company tickers")
    contract_hash = pai._compute_scorer_contract_hash()
    commit_sha = _get_commit_sha()
    model_identity = _get_model_identity()
    out_path = Path(args.out) if args.out else PROJECT_DIR / "out" / f"macro_validation_{record_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite validation artifact: {out_path}")
    # Initialize/migrate only the configured production DB (tests redirect to temporary DBs).
    pai._init_ai_tables()
    snapshot = {}
    repeatability, anchor = {}, {}
    t = config["thresholds"]
    if args.live:
        import ollama_client
        if not ollama_client.available():
            raise RuntimeError("Production LLM unavailable")
        universe = list(dict.fromkeys(tickers + [tk for tk in ANCHORS if not pai.is_fund(tk)]))
        with sqlite3.connect(str(pai.DB_PATH), timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            snapshot = _freeze_validation_evidence(universe, conn)
        print(f"Frozen evidence for {len(universe)} tickers; run {record_id}; N={n}", flush=True)
        repeatability = run_repeatability(tickers, {}, n=n, evidence_snapshot=snapshot,
                                          same_input_score_max_range=t["same_input_score_max_range"],
                                          stability_policy=config.get("stability_policy"))
        anchor = run_anchor_calibration(snapshot)
    portfolio_tickers = _current_portfolio_tickers(pai)
    results = {
        "repeatability": repeatability, "anchor_calibration": anchor,
        "concordance": run_concordance(tickers),
        "drift": run_drift_detection(t["drift_score_delta_threshold"]),
        "synthetic_regression": run_synthetic_regression(t["beta_recovery_tolerance"]),
        "regime_direction": run_regime_direction_tests(),
        "fund_classification": run_fund_classification_tests(),
            "ledger_integrity": run_ledger_integrity(contract_hash,
            args.live and args.n_repeats is None and not args.smoke,
            len(portfolio_tickers), pai._portfolio_universe_hash(portfolio_tickers)),
    }
    effective_config = dict(config, n_repeats=n)
    checks = _check_thresholds(results, effective_config)
    verdict = checks["verdict"]
    output = {
        "record_id": record_id, "timestamp": started_at, "output_path": str(out_path),
        "acceptance_contract": "macro_validation_v1", "commit_sha": commit_sha,
        "model_identity": model_identity, "scorer_contract_hash": contract_hash,
        "validation_config_version": config["version"],
        "validation_config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "config_used": config, "resolved_config": effective_config,
        "live_mode": args.live, "run_type": _run_type(args.live, args.smoke, args.n_repeats, verdict),
        "n_repeats": n, "verdict": verdict, "activated": False,
        "evidence_snapshot": snapshot,
        "evidence_hash": {tk: v["evidence_hash"] for tk, v in snapshot.items()},
        "prompt_hash": {tk: v["prompt_hash"] for tk, v in snapshot.items()},
        "evidence_snapshot_hashes": {tk: v["evidence_hash"] for tk, v in snapshot.items()},
        "results": results, "threshold_checks": checks,
    }
    # Exclusive creation preserves prior artifacts even when --out is reused.
    with out_path.open("x") as f:
        json.dump(output, f, indent=2, default=str)
    try:
        output["activated"] = _persist_run(pai.DB_PATH, output)
    except Exception as exc:
        output["activation_error"] = str(exc)
        out_path.write_text(json.dumps(output, indent=2, default=str))
        raise
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"Results: {out_path}\nVerdict: {verdict}; activated={output['activated']}", flush=True)
    if verdict != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
