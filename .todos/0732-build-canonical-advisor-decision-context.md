# Build Canonical Advisor Decision Context

- **ID:** 0732
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** none

## Problem

The Portfolio Advisor currently assembles its own prompt context from holdings, layer weights, candidate data, covered-call state, realized gains, macro context and macro scores. That path bypasses the canonical Portfolio Decision Brief state, so chat can reason without the same thesis health, Guardian findings, Critic verdicts, execution state, freshness state and capability-state authority used elsewhere in the system.

A decision-grade advisor needs one read-only, deterministic snapshot that all later advisor stages consume.

## Proposed approach

- Add an advisor package with a canonical context builder, e.g. `agents/advisor/context.py`.
- Compose the advisor context from `build_portfolio_brief_state(conn)` plus canonical holdings/position marks, exact cost lots, layer allocation, covered-call state and deterministic candidate rankings.
- Extract a deterministic candidate-ranking function from `agents/opportunity_agent.py` so the advisor consumes the same Q/V/PF/C/R/EC comparison scores rather than maintaining `_build_candidate_universe_block()` as an independent ranking path.
- Keep the context builder network-free and LLM-free. It may read current persisted state only.
- Include source timestamps, source authority/criticality, policy/scorer versions and a deterministic `context_hash`.

## Touches

- `agents/advisor/__init__.py`
- `agents/advisor/context.py`
- `agents/opportunity_agent.py`
- `portfolio_ai.py`
- `tests/`

## Implementation guardrails

- The context builder is read-only: no brief snapshots, recommendations, decisions, intents, orders, fills or user-response rows may be written.
- Do not duplicate candidate scoring formulas, layer targets, thesis logic, Guardian logic, Critic logic or freshness rules.
- Observe-only/advisory/experimental sources must be labeled as such in the structured context; do not silently promote them to production evidence.
- Missing data must be represented explicitly as unavailable/stale/unknown rather than replaced with neutral defaults that look authoritative.
- Preserve existing public APIs and current Decision Brief behavior.
- Context hashing must be deterministic across macOS/Linux and exclude runtime object identity, paths and timestamps that are not part of the captured state.

## Done when

- [ ] `build_advisor_decision_context(conn)` returns one structured snapshot containing canonical portfolio state, open governed recommendations with Critic state, thesis health, Guardian findings, execution state, freshness/capability state, holdings/marks, exact lots, layer allocation, CC state and deterministic candidate ranks.
- [ ] Candidate ordering and component scores exactly match the canonical comparison scorer for the same fixture.
- [ ] Repeated builds from an unchanged fixture produce the same `context_hash`.
- [ ] No Ollama/MLX call, network call or write statement occurs while building context; tests fail if one is attempted.
- [ ] Required unavailable/stale sources are preserved in the context and never silently converted to healthy values.
- [ ] Existing `score_for_comparison()`, Decision Brief and advisor Explore behavior remain backward compatible.
- [ ] Focused tests cover healthy, degraded, missing-thesis, missing-price, empty-candidate and open-CC fixtures.
- [ ] QA evaluation conducted: focused tests plus full `pytest tests/ -v --tb=short` pass with no regressions introduced.
