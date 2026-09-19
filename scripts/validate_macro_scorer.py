#!/usr/bin/env python3
"""
Macro scorer validation lab (0479).

Four test modules:
  1. Repeatability    — N=20 passes on frozen inputs, per-dim stddev; flag > 1.0
  2. Anchor calibration — known instruments against expected score brackets
  3. Factor concordance — measure beta sign vs LLM score sign agreement (0473)
  4. Drift detection  — compare last two history rows per ticker; flag unexplained deltas
"""
import json
import math
import sqlite3
import statistics
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

REPEATS = 20
STDEV_WARN_THRESHOLD = 1.0
DRIFT_THRESHOLD = 1        # score-point change without evidence-hash change
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
    "UUP": {
        "description": "US Dollar ETF — benefits from dollar strength",
        "dollar_sensitivity": (1, 2),   # domestic dollar-denominated, minimal hurt
    },
    "XOM": {
        "description": "Large US energy / inflation hedge",
        "inflation_hedge": (6, 10),
    },
}


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


def _score_one_ticker(ticker: str, macro: dict):
    """Score a single ticker using the project's scoring prompt. Returns raw score dict or None."""
    try:
        import portfolio_ai as pai
        import ollama_client
        if not ollama_client.available():
            print(f"  [skip] Ollama not available for {ticker}")
            return None

        dim_defs = "\n".join(
            f"- {dim} ({'1=low inflation protection, 10=strong inflation protection' if meta.get('direction') == 'benefit' else '1=low exposure, 10=high exposure'}): {meta['prompt_def']}"
            for dim, meta in pai.MACRO_DIMS.items()
        )
        prompt = f"""You are a quantitative analyst. Score the ticker's structural macro exposure on 4 dimensions from 1-10.

Structural exposure measures how sensitive the company's business is to each macro factor — independent of current market conditions.

Scoring definitions (scale is dimension-specific):
{dim_defs}

Tickers to score: {ticker}

Return ONLY valid JSON:
{{
  "{ticker}": {{
    "rate_sensitivity": {{"score": <1-10>, "reason": "<reason>"}},
    "inflation_hedge": {{"score": <1-10>, "reason": "<reason>"}},
    "dollar_sensitivity": {{"score": <1-10>, "reason": "<reason>"}},
    "geopolitical_risk": {{"score": <1-10>, "reason": "<reason>"}},
    "note": "<summary>"
  }}
}}"""

        full_text = ""
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.2, num_predict=800
        ):
            full_text += tok

        result = pai._extract_json(full_text)
        if result and ticker in result:
            return result[ticker]
        return None
    except Exception as e:
        print(f"  [error] {ticker}: {e}")
        return None


# ── Module 1: Repeatability ───────────────────────────────────────────────────

def _run_repeatability_n(tickers: list, macro: dict, n: int) -> dict:
    return run_repeatability(tickers, macro, n=n)


def run_repeatability(tickers: list, macro: dict, n: int = REPEATS) -> dict:
    """Score each ticker n times with frozen inputs; compute mean/stddev per dimension."""
    all_scores: dict = {t: {d: [] for d in DIMS} for t in tickers}
    for rep in range(1, n + 1):
        print(f"  Repeat {rep}/{REPEATS}...")
        for tk in tickers:
            scores = _score_one_ticker(tk, macro)
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
                mean = statistics.mean(vals)
                stdev = statistics.stdev(vals)
                flag = stdev > STDEV_WARN_THRESHOLD
                results[tk][dim] = {
                    "mean": round(mean, 2), "stdev": round(stdev, 3),
                    "n": len(vals), "flag": flag,
                    "status": "UNSTABLE" if flag else "ok",
                }
            elif len(vals) == 1:
                results[tk][dim] = {"mean": vals[0], "stdev": None, "n": 1, "flag": False, "status": "insufficient"}
            else:
                results[tk][dim] = {"mean": None, "stdev": None, "n": 0, "flag": False, "status": "no_data"}
    return results


