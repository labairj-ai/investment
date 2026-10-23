# TODO 0828 — Activate Read-Only Continuous Discovery and Signal Collection

- **ID:** 0828
- **Status:** backlog
- **Priority:** high
- **Risk:** L3 — production scheduler / read-only observation
- **Depends:** 0825
- **Blocks:** 0829, 0831

## Problem

PR #10 deployed the discovery, signal and scheduler infrastructure, but all continuous-improvement activation settings remain disabled.

The next safe operational step is to enable only read-only observation and discovery.

No Builder execution should be enabled by this TODO.

## Scope

Install and enable reviewed units for:

- [ ] `development-scout.service`
- [ ] `development-scout.timer`
- [ ] development scheduler observer
- [ ] scheduler observer timer
- [ ] development signal collector
- [ ] signal collector timer

Do **not** enable:

- supervised build loop;
- autonomous implementation;
- autonomous PR publication;
- auto-merge.

## Read-only signal sources

Enable bounded collection for:

- [ ] GitHub CI failures;
- [ ] service restarts/failures;
- [ ] dashboard HTTP health;
- [ ] application errors where sanitized;
- [ ] stale jobs/timers;
- [ ] performance regressions;
- [ ] accessibility/mobile observations;
- [ ] TODO/FIXME inventory;
- [ ] user-submitted development signals.

## Scheduler acceptance

Observe at least three actual scheduled runs.

For every run record:

- trigger source;
- systemd invocation ID;
- scheduled slot;
- start time;
- end time;
- duration;
- candidate count;
- deduplicated count;
- suppressed count;
- unavailable signal sources;
- resulting candidate IDs;
- exact source head.

## State safety

Across all runs verify:

- [ ] holdings unchanged;
- [ ] investment database unchanged;
- [ ] recommendation state unchanged;
- [ ] no agent run triggers broker calls;
- [ ] no Builder invoked;
- [ ] no worktree implementation created;
- [ ] no PR created;
- [ ] no deployment invoked.

## Failure testing

- [ ] failed signal collection does not trigger implementation;
- [ ] duplicate daily timer execution deduplicates;
- [ ] stale spool fails closed;
- [ ] malformed signal fails closed;
- [ ] oversized signal inventory fails closed;
- [ ] backlog limit prevents excess candidate creation;
- [ ] daily candidate cap enforced.

## Dashboard

Expose:

- next run;
- last run;
- last successful run;
- last failure;
- discovered count;
- deduplicated count;
- source availability;
- scheduler health;
- stale threshold.

## Guardrails

- `autonomous_implementation=false`
- `supervised_loop_enabled=false`
- `supervised_publish_pr=false`
- `auto_merge=false`
- No new outbound model/network authority from Scout.
- Discovery remains read-only.

## Done when

- [ ] Three real scheduled runs succeed.
- [ ] Scheduler health is PASS.
- [ ] No production-state mutation observed.
- [ ] Durable run receipts exist.
