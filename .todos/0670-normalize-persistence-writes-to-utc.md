# Normalize New Persistence Writes to UTC

- **ID:** 0670
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0669

## Problem

Many persistence paths create timestamps with `datetime.now()` (host-local) or `utcfromtimestamp()` (UTC value but timezone-naive), making the stored format ambiguous and dependent on the server's configured timezone. If the optiplex host ever runs in a non-UTC timezone, persisted ordering and provenance will silently break.

## Proposed approach

Audit all `INSERT`/`UPDATE` statements in:
- portfolio briefs, provenance, snapshots
- recommendations, decision episodes, model observations
- learning sweeps, outcome labels
- trade intents, orders, fills, virtual books/fills
- model lifecycle records
- news events/snapshots, macro evidence, acceptance records
- canary/ledger records

Replace `datetime.now(...)`, `datetime.utcnow()`, `utcfromtimestamp()` calls with `now_utc_iso()` from the canonical time utilities. Do not rewrite existing rows.

After the audit, verify that ordering across old and new timestamp formats remains correct after parsing through `parse_timestamp()`.

## Touches

- `portfolio_ai.py`, `serve.py`, `generate_dashboard.py`, agent modules — all persistence write sites
- `tests/` — prove that running under an Eastern host TZ and a UTC host TZ produces equivalent persisted instants

## Done when

- [x] All new persistent timestamp writes use canonical UTC helpers
- [x] No persistence path depends on the optiplex host timezone
- [x] Existing rows are not rewritten
- [x] Ordering across old and new timestamp formats remains correct after parsing
- [x] Tests prove Eastern-host vs UTC-host produces equivalent persisted instants
## Outcome

Implemented as part of 0668-0680 batch commit.
