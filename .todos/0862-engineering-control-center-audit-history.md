# TODO 0862 — Create Immutable Audit History, Filters and Safe Export

- **ID:** 0862
- **Status:** backlog
- **Created:** 2026-10-29
- **Priority:** high
- **Risk:** L5 (conservative; verify via deterministic whole-diff policy)
- **Depends:** 0856
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Show the evidence-backed chronological record of every candidate/run/review/approval/merge/deployment decision so the owner can trace why a change progressed or stopped. Preserve provenance and reject invented or unverified events.

## Target files / interfaces

- `dev_agent/store.py (bounded read queries only if necessary)`
- `dev_agent/dashboard.py (audit read UI)`
- `tests/test_engineering_control_center.py`
- `scripts/check_development_agent_browser.mjs`

## Scope and acceptance

- [ ] Use append-only ledger event sequence as the authoritative timeline; include event ID, canonical UTC timestamp + ET formatting, actor identity source, candidate, linked PR, exact SHA, mode, policy version, reason and receipt ID.
- [ ] Event kinds distinguish discovered, planned, scored, builder iteration, reviewer finding, trusted validation, certification, Go/No-Go attestation, merge, deployment, rollback, scheduled/manual/fixture activity.
- [ ] Add server-filtered event type, actor, candidate, PR, status, date range with stable cursor pagination; preserve negative failure events after later success.
- [ ] Provide candidate-to-PR and PR-to-receipt drilldown with trusted HTTPS constrained links. Redacted JSON/CSV export uses bounded pages and explicit authentication, server-generated timestamps and provenance.
- [ ] Make status/freshness legible: signed/cross-verified proof differs from untrusted model claims and synthesized UI activity; unknown actor or missing receipt is stated as unavailable.
- [ ] Read-only history/export never edits event ledger, stores synthetic events, triggers certification or starts any host process.

## QA requirements and negative paths

- [ ] Prove deterministic ordering and no skipped/duplicated event rows with concurrent appends/cursor paging.
- [ ] Export redaction blocks credentials/bearer tokens/headers, raw prompts, financial rows, broker info, large logs and HTML injection; test CSV formula injection and malicious field names.
- [ ] Test missing or tampered event/receipt, forged owner actor, bogus timestamp, oversized event and broken candidate/PR relationships.
- [ ] Verify GET/export leaves event count, ledger hash and financial state unchanged; unauthorized export blocked.
- [ ] Keyboard/mobile timeline filters, timezone/DST and source labeling tests; full suite.

## Task-specific guardrails

- Do not rewrite, compact or delete historical negative evidence.
- Critical receipts honor indefinite retention; transient logs honor existing policy (14 days).
- Export is a view of source records, not an attestation itself.

## Non-negotiable boundaries

- Investment continues to use its own Development Agent and trusted single-owner Go/No-Go gateway, with no dependency on the separate Qwen microservice.
- No change to live portfolio/broker data, policy thresholds, Scout timers, validators, Oracle authority, credential owners, autonomy settings or deployment service solely for dashboard delivery.
- Distinguish committed config/source tests from live host acceptance and exact-SHA authoritative evidence; unknown/unavailable/stale remains blocked.
- This is governance-adjacent L5 planning until deterministic whole-diff classification establishes required review.
- For every completion, retain exact source/PR SHA, trusted gate receipts, all eight existing release gates, focused/full tests, independent review, browser evidence and remaining physical/external acceptance.

## Done when

Every audited step is securely searchable and traceable to source-backed evidence; sanitized exports and negative tests pass without mutations.
