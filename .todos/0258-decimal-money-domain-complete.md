# Complete Decimal Money Domain Across All Broker Types

- **ID:** 0258
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0252

## Problem

0250 was marked done but only migrated `Fill` fields to `Decimal`. The broader money
domain is still float-based: `BrokerFill.qty/price/fee`, `BrokerAccountState.cash/nav/
buying_power`, `BrokerPosition.qty/avg_cost/market_value`, and all position-level
arithmetic in `shadow_broker.py` and `execution_engine.py` continue to use IEEE-754
`float`. More critically, `sqlite3.register_adapter(Decimal, float)` converts `Decimal`
back to a floating-point number at the DB write boundary, so the `Fill` Decimal fields
are rounded to float precision on every persist/read cycle — no exact money domain
actually exists end-to-end.

## Proposed approach

**Option A — Full Decimal migration (preferred if scope is manageable):**
1. Change `BrokerFill`, `BrokerAccountState`, and `BrokerPosition` monetary fields
   (`qty`, `price`, `fee`, `cash`, `nav`, `buying_power`, `avg_cost`, `market_value`)
   from `float` to `Decimal`.
2. Remove `sqlite3.register_adapter(Decimal, float)`. Instead store monetary values as
   `TEXT` in canonical decimal notation (`str(value)`) and register a converter that
   reads them back as `Decimal`. This preserves exactness at the DB boundary.
   - Alternative: store as integer micros (multiply by 1,000,000 before write, divide
     on read). Requires schema migration but is idiomatic for financial ledgers.
3. Audit all arithmetic sites that mix `float` and `Decimal`; convert float literals and
   DB reads to `Decimal` where needed.
4. Update test assertions to compare `Decimal` values (most `pytest.approx` comparisons
   already work; direct `== float` comparisons need `== Decimal('...')`).

**Option B — Narrow scope, create ledger story:**
1. Revert or annotate `sqlite3.register_adapter(Decimal, float)` as a known precision
   compromise. Document it explicitly.
2. Leave `BrokerFill` etc. as float.
3. Create a follow-up story (0259) specifically for ledger precision: integer minor-unit
   cash storage, schema migration, exact roundtrip testing.
4. Update 0250's done-when criteria to reflect only what was actually achieved.

Open question: which option is right depends on whether a paper-broker adapter is
imminent. If paper trading is within 1–2 milestones, Option A is worth the investment
now. Otherwise Option B defers risk without accumulating more float debt.

## Touches

- `trade_engine/broker_types.py` — `BrokerFill`, `BrokerAccountState`, `BrokerPosition`
- `trade_engine/models.py` — `sqlite3.register_adapter` / converter
- `trade_engine/shadow_broker.py` — arithmetic sites
- `trade_engine/execution_engine.py` — arithmetic sites
- `agent_db.py` — schema migration if using TEXT/integer storage
- `tests/` — assertion updates

## Done when

- [ ] Decision made between Option A and Option B and documented in this file
- [ ] `BrokerFill`, `BrokerAccountState`, `BrokerPosition` monetary fields are `Decimal` (Option A) OR scope is explicitly narrowed with a new 0259 ledger story (Option B)
- [ ] `sqlite3.register_adapter(Decimal, float)` is removed; DB boundary preserves decimal exactness (Option A) OR is explicitly documented as a known precision compromise (Option B)
- [ ] Round-trip test: write a `Decimal` monetary value, read it back, assert equality without float conversion loss
- [ ] 0250 status is updated to reflect actual coverage
- [ ] All existing tests pass
