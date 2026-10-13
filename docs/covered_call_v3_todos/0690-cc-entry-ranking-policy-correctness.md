# Correct Covered Call Entry Ranking and Policy Enforcement

- **ID:** 0690
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** none

## Problem

Initial SELL_CC selection has several correctness issues before any new modeling is added:

- `_compute_scores()` rewards raw `premium_pct`, which structurally favors larger nominal premium and can favor longer DTE.
- Production candidate selection ranks by `score` even though `opp_score` already uses more absolute economics.
- The candidate set is truncated before all thesis-policy constraints are applied.
- `preferred_dte_min` / `preferred_dte_max` exist in CC policy but are not enforced.
- If policy filters remove every contract, the agent falls back to the unfiltered universe instead of returning NO_CALL.
- `acceptable_assignment_min_price` exists but is not enforced at initial write.
- `regret_prob` and related fields are rounded before persistence/presentation, allowing small non-zero probabilities to appear as literal zero.
- Liquidity is scored 0-100 but evidence logic compares it to a 0-1 threshold.

These issues make it difficult to determine whether poor outcomes are caused by the model itself or by implementation inconsistencies.

## Proposed approach

Separate the entry pipeline into four explicit stages:

1. **Hard eligibility**
   - strategy != NONE
   - DTE policy
   - minimum OTM
   - maximum preferred delta
   - earnings/event veto
   - acceptable assignment floor
   - quote/liquidity minimums
2. **Economic calculations**
   - premium
   - annualized return
   - cc_alpha
   - regret and ITM probabilities
3. **Ranking**
   - rank only contracts that passed all hard gates
4. **Presentation**
   - round values only for UI/email display

Remove automatic fallback to policy-invalid contracts. If nothing passes, return deterministic NO_CALL with rejection reasons.

Replace the primary score's raw `premium_pct` term with a duration-normalized metric such as `annualized_ret` until 0694 replaces the composite scorer.

Keep full-precision floats internally and in persisted evidence.

Normalize liquidity explicitly to 0-1 or compare against a 0-100 threshold consistently.

## Guardrails

- Do not change roll-management logic in this TODO.
- Do not add new predictive models here.
- Preserve current output schema where possible; add fields rather than repurposing existing semantics.
- Every hard rejection should have a machine-readable reason.

## Touches

- `covered_call_rec.py`
- `agents/covered_call_agent.py`
- `strategy_config.py`
- `config/strategy.json`
- `tests/test_covered_call_rec.py`
- covered-call agent tests

## Done when

- [ ] Policy-invalid contracts can never be selected for SELL_CC.
- [ ] Zero valid contracts returns NO_CALL; no unfiltered fallback exists.
- [ ] `preferred_dte_min` / `preferred_dte_max` are enforced and tested.
- [ ] `acceptable_assignment_min_price` is enforced at entry.
- [ ] Raw `premium_pct` no longer creates a duration bias in production ranking.
- [ ] Candidate filtering occurs before top-N truncation.
- [ ] Probabilities and ratios retain full precision until presentation.
- [ ] Liquidity evidence uses a consistent scale.
- [ ] Rejection reasons are persisted or returned for diagnostics.
- [ ] Existing management/roll tests remain green.
- [ ] Regression fixtures document every intentional ranking change.
