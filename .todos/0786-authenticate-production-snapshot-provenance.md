# Bind Production Snapshot Certification to Authentic Backup Provenance

- **ID:** 0786
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0784

## Problem

The development-agent snapshot canary proves that an isolated SQLite database is opened read-only and remains unchanged, but it does not prove that the supplied database is an authentic, recent snapshot of the authoritative Investment production database.

An arbitrary valid SQLite `.db` must not satisfy `production_snapshot=PASS`.

## Scope and acceptance

- [ ] Define a canonical production-backup provenance receipt.
- [ ] Bind the receipt to the authoritative production database backup workflow.
- [ ] Include at minimum:
  - source environment identity
  - backup timestamp
  - backup file SHA-256
  - SQLite integrity result
  - schema/migration fingerprint
  - canonical table/schema fingerprint
  - source application SHA where available
  - backup mechanism/version
- [ ] Require `check_snapshot()` to receive both the isolated snapshot and its provenance receipt.
- [ ] Verify snapshot hash exactly matches the provenance receipt.
- [ ] Verify canonical schema identity instead of merely recording `table_count`.
- [ ] Reject unrelated SQLite databases even if integrity_check succeeds.
- [ ] Reject stale snapshots outside an explicitly defined certification freshness policy.
- [ ] Reject snapshots with a WAL or evidence of an incomplete SQLite copy.
- [ ] Preserve immutable/read-only SQL checks and before/after byte identity.
- [ ] Never open the live production runtime database during development-agent certification.
- [ ] Surface snapshot provenance, timestamp and schema identity in the certification receipt.

## QA requirements

- [ ] Empty SQLite DB must fail authenticity validation.
- [ ] Investment-like DB with incorrect schema fingerprint must fail.
- [ ] Correct DB with forged provenance hash must fail.
- [ ] Correct provenance paired with a different snapshot must fail.
- [ ] WAL-backed/inconsistent copy must fail.
- [ ] Valid isolated production backup must PASS.
- [ ] Canary must leave snapshot byte-for-byte unchanged.
- [ ] Existing production backup workflow remains unaffected.

## Implementation guardrails

- Do not use a hardcoded current table count as the sole schema check.
- Do not permit caller-supplied `"production": true` metadata to establish provenance.
- Do not copy the live DB from inside the coding-agent process.
- Production backup creation remains an operator/deployment responsibility.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
