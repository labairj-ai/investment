# Persist Advisor Decision Lineage And Invalidation

- **ID:** 0739
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0732, 0733, 0734, 0735, 0736, 0737, 0738

## Problem

A decision-grade advisor response needs to be reproducible later. Today the streamed answer is ephemeral and there is no durable record binding the verdict to exact portfolio state, evidence, policy versions, Critic review, tax lots and risk preview.

Without lineage and invalidation, an old recommendation can look current after its inputs change.

## Proposed approach

- Add advisor decision tables/schema for immutable decision snapshots and source/dependency references.
- Persist `advisor_decision_id`, raw request hash, normalized request, context hash, trade-impact result, tax-lot plan, Critic review, risk preview, deterministic state/reasons, policy versions, model/prompt identity and rendered answer.
- Reuse dependency concepts from agent recommendations where practical: price/position, thesis version, candidate/evidence version, CC state, policy version and cost-lot state.
- Add deterministic `VALID`, `STALE`, `SUPERSEDED`, `EXPIRED` status calculation.
- Store decision TTL/valid-until independently from conversational transcript lifetime.

## Touches

- `schema.sql`
- `agents/advisor/persistence.py`
- `agents/advisor/contracts.py`
- `agents/dependency_checker.py` or a shared dependency helper
- `tests/`

## Implementation guardrails

- Persist the structured decision before/with rendered output atomically; never store a prose verdict without its authoritative structured state.
- Repeated retries with the same decision id must be idempotent.
- Historical decision rows are immutable except for lifecycle/status fields that are explicitly designed to change.
- A stale decision must never silently become valid again without recomputation.
- Do not make historical advisor rows eligible for learning/training by default.
- Database migrations must be backward compatible with existing production data.

## Done when

- [x] Every Decision-mode answer has a unique `advisor_decision_id` and deterministic source/context hashes.
- [x] The persisted record can reconstruct the actionability state, exact trade delta, evidence references, Critic result and risk preview without re-calling the LLM.
- [x] Changing a referenced thesis version, position/share state, required price snapshot, CC coverage state or advisor policy version invalidates the applicable decision.
- [x] Invalidated decisions are visibly non-actionable and never reactivated without a new decision id.
- [x] Retry/idempotency tests do not duplicate decision records.
- [x] Migration tests pass on a pre-advisor schema fixture.
- [x] QA evaluation conducted: lifecycle/invalidation tests plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.

## Completion evidence

Completed 2026-10-14. Implementation and acceptance fixtures are documented in
`docs/advisor-decision.md`; focused advisor QA: 55 passed. Full local suite:
2,529 passed, 16 existing skips, no failures. Exact baseline and CC behavioral
contract gates passed. Read-only production-snapshot canary passed with trading
state unchanged and degraded evidence held in review. Real GitHub Actions passed:
https://github.com/labairj-ai/investment/actions/runs/38552153244
