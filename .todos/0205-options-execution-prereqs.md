# Options Execution Prerequisites: Multiplier, Instrument Identity, MAX_CONTRACTS Bug

- **ID:** 0205
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

Three latent issues that are harmless today (SELL_CC is disabled) but must be fixed before options execution is enabled:

1. **`Fill.cash_impact()` ignores contract multiplier.** An option premium of $3.20 for 1 contract should affect cash by ~$320, not $3.20. The current formula is `qty × price` with no multiplier.

2. **No durable instrument identity for options.** `TradeIntent` knows `strike`/`expiration`/`option_type`, but `Order` and `Fill` collapse options back to just `symbol/side/quantity`. When ANET Oct $160C and ANET Oct $170C are both open, reconciliation and position tracking become ambiguous.

3. **`MAX_CONTRACTS_PER_SYMBOL` has an off-by-one bug.** Currently tests `open_c < limit_c`. With `open_c=0` and `limit=1`, an intent requesting 2 contracts passes. Should be `open_c + requested_contracts <= limit_c`.

## Proposed approach

**Fix the multiplier** in `Fill.cash_impact()`:
```python
multiplier = 100 if self.side in (Side.SELL_TO_OPEN, Side.BUY_TO_CLOSE) else 1
sign = 1.0 if self.side in (Side.SELL, Side.SELL_TO_OPEN) else -1.0
return sign * (self.qty * self.price * multiplier) - self.fee
```

**Add `Instrument` dataclass** in `models.py`:
```python
@dataclass(frozen=True)
class Instrument:
    instrument_type: InstrumentType
    symbol: str                    # underlying for options, ticker for equity
    option_type: str | None        # 'CALL' | 'PUT'
    expiration: str | None         # ISO date
    strike: float | None
    multiplier: int = 1            # 100 for equity options
    contract_symbol: str | None = None  # OCC symbol if available
```

Add `instrument` field to `Order` and `Fill` (stored as JSON in a new `instrument_json` column), so downstream position tracking can distinguish contracts on the same underlying.

**Fix `MAX_CONTRACTS_PER_SYMBOL` check**:
```python
open_c + (intent.contracts or 1) <= limit_c  # was: open_c < limit_c
```

## Touches

- `trade_engine/models.py` — `Instrument` dataclass, `Fill.cash_impact()` multiplier, `instrument` on Order/Fill
- `trade_engine/risk_engine.py` — fix `MAX_CONTRACTS_PER_SYMBOL` condition
- `agent_db.py` — add `instrument_json` column to `orders` and `fills`

## Done when

- [ ] `Fill.cash_impact()` applies 100× multiplier for SELL_TO_OPEN / BUY_TO_CLOSE fills
- [ ] `MAX_CONTRACTS_PER_SYMBOL`: open=0 + requesting 2 + limit=1 → REJECTED
- [ ] `Instrument` dataclass importable from `trade_engine.models`
- [ ] Test: option fill cash_impact = qty × price × 100 − fee
- [ ] Test: MAX_CONTRACTS off-by-one fixed (two-contract intent with limit=1 → FAIL)
