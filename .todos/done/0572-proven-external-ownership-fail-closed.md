# Proven external ownership, fail closed

- **ID:** 0572
- **Status:** done
- **Created:** 2026-09-22
- **Priority:** high

## Problem

Broker lookup failure must never turn an unresolved engine fill into BROKER_EXTERNAL.

## Done when

- [x] Halt initialization on failed PENDING_SUBMIT ownership lookup.
- [x] Resolve unknown fill ownership through broker order identity; recover local lineage or halt ambiguous engine ownership.
- [x] Cover timeout with a fill present, confirmed external ownership, and crash recovery through FILLED.

## Verification

See `docs/fill-reconciliation-hardening.md` and `tests/test_fill_hardening.py`.
The canary is deterministic and isolated; no Alpaca account orders are submitted.
