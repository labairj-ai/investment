# Finish Canary and Test Precision

- **ID:** 0661
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0655, 0656, 0658

## Problem

Four precision gaps remain across the fixture canary (0655) and persistence chain test (0656):

1. **Macro staleness assertion too permissive:** `assert macro_status in ("STALE", "UNAVAILABLE")`. The fixture explicitly seeds a 96-hour-old macro score. The only acceptable result is `STALE`. Allowing `UNAVAILABLE` means the test would pass silently if the seeded macro score stopped loading entirely.

2. **FADING event goes to watch, not dropped:** The 0655 canary asserts WMT (FADING) is not in `attention_items`, but the full contract is:
   - `ACTIVE` → classified normally (attention or opportunity)
   - `FADING` → appears in `watch_items`
   - `RESOLVED` → absent from all sections
   Currently only the attention exclusion is checked. The FADING→watch and RESOLVED→excluded contracts are untested.

3. **`agent_db.DB_PATH` isolation in 0656:** The persistence-chain test re-points `portfolio_ai.DB_PATH` but does not re-point `agent_db.DB_PATH` before calling `create_portfolio_brief()`. `build_portfolio_brief_state()` imports `agent_db` and calls `get_thesis()`, which reads from whatever DB `agent_db.DB_PATH` points to — potentially the local dev or production DB rather than the test fixture. Both paths must be redirected for the duration of the `create_portfolio_brief()` call.

4. **Snapshot/provenance consistency not checked:** The persistence chain test proves a `portfolio_brief_snapshots` row exists but doesn't compare its `snapshot_json` to `portfolio_brief_provenance.brief_snapshot_json` for the same `brief_id`. Both should represent the same deterministic state snapshot.

## Proposed approach

**Fix 1** (macro assertion): Replace `in ("STALE", "UNAVAILABLE")` with `== "STALE"` in the 0655 fixture assertions.

**Fix 2** (FADING/RESOLVED): Add to 0655 canary:
- `assert any(item.get("ticker") == "WMT" for item in brief_state.get("watch_items", []))` — FADING event is in watch
- `assert not any(item.get("ticker") == "ITW" for item in brief_state.get("attention_items", []) + brief_state.get("opportunities", []) + brief_state.get("watch_items", []))` — RESOLVED event is completely absent

**Fix 3** (DB isolation): In the 0656 persistence chain test, ensure both `portfolio_ai.DB_PATH` and `agent_db.DB_PATH` are redirected to the temp fixture DB before `create_portfolio_brief()` is called, and both are restored in the `finally` block.

**Fix 4** (snapshot/provenance consistency): After `create_portfolio_brief()` returns, query both tables for the returned `brief_id`. Parse both JSON blobs and compare `attention_items`, `opportunities`, and `portfolio_state` — they should be identical (same state was captured in both tables).

## Touches

- `tests/test_portfolio_brief.py` — fixes 1, 2, 3, 4 above; no new production code changes needed

## Done when

- [ ] Macro staleness assertion uses `== "STALE"` not `in ("STALE", "UNAVAILABLE")`
- [ ] WMT (FADING) asserted in `watch_items`
- [ ] ITW (RESOLVED) asserted absent from all sections (attention + opportunities + watch)
- [ ] `agent_db.DB_PATH` redirected to fixture DB before `create_portfolio_brief()` and restored in `finally`
- [ ] `portfolio_brief_snapshots.snapshot_json` compared to `portfolio_brief_provenance.brief_snapshot_json` for the same `brief_id`; `attention_items` match
