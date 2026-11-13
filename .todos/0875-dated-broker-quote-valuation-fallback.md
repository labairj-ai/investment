# 0875 — Dated broker quote fallback for tracked net value

Status: in-progress
Base: 53f70764ab7585f92a4673322c90c4203f0e2099
Risk: L5 conservative financial display; task-authorized software repair only.

Problem: Yahoo omits an existing quarterly call. One unavailable liability hides
tracked net value and portfolio value goal despite a dated broker quote supplied
by the owner. Expiration and position identity must remain unchanged.

Scope: display-only broker bid/ask sidecar, explicit dry-run/apply importer,
identity/time/evidence validation, and shared valuation/source disclosure.
No investment.db writes, position mutation, broker access, daily P&L baseline,
financial safety policy, recommendation, scoring, historical chart or trading change.
Fresh valid Yahoo evidence wins. A manual quote is never refreshed by import time.

Acceptance: exact-contract midpoint fills only missing feed coverage; source and
original quote timestamp disclosed; stale, future, malformed or changed-position
evidence rejected; same normal freshness and next-open expiry; database byte
identity across dry-run/apply; idempotent imports; both live UI consumers update.

Validation: focused synthetic fixtures, Node frontend tests, unchanged TODO/agent/
governance/release-baseline/CC gates and full exact-head Linux CI. Use existing
owner and protected source release path, verify actual live values and invariance.
Keep open until deployment evidence and final QA are complete.

Additional owner request: daily P&L shows dollars plus percentage; move component,
coverage and timing text inside the existing Sources & coverage accordion. The
percentage denominator must match the known components in the displayed dollars:
prior stock value less verified prior liability of those same priced calls. Partial
coverage stays labelled partial; unavailable/nonpositive denominators stay blank.
Expose verified prior liability in the read-only daily report only; do not change
P&L formulas, quote eligibility or any financial safety policy.
