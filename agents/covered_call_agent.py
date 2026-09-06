"""Covered Call Agent — proactively scans CC-eligible holdings and surfaces best contracts.

Triggered by:
  cc_eligible  — holding ≥ 100 shares, layers 1-3, no open CC
  cc_mgmt_dte  — existing CC approaching DTE management window

Flow:
  1. Check DB for open CC → skip if one already exists (cc_eligible path only)
  2. Call covered_call_rec.analyze() — all contract math is done in Python
  3. AVOID-level event risk contracts are filtered deterministically before LLM
  4. LLM receives contract IDs + pre-computed scores; outputs only contract_id + rationale
  5. Python resolves contract_id → actual financial values; builds Recommendation
"""
import sqlite3
from pathlib import Path

import agent_db
import ollama_client
from .confidence import calculate_confidence
from .contracts import AgentContext, EvidenceBundle, Recommendation
from .orchestrator import register_agent

_DB = Path(__file__).resolve().parent.parent / "out" / "investment.db"

_SYSTEM = """You are an investment analyst evaluating covered call opportunities.
You receive pre-computed contract metrics. Select the best contract and explain the
key trade-offs. Do NOT invent or modify any financial numbers — all values come from
the provided table.

Return JSON with these exact fields:
  action        : "SELL_CC" or "NO_CALL"
  contract_id   : the exact contract ID string (null if action is NO_CALL)
  why           : 2-3 sentences referencing specific metrics from the table
  main_tradeoff : 1-2 sentences on the key risk/reward trade-off
  no_call_case  : 1-2 sentences on why NOT selling may be the right choice
"""

_SCHEMA = {
    "action": "SELL_CC",
    "contract_id": "TICKER:YYYYMMDD:STRIKE",
    "why": "",
    "main_tradeoff": "",
    "no_call_case": "",
}

_CC_ELIGIBLE_LAYERS = {1, 2, 3}
_CC_MIN_SHARES = 100


