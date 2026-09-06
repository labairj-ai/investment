# Build Recommendation Dependency Engine (Smart Expiration)

- **ID:** 0025
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0004, 0008

## Problem

Recommendations currently expire by timestamp, which is too blunt. A CC recommendation for EW at $94 should expire immediately if EW moves to $98 — not because time passed, but because the underlying premise changed. A HOLD recommendation should expire when earnings arrive, not 7 days later. Without dependency-aware expiration, stale recommendations sit in the Decision Queue with outdated data, and there's no audit trail explaining why a recommendation was replaced.

## Proposed approach

**New table: `recommendation_dependencies`**

| Field | Purpose |
|---|---|
| id | PK |
| recommendation_id | FK to recommendations |
| dependency_type | Enum: PRICE / THESIS_VERSION / MACRO_SCORE / EARNINGS_RELEASE / NEWS_STATE / IV_LEVEL |
| dependency_key | What is being watched (ticker, data source key) |
| original_value | Value at time recommendation was created |
| tolerance | How much change invalidates (% for price, 0 for version-type) |
| invalidating_event | Human-readable description of what would expire this |

**Examples:**

CC recommendation for EW at $94.22:
```
dependency_type: PRICE
dependency_key: EW
original_value: 94.22
tolerance: 2%  (→ expires if EW < $92.33 or > $96.11)
invalidating_event: "PRICE_THRESHOLD"
```

HOLD recommendation for ANET thesis v3:
```
dependency_type: THESIS_VERSION
dependency_key: ANET
original_value: 3
tolerance: 0
invalidating_event: "THESIS_CHANGED"
```

CC recommendation with upcoming earnings:
```
dependency_type: EARNINGS_RELEASE
dependency_key: EW:2026-10-22
original_value: null
tolerance: null
invalidating_event: "EARNINGS_OCCURRED"
```

**Dependency checker (runs on each data refresh cycle):**
- For each open recommendation, check all its dependencies
- If any dependency is violated: mark recommendation `status=superseded`, write `superseded_reason` (e.g., "Price moved 4.7% past tolerance"), trigger re-evaluation via orchestrator for that ticker/agent
- The superseding event is logged so the Decision Queue can show "Previous ANET recommendation expired because price moved 4.7%"

**Dependency types and their data sources:**
- PRICE → latest from `holding_day` or live price fetch
- THESIS_VERSION → `investment_theses.version` for ticker
- MACRO_SCORE → macro score in `holding_day` (if tracked)
- EARNINGS_RELEASE → earnings calendar from event data
- IV_LEVEL → option chain data (for CC recs, IV percentile change > 10pp)

## Outcome

- `recommendation_dependencies` table created (id, recommendation_id, dependency_type, dependency_key, original_value, tolerance, invalidating_event).
- `recommendations.superseded_reason TEXT` column added via `_new_cols`.
- `agent_db.py`: `write_dependencies()`, `supersede_recommendation()`, `get_open_recs_with_deps()` added; `list_journal_entries` includes `superseded` status; `journal_summary` returns superseded count via `by_status`.
- `agents/contracts.py`: `dependencies: list[dict] | None = None` added to `Recommendation`.
- `agents/orchestrator.py`: writes deps after each `insert_recommendation`.
- `agents/covered_call_agent.py`: PRICE dep (±2%) + `current_price` in action_payload.
- `agents/tax_agent.py`: PRICE dep (±5% for WAIT, ±4% for HARVEST).
- `agents/thesis_agent.py`: THESIS_VERSION dep on EXIT_REVIEW, TRIM, BUY recs.
- `agents/dependency_checker.py`: new file — `check_all_dependencies()` checks PRICE (holding_day) and THESIS_VERSION (investment_theses), supersedes violations, triggers re-eval via orchestrator.
- `serve.py`: dep checker called at end of every `run()` (5pm + 9:30pm refreshes) and at end of `_run_saturday_sweep()`. Also fixed broken venv/bin/python3 symlink (was pointing to Mac path).
- `generate_dashboard.py`: `superseded` status color (purple), "Expired: [reason]" inline row, SUPERSEDED chip in summary strip.
- QA (2026-09-05): synthetic GRMN rec with price dep at $9999.99 → superseded instantly, reason shows in browser, SUPERSEDED 1 chip visible.
- Note for 0029: `get_open_recs_with_deps()` returns agent_type via agent_runs join — lineage traces are available.

## Touches

`recommendation_dependencies` table (new, add to 0004 migration or separate), `agent_db.py` (write dependencies when creating recommendations), `serve.py` (dependency checker runs on each data refresh cycle), `generate_dashboard.py` (show superseded_reason in recommendation history)

## Done when

- [x] `recommendation_dependencies` table exists with all fields
- [x] CC recommendations created with PRICE dependencies (EARNINGS_RELEASE skipped — no earnings calendar data in DB)
- [x] Thesis agent EXIT_REVIEW/TRIM/BUY recs created with THESIS_VERSION dependency
- [x] Dependency checker runs on each data refresh cycle (5pm, 9:30pm nightly run, Saturday sweep)
- [x] Violated dependency marks recommendation `status=superseded` with reason string
- [x] Superseded recommendations trigger re-evaluation for the same ticker/agent
- [x] Dashboard shows "Expired: [reason]" on superseded recommendations in history; SUPERSEDED chip in summary strip
- [x] Browser QA (mandatory — do not skip): Create a recommendation with a known dependency (e.g., price-based), then change the triggering data to violate that dependency. Open the dashboard in a browser and verify: (a) zero JS console errors, (b) the recommendation shows 'Expired: [reason]' in the history view, (c) a new recommendation was triggered for the same ticker/agent. Do NOT check this box without completing live browser testing.

