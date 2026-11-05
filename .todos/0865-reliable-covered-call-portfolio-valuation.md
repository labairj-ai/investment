# TODO 0865 — Reliable covered-call portfolio valuation

- **ID:** 0865
- **Status:** in-progress
- **Created:** 2026-11-05
- **Priority:** high
- **Risk:** L5 per risk-surface-2 whole-diff classification (unknown dashboard surface and unresolved dynamic protected dependency); display valuation and shared legacy mark refresh, no policy or execution changes
- **Source:** Owner request to reconcile recurring portfolio value mismatch; reference approximately $221,170.15
- **Base:** d36b7b415517424b5c20bbfe952c98a1d294d502

## Plan and acceptance

The existing dashboard subtracts undated legacy marks, substitutes zero for missing marks, and uses gross stock value for goals. Latest production observations had seven failed refreshes, a missing NFLX mark, gross stocks $229,636.27400569533 and legacy liability $5,735.00. These observations do not establish brokerage equity or authorize changing stored investment state.

- [x] Use read-only session/identity/freshness-verified quotes for every open call; reject incomplete coverage rather than substituting zero, old marks or entry premiums.
- [x] Separate current midpoint availability from previous-close history availability; never fabricate daily P&L.
- [x] Share nullable net value across headline, portfolio goal and net-value yield; preserve gross-stock allocation denominators and label stock-only gain/history.
- [x] Disclose gross stocks, option coverage, quote observations, source/session and cash/instrument exclusions; expire open-page option valuations.
- [x] Add synthetic reconciliation, stale/missing/partial coverage, history outage, no-write and client/dashboard integration regressions.
- [ ] Full CI suite, TODO consistency, exact release-baseline and unchanged CC contract gates on exact head.
- [ ] Review candidate diff and record exact SHA, real CI URL, skip inventory and any unavailable checks.
- [ ] PR/owner release path and applicable financial canaries; verify actual deployed source and served page. Do not claim production fixed without deployment evidence.

No brokerage calls, account mutation, policy changes, inferred cash or forced reconciliation target. Remaining brokerage timestamp/cash/option statement evidence is needed for exact reconciliation, not for implementing the reliability fix.
