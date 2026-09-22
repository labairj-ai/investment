# Complete invocation fill telemetry

- **ID:** 0574
- **Status:** done
- **Created:** 2026-09-22
- **Priority:** high

## Problem

Initialization HALTs and event-only fills must remain visible in invocation telemetry.

## Done when

- [x] Merge initialization observations into HALTED runner summaries.
- [x] Deduplicate event and ledger observations without changing fills_applied semantics.
- [x] Correct TODO 0569–0571 status metadata.
- [x] Run the full suite and deterministic paper-broker canary: engine BUY/losing SELL, external BUY/losing SELL, duplicate replay, crash recovery, exact reconciliation.

## Verification

See `docs/fill-reconciliation-hardening.md` and `tests/test_fill_hardening.py`.
The canary is deterministic and isolated; no Alpaca account orders are submitted.
