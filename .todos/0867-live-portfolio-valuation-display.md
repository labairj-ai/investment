# TODO 0867 — Keep open portfolio pages synchronized with refreshed quotes

- **ID:** 0867
- **Status:** in-progress
- **Created:** 2026-11-05
- **Risk:** L5 conservative; generated financial display artifact and browser synchronization
- **Base:** 58e3bb1767f754bbf96ab5f0a608d9d672fd3189
- **Source:** Same owner request for reliable bid/ask fallback and historical values; standing publication/deployment authorization.

## Plan and acceptance

PR48 refreshes quote records and generated HTML, but an already open browser keeps its initial snapshot and permanently hides an expired value until reload. Publish a small generated valuation JSON alongside the dashboard and poll it read only. Update headline/goals/yield together without reloading forms or initiating market-data/broker writes.

- [ ] Atomic generated snapshot publication on OptiPlex; no new HTTP mutation endpoint, broker calls or account changes.
- [ ] An open page restores a fresh value after quote expiry, hides missing/expired values, preserves request bounds and rejects malformed data.
- [ ] Synthetic generation, Node/browser behavior and stale-network regressions.
- [ ] Focused/full tests, exact release-baseline, TODO and unchanged CC contract gates; exact-head CI and whole-diff review.
- [ ] Existing owner release path, merged-main CI and actual live refresh/history verification, with separate historical-data backup/apply receipt. Keep TODO open until evidence is complete.
