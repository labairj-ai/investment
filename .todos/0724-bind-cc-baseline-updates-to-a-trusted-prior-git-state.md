# Bind CC Baseline Updates to a Trusted Prior Git State

- **ID:** 0724
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0718, 0719, 0723

## Problem

The baseline in the candidate checkout can be rewritten alongside behavioral code to erase drift. Authorization must compare trusted prior Git state to computed current identity.

## Implementation guardrails and acceptance

- [ ] PR uses the exact event base SHA; push to main uses event.before. Read baseline from checked-out Git history without network.
- [ ] Never silently trust candidate as prior. Missing, malformed, unknown-schema or unresolved prior rejects.
- [ ] Candidate must exactly equal computed current state after transition authorization; missing promotion or malformed candidate rejects.
- [ ] Direct or regenerated baseline plus changed behavior cannot bypass manifest or component version enforcement.
- [ ] Expose explicit prior SHA/file API and CLI inputs; event authority rejects stale or unrelated SHA overrides.
- [ ] Exercise real temporary Git history A→B, approved transition, direct rewrite rejection, and B→C replay rejection.
- [ ] Report exact prior SHA and short prior/current hashes. No CI writes, production DB writes, or V3 activation.
- [ ] Run focused/full suites and release gate; verify PR and push event shapes in GitHub Actions.

## Completion

Pending full QA and actual GitHub Actions verification.
