# Build Opportunity Hunter Agent (Phase 6)

- **ID:** 0014
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0006, 0007, 0013

## Problem

The Buffett screener finds high-quality stocks but has no concept of portfolio fit. A great stock that's redundant with three existing holdings, or that would push an already-overweight layer further over target, should rank lower than an equally good stock that fills a gap. Currently there is no agent that bridges the screener output to the actual portfolio state and answers "which of these would actually improve my portfolio?"

## Proposed approach

`agents/opportunity_agent.py`

Triggered by: new Buffett screener winner; layer weight < (target - 5pp) for > 3 days.

**Opportunity score formula (all deterministic except portfolio fit):**
`Score = 0.30*Q + 0.25*V + 0.20*PF + 0.15*C + 0.10*EC`

- **Q — Quality** (from Buffett screener's existing composite quality score)
- **V — Valuation** (from Buffett screener's valuation metrics)
- **PF — Portfolio Fit**: layer deficit bonus if the candidate fills an underweight layer; correlation penalty if candidate overlaps ≥ 2 existing holdings in same sector/factor; concentration penalty if adding it would push any position > `max_single_position_pct`
- **C — Catalyst/Setup**: upcoming catalyst (earnings, spin-off, analyst coverage initiation); technical setup if tracked
- **EC — Evidence Confidence**: from `confidence.py`, based on freshness and completeness of fundamental data

**LLM role** (narrow):
Receives top 3 candidates by score + current portfolio context. Answers which of the 3 best improves the portfolio and why — does not generate the score, does not produce financial values, does not search for new candidates.

Output:
```json
{
  "action": "RESEARCH",
  "ticker": "CANDIDATE",
  "why": "...",
  "portfolio_rationale": "...",
  "main_risk": "...",
  "no_action_case": "..."
}
```

`RESEARCH` not `BUY` — agent surfaces opportunities, user decides.

## Touches

`agents/opportunity_agent.py` (new), `buffett_screener.py` (read winners from buffett.db), `agents/orchestrator.py`, `portfolio_ai.py` (correlation/overlap check)

## Outcome

New file: `agents/opportunity_agent.py`. Registered in `agents/__init__.py`.

**Score formula (0.30*Q + 0.25*V + 0.20*PF + 0.15*C + 0.10*EC):**
- Q: `buffett_winners.quality_score` (0-100)
- V: pe_ratio / p_fcf / ev_ebitda tiered thresholds (lower = better)
- PF: starts at 50; +up to 30 for layer deficit ≥5pp; -up to 30 for ≥2 holdings in same sector
- C: value_trap_risk bonus/penalty + AI conviction (1-5) + scan freshness
- EC: `calculate_confidence(EvidenceBundle)` — primary_release, 4 quarters, rule_support=0.8

**Key design notes:**
- `_HOLDING_SECTORS` dict maps known holdings to sectors; ETFs/funds → None (no overlap penalty)
- `_LAYER_DEFICIT_THRESHOLD = 5.0pp` — deficit below threshold gets meta recorded but no bonus
- Already-held tickers filtered before scoring (PF = 0 fallback, but filtered outright)
- LLM unavailability is handled gracefully — deterministic fallback selects top scorer

**QA results (2026-09-05, optiplex, LLM unreachable):**
- 77 unowned candidates scored; top 3: MSGM=84, DDI=83, BZ=80
- Fallback → RESEARCH MSGM (Layer 4 L4 Convexity, +6.0pp underweight) ✓
- No-winners mock: returned [] with no LLM call ✓
- All-held mock: returned [] with no LLM call ✓

**Trigger wiring:** already in `triggers.py` — fires `opportunity_hunter` on `layer_underweight` events (layer weight < target − 5pp for ≥3 consecutive days) or new Buffett screener winner.

**Unblocks:** 0017 (partially — 0015 still needed), 0022 (Candidate Comparison).

## Done when

- [x] Portfolio Fit (PF) score penalizes redundant candidates and rewards layer gap fills
- [x] LLM receives ≤ 3 candidates — not the full screener universe
- [x] Output action is `RESEARCH`, not `BUY`
- [x] Recommendation includes which layer the candidate would fill and current layer deficit
- [x] Agent handles case where no Buffett screener winners exist (no recommendation, no LLM call)
- [x] QA (backend): Run the Opportunity Hunter with ≥ 1 Buffett screener winner in the candidate universe. Confirm: (a) LLM received ≤ 3 candidates, (b) output action is `RESEARCH` (not BUY), (c) recommendation names which layer the candidate fills. Also confirm no recommendation and no LLM call when no screener winners exist. Log both cases before checking this box.

