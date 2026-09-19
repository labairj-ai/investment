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

def run_repeatability(tickers: list, macro: dict) -> dict:
    """Score each ticker REPEATS times with frozen inputs; compute mean/stddev per dimension."""
    all_scores: dict = {t: {d: [] for d in DIMS} for t in tickers}
    for rep in range(1, REPEATS + 1):
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


# ── Module 3: Factor vs LLM Concordance (0473) ───────────────────────────────

def run_concordance(tickers: list) -> dict:
    """Compare measured rate_beta sign to LLM rate_sensitivity direction.
    Requires 0473 betas (rate_beta_100bp_return_pct) stored in macro scores DB.
    rate_beta < 0  → should have rate_sensitivity ≥ 5 (hurt by rising rates)
    rate_beta ≥ 0  → should have rate_sensitivity ≤ 5 (not hurt / benefits)
    Returns concordance rate and per-ticker results.
    """
    if not DB_PATH.exists():
        return {"skipped": True, "reason": "DB not found"}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT ticker, scores FROM holding_macro_scores").fetchall()
        conn.close()
    except Exception as e:
        return {"skipped": True, "reason": str(e)}

    checked = []
    for row in rows:
        try:
            s = json.loads(row["scores"])
        except Exception:
            continue
        rb = s.get("rate_beta_100bp_return_pct")
        rs = _score_val(s.get("rate_sensitivity"))
        if rb is None or rs is None:
            continue
        # beta < 0 → equity falls when rates rise → high rate_sensitivity expected (≥ 5)
        expected_high = rb < 0
        actual_high   = rs >= 5
        agree = (expected_high == actual_high)
        checked.append({
            "ticker": row["ticker"],
            "rate_beta": round(rb, 4),
            "rate_sensitivity": rs,
            "expected_high": expected_high,
            "actual_high": actual_high,
            "agree": agree,
        })

    if not checked:
        return {"skipped": True, "reason": "no tickers with both beta and LLM score"}

    concordance_rate = sum(1 for c in checked if c["agree"]) / len(checked)
    return {
        "skipped": False,
        "concordance_rate": round(concordance_rate, 3),
        "n": len(checked),
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


# ── Summary + Output ──────────────────────────────────────────────────────────

def print_summary(repeatability: dict, anchor_cal: dict, concordance: dict, drift: dict):
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
        print(f"  Sign concordance: {concordance['concordance_rate']:.1%} ({concordance['n']} tickers)")
        disagree = [c for c in concordance.get("tickers", []) if not c["agree"]]
        if disagree:
            print(f"  Disagreements ({len(disagree)}):")
            for c in disagree[:10]:
                print(f"    {c['ticker']}: beta={c['rate_beta']:+.3f}, LLM rate_sensitivity={c['rate_sensitivity']}")

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


def _count_fails(repeatability, anchor_cal, concordance, drift) -> tuple[int, int, int]:
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

    # Concordance: < 60% = warn
    if not concordance.get("skipped"):
        if concordance["concordance_rate"] < 0.6:
            warns += 1
        else:
            passes += 1

    # Drift: each flag = warn
    if not drift.get("skipped"):
        warns += len(drift.get("drift_flags", []))
        passes += drift.get("stable_count", 0)

    return fails, warns, passes


def main():
    import macro_context
    print("Loading macro context (frozen for validation)...")
    macro = macro_context.fetch()

    try:
        import portfolio_ai as pai
        holdings = pai._load_holdings_csv()
        tickers = list({pai._normalize_ticker(h.get("Stock", "")) for h in holdings if h.get("Stock")})[:8]
    except Exception:
        tickers = []

    print(f"\n1. Repeatability test ({len(tickers)} holdings, N={REPEATS})...")
    repeatability = run_repeatability(tickers, macro) if tickers else {}

    print("\n2. Anchor calibration...")
    anchor_cal = run_anchor_calibration(macro)

    print("\n3. Factor vs LLM concordance...")
    concordance = run_concordance(tickers)

    print("\n4. Drift detection...")
    drift = run_drift_detection()

    print_summary(repeatability, anchor_cal, concordance, drift)

    fails, warns, passes = _count_fails(repeatability, anchor_cal, concordance, drift)
    summary_status = "FAIL" if fails > 0 else ("WARN" if warns > 0 else "PASS")

    output = {
        "run_at":           time.strftime("%Y-%m-%d %H:%M:%S"),
        "repeats":          REPEATS,
        "repeatability":    repeatability,
        "anchor_calibration": anchor_cal,
        "concordance":      concordance,
        "drift":            drift,
        "summary": {
            "status": summary_status,
            "fail":   fails,
            "warn":   warns,
            "pass":   passes,
        },
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nResults written to {OUT_PATH}")
    print(f"Summary: {summary_status} — {fails} fail, {warns} warn, {passes} pass")

    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
