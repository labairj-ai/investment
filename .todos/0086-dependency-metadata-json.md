# Dependency Metadata JSON Column

- **ID:** 0086
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

`recommendation_dependencies` stores only `dependency_type`, `dependency_key`, `original_value`, `tolerance`, `invalidating_event`. But `agents/dependency_checker.py` calls `dep.get("strike")`, `dep.get("expiration")`, `dep.get("threshold")`, `dep.get("event_type")` — fields that are not persisted. As a result, `_check_option_iv()` calls `get_latest_option_snapshot(ticker, dep.get("strike"), dep.get("expiration"))` with None for both, retrieving any snapshot for the ticker rather than the specific contract that was evaluated. This makes contract-specific dependency checking impossible even after option snapshots are wired.

## Proposed approach

- Add `dependency_metadata_json TEXT` column to `recommendation_dependencies` table (via `migrate()` with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`-style guard).
- Update `write_dependencies()` in `agent_db.py` to serialize and persist `d.get("metadata", {})` into `dependency_metadata_json`.
- Update `get_open_recommendations_with_deps()` (or equivalent) to deserialize `dependency_metadata_json` and merge its keys into the dep dict before passing to checkers.
- Update all dependency checkers in `dependency_checker.py` to read contract-specific fields from `dep.get(...)` as they already do — they'll just work once the column is wired.
- Example metadata shapes to document:
  - OPTION_IV/OPTION_LIQUIDITY/OPTION_EXPIRATION: `{"strike": 175, "expiration": "2026-10-16", "contract_id": "ANET:20261016:175", "threshold": 0.20}`
  - ESTIMATE_REVISION: `{"period": "2027FY", "estimate_type": "EPS", "threshold": 0.10}`
  - EVENT_CALENDAR: `{"event_type": "EARNINGS"}`

## Touches

- `agent_db.py` — `migrate()`, `write_dependencies()`, dep-fetching queries
- `agents/dependency_checker.py` — no logic changes needed; just confirm fields are now available
- `agents/covered_call_agent.py` — include metadata dict when writing OPTION_IV/LIQUIDITY/EXPIRATION deps
- `tests/test_lifecycle.py` — verify metadata round-trips through DB and is readable by checkers

## Done when

- [ ] `dependency_metadata_json` column exists in `recommendation_dependencies`
- [ ] `write_dependencies()` persists metadata for each dep that provides it
- [ ] Fetched dep dicts include deserialized metadata keys
- [ ] OPTION_IV checker receives strike + expiration from stored metadata
- [ ] Test: write dep with strike=175, read back, checker receives strike=175
