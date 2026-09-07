from __future__ import annotations
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

_PROMPT_VERSION = "covered_call_v1"

_CC_ELIGIBLE_LAYERS = {1, 2, 3}
_CC_MIN_SHARES = 100


def _has_open_cc(ticker: str) -> bool:
    """Return True if an open covered call position exists for this ticker.
    Checks both the raw ticker and the dot→dash normalized form (BRK.B ↔ BRK-B).
    """
    alt = ticker.replace(".", "-") if "." in ticker else ticker.replace("-", ".")
    try:
        conn = sqlite3.connect(str(_DB), timeout=5)
        row = conn.execute(
            "SELECT 1 FROM cc_positions WHERE ticker IN (?,?) AND status='open' LIMIT 1",
            (ticker, alt),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def _get_open_cc_position(ticker: str) -> dict | None:
    """Return the most recent open cc_positions row for ticker, with DTE added."""
    from datetime import date as _date
    alt = ticker.replace(".", "-") if "." in ticker else ticker.replace("-", ".")
    try:
        conn = sqlite3.connect(str(_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM cc_positions WHERE ticker IN (?,?) AND status='open' "
            "ORDER BY id DESC LIMIT 1",
            (ticker, alt),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        pos = dict(row)
        try:
            exp = _date.fromisoformat(pos["expiry"])
            pos["dte"] = (exp - _date.today()).days
        except Exception:
            pos["dte"] = 0
        return pos
    except Exception:
        return None


_MGMT_SYSTEM = """You are an investment analyst writing rationale for a covered call management decision.
The action has already been determined by a rule-based engine. Your role is to explain
why this action is correct using the specific metrics provided. Do NOT override the action.

Return JSON with these exact fields:
  why          : 2-3 sentences explaining why this action is appropriate, citing key metrics
  counter_case : 1-2 sentences on what could go wrong or argue against this action
"""

_MGMT_SCHEMA = {"why": "", "counter_case": ""}


_CC_POLICY_DEFAULTS: dict = {
    "strategy":           "INCOME",   # INCOME | UPSIDE_PRESERVATION | NONE
    "max_preferred_delta": 0.30,
    "minimum_otm_pct":     0.03,       # fraction, e.g. 0.03 = 3% OTM
    "avoid_earnings":      False,
    "preferred_dte_min":   None,
    "preferred_dte_max":   None,
}


def _get_cc_policy(ticker: str) -> dict:
    """Return cc_policy dict for ticker, merged with defaults."""
    import json as _json
    try:
        conn = sqlite3.connect(str(_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT cc_policy FROM investment_theses "
            "WHERE ticker=? AND status='active' ORDER BY version DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        conn.close()
        if row and row["cc_policy"]:
            stored = _json.loads(row["cc_policy"])
            return {**_CC_POLICY_DEFAULTS, **stored}
    except Exception:
        pass
    return dict(_CC_POLICY_DEFAULTS)


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


def _decide_mgmt_action(
    *,
    current_price: float,
    strike: float,
    dte: int,
    pct_captured: float | None,
    has_avoid: bool,
    delta: float | None,
) -> str:
    """Deterministic 6-way CC management decision. Priority order is intentional."""
    is_itm     = current_price >= strike
    near_money = current_price >= strike * 0.97
    deeply_itm = current_price >= strike * 1.05
    cap        = pct_captured or 0.0

    if has_avoid:
        return "ROLL_OUT"          # earnings/risk event — must extend past it
    if deeply_itm and dte <= 14:
        return "ALLOW_ASSIGNMENT"  # profitable exit, stock called away cleanly
    if cap >= 80:
        return "BUY_TO_CLOSE"      # negligible extrinsic left, lock in profit
    if dte <= 7 and not is_itm:
        return "HOLD_CALL"         # expires worthless in days, cost to close not worth it
    if is_itm or near_money:
        return "ROLL_UP_AND_OUT"   # near/at/above strike — defensive roll needed
    if delta is not None and delta >= 0.30:
        return "ROLL_UP"           # delta elevated, raise strike at same expiry
    return "HOLD_CALL"             # well OTM, let theta work


def _analyze_roll(ctx: AgentContext, ticker: str, position: dict) -> list[Recommendation]:
    """Management engine for existing CC positions triggered by cc_mgmt_dte."""
    snapshot = ctx.snapshot
    holding = next((h for h in snapshot.holdings if h.ticker == ticker), None)
    if holding is None:
        print(f"[covered_call] {ticker}: not in snapshot, cannot manage")
        return []

    existing_strike  = float(position["strike"])
    existing_expiry  = position["expiry"]
    existing_premium = float(position["premium_per_contract"])
    stored_mark      = float(position.get("current_mark") or 0.0)
    contracts        = int(position["contracts"])

    print(f"[covered_call] {ticker}: mgmt — strike={existing_strike} exp={existing_expiry}")

    import covered_call_rec
    try:
        eval_result = covered_call_rec.evaluate_open_position(
            ticker=ticker,
            strike=existing_strike,
            expiry=existing_expiry,
            original_premium=existing_premium,
            current_mark=stored_mark,
        )
    except Exception as e:
        print(f"[covered_call] {ticker}: evaluate_open_position failed: {e}")
        return []

    current_price = eval_result["current_price"]
    current_mark  = eval_result["current_mark"] if eval_result["current_mark"] is not None else stored_mark
    dte           = eval_result["dte"]
    pct_captured  = eval_result["pct_captured"]
    has_avoid     = eval_result["has_avoid"]
    delta         = eval_result["delta"]
    risk_events   = eval_result["risk_events"]
    remaining_ext = eval_result.get("remaining_extrinsic")
    pnl           = round((existing_premium - current_mark) * contracts * 100, 2)

    action = _decide_mgmt_action(
        current_price=current_price,
        strike=existing_strike,
        dte=dte,
        pct_captured=pct_captured,
        has_avoid=has_avoid,
        delta=delta,
    )

    avoid_labels = [e["label"] for e in risk_events if e["severity"] == "avoid"]
    metrics_lines = [
        f"Ticker: {ticker}  Shares: {holding.shares:.0f}  Avg cost: ${holding.avg_cost:.2f}",
        f"Position: strike=${existing_strike:.2f}  expiry={existing_expiry}  DTE={dte}",
        f"Original premium: ${existing_premium:.2f}/share  Current mark: ${current_mark:.2f}/share",
        f"P&L to date: ${pnl:+.2f} total  Premium captured: {f'{pct_captured:.0f}%' if pct_captured is not None else 'N/A'}",
        f"Current price: ${current_price:.2f}  Delta: {f'{delta:.3f}' if delta is not None else 'N/A'}",
        f"Remaining extrinsic: ${remaining_ext:.2f}" if remaining_ext is not None else "Remaining extrinsic: N/A",
    ]
    if avoid_labels:
        metrics_lines.append(f"Risk events: {'; '.join(avoid_labels)}")
    metrics_summary = "\n".join(metrics_lines)

    prompt = (
        f"{_MGMT_SYSTEM}\n\n"
        f"Determined action: {action}\n\n"
        f"{metrics_summary}\n\n"
        "Explain why this action is correct given these metrics. Return JSON."
    )

    why = f"Rule engine selected {action}: {eval_result.get('reason', '')}"
    counter_case = "Monitor position for adverse price moves before acting."
    try:
        llm_out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_MGMT_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=600,
            thinking=False,
            retries=2,
        )
        if llm_out and isinstance(llm_out, dict):
            why          = llm_out.get("why", why)
            counter_case = llm_out.get("counter_case", counter_case)
    except Exception as e:
        print(f"[covered_call] {ticker}: mgmt LLM rationale failed: {e} — using rule reason")

    financial_line = (
        f"{action}: {ticker} ${existing_strike:.2f} exp {existing_expiry} ({dte} DTE). "
        f"P&L: ${pnl:+.2f}. "
        f"Premium captured: {f'{pct_captured:.0f}%' if pct_captured is not None else 'N/A'}. "
        f"Current price: ${current_price:.2f}."
    )
    why_now = financial_line + " " + why

    if action == "ROLL_OUT" and has_avoid:
        priority = "urgent"
    elif action in ("ALLOW_ASSIGNMENT", "BUY_TO_CLOSE", "ROLL_UP_AND_OUT") and dte <= 14:
        priority = "high"
    elif action == "HOLD_CALL":
        priority = "low"
    else:
        priority = "normal"

    rec_scores = {
        "HOLD_CALL": 40, "BUY_TO_CLOSE": 70, "ROLL_OUT": 65,
        "ROLL_UP": 55, "ROLL_UP_AND_OUT": 60, "ALLOW_ASSIGNMENT": 60,
    }

    action_payload = {
        "mgmt_action":       action,
        "decision_reason":   eval_result.get("reason", ""),
        "existing_strike":   existing_strike,
        "existing_expiry":   existing_expiry,
        "existing_dte":      dte,
        "existing_premium":  existing_premium,
        "current_mark":      current_mark,
        "current_price":     current_price,
        "pct_captured":      pct_captured,
        "pnl":               pnl,
        "contracts":         contracts,
        "has_avoid":         has_avoid,
        "delta":             delta,
        "remaining_extrinsic": remaining_ext,
    }

    rec = Recommendation(
        ticker=ticker,
        action=action,
        recommendation_score=rec_scores.get(action, 50),
        confidence=70 if delta is not None else 55,
        priority=priority,
        why_now=why_now,
        rationale=why,
        counter_case=counter_case,
        no_action_case=(
            "Allow position to run to expiry and reassess at that time."
            if action == "HOLD_CALL" else
            f"Instead of {action}, hold the position and reassess closer to expiration."
        ),
        action_payload=action_payload,
        dependencies=[{
            "dependency_type": "PRICE",
            "dependency_key": ticker,
            "original_value": current_price,
            "tolerance": 0.03,
            "invalidating_event": "PRICE_THRESHOLD",
        }],
    )
    print(f"[covered_call] {ticker}: mgmt → {action} (DTE={dte}, captured={pct_captured}%)")
    return [rec]


def _analyze_ticker(ctx: AgentContext, ticker: str) -> list[Recommendation]:
    """Full pipeline for one ticker. Returns 0 or 1 Recommendation."""
    snapshot = ctx.snapshot
    holding = next((h for h in snapshot.holdings if h.ticker == ticker), None)
    if holding is None:
        print(f"[covered_call] {ticker}: not found in snapshot — skipping")
        return []

    policy = _get_cc_policy(ticker)

    if policy["strategy"] == "NONE":
        print(f"[covered_call] {ticker}: thesis cc_policy=NONE — CC writing not permitted")
        return []

    if _has_open_cc(ticker):
        position = _get_open_cc_position(ticker)
        if position is None:
            print(f"[covered_call] {ticker}: open CC exists but position unreadable — skipping")
            return []
        return _analyze_roll(ctx, ticker, position)

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

    # Policy: avoid_earnings — veto entire ticker if any AVOID event risk
    current_price_for_otm = holding.current_price or holding.avg_cost
    if policy["avoid_earnings"]:
        floor_passing_all = recs_df[recs_df["passes_floor"]]
        if not floor_passing_all.empty and floor_passing_all["has_avoid"].any():
            print(f"[covered_call] {ticker}: VETOED by policy avoid_earnings — AVOID event present")
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

    # Apply per-thesis policy filters to narrow the candidate universe
    policy_filtered = recs_df.copy()
    max_delta = policy["max_preferred_delta"]
    if max_delta is not None:
        policy_filtered = policy_filtered[policy_filtered["delta"] <= max_delta]
    min_otm = policy["minimum_otm_pct"]
    if min_otm is not None and current_price_for_otm > 0:
        min_strike = current_price_for_otm * (1 + min_otm)
        policy_filtered = policy_filtered[policy_filtered["strike"] >= min_strike]
    if not policy_filtered.empty:
        recs_df = policy_filtered
        print(f"[covered_call] {ticker}: policy={policy['strategy']} "
              f"delta<={max_delta} OTM>={min_otm*100:.0f}% → "
              f"{len(recs_df)} contract(s) remain")
    else:
        print(f"[covered_call] {ticker}: policy filters left 0 contracts — "
              f"falling back to unfiltered universe")

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

    # Financial summary — prepended to why_now so it appears first in the card
    contracts   = action_payload["contracts"]
    ep          = action_payload["exec_premium"]
    cur_price   = action_payload["current_price"] or holding.avg_cost
    dte         = action_payload["dte"]
    total_income   = round(ep * contracts * 100, 2)
    breakeven      = round(cur_price - ep, 2)
    annual_pct     = round((ep / cur_price) * (365 / dte) * 100, 1) if cur_price and dte else 0
    financial_line = (
        f"Income: ${total_income:,.0f} ({contracts} contract{'s' if contracts != 1 else ''} "
        f"× ${ep:.2f} premium). Break-even: ${breakeven:.2f}. "
        f"Annualized: {annual_pct:.1f}%."
    )
    why = financial_line + " " + why

    # Rough recommendation score: anchor at 50, boost by cc_alpha magnitude
    cc_alpha = action_payload["cc_alpha"]
    rec_score = min(100, max(0, round(50 + cc_alpha * 1000)))
    priority = "high" if data_mode == "live" and cc_alpha > 0.002 else "normal"

    import json as _json
    price_dep = {
        "dependency_type": "PRICE",
        "dependency_key": ticker,
        "original_value": holding.current_price,
        "tolerance": 0.02,
        "invalidating_event": "PRICE_THRESHOLD",
    }
    deps = [price_dep]
    macro_scores = (ctx.snapshot.macro_scores or {}).get(ticker)
    if macro_scores:
        deps.append({
            "dependency_type": "MACRO_STATE",
            "dependency_key": ticker,
            "original_value": _json.dumps({
                k: v for k, v in macro_scores.items()
                if isinstance(v, (int, float))
            }),
            "tolerance": 15.0,
            "invalidating_event": "MACRO_SHIFT",
        })
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
        dependencies=deps,
    )
    print(f"[covered_call] {ticker}: SELL_CC {contract_id} "
          f"confidence={confidence} score={rec_score}")
    return [rec]


def run_covered_call_agent(ctx: AgentContext) -> list[Recommendation]:
    recommendations: list[Recommendation] = []

    if ctx.trigger_events:
        for event in ctx.trigger_events:
            if not event.ticker:
                continue
            if event.trigger_type == "cc_mgmt_dte":
                position = _get_open_cc_position(event.ticker)
                if position:
                    recommendations.extend(_analyze_roll(ctx, event.ticker, position))
                else:
                    print(f"[covered_call] {event.ticker}: cc_mgmt_dte but no open position found, skipping roll")
            else:
                recommendations.extend(_analyze_ticker(ctx, event.ticker))
    elif ctx.ticker:
        recommendations.extend(_analyze_ticker(ctx, ctx.ticker))
    else:
        # Fallback: scan all eligible holdings (shouldn't normally be needed
        # since trigger engine fires per holding)
        for h in ctx.snapshot.holdings:
            if h.layer in _CC_ELIGIBLE_LAYERS and h.shares >= _CC_MIN_SHARES:
                recommendations.extend(_analyze_ticker(ctx, h.ticker))

    return recommendations


register_agent("covered_call", run_covered_call_agent)
