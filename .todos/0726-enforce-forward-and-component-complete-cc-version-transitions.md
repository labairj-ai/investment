# Enforce Forward and Component-Complete CC Version Transitions

- **ID:** 0726
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0720, 0724, 0725

## Problem

Version inequality permits backward or malformed releases and unrelated component bumps. Protected metadata can drift without behavioral authorization.

## Implementation guardrails and acceptance

- [ ] Use canonical numeric component parsers; required bump must move forward without lexical ordering or silent normalization.
- [ ] Engine hash change requires forward model version; simulator hash change requires forward simulator contract version; both require both.
- [ ] Simulator version alone cannot satisfy simulator contract bump; unrelated component cannot satisfy another required bump.
- [ ] Reject protected behavioral metadata changes when corresponding behavior is unchanged; no gratuitous version churn.
- [ ] Policy and cadence versions drive exact manifest authorization and require corresponding simulator contract change with a forward contract bump.
- [ ] Findings distinguish wrong component, missing bump, backward, malformed, and unjustified metadata drift; name prior/proposed values.
- [ ] Test every canonical historical version format, backward/malformed variants, policy/cadence changes, and multi-component success.
- [ ] No automatic version mutation or behavioral/economic changes. Run focused/full suites and release gate.

## Completion

Pending full QA and actual GitHub Actions verification.
