# Add Recommendation Lineage (Chain of Agent Reasoning Over Time)

- **ID:** 0029
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** low
- **Depends:** 0025, 0016

## Problem

Recommendations are currently independent records. When an ANET HOLD from September is superseded by a REVIEW in October and then a TRIM in November, there is no visible connection between them. The user cannot see how the agent's reasoning evolved, cannot audit why a position's assessment changed, and cannot spot patterns like "the agent has been escalating concern about ANET for 8 weeks." Lineage turns isolated data points into a narrative.

## Proposed approach

**Lineage links:** add two columns to the `recommendations` table (migration):
- `supersedes_id` — FK to the recommendation this one replaced (nullable)
- `lineage_root_id` — FK to the first recommendation in the chain for this ticker+agent_type

On each new recommendation for a ticker:
1. Find the most recent recommendation for the same ticker + agent_type
2. If found: set `supersedes_id = that recommendation's id`, `lineage_root_id = that recommendation's lineage_root_id` (or its own id if it's the root)
3. Mark the prior recommendation `status=superseded`

**Lineage timeline UI (per-ticker, in dashboard):**

Clicking a ticker in the Decision Queue or holdings table opens a lineage view:

```
ANET — Recommendation History

Sept 1    HOLD           Confidence 91   [Decision: HOLD ✓]
Sept 18   HOLD           Confidence 89   Superseded by price move
Oct 6     REVIEW         Confidence 87   Estimates declined
          └─ Thesis Claim #2 weakened
Nov 3     TRIM           Confidence 83   [Decision: Deferred]
          └─ Warning: valuation + concentration
Feb 7     EXIT           Confidence 79   [Decision: Rejected]
          └─ Critic: CHALLENGE
          └─ Thesis violation confirmed
```

Each entry shows: date, action, confidence, user decision (if any), primary reason, critic verdict.

**API:**
- `GET /api/agents/recommendations/{ticker}/lineage` — returns full chain for a ticker, ordered by created_at
- Response includes: all recommendations in chain, user decisions on each, supersession reasons

**Root cause analysis:** when a recommendation escalates from HOLD → REVIEW → TRIM over multiple runs, the lineage allows the system to compute: "This position has been in a declining trend for N weeks" — which can itself become a Trigger Engine input or influence the Sell Agent's SellStrength T-score.

## Touches

`recommendations` table (add `supersedes_id`, `lineage_root_id` columns — migration), `agent_db.py` (lineage linking logic on every recommendation insert), `serve.py` (`GET /api/agents/recommendations/{ticker}/lineage`), `generate_dashboard.py` (lineage timeline UI)

## Done when

- [ ] `supersedes_id` and `lineage_root_id` populated on all new recommendations
- [ ] Prior recommendation status set to `superseded` when a new one is created for same ticker+agent_type
- [ ] `GET /api/agents/recommendations/{ticker}/lineage` returns ordered chain
- [ ] Timeline UI renders per-ticker lineage with action, date, confidence, user decision, reason
- [ ] Escalating trend (≥ 3 recommendations showing increasing severity) detected and surfaced as a note on the current recommendation
