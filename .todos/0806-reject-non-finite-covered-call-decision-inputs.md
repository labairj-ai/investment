# TODO 0806 — Fail Closed on Non-Finite Covered-Call Decision Inputs Before Recommendation Math

- **ID:** 0806
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** high
- **Depends:** 0795
- **Blocks:** production promotion of cc-v3.4

## Problem

cc-v3.4 correctly sanitizes non-finite values before JSON persistence, but several decision-critical values are used in recommendation calculations before `_sanitize_payload()` runs.

Values such as `cc_alpha`, `exec_premium`, `current_price`, `regret_prob` or `delta` can therefore cause invalid calculations or exceptions before persistence sanitization.

JSON safety and decision-input validity must be separate controls.

## Scope and acceptance

- [ ] Define canonical validation for decision-critical CC numeric inputs.
- [ ] Validate finite values before:
  - recommendation score calculation
  - premium/income calculation
  - breakeven calculation
  - annualized return calculation
  - priority calculation
  - trade-chain construction where numeric values are required
- [ ] Decision-critical missing/non-finite values must result in:
  - `NO_CALL`, or
  - explicit `INSUFFICIENT_DATA`
- [ ] Do not silently replace decision-critical NaN/Infinity with zero.
- [ ] Preserve JSON null conversion only for non-decision-critical evidence fields where absence is valid.
- [ ] Expand numeric sanitization to safely recognize NumPy/Pandas numeric scalars.
- [ ] Preserve valid finite values exactly.
- [ ] Record explicit reason codes for non-finite decision input failures.
- [ ] Ensure challenger/champion comparison cannot operate on invalid required metrics.

## QA requirements

- [ ] `cc_alpha = NaN` fails closed without exception.
- [ ] `exec_premium = Infinity` fails closed.
- [ ] `current_price = NaN` cannot produce financial summary math.
- [ ] Invalid `regret_prob` cannot pass recommendation eligibility.
- [ ] NumPy `float64(nan)` is recognized.
- [ ] Valid finite values produce unchanged recommendations versus cc-v3.4 baseline.
- [ ] Strict JSON serialization still succeeds.
- [ ] CC behavioral contract is deliberately versioned if this changes behavior.
- [ ] Existing observe-only/promotion policy remains unchanged.

## Implementation guardrails

- Do not convert invalid required values to zero.
- Do not silently remove a decision-critical metric.
- Any behavioral change must follow existing CC change-control process.

## Source

User-supplied 2026-10-22 trust-boundary code-review follow-up. Backlog creation does not authorize implementation, promotion, pilot execution or autonomy activation.

## Implementation checkpoint — 2026-10-22

Implementation is on `codex/trust-boundary-0803-0809`; see the
[implementation plan](../docs/plans/development-agent-trust-boundaries-0803-0809.md)
and [trust-boundary contract](../docs/development-agent-trust-boundaries.md).
Source/fixture validation does not close environmental acceptance. This TODO remains
open pending its complete QA, required human decisions and exact-head CI evidence.
