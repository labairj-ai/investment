# Rollback on Persist Failure and Block Degraded Cache Writes

- **ID:** 0616
- **Status:** backlog
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0613, 0614

## Problem

Two gaps that can corrupt the committed intelligence state. (a) `persist_events()` has no rollback handler. If an INSERT fails partway through, uncommitted writes (snapshot row, deleted prior events, partial new events) sit in the connection's open transaction. A subsequent `conn.commit()` from `update_event_state_sweep()` or any other caller will commit them, leaving the DB with no prior events and an incomplete replacement. (b) `generate_news_summaries()` never inspects `_extraction_degraded` or `_persistence_degraded` from `run_pipeline()`. On extraction failure, `run_pipeline()` returns the flag and preserves prior DB events, but `generate_news_summaries()` generates prose with zero events, writes a `news_summaries` row for the new snapshot hash, and the content-addressed cache then serves this degraded summary on every subsequent refresh — silently blocking structured intelligence until the article set changes.

## Proposed approach

- **Rollback handler:** Wrap the entire `persist_events()` body in `try/except Exception: conn.rollback(); raise`. This ensures that any mid-write failure leaves the DB in its prior committed state. In `run_pipeline()`, catch a `persist_events()` exception, skip `update_event_state_sweep()`, and return `_persistence_degraded=True`.
- **Atomicity test:** Write a test that monkeypatches `conn.execute` to raise after the DELETE but before all event INSERTs complete. Assert that: prior events still exist in the DB; no snapshot row was committed; no partial events or themes were committed.
- **Degraded-cache gate:** In `generate_news_summaries()`, check the `_extraction_degraded` and `_persistence_degraded` flags from `run_pipeline()`. If either is set: do not write a `news_summaries` row for the new snapshot hash (the prior row, if any, remains cached as the last good result); optionally add a `status='EXTRACTION_DEGRADED'` or `status='PERSISTENCE_DEGRADED'` marker to `news_summaries` for dashboard visibility; allow fresh prose to be generated but do not certify the new hash as successfully processed.

## Touches

- `agents/news/intelligence.py` — `persist_events()` rollback handler; `run_pipeline()` persistence-degraded propagation and sweep gate
- `portfolio_ai.py` — `generate_news_summaries()` degradation-aware cache write; `news_summaries` status field (may need schema migration)
- `tests/test_news_intelligence.py` — rollback atomicity proof test; degraded-cache propagation test

## Done when

- [ ] `persist_events()` rolls back and re-raises on any exception; no partial state can be committed by a later caller
- [ ] `run_pipeline()` returns `_persistence_degraded=True` and skips `update_event_state_sweep()` when `persist_events()` raises
- [ ] Test proves that a mid-persist failure leaves prior events intact and no partial writes committed
- [ ] `generate_news_summaries()` does not write a `news_summaries` cache row for a degraded snapshot hash
- [ ] Dashboard can surface a STALE/DEGRADED indicator when the last structured run was degraded
