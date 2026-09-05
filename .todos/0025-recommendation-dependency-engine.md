# Build Recommendation Dependency Engine (Smart Expiration)

- **ID:** 0025
- **Status:** backlog
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

## Touches

`recommendation_dependencies` table (new, add to 0004 migration or separate), `agent_db.py` (write dependencies when creating recommendations), `serve.py` (dependency checker runs on each data refresh cycle), `generate_dashboard.py` (show superseded_reason in recommendation history)

## Done when

- [ ] `recommendation_dependencies` table exists with all fields
- [ ] CC recommendations created with PRICE and EARNINGS_RELEASE dependencies
- [ ] HOLD recommendations created with THESIS_VERSION dependency
- [ ] Dependency checker runs on each data refresh cycle (not just at midnight)
- [ ] Violated dependency marks recommendation `status=superseded` with reason string
- [ ] Superseded recommendations trigger re-evaluation for the same ticker/agent
- [ ] Dashboard shows "Expired: [reason]" on superseded recommendations in history
