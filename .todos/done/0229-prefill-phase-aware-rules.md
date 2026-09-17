# Make PRE_FILL Risk Rules Phase-Aware

- **ID:** 0229
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`MAX_ORDERS_PER_DAY` (rule 11, `risk_engine.py:437`) counts all orders submitted today, including the WORKING order being revalidated. An order submitted as the fifth order of five (at the daily limit) will pass `PRE_ORDER` (`orders_today=4 < 5`), be submitted, and then fail `PRE_FILL` (`orders_today=5, 5 < 5 → False`) and be incorrectly cancelled. The order already consumed its admission slot; re-counting it is double-counting.

Admission rules (one-time gates) and continuous rules (re-checked on every cycle) must behave differently in `PRE_FILL`. Specifically, `MAX_ORDERS_PER_DAY` is an admission rule — it should SKIP in `PRE_FILL` because the order was already counted when submitted.

## Proposed approach

- In `evaluate()` (`risk_engine.py`), when `phase == "PRE_FILL"`, replace the `MAX_ORDERS_PER_DAY` rule result with `RuleCheck(rule="MAX_ORDERS_PER_DAY", result=_SKIP, reason="admission rule; order already counted at submission")`.
- Audit all 19 rules and document each as: **admission** (PRE_ORDER only), **continuous** (both phases), or **fill-time** (PRE_FILL only). Add a comment block at the top of `evaluate()` listing the classification.
- Rules likely admission-only: `MAX_ORDERS_PER_DAY`, `MAX_NEW_POSITION_PCT` (for new-position opens), `VALID_SIDE_FOR_INSTRUMENT`.
- Rules that remain continuous: `TRADING_ENABLED`, `VALID_ACCOUNT`, `SUFFICIENT_CASH`, `MAX_DAILY_NOTIONAL`, `RISK_STATE_STALE`, `DATA_FRESHNESS`, `CIRCUIT_BREAKER_*`.
- Tests: submit the 5th order of 5 (at the daily limit); PRE_ORDER passes, order submitted; PRE_FILL must not self-reject on `MAX_ORDERS_PER_DAY`.

## Touches

- `trade_engine/risk_engine.py` — `evaluate()`, rule 11 block, rule classification comments
- `tests/test_trade_engine.py` — new self-exclusion test for order count

## Done when

- [x] `MAX_ORDERS_PER_DAY` returns SKIP during `PRE_FILL` phase
- [x] The 5th-order-of-5 scenario passes PRE_FILL without self-rejection
- [x] All 19 rules documented as admission / continuous / fill-time in code comments
- [x] Tests confirm the self-rejection scenario is eliminated
