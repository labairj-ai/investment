# Conduct Agent-by-Agent Investment Logic Audit

- **ID:** 0137
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

The investment agent system's software architecture is assessed as ~97% complete — plumbing, execution lifecycle, outcome infrastructure, and test coverage have all substantially caught up. The remaining high-value work is scrutinizing the economic correctness of each agent's signal logic: whether the inputs, scoring heuristics, thresholds, and recommendation criteria actually reflect sound investment reasoning, not just working code. No systematic audit of agent-level logic has been done; issues found so far (e.g., CC management MTM baseline) were discovered incidentally rather than by deliberate review.

## Proposed approach

Conduct one focused audit per agent in priority order, reading each agent's full signal-construction and recommendation logic and producing concrete backlog findings:

1. **Covered Call agent** (`agents/covered_call_agent.py`, `covered_call_rec.py`) — most sophisticated math and most subtle path-dependent economics; audit cc_alpha formula, regret_prob scoring, candidate filtering thresholds, and LLM prompt framing.
2. **Sell/Trim agent** — TRIM evaluator math now confirmed correct; focus on signal quality: what triggers a trim recommendation, position-size logic, concentration thresholds.
3. **Thesis agent** — claim verification logic: how thesis claims are validated, staleness thresholds, claim confidence scoring.
4. **Portfolio Guardian agent** — drift/rebalance logic: layer targets, drift tolerance bands, rebalancing trigger conditions.
5. **Opportunity agent** — entry criteria and candidate ranking: scoring formula, valuation gate, catalyst requirements.
6. **Tax agent** — loss harvesting logic: lot selection, wash-sale avoidance, harvest threshold vs. transaction cost.

Each audit session: read the agent end-to-end, compare logic against investing first principles, produce 1–N new backlog items for any economic-correctness gaps found. This todo tracks the meta-work; each audit's findings become their own todos.

## Touches

- `agents/covered_call_agent.py`, `covered_call_rec.py` (first audit)
- `agents/` (subsequent audits)
- `.todos/` (each audit produces new backlog items here)

## Done when

- [x] Covered Call agent audit complete and all findings captured as backlog items (0138, 0139)
- [x] Sell/Trim agent audit complete and findings captured (0141 done; 0142-0145 created)
- [x] Thesis agent audit complete and findings captured (0146 HIGH: ADD rec valuation gate; 0147: TRIM importance-weighted gate)
- [x] Portfolio Guardian agent audit complete and findings captured (0148: sector cache)
- [x] Opportunity agent audit complete and findings captured (0149: sector hardcode + min composite gate)
- [x] Tax agent audit complete and findings captured (0150 HIGH: LT loss/LT gain harvest gap)