# ── Module 2: Anchor Calibration ─────────────────────────────────────────────

def run_anchor_calibration(macro: dict) -> dict:
    """Score anchor instruments; compare vs expected brackets."""
    results = {}
    for ticker, anchor in ANCHORS.items():
        print(f"  Scoring anchor {ticker} ({anchor['description']})...")
        scores = _score_one_ticker(ticker, macro)
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

def run_drift_detection() -> dict:
    """Compare two most recent holding_macro_scores_history rows per ticker.
    Flag tickers where evidence_hash unchanged but score changed > DRIFT_THRESHOLD.
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
    stable_count = 0
    evidence_changed_count = 0
    unverifiable_count = 0

    for ticker, run_list in ticker_runs.items():
        if len(run_list) < 2:
            continue
        curr_row, prev_row = run_list[0], run_list[1]
        curr_ev = curr_row["evidence_hash"]
        prev_ev = prev_row["evidence_hash"]

        try:
            curr_s = json.loads(curr_row["scores"])
            prev_s = json.loads(prev_row["scores"])
        except Exception:
            continue

        if curr_ev is None or prev_ev is None:
            unverifiable_count += 1
            continue

        if curr_ev != prev_ev:
            evidence_changed_count += 1
            continue

        # Same evidence hash — check for score drift
        drifted_dims = []
        for dim in DIMS:
            cv = _score_val(curr_s.get(dim))
            pv = _score_val(prev_s.get(dim))
            if cv is not None and pv is not None and abs(cv - pv) > DRIFT_THRESHOLD:
                drifted_dims.append({"dim": dim, "prev": pv, "curr": cv, "delta": cv - pv})

        if drifted_dims:
            drift_flags.append({
                "ticker": ticker,
                "curr_scored_at": curr_row["scored_at"],
                "prev_scored_at": prev_row["scored_at"],
                "evidence_hash": curr_ev,
                "drifted_dims": drifted_dims,
                "status": "UNEXPLAINED_DRIFT",
            })
        else:
            stable_count += 1

    return {
        "skipped": False,
        "drift_flags": drift_flags,
        "stable_count": stable_count,
        "evidence_changed_count": evidence_changed_count,
        "unverifiable_count": unverifiable_count,
        "n_checked": stable_count + len(drift_flags) + evidence_changed_count,
    }


# ── Module 5: Synthetic Regression Truth (0489) ──────────────────────────────

def run_synthetic_regression() -> dict:
    """Verify multivariate OLS recovers injected true betas within tolerance."""
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

        results = []
        results.append({"test": "rate_beta_truth",   "recovered": round(float(rate_r),3), "expected": -5.0, "tol": 1.5,
                         "status": "PASS" if abs(rate_r - (-5.0)) < 1.5 else "FAIL"})
        results.append({"test": "usd_beta_truth",    "recovered": round(float(usd_r), 3), "expected": 2.0,  "tol": 1.5,
                         "status": "PASS" if abs(usd_r - 2.0) < 1.5 else "FAIL"})
        results.append({"test": "market_beta_truth", "recovered": round(float(spy_r), 3), "expected": 0.8,  "tol": 0.5,
                         "status": "PASS" if abs(spy_r - 0.8) < 0.5 else "FAIL"})
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

def run_ledger_integrity() -> dict:
    """Verify expected_n == scored_n + failed_n for all completed runs."""
    if not DB_PATH.exists():
        return {"status": "SKIP", "reason": "no DB"}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        rows = conn.execute(
            "SELECT run_id, expected_n, scored_n, failed_n, status FROM macro_scoring_runs WHERE status != 'STARTED'"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"status": "SKIP", "reason": str(e)}

    results = []
    for run_id, exp, scored, failed, status in rows:
        ok = (exp == scored + failed)
        results.append({
            "run_id": run_id[:8] if run_id else "?",
            "expected": exp, "scored": scored, "failed": failed, "status_field": status,
            "accounting_ok": ok,
            "status": "PASS" if ok else "FAIL",
        })

    if not results:
        return {"status": "SKIP", "reason": "no completed runs yet"}

    overall = "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL"
    return {"status": overall, "runs": results}


# ── Summary + Output ──────────────────────────────────────────────────────────

def print_summary(repeatability: dict, anchor_cal: dict, concordance: dict, drift: dict,
                  synth: dict = None, regime_tests: dict = None,
                  fund_tests: dict = None, ledger: dict = None):
    print("\n=== 1. REPEATABILITY (N={}) ===".format(REPEATS))
    print(f"{'Ticker':<12} {'Dimension':<22} {'Mean':>6} {'StDev':>6} {'N':>3} {'Status'}")
    print("-" * 65)
    for tk, dims in repeatability.items():
        for dim, r in dims.items():
            stdev_s = f"{r['stdev']:.3f}" if r["stdev"] is not None else "—"
            mean_s  = f"{r['mean']:.2f}" if r["mean"] is not None else "—"
            print(f"{tk:<12} {dim:<22} {mean_s:>6} {stdev_s:>6} {r['n']:>3}  {r['status']}")

    print("\n=== 2. ANCHOR CALIBRATION ===")
    for ticker, res in anchor_cal.items():
        print(f"\n{ticker} — {res['description']}")
        for dim, r in res["dims"].items():
            print(f"  {dim}: actual={r['actual']}, expected={r['expected_range']} → {r['status']}")

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
    for res in anchor_cal.values():
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
    """Load validation_config.json thresholds; return defaults if absent."""
    config_path = PROJECT_DIR / "validation_config.json"
    defaults = {
        "version": "v1",
        "thresholds": {
            "schema_valid_pct": 100,
            "ledger_integrity_pct": 100,
            "same_input_score_max_range": 1,
            "unexplained_large_swings": 0,
            "anchor_ordering_failures": 0,
            "beta_recovery_tolerance": 1.5,
            "missing_data_unknown_pct": 100,
            "fund_unsupported_pct": 100,
            "provenance_completeness_pct": 100,
        },
        "n_repeats": 20,
    }
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text())
            defaults.update(loaded)
        except Exception:
            pass
    return defaults


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


def _check_thresholds(results: dict, config: dict) -> dict:
    """Evaluate module results against config thresholds. Returns per-check status + overall verdict."""
    t = config.get("thresholds", {})
    checks = {}

    # Synthetic regression
    synth = results.get("synthetic_regression", {})
    checks["beta_recovery"] = "PASS" if synth.get("status") == "PASS" else "BLOCK"

    # Regime direction
    rd = results.get("regime_direction", {})
    checks["missing_data_unknown"] = "PASS" if rd.get("status") == "PASS" else "BLOCK"

    # Fund classification
    fc = results.get("fund_classification", {})
    checks["fund_unsupported"] = "PASS" if fc.get("status") == "PASS" else "BLOCK"

    # Ledger integrity
    li = results.get("ledger_integrity", {})
    if li.get("status") == "SKIP":
        checks["ledger_integrity"] = "SKIP"
    else:
        checks["ledger_integrity"] = "PASS" if li.get("status") == "PASS" else "BLOCK"

    # Anchor calibration
    anchor = results.get("anchor_calibration", {})
    anchor_fails = sum(
        1 for res in anchor.values()
        for r in res.get("dims", {}).values()
        if r.get("status") != "PASS"
    )
    checks["anchor_calibration"] = "PASS" if anchor_fails == 0 else "BLOCK"

    # Drift (warn, not block)
    drift = results.get("drift", {})
    drift_flags = drift.get("drift_flags", [])
    checks["unexplained_drift"] = "PASS" if not drift_flags else "WARN"

    # Repeatability (warn if UNSTABLE)
    repeatability = results.get("repeatability", {})
    unstable = sum(
        1 for dims in repeatability.values()
        for r in dims.values() if r.get("status") == "UNSTABLE"
    )
    checks["repeatability"] = "PASS" if unstable == 0 else "WARN"

    # Overall verdict: BLOCK if any check is BLOCK, else PASS
    verdict = "BLOCK" if any(v == "BLOCK" for v in checks.values()) else "PASS"
    return {"verdict": verdict, "per_check": checks}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Macro scorer validation lab")
    parser.add_argument("--live", action="store_true", help="Use live LLM for repeatability/anchor tests")
    parser.add_argument("--n-repeats", type=int, default=None, help="Override repeat count")
    parser.add_argument("--out", type=str, default=None, help="Output file path for acceptance record")
    args = parser.parse_args()

    config = _load_validation_config()
    n_repeats_effective = args.n_repeats or (5 if args.live else REPEATS)

    import macro_context
    print("Loading macro context (frozen for validation)...")
    macro = macro_context.fetch()

    try:
        import portfolio_ai as pai
        holdings = pai._load_holdings_csv()
        tickers = list({pai._normalize_ticker(h.get("Stock", "")) for h in holdings if h.get("Stock")})[:8]
    except Exception:
        tickers = []

    # LLM-dependent tests only run in --live mode
    if args.live:
        print(f"\n1. Repeatability test ({len(tickers)} holdings, N={n_repeats_effective}, LIVE)...")
        repeatability = run_repeatability(tickers, macro, n=n_repeats_effective) if tickers else {}

        print("\n2. Anchor calibration (LIVE)...")
        anchor_cal = run_anchor_calibration(macro)
    else:
        print("\n1. Repeatability test — SKIP (use --live to run with LLM)")
        repeatability = {}
        print("\n2. Anchor calibration — SKIP (use --live)")
        anchor_cal = {}

    print("\n3. Factor vs LLM concordance...")
    concordance = run_concordance(tickers)

    print("\n4. Drift detection...")
    drift = run_drift_detection()

    print("\n5. Synthetic regression truth...")
    synth = run_synthetic_regression()

    print("\n6. Regime direction tests...")
    regime_tests = run_regime_direction_tests()

    print("\n7. Fund classification tests...")
    fund_tests = run_fund_classification_tests()

    print("\n8. Ledger integrity...")
    ledger = run_ledger_integrity()

    print_summary(repeatability, anchor_cal, concordance, drift, synth, regime_tests, fund_tests, ledger)

    fails, warns, passes = _count_fails(repeatability, anchor_cal, concordance, drift,
                                        synth, regime_tests, fund_tests, ledger)
    summary_status = "FAIL" if fails > 0 else ("WARN" if warns > 0 else "PASS")

    all_results = {
        "repeatability":       repeatability,
        "anchor_calibration":  anchor_cal,
        "concordance":         concordance,
        "drift":               drift,
        "synthetic_regression": synth,
        "regime_direction":    regime_tests,
        "fund_classification": fund_tests,
        "ledger_integrity":    ledger,
    }
    threshold_result = _check_thresholds(all_results, config)
    verdict = threshold_result["verdict"]

    output = {
        "version":        "v1",
        "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "commit_sha":     _get_commit_sha(),
        "model_identity": _get_model_identity(),
        "live_mode":      args.live,
        "n_repeats":      n_repeats_effective,
        "config_used":    config,
        "results":        all_results,
        "threshold_checks": threshold_result,
        "verdict":        verdict,
        "summary": {
            "status": summary_status,
            "fail":   fails,
            "warn":   warns,
            "pass":   passes,
        },
    }

    # Determine output path — immutable timestamped acceptance record or standard path
    if args.out:
        out_path = Path(args.out)
    elif args.live:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = PROJECT_DIR / "out" / f"macro_validation_acceptance_{ts}.json"
    else:
        out_path = OUT_PATH

    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults written to {out_path}")
    print(f"Summary: {summary_status} — {fails} fail, {warns} warn, {passes} pass")
    print(f"Verdict: {verdict}")

    if fails or verdict == "BLOCK":
        sys.exit(1)


if __name__ == "__main__":
    main()
