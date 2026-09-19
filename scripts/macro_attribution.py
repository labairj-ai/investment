#!/usr/bin/env python3
"""
Macro Attribution Analysis (0495).

Run after ≥60 resolved decision episodes have macro_snapshot data (from 0494).
Analysis only — no model changes, no ranking changes, no weight updates.

Usage: venv/bin/python scripts/macro_attribution.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"
OUT_DIR = PROJECT_DIR / "out"
MIN_EPISODES = 10   # minimum to produce any output; 60 recommended for meaningful analysis


def load_episodes_with_macro() -> list[dict]:
    if not DB_PATH.exists():
        print("No DB found.")
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("""
                SELECT e.episode_id, e.ticker, o.outcome_alpha,
                       e.macro_snapshot, e.captured_at
                FROM decision_episodes e
                JOIN episode_outcomes o ON e.episode_id = o.episode_id
                WHERE e.macro_snapshot IS NOT NULL
                  AND o.outcome_alpha IS NOT NULL
            """).fetchall()
        except Exception as qe:
            print(f"Query failed: {qe}")
            conn.close()
            return []
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")
        return []

    episodes = []
    for row in rows:
        try:
            snap = json.loads(row["macro_snapshot"])
        except Exception:
            snap = {}
        if snap.get("macro_supported"):
            episodes.append({
                "episode_id": row["episode_id"],
                "ticker":     row["ticker"],
                "alpha":      float(row["outcome_alpha"]),
                "macro":      snap,
                "captured_at": row["captured_at"],
            })
    return episodes


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def analyse(episodes: list[dict]) -> dict:
    n = len(episodes)
    if n < MIN_EPISODES:
        print(f"Only {n} supported episodes — need ≥{MIN_EPISODES} for output, ≥60 for meaningful analysis.")
        return {"status": "insufficient_data", "n": n, "min_required": MIN_EPISODES}

    if n < 60:
        print(f"WARNING: {n} episodes is below the recommended minimum of 60. Treat results as exploratory.")

    # 1. Rate sensitivity bucket analysis
    high_rate  = [e for e in episodes if (e["macro"].get("rate_sensitivity") or 0) >= 7]
    low_rate   = [e for e in episodes if (e["macro"].get("rate_sensitivity") or 0) <= 3]
    high_dollar = [e for e in episodes if (e["macro"].get("dollar_sensitivity") or 0) >= 7]
    low_dollar  = [e for e in episodes if (e["macro"].get("dollar_sensitivity") or 0) <= 3]
    high_hedge  = [e for e in episodes if (e["macro"].get("inflation_hedge") or 0) >= 7]
    low_hedge   = [e for e in episodes if (e["macro"].get("inflation_hedge") or 0) <= 3]

    bucket_analysis = {
        "rate_sensitivity": {
            "high_7plus": {"n": len(high_rate),   "mean_alpha": _mean([e["alpha"] for e in high_rate])},
            "low_3minus": {"n": len(low_rate),    "mean_alpha": _mean([e["alpha"] for e in low_rate])},
        },
        "dollar_sensitivity": {
            "high_7plus": {"n": len(high_dollar), "mean_alpha": _mean([e["alpha"] for e in high_dollar])},
            "low_3minus": {"n": len(low_dollar),  "mean_alpha": _mean([e["alpha"] for e in low_dollar])},
        },
        "inflation_hedge": {
            "high_7plus": {"n": len(high_hedge),  "mean_alpha": _mean([e["alpha"] for e in high_hedge])},
            "low_3minus": {"n": len(low_hedge),   "mean_alpha": _mean([e["alpha"] for e in low_hedge])},
        },
    }

    # 2. Beta confidence vs outcome
    strong_beta  = [e for e in episodes if e["macro"].get("rate_beta_confidence") == "stronger"]
    weak_beta    = [e for e in episodes if e["macro"].get("rate_beta_confidence") in ("weak", "insufficient_data")]
    beta_analysis = {
        "stronger_confidence": {"n": len(strong_beta), "mean_alpha": _mean([e["alpha"] for e in strong_beta])},
        "weak_confidence":     {"n": len(weak_beta),   "mean_alpha": _mean([e["alpha"] for e in weak_beta])},
    }

    # 3. Evidence quality vs outcome
    full_ev    = [e for e in episodes if e["macro"].get("evidence_quality") == "full"]
    partial_ev = [e for e in episodes if e["macro"].get("evidence_quality") == "partial"]
    evidence_analysis = {
        "full_evidence":    {"n": len(full_ev),    "mean_alpha": _mean([e["alpha"] for e in full_ev])},
        "partial_evidence": {"n": len(partial_ev), "mean_alpha": _mean([e["alpha"] for e in partial_ev])},
    }

    return {
        "status":            "ok",
        "n":                 n,
        "bucket_analysis":   bucket_analysis,
        "beta_confidence_analysis": beta_analysis,
        "evidence_quality_analysis": evidence_analysis,
        "note": (
            "Exploratory only — no ranking, weight, or model changes. "
            "Minimum 60 episodes recommended for meaningful analysis. "
            "Simple conditional means; no significance testing."
        ),
    }


if __name__ == "__main__":
    print("=== Macro Attribution Analysis ===")
    print(f"DB: {DB_PATH}")
    episodes = load_episodes_with_macro()
    print(f"Loaded {len(episodes)} resolved supported episodes")

    results = analyse(episodes)
    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "analysis":     results,
    }
    print(json.dumps(results, indent=2))

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_file = OUT_DIR / f"macro_attribution_{ts}.json"
    out_file.write_text(json.dumps(output, indent=2))
    print(f"\nWritten to {out_file}")
