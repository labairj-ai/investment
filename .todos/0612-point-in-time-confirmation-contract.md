# Close Look-Ahead Leaks in All Confirmation Channels

- **ID:** 0612
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0609

## Problem

Three confirmation channels contain look-ahead leaks that allow information unavailable at snapshot time to vote. (a) Guardian run eligibility uses `started_at < snapshot_ts AND status='done'` — a run that started before but finished after the snapshot is selected, and findings created after the snapshot can vote. (b) The finding-level query dropped `af.created_at < snapshot_ts` and evaluates `expires_at > now` rather than at snapshot time, making the feature non-reproducible historically. (c) `_get_macro_score()` reads the current `holding_macro_scores` row without requiring `scored_at <= snapshot_captured_at`, so a macro score computed after the snapshot can confirm a news event from before it. All three must be closed before calibration data collection begins.

## Proposed approach

- **Guardian run:** Replace `started_at < snapshot_ts` with `finished_at IS NOT NULL AND finished_at < snapshot_ts`. This ensures only runs whose results fully existed at snapshot time are eligible.
- **Guardian finding:** Restore `af.created_at < snapshot_ts` to the finding query. Change expiry evaluation from `af.expires_at > time.time()` to `af.expires_at > snapshot_ts` so the feature is decision-time reproducible.
- **Macro channel:** In `_get_macro_score()` or its call site in `attach_confirmation()`, pass `snapshot_captured_at` and retrieve the latest row from `holding_macro_scores_history` where `scored_at <= snapshot_captured_at`. Fall back to no vote if no qualifying row exists.
- **Key test to add:** Guardian starts at T−5 min, news snapshot at T, Guardian finishes at T+5 min — assert `_get_agent_findings_flag()` returns None for that run.

## Touches

- `agents/news/intelligence.py` — `_get_agent_findings_flag()` (run eligibility + finding created_at + expiry at snapshot); `_get_macro_score()` or `attach_confirmation()` macro channel (point-in-time score lookup)
- `tests/test_news_intelligence.py` — start-before-finish-after Guardian test; macro channel snapshot-scoped test

## Done when

- [ ] Guardian run with `started_at < T` and `finished_at > T` cannot vote for a snapshot at T
- [ ] Guardian finding with `created_at > snapshot_ts` is excluded even if its run qualifies
- [ ] `expires_at` is evaluated at `snapshot_ts`, not `time.time()`
- [ ] Macro channel uses latest `holding_macro_scores_history` row with `scored_at <= snapshot_captured_at`; returns no vote if no qualifying row exists
- [ ] All new behaviors covered by tests
