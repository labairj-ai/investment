# Rename "shadow_equity" Strategy Label to Broker-Neutral Name

- **ID:** 0319
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** low
- **Depends:** none

## Problem

`intent_builder.py` stamps every `TradeIntent` with `strategy="shadow_equity"` regardless of which broker will execute it. `AGENTIC_ALPACA_01` intents therefore carry incorrect provenance in the `trade_intents` table and any downstream analytics or audit logs. This doesn't affect execution correctness but makes post-trade analysis misleading — real Alpaca fills will be attributed to a "shadow" strategy.

## Proposed approach

- Replace the hardcoded `"shadow_equity"` string with a broker-neutral label such as `"agentic_equity_v1"`.
- Open question: should the value be derived from the account's `broker` field (e.g. `f"agentic_equity_{broker}"`) or from a field in the strategy config / policy file? A config-driven approach is more flexible but adds a migration concern for existing rows.
- Update any tests that assert on the literal string `"shadow_equity"`.
- No DB migration needed for existing rows — `strategy` is a free-text label, old rows can stay as-is.

## Touches

- `trade_engine/intent_builder.py` — change hardcoded `strategy="shadow_equity"`
- `tests/` — update any assertions on the `"shadow_equity"` string

## Done when

- [ ] No new `TradeIntent` rows are written with `strategy="shadow_equity"`
- [ ] `AGENTIC_ALPACA_01` intents carry a label that does not reference "shadow"
- [ ] All tests pass with the updated string
