# Collect Coding-Agent Test and Evidence Receipts

- **ID:** 0755
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0747, 0752, 0753, 0754

## Problem

Agent-generated code needs machine-readable evidence comparable to the project's investment canaries and release receipts, rather than relying on prose claims that tests passed.

## Scope and acceptance

- [ ] Define an immutable development evidence receipt keyed by candidate/TODO, base SHA, head SHA and run iteration.
- [ ] Capture exact validation commands, exit codes, test counts, skipped/failed inventory, selected focused suites, full-suite status, release gates and reviewer decision.
- [ ] Record changed-file summary, risk classification, provider/model versions and relevant contract/config hashes.
- [ ] Hash or otherwise bind evidence to the exact head SHA so later code changes invalidate stale PASS receipts.
- [ ] Store large logs/artifacts by reference with bounded retention; preserve concise machine-readable summaries in the ledger.
- [ ] Distinguish `PASS`, `FAIL`, `PARTIAL`, `NOT_RUN` and `UNAVAILABLE`; missing evidence can never be treated as PASS.
- [ ] Provide a verification command that recomputes whether a current branch still matches its latest receipt.

## QA requirements

- [ ] Tamper tests prove edited code invalidates old receipts.
- [ ] Failure and skipped-test inventories are tested explicitly.
- [ ] Receipts remain read-only to downstream dashboard presentation.
- [ ] Full suite passes.

## Implementation guardrails

- Evidence collection must not rewrite baselines to manufacture success.
- Do not store secrets or full environment dumps.
- Use existing CI artifacts when authoritative rather than duplicating large payloads.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
