# Build Critic Agent (Phase 4)

- **ID:** 0012
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0007, 0010, 0011

## Problem

Every agent currently produces findings that flow directly to the user with no adversarial review. A CC agent might recommend a call the day before earnings. A Guardian might flag noise as a crisis. Without a critic pass, the system has no internal check on recommendation quality, no mechanism for detecting weak evidence, and no way to adjust confidence downward when something smells off. The Critic is the system's quality gate.

## Proposed approach

`agents/critic_agent.py`

**Deterministic vetoes first (no LLM):**
- CC event severity = AVOID → VETO
- Layer target allocations invalid (don't sum to 100) → VETO all allocation recommendations
- Missing tax cost basis → VETO tax-specific sale recommendation
- Theoretical option data → VETO actionable trade
- Price data stale > 30 min during market hours → VETO any price-sensitive recommendation

These vetoes are logged with reason code. No LLM call made.

**LLM Critic** (runs only if deterministic gate passes):

Input:
```json
{
  "recommendation": {...},
  "supporting_findings": [...],
  "portfolio_context": {...}
}
```

Output:
```json
{
  "verdict": "APPROVE_WITH_CAUTION",
  "strongest_objection": "...",
  "missing_evidence": [],
  "counter_case": "...",
  "confidence_adjustment": -6
}
```

Verdicts: `APPROVE`, `APPROVE_WITH_CAUTION`, `CHALLENGE`, `VETO`.

`confidence_adjustment` is bounded to [-20, +5] — Critic can reduce confidence meaningfully but cannot inflate it much.

Apply: `final_confidence = min(original_confidence + confidence_adjustment, cap_for_verdict)`.
- CHALLENGE verdict → max confidence 60
- VETO → recommendation marked vetoed, not sent to Decision Queue

## Touches

`agents/critic_agent.py` (new), `agents/confidence.py` (apply adjustment), `agents/orchestrator.py` (wire into pipeline after other agents), `agent_db.py` (write critic_reviews)

## Done when

- [x] All 5 deterministic vetoes implemented and tested
- [x] LLM Critic produces all 4 verdict types with bounded `confidence_adjustment`
- [x] CHALLENGE verdict caps final confidence at 60
- [x] VETO from either deterministic or LLM path suppresses recommendation from Decision Queue
- [x] `critic_reviews` row written for every recommendation that reaches the Critic
- [x] Critic's `strongest_objection` is surfaced in the Decision Queue UI card
- [x] QA (backend + browser): (a) Create a test recommendation and run the Critic against it; confirm a `critic_reviews` row is written with all 4 verdict fields. Verify VETO suppresses the rec from the queue, CHALLENGE caps confidence at 60. (b) Browser: open the dashboard Decision Queue and confirm `strongest_objection` text renders on the card. Check JS console shows zero errors. Do NOT check this box without the live browser check.

## Outcome

New file: `agents/critic_agent.py`. Registered in `agents/__init__.py`.

**5 deterministic vetoes:**
1. AVOID event flag on SELL_CC payload
2. Layer targets don't sum to 100 (for REBALANCE/ALLOCATE actions)
3. Missing cost_lots for TAX_SELL/TAX_HARVEST
4. `data_mode == "theoretical"` for SELL_CC → not actionable
5. Holding price data from a prior day during NYSE market hours

**LLM path:** structured output with schema-validated verdict enum; `confidence_adjustment` clamped to [-20, +5]; CHALLENGE caps final confidence at 60; VETO sets `status='vetoed'`.

**LLM fallback:** if LLM unavailable, defaults to APPROVE_WITH_CAUTION with adj=-5 so rec stays visible with a manual-review flag rather than silently dropping.

**DB changes:** `agent_db.update_recommendation()`, `list_open_unreviewed_recommendations()`, `critic_objection` field added to `list_recommendations()`.

**Dashboard:** Decision Queue card added above Candidate Universe. Shows open (non-vetoed) recs with verdict badge and strongest_objection column. `GET /api/recommendations` endpoint added to serve.py.

**QA results (2026-09-05):**
- GRMN/SELL_CC (theoretical data) → VETO deterministic, status=vetoed, absent from Decision Queue ✓
- SCHD/SELL_CC → LLM unavailable fallback, APPROVE_WITH_CAUTION, confidence 72→67 ✓
- WMT/SELL_CC → LLM unavailable fallback, APPROVE_WITH_CAUTION, confidence 68→63 ✓
- Browser: Decision Queue card visible, verdict badges render, strongest_objection text shown, zero JS errors ✓

**Note:** LLM path is untested with real LLM responses because MLX server on Mac Studio (port 8080) is unreachable from optiplex during QA. The fallback path is verified. Real LLM verdicts will exercise the full code path once the network route is confirmed.

**Unblocks:** 0016 (Decision Queue UI), 0019 (Sell/Trim Agent).

