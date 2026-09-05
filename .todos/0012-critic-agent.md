# Build Critic Agent (Phase 4)

- **ID:** 0012
- **Status:** backlog
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

- [ ] All 5 deterministic vetoes implemented and tested
- [ ] LLM Critic produces all 4 verdict types with bounded `confidence_adjustment`
- [ ] CHALLENGE verdict caps final confidence at 60
- [ ] VETO from either deterministic or LLM path suppresses recommendation from Decision Queue
- [ ] `critic_reviews` row written for every recommendation that reaches the Critic
- [ ] Critic's `strongest_objection` is surfaced in the Decision Queue UI card
