# TODO 0821 — Add Real Operational Signals to Development-Agent Discovery

- **ID:** 0821
- **Status:** in-progress
- **Priority:** high
- **Risk:** L2/L3 — read-only observability
- **Depends:** 0820
- **Blocks:** 0822, 0824

## Problem

Current discovery explicitly reports CI, telemetry, performance and user feedback as unavailable.

Static TODO/FIXME and architecture analysis are useful but insufficient for an agent expected to continually create, enhance, fix and update the site.

The agent needs evidence from actual application behavior.

## Scope and acceptance

Add read-only, bounded signal collectors for:

### CI

- [ ] Recent failed GitHub Actions runs.
- [ ] Repeated failing tests.
- [ ] Flaky test patterns.
- [ ] Skipped-test growth.
- [ ] CI duration regressions.
- [ ] Governance/release gate failures.

### Runtime health

- [ ] `investment.service` failures/restarts.
- [ ] HTTP health failures.
- [ ] HTTP 5xx counts where available.
- [ ] repeated application exceptions.
- [ ] failed scheduled jobs/timers.
- [ ] stale jobs.

### Performance

- [ ] slow dashboard generation.
- [ ] slow API endpoints where observable.
- [ ] expensive repeated queries.
- [ ] page-size or asset-size regressions where measurable.
- [ ] bounded trend comparisons rather than one-off noise.

### UX/mobile

- [ ] viewport overflow.
- [ ] obviously inaccessible touch targets.
- [ ] keyboard/navigation issues detectable by automation.
- [ ] missing labels/ARIA issues.
- [ ] mobile layout regressions.
- [ ] Lighthouse or equivalent bounded checks if practical.

### Code quality

- [ ] TODO/FIXME.
- [ ] import cycles.
- [ ] duplicated nontrivial helpers.
- [ ] repeated exception-handling patterns.
- [ ] dead code candidates with evidence.
- [ ] deprecated API usage.
- [ ] stale dependencies where a safe update path exists.

### User-requested improvement signals

- [ ] Accept explicitly submitted owner feedback as a high-confidence signal.
- [ ] Preserve source as `user`.
- [ ] Do not infer owner intent from unrelated conversation data.
- [ ] Require a concrete problem/outcome statement.

## Signal schema

Every candidate signal must contain:

- source
- observed timestamp
- evidence location
- problem
- affected files/components
- impact
- recurrence count where applicable
- confidence
- candidate category
- proposed outcome
- validation method
- whether the observation is synthetic or production-derived

## Deduplication

- [ ] Stable identity for recurring problems.
- [ ] Repeated occurrence increments evidence rather than creating unlimited duplicates.
- [ ] Resolved candidate can recur only with new post-fix evidence.
- [ ] Known accepted exceptions remain suppressed until expiry.

## Security requirements

- [ ] Read-only collectors only.
- [ ] No broker calls.
- [ ] No production DB writes.
- [ ] No secrets in candidate evidence.
- [ ] No full raw log retention.
- [ ] Bound extracted log snippets.
- [ ] Redact obvious credentials/tokens.
- [ ] Do not send private operational data to an external model unless explicitly approved.

## Required tests

- [ ] Synthetic CI failure produces candidate.
- [ ] Repeated same CI failure deduplicates.
- [ ] HTTP failure produces candidate.
- [ ] transient single healthy-recovery event can be deferred.
- [ ] recurring service restart raises severity.
- [ ] mobile accessibility issue produces appropriate category.
- [ ] user-submitted signal receives correct source.
- [ ] secret-like text is redacted.
- [ ] signal cannot mutate production.

## Done when

- [ ] Daily scout can generate candidates from real operational evidence.
- [ ] Dashboard shows signal provenance.
- [ ] The scout no longer reports CI/telemetry/performance/user feedback globally unavailable where collectors have been enabled.
