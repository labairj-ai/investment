"""Preference learner — infers soft preferences from user decision history.

Only accepted/rejected decisions are used (deferred = no signal yet).
Minimum _MIN_SAMPLE decisions required before any preference influences a recommendation.

Hard rules in strategy_config are NEVER modified here.  Learned preferences only
affect the Preference Fit display score on DQ cards; they do not touch
recommendation_score, confidence, or any evidence column.
"""
import json
import time

import agent_db

_HALF_LIFE_DAYS = 90.0
_MIN_SAMPLE = 5


def _decay_weight(decided_at: float, now: float) -> float:
    age_days = (now - decided_at) / 86400.0
    return 0.5 ** (age_days / _HALF_LIFE_DAYS)


def run_preference_learner() -> int:
    """Recalculate all soft preferences from decision history.

    Returns count of preference rows upserted.
    """
    conn = agent_db._connect()
    now = time.time()
    rows = conn.execute(
        """SELECT ud.decision, ud.decided_at,
                  r.action, r.recommendation_score, r.action_payload_json
           FROM user_decisions ud
           JOIN recommendations r ON r.id = ud.recommendation_id
           WHERE ud.decision IN ('accepted', 'rejected')
           ORDER BY ud.decided_at ASC"""
    ).fetchall()
    conn.close()

    decisions = [dict(r) for r in rows]
    by_action: dict[str, list[dict]] = {}
    for d in decisions:
        by_action.setdefault(d["action"], []).append(d)

    updated = 0

    # 1. Acceptance rate per action type (exponentially weighted by recency)
    for action, decs in by_action.items():
        w_accept = sum(_decay_weight(d["decided_at"], now) for d in decs if d["decision"] == "accepted")
        w_total  = sum(_decay_weight(d["decided_at"], now) for d in decs)
        rate = w_accept / w_total if w_total > 0 else 0.0
        n_accept = sum(1 for d in decs if d["decision"] == "accepted")
        agent_db.upsert_learned_preference(
            key=f"action_acceptance_rate.{action}",
            value=round(rate, 4),
            scope="global",
            sample_size=len(decs),
            evidence={"n_accepted": n_accept, "n_rejected": len(decs) - n_accept},
        )
        updated += 1

    # 2. CC-specific: preferred delta and DTE (from accepted SELL_CC payloads)
    cc_all = by_action.get("SELL_CC", [])
    cc_accepted = [d for d in cc_all if d["decision"] == "accepted"]
    if len(cc_all) >= _MIN_SAMPLE:
        deltas: list[tuple[float, float]] = []
        dtes:   list[tuple[float, float]] = []
        for d in cc_accepted:
            try:
                pl = json.loads(d["action_payload_json"] or "{}") or {}
                w = _decay_weight(d["decided_at"], now)
                if pl.get("delta") is not None:
                    deltas.append((float(pl["delta"]), w))
                if pl.get("dte") is not None:
                    dtes.append((float(pl["dte"]), w))
            except Exception:
                pass
        if deltas:
            tw = sum(w for _, w in deltas)
            preferred_delta = sum(v * w for v, w in deltas) / tw
            agent_db.upsert_learned_preference(
                "cc.preferred_delta", round(preferred_delta, 3), "global",
                len(deltas), {"source": "accepted_SELL_CC"},
            )
            updated += 1
        if dtes:
            tw = sum(w for _, w in dtes)
            preferred_dte = sum(v * w for v, w in dtes) / tw
            agent_db.upsert_learned_preference(
                "cc.preferred_dte", round(preferred_dte, 1), "global",
                len(dtes), {"source": "accepted_SELL_CC"},
            )
            updated += 1

    # 3. Sell score threshold — recency-weighted P25 of accepted TRIM/EXIT scores
    sell_decs = by_action.get("TRIM", []) + by_action.get("EXIT", [])
    sell_accepted = [d for d in sell_decs if d["decision"] == "accepted"]
    if len(sell_decs) >= _MIN_SAMPLE and sell_accepted:
        scores_with_w = [
            (d["recommendation_score"], _decay_weight(d["decided_at"], now))
            for d in sell_accepted
            if d["recommendation_score"] is not None
        ]
        if scores_with_w:
            if len(scores_with_w) < 5:
                threshold = float(min(s for s, _ in scores_with_w))
                method = "min_fallback"
            else:
                threshold = _weighted_percentile(scores_with_w, 0.25)
                method = "weighted_p25"
            agent_db.upsert_learned_preference(
                "sell.score_threshold", threshold, "global",
                len(sell_decs),
                {"method": method, "threshold": threshold, "n_accepted": len(sell_accepted)},
            )
            updated += 1

    # 4. CC: upside-preservation bias (fraction of accepted SELL_CC with delta < 0.20)
    if len(cc_all) >= _MIN_SAMPLE and cc_accepted:
        low_delta_w = 0.0
        total_cc_w = 0.0
        for d in cc_accepted:
            try:
                pl = json.loads(d["action_payload_json"] or "{}") or {}
                delta = pl.get("delta")
                if delta is not None:
                    w = _decay_weight(d["decided_at"], now)
                    total_cc_w += w
                    if float(delta) < 0.20:
                        low_delta_w += w
            except Exception:
                pass
        if total_cc_w > 0:
            bias = low_delta_w / total_cc_w
            agent_db.upsert_learned_preference(
                "cc.upside_preservation_bias", round(bias, 4), "global",
                len(cc_accepted),
                {"low_delta_fraction": round(bias, 4), "source": "accepted_SELL_CC_delta<0.20"},
            )
            updated += 1

    # 5. Valuation tolerance — average composite_score where TRIM was accepted vs rejected
    trim_decs = by_action.get("TRIM", [])
    if len(trim_decs) >= _MIN_SAMPLE:
        accepted_scores = []
        rejected_scores = []
        for d in trim_decs:
            try:
                pl = json.loads(d["action_payload_json"] or "{}") or {}
                score = pl.get("composite_score") or d["recommendation_score"]
                if score is not None:
                    if d["decision"] == "accepted":
                        accepted_scores.append(float(score))
                    else:
                        rejected_scores.append(float(score))
            except Exception:
                pass
        if accepted_scores:
            avg_accepted = sum(accepted_scores) / len(accepted_scores)
            avg_rejected = sum(rejected_scores) / len(rejected_scores) if rejected_scores else None
            agent_db.upsert_learned_preference(
                "sell.valuation_tolerance", round(avg_accepted, 2), "global",
                len(trim_decs),
                {
                    "avg_score_accepted_trim": round(avg_accepted, 2),
                    "avg_score_rejected_trim": round(avg_rejected, 2) if avg_rejected is not None else None,
                    "n_accepted": len(accepted_scores),
                    "n_rejected": len(rejected_scores),
                },
            )
            updated += 1

    print(f"[PrefLearner] updated {updated} preference(s) from {len(decisions)} decision(s)")
    return updated


def _weighted_percentile(
    values_weights: list[tuple[float, float]], percentile: float
) -> float:
    """Compute a weighted percentile via sorted interpolation."""
    if not values_weights:
        return 0.0
    sorted_vw = sorted(values_weights, key=lambda x: x[0])
    total_w = sum(w for _, w in sorted_vw)
    cumulative = 0.0
    target = percentile * total_w
    for i, (v, w) in enumerate(sorted_vw):
        cumulative += w
        if cumulative >= target:
            if i == 0:
                return float(v)
            prev_v = sorted_vw[i - 1][0]
            prev_cum = cumulative - w
            frac = (target - prev_cum) / w if w > 0 else 0.0
            return float(prev_v + frac * (v - prev_v))
    return float(sorted_vw[-1][0])
