# Production-State Canary

- **ID:** 0657
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0656

## Problem

0656 proves the code path works against a seeded fixture. It does not prove that the actual paper-production DB on optiplex conforms to the assumptions the code path makes. Silent assumptions can exist: schema columns that exist in tests but are missing on production, data shapes that differ from what was seeded, edge cases in real Guardian/news/recommendation rows that a synthetic fixture never exercises.

The distinction matters: 0656 proves correctness of the implementation; 0657 proves correctness of the implementation against the real data it will actually process.

## Proposed approach

A read-only validator that runs against a safe copy (or snapshot) of the current paper-production DB on optiplex. Do not mutate production state.

Two acceptable approaches — choose one:

**Option A (snapshot copy):** `cp ~/investment/out/investment.db /tmp/canary_snapshot.db`, then run the invariant checks against the copy. The snapshot is stale by definition; that's acceptable — the goal is to validate the data shape, not the freshness of any individual row.

**Option B (read-only live query):** open the production DB in WAL read-only mode (`uri=True, mode=ro`), run the invariant checks without writing. No copy required.

**Invariant checks to run:**

1. `portfolio_brief_provenance` — for every row, `briefing_output_json.portfolio_state` ∈ {STABLE, ATTENTION, URGENT, UNKNOWN}. No legacy rows with missing or invalid state values.
2. `portfolio_brief_provenance` — for every row with `attention_items` in `brief_snapshot_json`, verify `portfolio_state != STABLE`. (Any attention should have elevated state.)
3. `ai_insights` — for every row, `insight.portfolio_state` ∈ {STABLE, ATTENTION, URGENT, UNKNOWN}. Same normalization guarantee.
4. `portfolio_brief_provenance` — `source_refs_json` is valid JSON for every row; each entry has `source_type` and `item_key` fields.
5. `portfolio_brief_responses` — every row has a matching `brief_id` in `portfolio_brief_provenance`. No orphaned responses.
6. `brief_id` integrity — every `portfolio_brief_provenance.brief_id` referenced in `portfolio_brief_responses` exists.
7. `portfolio_brief_snapshots` — if this table exists, `portfolio_state` matches provenance for the same `brief_id`.

**Deliverable:** a script `scripts/canary_production_state.py` that can be run on optiplex as `python3 scripts/canary_production_state.py [--db path/to/db]`. Exits 0 if all invariants pass, 1 if any fail, with a human-readable summary of violations. Not a pytest test — a standalone script that can be run periodically or post-deploy.

**Important:** this script must not call `build_portfolio_brief_state()` or `create_portfolio_brief()` — it reads existing DB rows only and validates their shape. No LLM calls, no state generation.

## Touches

- `scripts/canary_production_state.py` — new standalone validator script
- Possibly surfaces bugs in legacy `ai_insights` rows written before 0648 normalization (those may have invalid state — expected; the script should report them as pre-normalization legacy violations with a distinct label)

## Done when

- [ ] `scripts/canary_production_state.py` exists and runs on optiplex without error
- [ ] All 7 invariants are checked
- [ ] Legacy `ai_insights` rows (before 0648) are labeled as pre-normalization rather than treated as bugs
- [ ] Script exits 0 on pass, 1 on any violation, with human-readable summary
- [ ] Script has been run against a production DB snapshot and the result is recorded (even if violations exist — the goal is to know the current state)
- [ ] Script can be re-run post-deploy to confirm no new violations were introduced
