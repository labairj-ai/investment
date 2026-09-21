# Score a Separate Macro Candidate Universe

- **ID:** 0559
- **Status:** backlog
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** 0558

## Problem

Macro scoring currently serves holdings while Opportunity Hunter selects unowned candidates. Candidate collection needs its own storage and operational ledger while sharing the accepted canonical scorer; generating scores alone must not confer experiment eligibility.

## Proposed approach

- Add macro_candidate_scores, macro_candidate_scoring_runs and macro_candidate_scoring_run_items, with immutable score history or linked snapshots sufficient for decision-time provenance.
- Reuse the canonical evidence adapter, request builder, model/sampling contract and response validator. Extract shared scoring machinery where needed; do not duplicate scorer logic or write candidate results into holding_macro_scores.
- Record ticker, accepted scorer/evidence schema identity, prompt/evidence hashes, model, per-dimension quality, score completion/publication timestamps and run/item status. Reuse crash recovery, accounting, contract/staleness handling and retry semantics.
- Prepare likely coverage targets from prior scheduled Opportunity Hunter universe snapshots. Prioritize risk-eligible candidates in the inclusive Bmax minus 2*Mmax envelope (10 points at the current cap), not all 79 candidates by default.
- Fetch evidence and score before a later decision sweep. Never score in response to an already captured cohort and attach the result retrospectively. Supplemental certification is a separate step.

## Touches

portfolio_ai.py; agent_db.py; agents/opportunity_agent.py; agents/learning/macro_provenance.py; scripts/; systemd/; tests/

## Done when

- [ ] Candidate scores and crash-safe run/item accounting are stored separately from holdings and use the same canonical scorer contract.
- [ ] Request/response parity, recovery, retries, stale/wrong-contract rejection and timestamp provenance are tested.
- [ ] Scheduled preparation targets the bounded decision-relevant envelope; runtime scores alone grant no formal eligibility.
- [ ] Candidate collection changes neither the Opportunity Hunter universe nor production recommendations/weights.
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced.
