# Bind CC Baseline Updates to a Trusted Prior Git State

- **ID:** 0724
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0718, 0719, 0723

## Problem

The baseline in the candidate checkout can be rewritten alongside behavioral code to erase drift. Authorization must compare trusted prior Git state to computed current identity.

## Implementation guardrails and acceptance

- [x] PR uses the exact event base SHA; push to main uses event.before. Read baseline from checked-out Git history without network.
- [x] Never silently trust candidate as prior. Missing, malformed, unknown-schema or unresolved prior rejects.
- [x] Candidate must exactly equal computed current state after transition authorization; missing promotion or malformed candidate rejects.
- [x] Direct or regenerated baseline plus changed behavior cannot bypass manifest or component version enforcement.
- [x] Expose explicit prior SHA/file API and CLI inputs; event authority rejects stale or unrelated SHA overrides.
- [x] Exercise real temporary Git history A→B, approved transition, direct rewrite rejection, and B→C replay rejection.
- [x] Report exact prior SHA and short prior/current hashes. No CI writes, production DB writes, or V3 activation.
- [x] Run focused/full suites and release gate; verify PR and push event shapes in GitHub Actions.

## Completion

Completed 2026-10-13. Implementation: 5da9016; final follow-up corrects the version_bumped summary to require all component-forward transitions.

- Local focused suites: 126 passed, 0 skipped, 0 failed.
- Adversarial suite alone under GITHUB_ACTIONS=true: 24 passed, 0 failed.
- Local full suite: 2079 passed, 16 skipped, 0 failed.
- GitHub Actions: 2077 passed, 18 skipped, 0 failed; all release gates executed successfully.
- CI evidence: https://github.com/labairj-ai/investment/actions/runs/38485375047
- CI trusted prior: c4bbd36187bec0efeb8ff56434d174bccdaaab19.
- PR and push event fixtures both executed in real CI, including real temporary Git histories and subprocess A→B approval/B→C replay rejection. The workflow itself was triggered by a push to main.
- TODO mismatch fixture exited 1; corrected temporary fixture exited 0.
- Release failure inventory and committed CC baseline are unchanged; no new waiver.
- Production baseline-update guard remains fail-closed for both CI flags. V3 remains observe-only; no economics or DB changes.
