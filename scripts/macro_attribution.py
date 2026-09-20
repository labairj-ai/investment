#!/usr/bin/env python3
"""
Macro Attribution Analysis (0495/0496).

Run after ≥60 resolved ACCEPTED decision episodes have macro_snapshot data.
Analysis only — no model changes, no ranking changes, no weight updates.

Usage:
  venv/bin/python scripts/macro_attribution.py
  venv/bin/python scripts/macro_attribution.py --horizon 1m --include-pre-acceptance --debug
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"
OUT_DIR = PROJECT_DIR / "out"
MIN_EPISODES = 10   # minimum to produce any output; 60 recommended for meaningful analysis


MIN_DIM_USABLE = 20  # episodes needed per dim for formal attribution
MIN_SUBGROUP_N = 10  # minimum divergence subgroup size to emit a win rate


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Macro Attribution Analysis")
    p.add_argument("--horizon", default="3m",
                   help="Outcome horizon to analyse (default: 3m). Options: 1w, 1m, 3m, 6m, 12m")
    p.add_argument("--include-pre-acceptance", action="store_true",
                   help="Include PRE_ACCEPTANCE episodes (diagnostic use only)")
    p.add_argument("--include-legacy", action="store_true",
                   help="Include pre-v2 schema episodes (diagnostic only; these lack per-dim usability fields)")
    p.add_argument("--show-all-dims", action="store_true",
                   help="Include all dims in formal tables (incl. geopolitical_risk)")
    p.add_argument("--debug", action="store_true",
                   help="Print SQL errors with full traceback")
    return p.parse_args()


def load_episodes_with_macro(horizon: str = "3m",
                              include_pre_acceptance: bool = False,
                              include_legacy: bool = False,
                              debug: bool = False) -> list[dict]:
    if not DB_PATH.exists():
        print(f"[Attribution] ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    # Check what columns are available in episode_outcomes
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        outcome_cols = {row[1] for row in conn.execute("PRAGMA table_info(episode_outcomes)").fetchall()}
    except Exception as e:
        print(f"[Attribution] ERROR: Cannot read DB schema: {e}", file=sys.stderr)
        if debug:
            import traceback; traceback.print_exc()
        sys.exit(1)

    # Build SELECT for optional MFE/MAE columns
    mfe_sel = ", o.mfe" if "mfe" in outcome_cols else ""
    mae_sel = ", o.mae" if "mae" in outcome_cols else ""

    # Fix 0496 bug #1: use o.alpha not o.outcome_alpha
    # Fix 0496 bug #2: filter to single horizon to avoid 5× fan-out
    query = f"""
        SELECT e.episode_id, e.ticker, o.alpha{mfe_sel}{mae_sel},
               e.macro_snapshot, e.captured_at
        FROM decision_episodes e
        JOIN episode_outcomes o ON e.episode_id = o.episode_id
        WHERE e.macro_snapshot IS NOT NULL
          AND o.alpha IS NOT NULL
          AND o.horizon = ?
    """
    try:
        rows = conn.execute(query, (horizon,)).fetchall()
    except Exception as qe:
        print(f"[Attribution] ERROR: Query failed: {qe}", file=sys.stderr)
        if debug:
            import traceback; traceback.print_exc()
        conn.close()
        sys.exit(1)

    conn.close()

    total_loaded = 0
    episodes = []
    for row in rows:
        total_loaded += 1
        try:
            snap = json.loads(row["macro_snapshot"])
        except Exception:
            snap = {}
        if not snap.get("macro_supported"):
            continue
        ep = {
            "episode_id":  row["episode_id"],
            "ticker":      row["ticker"],
            "alpha":       float(row["alpha"]),
            "macro":       snap,
            "captured_at": row["captured_at"],
        }
        if "mfe" in outcome_cols and row["mfe"] is not None:
            ep["mfe"] = float(row["mfe"])
        if "mae" in outcome_cols and row["mae"] is not None:
            ep["mae"] = float(row["mae"])
        episodes.append(ep)

    # 0497: filter to ACCEPTED only by default
    pre_acceptance_count = 0
    if not include_pre_acceptance:
        accepted = [e for e in episodes
                    if e["macro"].get("macro_validation_status") == "ACCEPTED"]
        pre_acceptance_count = len(episodes) - len(accepted)
        if pre_acceptance_count > 0:
            print(f"[Attribution] Excluded {pre_acceptance_count} PRE_ACCEPTANCE episodes "
                  f"(use --include-pre-acceptance for diagnostics)")
        episodes = accepted

    # 0513/0518: schema gate — only v2/v3 scores carry per-dim usability fields.
    # v3 standardises evidence_quality vocab (full/partial/none). Legacy scores have
    # get(key, True) semantics and must not enter formal attribution.
    # Use --include-legacy for diagnostic viewing of pre-v2 episodes.
    legacy_count = 0
    if not include_legacy:
        current = [e for e in episodes if e["macro"].get("schema_version") in {"v2", "v3"}]
        legacy_count = len(episodes) - len(current)
        if legacy_count > 0:
            print(f"[Attribution] Excluded {legacy_count} pre-v2 schema episodes "
                  f"(use --include-legacy for diagnostics)")
        episodes = current

    return episodes, total_loaded, pre_acceptance_count


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return round(s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2, 4)


def _iqr(vals: list[float]) -> float | None:
    if len(vals) < 4:
        return None
    s = sorted(vals)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    return round(q3 - q1, 4)


def _extract_dim_score(val) -> int | None:
    """Extract scalar 1-10 from dict {score, ...} or bare int. Handles legacy and new formats."""
    if isinstance(val, dict):
        v = val.get("score")
    elif isinstance(val, (int, float)):
        v = val
    else:
        return None
    try:
        return max(1, min(10, int(v)))
    except (TypeError, ValueError):
        return None


def _filter_by_dim_usability(episodes: list[dict], dim_key: str) -> list[dict]:
    """Gate 2: filter to episodes where this dimension is explicitly marked usable_for_attribution.
    Requires explicit True — missing key or False both exclude the episode (0513 fail-closed).
    Geo (geopolitical_risk) attribution requires confidence='high' + source_date ≤18 months old
    in company_geo_profile — currently all seeds are confidence='medium' so geo remains disabled
    until at least one ticker is re-sourced with confidence='high' (0522)."""
    key = f"{dim_key}_usable_for_attribution"
    return [e for e in episodes if e["macro"].get(key) is True]


def _coverage_summary(episodes: list[dict]) -> dict:
    """Count episodes by coverage_state."""
    counts: dict[str, int] = {}
    for e in episodes:
        state = e["macro"].get("coverage_state", "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


def _cohort_date(episode):
    from datetime import datetime
    value = episode.get("captured_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _rate_interaction_sign(episode: dict):
    """Return 'positive', 'negative', or None for missing/malformed rate_interaction (0532).
    Used for both observed grouping and bootstrap draws to ensure the same population
    is used in both places. None means the episode is excluded from that analysis.
    """
    v = episode.get("macro", {}).get("rate_interaction")
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    import math
    if not math.isfinite(fv):
        return None
    return "positive" if fv > 0 else "negative"


def analyse(episodes: list[dict], horizon: str, show_all_dims: bool = False) -> dict:
    n = len(episodes)
    if n < MIN_EPISODES:
        print(f"Only {n} supported ACCEPTED episodes at horizon={horizon} — "
              f"need ≥{MIN_EPISODES} for output, ≥60 for meaningful analysis.")
        return {"status": "insufficient_data", "n": n, "min_required": MIN_EPISODES,
                "horizon": horizon}

    if n < 60:
        print(f"WARNING: {n} episodes is below the recommended minimum of 60. "
              f"Treat results as exploratory.")

    has_mfe = any("mfe" in e for e in episodes)
    has_mae = any("mae" in e for e in episodes)

    def bucket_stats(bucket: list[dict]) -> dict:
        alphas = [e["alpha"] for e in bucket]
        s: dict = {
            "n": len(bucket),
            "mean_alpha": _mean(alphas),
            "median_alpha": _median(alphas),
            "iqr_alpha": _iqr(alphas),
        }
        if has_mfe:
            mfes = [e["mfe"] for e in bucket if "mfe" in e]
            s["mean_mfe"] = _mean(mfes)
            s["median_mfe"] = _median(mfes)
        if has_mae:
            maes = [e["mae"] for e in bucket if "mae" in e]
            s["mean_mae"] = _mean(maes)
            s["median_mae"] = _median(maes)
        return s

    # 0509: per-dim usability filter + scalar extraction (handles both dict and legacy int scores)
    def split_buckets(field: str, dim_episodes: list[dict]) -> tuple[list, list, int]:
        high, low, unknown = [], [], 0
        for e in dim_episodes:
            v = _extract_dim_score(e["macro"].get(field))
            if v is None:
                unknown += 1
                continue
            if v >= 7:
                high.append(e)
            elif v <= 3:
                low.append(e)
        return high, low, unknown

    def _dim_analysis(dim_key: str) -> dict:
        """Per-dim Gate 2 filter + bucket analysis with N reporting."""
        usable = _filter_by_dim_usability(episodes, dim_key)
        excluded = len(episodes) - len(usable)
        if len(usable) < MIN_DIM_USABLE:
            return {
                "status": "insufficient_data",
                "n_usable": len(usable),
                "n_excluded_by_usability": excluded,
                "min_required": MIN_DIM_USABLE,
                "note": f"Dimension {dim_key} has <{MIN_DIM_USABLE} usable episodes — excluded from formal attribution.",
            }
        h, l, unk = split_buckets(dim_key, usable)
        return {
            "status": "ok",
            "n_usable": len(usable),
            "n_excluded_by_usability": excluded,
            "high_7plus":  bucket_stats(h),
            "low_3minus":  bucket_stats(l),
            "n_unknown":   unk,
        }

    dims_to_analyse = ["rate_sensitivity", "dollar_sensitivity", "inflation_hedge"]
    if show_all_dims:
        dims_to_analyse.append("geopolitical_risk")

    bucket_analysis = {d: _dim_analysis(d) for d in dims_to_analyse}

    # Beta confidence vs outcome
    strong_beta = [e for e in episodes if e["macro"].get("rate_beta_confidence") == "stronger"]
    weak_beta   = [e for e in episodes if e["macro"].get("rate_beta_confidence")
                   in ("weak", "insufficient_data")]
    beta_analysis = {
        "stronger_confidence": bucket_stats(strong_beta),
        "weak_confidence":     bucket_stats(weak_beta),
    }

    # Evidence quality vs outcome
    full_ev    = [e for e in episodes if e["macro"].get("evidence_quality") == "full"]
    partial_ev = [e for e in episodes if e["macro"].get("evidence_quality") == "partial"]
    evidence_analysis = {
        "full_evidence":    bucket_stats(full_ev),
        "partial_evidence": bucket_stats(partial_ev),
    }

    # Signed interaction analysis (0501, 0528): exploratory — uses all ACCEPTED v2/v3 episodes,
    # not gated per-dim since rate_interaction is a composite field. Labeled exploratory so
    # downstream consumers know not to use it as formal attribution evidence.
    def _signed_interaction_analysis() -> dict:
        pos, neg, missing = [], [], 0
        for e in episodes:
            sign = _rate_interaction_sign(e)
            if sign is None:
                missing += 1
            elif sign == "positive":
                pos.append(e)
            else:
                neg.append(e)
        if missing == len(episodes):
            return {"exploratory": True, "status": "no_data",
                    "note": "rate_interaction field absent from all episodes"}
        return {
            "exploratory": True,
            "status": "ok",
            "positive_interaction": bucket_stats(pos),
            "negative_interaction": bucket_stats(neg),
            "n_missing_field": missing,
            "note": "Exploratory. rate_interaction > 0 = macro tailwind for rate-sensitive stocks; < 0 = headwind. Not gated on formal dim usability.",
        }

    # Cohort-blocked bootstrap CI (0501, 0528): 95% CI around the positive-vs-negative
    # rate_interaction alpha CONTRAST, not the overall mean. CI excluding zero = meaningful evidence.
    def _cohort_bootstrap_ci(n_boot: int = 1000) -> dict:
        import random
        eligible = [e for e in episodes if _cohort_date(e) is not None
                    and _rate_interaction_sign(e) is not None]
        if len(eligible) < 60:
            return {
                "status": "insufficient_data",
                "n": len(eligible),
                "note": f"Need ≥60 ACCEPTED episodes for cohort bootstrap; have {len(eligible)}.",
            }
        # Partition by rate_interaction sign using shared helper (0532: same population for
        # observed contrast and bootstrap draws)
        pos_eps, neg_eps = [], []
        for e in eligible:
            sign = _rate_interaction_sign(e)
            if sign == "positive":
                pos_eps.append(e)
            elif sign == "negative":
                neg_eps.append(e)
        MIN_GROUP = 10
        if len(pos_eps) < MIN_GROUP or len(neg_eps) < MIN_GROUP:
            return {
                "status": "insufficient_contrast_data",
                "n_positive": len(pos_eps),
                "n_negative": len(neg_eps),
                "min_required_per_group": MIN_GROUP,
                "note": "Both groups need ≥10 episodes for a meaningful contrast CI.",
            }
        # 0532: exclude episodes without a parseable captured_at from cohort bootstrap
        cohort_map: dict[str, list] = {}
        for e in eligible:
            ca = _cohort_date(e)
            if ca is None:
                continue  # exclude; not binned into an empty-string pseudo-cohort
            cohort_map.setdefault(ca, []).append(e)
        cohort_list = list(cohort_map.values())
        n_cohorts = len(cohort_list)
        if n_cohorts < 5:
            return {
                "status": "insufficient_cohorts",
                "n_cohorts": n_cohorts,
                "note": "Need ≥5 distinct decision-date cohorts for cohort bootstrap.",
            }
        # Bootstrap: resample cohorts, compute contrast using _rate_interaction_sign (0532)
        boot_contrasts = []
        rng = random.Random(42)
        for _ in range(n_boot):
            sample_cohorts = rng.choices(cohort_list, k=n_cohorts)
            all_eps = [ep for c in sample_cohorts for ep in c]
            b_pos = [e["alpha"] for e in all_eps if _rate_interaction_sign(e) == "positive"]
            b_neg = [e["alpha"] for e in all_eps if _rate_interaction_sign(e) == "negative"]
            if b_pos and b_neg:
                boot_contrasts.append(sum(b_pos) / len(b_pos) - sum(b_neg) / len(b_neg))
        if len(boot_contrasts) < n_boot * 0.5:
            return {"status": "error", "note": "Too few valid bootstrap samples"}
        boot_contrasts.sort()
        k = len(boot_contrasts)
        lo = boot_contrasts[int(0.025 * k)]
        hi = boot_contrasts[int(0.975 * k)]
        observed_contrast = round(
            _mean([e["alpha"] for e in pos_eps]) - _mean([e["alpha"] for e in neg_eps]), 4
        ) if pos_eps and neg_eps else None
        return {
            "status": "ok",
            "n_cohorts": n_cohorts,
            "n_boot": k,
            "n_positive_episodes": len(pos_eps),
            "n_negative_episodes": len(neg_eps),
            "observed_contrast": observed_contrast,
            "contrast_ci_95_lo": round(lo, 4),
            "contrast_ci_95_hi": round(hi, 4),
            "ci_excludes_zero": lo > 0 or hi < 0,
            "note": "Cohort-blocked 95% CI around (pos_rate_interaction alpha − neg_rate_interaction alpha). CI excluding zero = meaningful evidence of rate_interaction effect.",
        }

    # MFE/MAE by stress group (0501, 0528): exploratory diagnostic — labeled as such.
    def _stress_mfe_mae() -> dict:
        if not (has_mfe or has_mae):
            return {"exploratory": True, "status": "no_mfe_mae_data"}
        # 0532: renamed from high_stress/low_stress — grouping is by rate sensitivity score,
        # not by a macro stress composite; the label was misleading.
        high_rate_sens = [e for e in episodes
                          if _extract_dim_score(e["macro"].get("rate_sensitivity")) is not None
                          and (_extract_dim_score(e["macro"].get("rate_sensitivity")) or 0) >= 7]
        low_rate_sens  = [e for e in episodes
                          if _extract_dim_score(e["macro"].get("rate_sensitivity")) is not None
                          and (_extract_dim_score(e["macro"].get("rate_sensitivity")) or 10) <= 3]
        result: dict = {
            "exploratory": True,
            "note": "Exploratory. high_rate_sensitivity = rate_sensitivity score ≥7; low_rate_sensitivity ≤3. Not gated on formal dim usability.",
        }
        if has_mae:
            result["high_rate_sensitivity_mean_mae"]   = _mean([e["mae"] for e in high_rate_sens if "mae" in e])
            result["low_rate_sensitivity_mean_mae"]    = _mean([e["mae"] for e in low_rate_sens  if "mae" in e])
            result["high_rate_sensitivity_median_mae"] = _median([e["mae"] for e in high_rate_sens if "mae" in e])
            result["low_rate_sensitivity_median_mae"]  = _median([e["mae"] for e in low_rate_sens  if "mae" in e])
        if has_mfe:
            result["high_rate_sensitivity_mean_mfe"] = _mean([e["mfe"] for e in high_rate_sens if "mfe" in e])
            result["low_rate_sensitivity_mean_mfe"]  = _mean([e["mfe"] for e in low_rate_sens  if "mfe" in e])
        result["n_high_rate_sensitivity"] = len(high_rate_sens)
        result["n_low_rate_sensitivity"]  = len(low_rate_sens)
        return result

    # Divergence analysis (0502): when base and challenger diverge, are macro conditions
    # associated with which one wins? Purely descriptive — no weight changes.
    def _divergence_analysis() -> dict:
        divergent = [
            e for e in episodes
            if e["macro"].get("challenger_recommendation") is not None
            and e["macro"].get("base_recommendation") is not None
            and e["macro"].get("challenger_recommendation") != e["macro"].get("base_recommendation")
        ]
        MIN_DIVERGENT = 30
        if len(divergent) < MIN_DIVERGENT:
            return {
                "status": "insufficient_data",
                "n_divergent": len(divergent),
                "min_required": MIN_DIVERGENT,
                "note": f"Need ≥{MIN_DIVERGENT} divergent ACCEPTED episodes with 3m outcomes; have {len(divergent)}.",
            }
        # Challenger win = challenger alpha > base alpha (use episode alpha as proxy if individual not stored)
        # If per-agent alpha not available, skip win-rate analysis
        can_compare = any(
            e["macro"].get("challenger_alpha") is not None and e["macro"].get("base_alpha") is not None
            for e in divergent
        )
        if not can_compare:
            return {
                "status": "no_per_agent_alpha",
                "n_divergent": len(divergent),
                "note": "challenger_alpha / base_alpha not stored in macro_snapshot — cannot compute win rates.",
            }

        def _outcome(e: dict):
            """Return 'win', 'loss', 'tie', or None for undecidable (0532: explicit tie state)."""
            ca = e["macro"].get("challenger_alpha")
            ba = e["macro"].get("base_alpha")
            if ca is None or ba is None:
                return None
            try:
                ca_f, ba_f = float(ca), float(ba)
            except (TypeError, ValueError):
                return None
            import math
            if not math.isfinite(ca_f) or not math.isfinite(ba_f):
                return None
            if ca_f > ba_f:
                return "win"
            if ca_f < ba_f:
                return "loss"
            return "tie"

        def _regime_win_rate(subset: list) -> dict:
            """Win/loss/tie counts; suppresses win_rate when n < MIN_SUBGROUP_N (0532)."""
            if len(subset) < MIN_SUBGROUP_N:
                return {"n": len(subset), "suppressed": True,
                        "note": f"n < {MIN_SUBGROUP_N} — win rate not reported"}
            outcomes = [_outcome(e) for e in subset]
            decided  = [o for o in outcomes if o is not None]
            if len(decided) < MIN_SUBGROUP_N:
                return {"n": len(decided), "suppressed": True,
                        "note": f"n < {MIN_SUBGROUP_N} — win rate not reported"}
            wins   = sum(1 for o in decided if o == "win")
            losses = sum(1 for o in decided if o == "loss")
            ties   = sum(1 for o in decided if o == "tie")
            return {
                "n": len(decided),
                "wins": wins, "losses": losses, "ties": ties,
                "challenger_win_rate": round(wins / len(decided), 4),
            }

        # 0532: use _rate_interaction_sign for consistent grouping
        pos_regime   = [e for e in divergent if _rate_interaction_sign(e) == "positive"]
        neg_regime   = [e for e in divergent if _rate_interaction_sign(e) == "negative"]
        concordant   = [e for e in divergent if e["macro"].get("concordance_ok") is True]
        discordant   = [e for e in divergent if e["macro"].get("concordance_ok") is False]

        return {
            "status": "ok",
            "n_divergent": len(divergent),
            "regime_group_win_rates": {
                "positive_rate_interaction": _regime_win_rate(pos_regime),
                "negative_rate_interaction": _regime_win_rate(neg_regime),
            },
            "concordance_group_win_rates": {
                "concordant_beta_llm": _regime_win_rate(concordant),
                "discordant_beta_llm": _regime_win_rate(discordant),
            },
            "note": (
                "Descriptive only. challenger_win_rate = fraction of divergent episodes "
                "where challenger alpha > base alpha. Ties reported separately. "
                f"Subgroups with n < {MIN_SUBGROUP_N} suppressed. No model weights changed."
            ),
        }

    return {
        "status":            "ok",
        "n":                 n,
        "horizon":           horizon,
        "bucket_analysis":   bucket_analysis,
        "beta_confidence_analysis": beta_analysis,
        "evidence_quality_analysis": evidence_analysis,
        "signed_interaction_analysis": _signed_interaction_analysis(),
        "cohort_bootstrap_ci": _cohort_bootstrap_ci(),
        "stress_mfe_mae": _stress_mfe_mae(),
        "divergence_analysis": _divergence_analysis(),
        "coverage_by_state": _coverage_summary(episodes),
        "note": (
            "Exploratory only — no ranking, weight, or model changes. "
            "Minimum 60 ACCEPTED episodes recommended. "
            "Medians and IQR reported alongside means for robustness. "
            "Cohort-blocked bootstrap CI guards against date-cohort inflation."
        ),
    }


if __name__ == "__main__":
    args = _parse_args()
    print(f"=== Macro Attribution Analysis (horizon={args.horizon}) ===")
    print(f"DB: {DB_PATH}")

    episodes, total_rows, pre_accept = load_episodes_with_macro(
        horizon=args.horizon,
        include_pre_acceptance=args.include_pre_acceptance,
        include_legacy=args.include_legacy,
        debug=args.debug,
    )
    print(f"Loaded {len(episodes)} resolved supported ACCEPTED episodes "
          f"from {total_rows} total outcome rows at horizon={args.horizon}")

    # Coverage report first
    cov = _coverage_summary(episodes)
    if cov:
        print("\nCoverage by state:")
        for state, count in sorted(cov.items()):
            print(f"  {state}: {count}")

    results = analyse(episodes, args.horizon, show_all_dims=args.show_all_dims)
    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "horizon":      args.horizon,
        "analysis":     results,
    }
    print(json.dumps(results, indent=2))

    OUT_DIR.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_file = OUT_DIR / f"macro_attribution_{ts}.json"
    out_file.write_text(json.dumps(output, indent=2))
    print(f"\nWritten to {out_file}")
