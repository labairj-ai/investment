# Produce and Certify an Authentic Production Backup Snapshot

- **ID:** 0799
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0786, 0796

## Problem

Authenticated snapshot provenance is implemented, but no real production backup has yet been certified through the new mechanism.

Operational certification requires proof that the agent remains read-only against an authentic isolated copy of authoritative production state.

## Scope and acceptance

- [ ] Run the approved consistent production backup workflow on OptiPlex.
- [ ] Generate authenticated provenance using operator-controlled signing configuration.
- [ ] Record:
  - production environment identity
  - source application SHA
  - backup timestamp
  - backup SHA-256
  - SQLite integrity result
  - schema/migration fingerprint
  - canonical schema identity
  - backup mechanism/version
- [ ] Move/copy the completed backup to the isolated certification location.
- [ ] Ensure no `-wal`, `-shm` or journal file accompanies the snapshot.
- [ ] Run development-agent snapshot certification using the authenticated receipt.
- [ ] Require freshness within configured `snapshot_max_age_hours`.
- [ ] Verify read-only SQLite denial.
- [ ] Verify complete byte identity before/after.
- [ ] Record certification receipt in development-agent evidence.

## QA requirements

- [ ] Real authenticated backup PASS.
- [ ] Same DB without provenance FAIL.
- [ ] Modified DB with original provenance FAIL.
- [ ] Expired backup FAIL.
- [ ] Wrong schema identity FAIL.
- [ ] Production runtime DB is never opened by the certification process.
- [ ] Holdings and all authoritative production state remain unchanged.

## Implementation guardrails

- Development agent may consume an isolated backup only.
- Development agent may not create/copy the live production database itself.
- Signing key must not enter repository or development-agent ledger.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.
