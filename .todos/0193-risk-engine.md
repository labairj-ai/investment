# Independent Pre-Trade Risk Engine

- **ID:** 0193
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0191, 0192

## Problem

`execution_validation.py` asks: "Was this recorded execution internally valid?" (e.g. does SELL_CC have contracts, strike, premium?). That job is correct and must stay.

`trade_engine/risk_engine.py` asks an entirely different question: "Is this proposed transaction authorized to occur?" The risk engine runs before any order is placed, knows nothing about what the LLM said, and trusts only the policy file and live DB state. It never uses an LLM.

Every rule must report its result individually — not a single boolean — so that every authorization/rejection is fully auditable.

## Proposed approach

```python
def evaluate(intent: TradeIntent, policy: TradingPolicy, account: TradingAccount) -> RiskDecision:
```

Runs these checks in order, collecting `RuleCheck` results. First FAIL stops further checks (fail-fast) unless `strict_all=True` is passed (for diagnostics):

1. **TRADING_ENABLED** — `policy.trading_enabled()` must be True
2. **VALID_ACCOUNT** — `intent.account_id` matches a known enabled account
3. **INTENT_NOT_EXPIRED** — `intent.valid_until` >= now
4. **NO_DUPLICATE_INTENT** — no other intent with same `recommendation_id` in status APPROVED/FILLED
5. **INSTRUMENT_ALLOWED** — equities.buy_allowed / sell_allowed / shorting_allowed / options.*_allowed
6. **NO_MARKET_ORDER** — order_type != MARKET (unless policy allows)
7. **SUFFICIENT_CASH** — post-trade cash >= policy min_cash_pct × NAV
8. **MAX_POSITION_WEIGHT** — post-trade position weight <= policy.max_single_position_pct
9. **MAX_NEW_POSITION_WEIGHT** — if new position, <= policy.max_new_position_pct
10. **MAX_DAILY_NOTIONAL** — today's total notional + this trade <= policy.max_daily_notional_pct × NAV
11. **MAX_ORDERS_PER_DAY** — count(orders today) < policy.max_orders_per_day
12. **SELL_QUANTITY_COVERED** — for SELL/BUY_TO_CLOSE: position holds >= quantity
13. **NO_NAKED_OPTIONS** — SELL_TO_OPEN only if covered call (underlying position >= contracts×100)
14. **MAX_CONTRACTS_PER_SYMBOL** — open contracts <= policy.max_contracts_per_symbol
15. **DATA_FRESHNESS** — last quote for symbol is < policy.halt_on_data_stale_minutes old
16. **NO_EARNINGS_CONFLICT** — for options: no earnings event before expiration
17. **MAX_DAILY_LOSS** — realized + unrealized loss today < policy.max_daily_loss_pct × starting_capital
18. **MAX_DRAWDOWN** — NAV drawdown from peak < policy.max_drawdown_pct

Each `RuleCheck` carries:
```python
RuleCheck(
    rule="MAX_POSITION_WEIGHT",
    result=RuleResult.PASS,
    limit=10.0,    # policy limit
    before=3.2,   # current weight
    after=7.6,    # projected post-trade
    reason=None,
)
```

Final `RiskDecision` has `decision="APPROVED"` only when all checks PASS. Any FAIL → `decision="REJECTED"`.

The decision + full checks JSON is written to `risk_decisions` table.

## Touches

- `trade_engine/risk_engine.py`
- `agent_db.py` — helper reads for position/cash state (re-use existing query patterns)
- `tests/test_trade_engine.py`

## Done when

- [ ] `evaluate()` returns `RiskDecision` with per-rule `RuleCheck` list
- [ ] TRADING_ENABLED=False → REJECTED with single TRADING_ENABLED FAIL check
- [ ] Expired intent → REJECTED with INTENT_NOT_EXPIRED FAIL
- [ ] Duplicate recommendation_id → REJECTED with NO_DUPLICATE_INTENT FAIL
- [ ] Insufficient cash → REJECTED; checks include before/after cash pct values
- [ ] Position limit violation → REJECTED; checks include before/after weight values
- [ ] All checks PASS → APPROVED
- [ ] Decision written to risk_decisions table with checks_json
- [ ] No LLM call anywhere in this module
- [ ] Tests cover each of the 18 rules independently
