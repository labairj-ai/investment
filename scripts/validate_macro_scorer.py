#!/usr/bin/env python3
"""
Macro scorer validation lab (0471).
Runs N repeated scoring passes on frozen inputs to measure repeatability,
tests anchor instruments against expected calibration ranges,
and writes results to out/macro_validation_results.json.
"""
import json
import math
import statistics
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

REPEATS = 5
OUT_PATH = PROJECT_DIR / "out" / "macro_validation_results.json"

# Anchor instruments: {ticker: {dim: (expected_min, expected_max)}}
ANCHORS = {
    "BIL": {
        "description": "T-bill/cash equivalent",
        "rate_sensitivity":   (1, 3),   # very low rate sensitivity
        "dollar_sensitivity": (1, 3),   # domestic, dollar-denominated
    },
    "VNQ": {
        "description": "REIT / long-duration bond-like",
        "rate_sensitivity":   (7, 10),  # high rate sensitivity
    },
}

STDEV_WARN_THRESHOLD = 1.0
DIMS = ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk")


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


def _score_one_ticker(ticker: str, macro: dict) -> dict | None:
    """Score a single ticker using the project's ollama client. Returns raw score dict or None."""
    try:
        import portfolio_ai as pai
        import ollama_client
        if not ollama_client.available():
            print(f"  [skip] Ollama not available for {ticker}")
            return None

        dim_defs = "\n".join(
            f"- {dim}: {meta['prompt_def']}"
            for dim, meta in pai.MACRO_DIMS.items()
        )
        prompt = f"""You are a quantitative analyst. Score the ticker's structural macro exposure on 4 dimensions from 1-10.

Scoring definitions (1=low exposure, 10=high exposure):
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


def run_repeatability(tickers: list, macro: dict) -> dict:
    """Score each ticker REPEATS times, compute mean/stddev per dimension."""
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
                    "mean": round(mean, 2),
                    "stdev": round(stdev, 3),
                    "n": len(vals),
                    "flag": flag,
                }
            elif len(vals) == 1:
                results[tk][dim] = {"mean": vals[0], "stdev": None, "n": 1, "flag": False}
            else:
                results[tk][dim] = {"mean": None, "stdev": None, "n": 0, "flag": False}
    return results


def run_anchor_calibration(macro: dict) -> dict:
    """Score anchor instruments and compare against expected ranges."""
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
                "actual": sv,
                "expected_range": [lo, hi],
                "pass": pass_cal,
            }
        results[ticker] = anchor_result
        time.sleep(8)
    return results


def print_summary(repeatability: dict, anchor_cal: dict):
    print("\n=== REPEATABILITY SUMMARY ===")
    print(f"{'Ticker':<12} {'Dimension':<22} {'Mean':>6} {'StDev':>6} {'N':>3} {'Status'}")
    print("-" * 60)
    for tk, dims in repeatability.items():
        for dim, r in dims.items():
            status = "FLAGGED" if r["flag"] else ("ok" if r["mean"] is not None else "no data")
            stdev_s = f"{r['stdev']:.3f}" if r["stdev"] is not None else "—"
            mean_s  = f"{r['mean']:.2f}" if r["mean"] is not None else "—"
            print(f"{tk:<12} {dim:<22} {mean_s:>6} {stdev_s:>6} {r['n']:>3}  {status}")

    print("\n=== ANCHOR CALIBRATION ===")
    for ticker, res in anchor_cal.items():
        print(f"\n{ticker} — {res['description']}")
        for dim, r in res["dims"].items():
            status = "PASS" if r["pass"] else "FAIL"
            print(f"  {dim}: actual={r['actual']}, expected={r['expected_range']} → {status}")


def main():
    import macro_context
    print("Loading macro context (frozen for validation)...")
    macro = macro_context.fetch()

    try:
        import portfolio_ai as pai
        holdings = pai._load_holdings_csv()
        tickers = list({pai._normalize_ticker(h.get("Stock", "")) for h in holdings if h.get("Stock")})[:10]
    except Exception:
        tickers = []

    all_tickers = tickers + list(ANCHORS.keys())

    print(f"\nRunning repeatability test on {len(tickers)} holdings ({REPEATS} repeats each)...")
    repeatability = run_repeatability(tickers, macro)

    print("\nRunning anchor calibration...")
    anchor_cal = run_anchor_calibration(macro)

    print_summary(repeatability, anchor_cal)

    output = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repeats": REPEATS,
        "repeatability": repeatability,
        "anchor_calibration": anchor_cal,
        "flags": {
            tk: [dim for dim, r in dims.items() if r.get("flag")]
            for tk, dims in repeatability.items()
        },
    }
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"\nResults written to {OUT_PATH}")

    flagged = sum(1 for dims in output["flags"].values() for _ in dims)
    anchor_fails = sum(
        1 for res in anchor_cal.values()
        for r in res["dims"].values() if not r["pass"]
    )
    if flagged or anchor_fails:
        print(f"\nWARNING: {flagged} repeatability flags, {anchor_fails} anchor calibration failures")
        sys.exit(1)
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
