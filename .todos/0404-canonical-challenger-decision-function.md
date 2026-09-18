# Canonical Challenger Decision Function

- **ID:** 0404
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

The shadow evaluator (`score_for_observe`) and the actual paper/book selection path use different scoring and ranking semantics. `score_for_observe` ranks on raw floating-point challenger scores with explicit tie-breaking (ch_score DESC, base_score DESC, ticker ASC). `apply_challenger_adjustment` returns a rounded integer composite, and Opportunity Hunter sorts scored candidates by `_composite_challenger` without that same deterministic tie-break. This means a shadow observation can record challenger selected A while the paper variant and virtual book actually execute with B — directly undermining the prospective evaluation the learning system depends on.

Concrete example: raw scores A=82.41, B=82.36 → shadow sees A>B; after rounding both become 82 → paper picks by list order.

## Proposed approach

- Extract three shared helpers (or a single scoring module):
  - `score_candidate_with_model(candidate, model) -> dict` — returns both `challenger_score_raw` and `challenger_score_effective`
  - `select_base_winner(candidates) -> candidate` — deterministic top-1 by base_score DESC, ticker ASC
  - `select_challenger_winner(candidates, model) -> candidate` — deterministic top-1 by challenger_score_raw DESC, base_score DESC, ticker ASC
- Use these helpers everywhere: `score_for_observe()`, decision variants, CHALLENGER_BOOK, paper challenger intents, prospective cohort evaluation
- Do not round scores for ranking. Round only for display/storage.
- Remove duplicate tie-breaking logic from `challenger.py` and `opportunity_agent.py`.

## Touches

- `agents/learning/challenger.py` — `score_for_observe()`
- `agents/opportunity_agent.py` — `_composite_challenger`, sorted() call, variant selection
- New shared module or function in `agents/learning/` for canonical selection
- Tests verifying shadow and paper selections agree on same input

## Done when

- [ ] One canonical `select_challenger_winner()` function exists and is called by both shadow and paper paths
- [ ] Ranking uses raw floating-point scores throughout; rounding is display-only
- [ ] A test confirms: given the same candidates and model, `score_for_observe` and the paper execution path would select the same episode
- [ ] No other sorted()/max() call on composite scores remains in the execution path
