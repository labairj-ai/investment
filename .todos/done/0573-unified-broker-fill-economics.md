# Unified broker fill economics

- **ID:** 0573
- **Status:** done
- **Created:** 2026-09-22
- **Priority:** high

## Problem

Engine and external broker sells must record identical realized economics, including percentage units and daily-loss risk visibility.

## Done when

- [x] Share equity settlement math across engine, external, and shadow fills.
- [x] Persist cost basis, realized P&L and percentage units on engine sells.
- [x] Test partial/full sells, fees, zero basis, duplicate replay, and MAX_DAILY_LOSS.

## Verification

See `docs/fill-reconciliation-hardening.md` and `tests/test_fill_hardening.py`.
The canary is deterministic and isolated; no Alpaca account orders are submitted.
