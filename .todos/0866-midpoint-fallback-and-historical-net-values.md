# TODO 0866 — Midpoint fallback and historical tracked net values

- **ID:** 0866
- **Status:** in-progress
- **Created:** 2026-11-05
- **Priority:** high
- **Risk:** L5; display quote collection/scheduling and historical valuation projection
- **Base:** 3315e12d1ca6d1383be12461bc668bc3ceffaed9
- **Source:** Owner requests historical values reflecting covered calls and bid/ask midpoint fallback when actual marks are unavailable.

## Plan and acceptance

Live diagnostics confirm valid spreads while prior retrievals ran premarket and last-trade activity was incorrectly used as quote freshness. Preserve actual position marks when supplied with dated evidence; otherwise use a valid observed bid/ask midpoint, clearly labelled. Last trade time is diagnostic, not quote time. Do not change recommendation/risk/execution policy or call brokers.

- [x] Store bid, ask, mark basis and retrieval time; validate observation freshness without rejecting old/missing last-trade metadata.
- [x] Preserve append-only quote observations so a failed refresh cannot erase usable history; support fresh last-good midpoint fallback after transient failures.
- [x] Refresh tracked option display quotes every market quarter-hour through a bounded background job; no email, LLM, orders or account operations.
- [x] Derive historical net-value estimates from dated quotes, daily closes and exact position lifetimes. Preserve original stock snapshots and evidence. Do not project today's quotes backward or invent missing prices.
- [x] Show corrected historical values with coverage and source disclosure, and explicit gaps where all open calls cannot be valued. Keep stock-return calculations separate from net-value history.
- [x] Synthetic regressions for old last trades/live spreads, invalid spreads, failure recovery, archive immutability, scheduling boundaries, historical position lifetimes and missing history; dashboard/Node checks.
- [ ] Focused/full suite, unchanged TODO/release-baseline/CC gates; exact-head CI and risk/diff review.
- [ ] Existing owner release path, merged-main CI, financial canaries and post-deploy evidence. Execute requested market-data refresh/backfill only on OptiPlex with backup and separate receipt; no broker/account mutation or historical training-label rewrites.