def _has_open_cc(ticker: str) -> bool:
    """Return True if an open covered call position exists for this ticker."""
    try:
        conn = sqlite3.connect(str(_DB), timeout=5)
        row = conn.execute(
            "SELECT 1 FROM cc_positions WHERE ticker=? AND status='open' LIMIT 1",
            (ticker,),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _make_contract_id(ticker: str, expiration: str, strike: float) -> str:
    """Build a stable contract ID: TICKER:YYYYMMDD:STRIKE."""
    date_part = expiration.replace("-", "")  # "2026-10-16" → "20261016"
    strike_str = str(int(strike)) if strike == int(strike) else str(strike)
    return f"{ticker}:{date_part}:{strike_str}"


def _build_candidates(ticker: str, recs_df) -> tuple[list[dict], dict[str, dict]]:
    """Filter to AVOID-free, floor-passing contracts; return top-5 by score.

    Returns (candidates_list, id_to_row_dict).
    """
    eligible = recs_df[recs_df["passes_floor"] & ~recs_df["has_avoid"]].copy()
    if eligible.empty:
        return [], {}

    eligible = eligible.sort_values("score", ascending=False).head(5)

    candidates: list[dict] = []
    id_to_row: dict[str, dict] = {}
    for _, row in eligible.iterrows():
        cid = _make_contract_id(ticker, str(row["expiration"]), float(row["strike"]))
        id_to_row[cid] = row.to_dict()
        candidates.append({
            "id": cid,
            "expiration": row["expiration"],
            "dte": int(row["dte"]),
            "strike": float(row["strike"]),
            "exec_premium": round(float(row["exec_premium"]), 2),
            "cc_alpha": round(float(row["cc_alpha"]), 4),
            "cc_alpha_pct": round(float(row.get("cc_alpha_pct", 0)), 2),
            "regret_prob": round(float(row["regret_prob"]), 3),
            "delta": round(float(row["delta"]), 3),
            "iv_richness": round(float(row["iv_richness"]), 3),
            "liquidity_score": round(float(row["liquidity_score"]), 3),
            "score": round(float(row["score"]), 2),
            "has_caution": bool(row.get("has_caution", False)),
        })
    return candidates, id_to_row


def _build_evidence(result: dict, candidates: list[dict]) -> EvidenceBundle:
    data_mode = result.get("data_mode", "theoretical")
    hv_rank = result.get("hv_rank")

    signals: list[str] = []
    if hv_rank is not None and hv_rank >= 50:
        signals.append("sell")
    if candidates:
        best = candidates[0]
        if best.get("cc_alpha", 0) > 0:
            signals.append("sell")
        if best.get("iv_richness", 0) > 0.05:
            signals.append("sell")

    best_liquidity = candidates[0].get("liquidity_score", 0) if candidates else 0

    return EvidenceBundle(
        has_price=True,
        has_event_calendar=True,
        has_cost_basis=True,
        has_strategy_metadata=True,
        option_quote_age_min=5.0 if data_mode == "live" else None,
        market_quote_age_min=5.0,
        source_quality="primary_release" if data_mode == "live" else "secondary_commentary",
        signal_directions=signals,
        recommendation_direction="sell",
        rule_support=0.8 if data_mode == "live" else 0.5,
        has_live_option_quote=(data_mode == "live"),
        option_liquidity_good=(data_mode == "live" and best_liquidity >= 0.7),
        uses_ask_proxy=(data_mode == "ask_proxy"),
        uses_theoretical_pricing=(data_mode == "theoretical"),
    )


def _analyze_ticker(ctx: AgentContext, ticker: str) -> list[Recommendation]:
    """Full pipeline for one ticker. Returns 0 or 1 Recommendation."""
    snapshot = ctx.snapshot
    holding = next((h for h in snapshot.holdings if h.ticker == ticker), None)
    if holding is None:
        print(f"[covered_call] {ticker}: not found in snapshot — skipping")
        return []

    if ctx.trigger_type == "cc_eligible" and _has_open_cc(ticker):
        print(f"[covered_call] {ticker}: open CC exists — skipping")
        return []

    print(f"[covered_call] Analyzing {ticker} "
          f"({holding.shares:.0f} shares @ avg ${holding.avg_cost:.2f})")

    import covered_call_rec
    result = covered_call_rec.analyze(ticker, holding.avg_cost, holding.shares)
    if result is None:
        print(f"[covered_call] {ticker}: analyze() returned None")
        return []

    recs_df = result.get("recs")
    if recs_df is None or recs_df.empty:
        print(f"[covered_call] {ticker}: no contracts from analyze()")
        return []

    # Deterministic AVOID gate — veto entire ticker if all floor-passing contracts are AVOID
    floor_passing = recs_df[recs_df["passes_floor"]]
    if not floor_passing.empty and floor_passing["has_avoid"].all():
        print(f"[covered_call] {ticker}: VETOED — all floor-passing contracts carry AVOID event risk")
        agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="cc_avoid_veto",
            ticker=ticker,
            summary=(f"{ticker}: all {len(floor_passing)} floor-passing contracts blocked by "
                     "AVOID-level event risk — CC writing vetoed for this cycle"),
            severity=60,
            confidence=90,
        )
        return []

    candidates, id_to_row = _build_candidates(ticker, recs_df)
    if not candidates:
        print(f"[covered_call] {ticker}: no eligible contracts after AVOID filter")
        return []

    # Build vol context for LLM prompt
    data_mode = result.get("data_mode", "theoretical")
    hv_rank = result.get("hv_rank")
    atm_iv = result.get("atm_iv")
    vm = result.get("vol_model", {})
    hv20 = vm.get("hv20")

    vol_lines: list[str] = []
    if atm_iv is not None and hv20:
        vol_lines.append(f"ATM IV: {atm_iv:.1f}%  HV20: {hv20*100:.1f}%  "
                         f"IV/HV ratio: {atm_iv/(hv20*100):.2f}x")
    elif atm_iv is not None:
        vol_lines.append(f"ATM IV: {atm_iv:.1f}%")
    if hv_rank is not None:
        vol_lines.append(f"HV rank: {hv_rank:.0f}th percentile (1-year range)")
    vol_ctx = "  ".join(vol_lines) if vol_lines else "(no vol data)"

    contract_lines = "\n".join(
        f"  {c['id']}: DTE={c['dte']}, strike=${c['strike']:.2f}, "
        f"premium=${c['exec_premium']:.2f}, cc_alpha={c['cc_alpha']:.4f}, "
        f"regret_prob={c['regret_prob']:.1%}, delta={c['delta']:.3f}, "
        f"iv_richness={c['iv_richness']:.3f}, score={c['score']:.2f}"
        + (" [CAUTION event]" if c["has_caution"] else "")
        for c in candidates
    )

    prompt = (
        f"{_SYSTEM}\n\n"
        f"Ticker: {ticker}\n"
        f"Shares: {holding.shares:.0f}  Avg cost: ${holding.avg_cost:.2f}  "
        f"Layer: {holding.layer}  Data mode: {data_mode}\n"
        f"Volatility: {vol_ctx}\n\n"
        f"Eligible contracts (AVOID contracts already removed, sorted by score):\n"
        f"{contract_lines}\n\n"
        "Select the best contract ID, or recommend NO_CALL if premium environment "
        "doesn't justify writing. Return JSON matching the schema exactly."
    )

    try:
        llm_out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=800,
            thinking=False,
            retries=2,
        )
    except Exception as e:
        print(f"[covered_call] {ticker}: LLM call failed: {e}")
        return []

    if not llm_out or not isinstance(llm_out, dict):
        print(f"[covered_call] {ticker}: LLM returned invalid output")
        return []

    action = llm_out.get("action", "NO_CALL")
    contract_id = llm_out.get("contract_id")
    why = llm_out.get("why", "")
    main_tradeoff = llm_out.get("main_tradeoff", "")
    no_call_case = llm_out.get("no_call_case", "")

    if action == "NO_CALL" or not contract_id:
        print(f"[covered_call] {ticker}: LLM recommends NO_CALL")
        agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="cc_no_call",
            ticker=ticker,
            summary=f"{ticker}: CC analysis complete — LLM recommends not writing: {why}",
            severity=20,
            confidence=60,
        )
        return []

    row = id_to_row.get(contract_id)
    if row is None:
        print(f"[covered_call] {ticker}: LLM selected unknown contract_id={contract_id!r}")
        return []

    evidence = _build_evidence(result, candidates)
    confidence = calculate_confidence(evidence)

    action_payload = {
        "contract_id": contract_id,
        "expiration": row["expiration"],
        "strike": float(row["strike"]),
        "exec_premium": round(float(row["exec_premium"]), 2),
        "cc_alpha": round(float(row["cc_alpha"]), 4),
        "cc_alpha_pct": round(float(row.get("cc_alpha_pct", 0)), 2),
        "regret_prob": round(float(row["regret_prob"]), 3),
        "delta": round(float(row["delta"]), 3),
        "dte": int(row["dte"]),
        "shares": int(holding.shares),
        "contracts": int(holding.shares // 100),
        "avg_cost": holding.avg_cost,
        "current_price": holding.current_price,
        "data_mode": data_mode,
        "hv_rank": hv_rank,
        "atm_iv": atm_iv,
        "has_caution": bool(row.get("has_caution", False)),
        "liquidity_score": round(float(row.get("liquidity_score", 0)), 3),
        "iv_richness": round(float(row.get("iv_richness", 0)), 3),
        "score": round(float(row["score"]), 2),
        "candidates_evaluated": len(candidates),
    }

    # Rough recommendation score: anchor at 50, boost by cc_alpha magnitude
    cc_alpha = action_payload["cc_alpha"]
    rec_score = min(100, max(0, round(50 + cc_alpha * 1000)))
    priority = "high" if data_mode == "live" and cc_alpha > 0.002 else "normal"

    price_dep = {
        "dependency_type": "PRICE",
        "dependency_key": ticker,
        "original_value": holding.current_price,
        "tolerance": 0.02,
        "invalidating_event": "PRICE_THRESHOLD",
    }
    rec = Recommendation(
        ticker=ticker,
        action="SELL_CC",
        recommendation_score=rec_score,
        confidence=confidence,
        priority=priority,
        why_now=why,
        rationale=main_tradeoff,
        counter_case=no_call_case,
        no_action_case=no_call_case,
        action_payload=action_payload,
        dependencies=[price_dep],
    )
    print(f"[covered_call] {ticker}: SELL_CC {contract_id} "
          f"confidence={confidence} score={rec_score}")
    return [rec]


def run_covered_call_agent(ctx: AgentContext) -> list[Recommendation]:
    recommendations: list[Recommendation] = []

    if ctx.ticker:
        recommendations.extend(_analyze_ticker(ctx, ctx.ticker))
    else:
        # Fallback: scan all eligible holdings (shouldn't normally be needed
        # since trigger engine fires per holding)
        for h in ctx.snapshot.holdings:
            if h.layer in _CC_ELIGIBLE_LAYERS and h.shares >= _CC_MIN_SHARES:
                recommendations.extend(_analyze_ticker(ctx, h.ticker))

    return recommendations


register_agent("covered_call", run_covered_call_agent)
