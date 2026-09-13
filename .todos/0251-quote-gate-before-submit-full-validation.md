# Fix Quote-Before-Submit Ordering and Full Validation Gate

- **ID:** 0251
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

The commit 49cb263 partially implemented 0243 but reversed the required ordering.
`process_intent()` calls `broker.submit_order()` at line 323 and only calls
`broker.get_quote()` at line 333. A future Alpaca/IBKR adapter would therefore receive
a real order before the system discovers the quote is stale, unavailable, or crosses
a spread limit. This is the same blocker the prior review identified; the implementation
attempt did not satisfy it.

The intended pipeline is:
  `broker.get_quote()` → freshness + sanity + spread + limit-price check
  → only then `broker.submit_order()`

Additionally, the validation gate is incomplete: no maximum-spread check, no
limit-price sanity (e.g., BUY limit not more than N% above ask), and no spy-broker test
that asserts `submit_order.call_count == 0` for each individual invalid-quote case.

## Proposed approach

1. In `process_intent()`, move `broker.get_quote()` to the top of the function, before
   any call to `broker.submit_order()`. If the quote is missing, return without submitting.
2. Run the full validation gate on the returned quote before proceeding to submission:
   - `retrieved_at` / `market_timestamp` freshness (already in `_is_quote_fresh()`)
   - `bid > 0` and `ask > 0`
   - `bid <= ask`
   - `(ask - bid) / ask <= policy.max_spread_pct` (add field to policy, default ~2%)
   - For LIMIT BUY: `limit_price >= ask * (1 - tolerance)` (reject absurdly low limits)
   - For LIMIT SELL: `limit_price <= bid * (1 + tolerance)` (reject absurdly high limits)
3. Each failing check must return without calling `submit_order()` and write a
   descriptive reason to `market_data_status` on the intent.
4. Add a spy-broker test fixture that records calls. Write one parameterised test per
   invalid-quote condition asserting `submit_order.call_count == 0`.
5. In `process_open_orders()`, apply the same gate to the retry-fill path.

## Touches

- `trade_engine/execution_engine.py`
- `trade_engine/policy.py` (add `max_spread_pct` field)
- `tests/test_trade_engine.py`
- `tests/test_broker_contract.py`

## Done when

- [ ] `broker.get_quote()` is called before `broker.submit_order()` in `process_intent()`
- [ ] Quote missing or stale → intent not submitted, reason recorded
- [ ] `bid <= 0`, `ask <= 0`, `bid > ask` each independently block submission
- [ ] Spread exceeding `policy.max_spread_pct` blocks submission
- [ ] Absurd limit-price (BUY far below ask / SELL far above bid) blocks submission
- [ ] Spy-broker parametrised test asserts `submit_order.call_count == 0` for every bad-quote case
- [ ] `process_open_orders()` applies the same gate on the retry path
- [ ] All existing tests pass
