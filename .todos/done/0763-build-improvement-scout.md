# Build Improvement Scout

- **ID:** 0763
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0762

## Problem

A continuous coding agent needs a bounded discovery process that identifies worthwhile work without immediately modifying code or creating an endless stream of speculative features.

## Scope and acceptance

- [x] Implement a read-only Scout that gathers signals from approved sources: active TODOs, recent completed work, git history, CI/test failures, application errors, performance/health metrics, TODO/FIXME markers and explicitly captured user feedback.
- [x] Have the Scout produce structured candidate proposals only; it must not edit source files, create branches, deploy, merge or mutate investment state.
- [x] Require every proposal to include evidence, user/problem impact, affected area, estimated scope, likely validation method and duplicate-candidate check.
- [x] Cap proposals per run and enforce diversity so repeated feature-addition ideas cannot crowd out reliability, simplification, removal, refactor or accessibility work.
- [x] Support discovery categories `FIX`, `SIMPLIFY`, `REMOVE`, `CONSOLIDATE`, `REFACTOR`, `OPTIMIZE`, `TEST`, `DOCUMENT` and `ADD`.
- [x] Suppress candidates lacking concrete repository or operational evidence; speculative ideas may be recorded separately as low-confidence suggestions but cannot auto-enter implementation.
- [x] Produce deterministic run metadata and trace which source signals generated each candidate.

## QA requirements

- [x] Fixture-based Scout tests cover each input source and duplicate suppression.
- [x] Prove Scout performs no repository writes or production DB mutations.
- [x] Run with network/model failures and verify partial evidence cannot silently become an approved candidate.
- [x] Full suite passes.

## Implementation guardrails

- Initial Scout cadence is manual/on-demand; scheduling is deferred to 0782.
- Do not reward the Scout for number of candidates generated.
- Missing telemetry must be reported as unavailable rather than inferred.

## Numbering history

Renumbered from coding-agent task 0748 to 0763; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/discovery.py: scout`. See [harness implementation](../../docs/plans/development-agent-harness.md) and [operator contract](../../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.


## Evidence review — 2026-11-09

Implementation and original checklist reviewed against current deployed source `6db0b6ccf2494721d024a6e29ecf8fbb55c66bf6`, including merged PRs #52–#55 and the earlier Scout foundation. dev_agent/discovery.py consumes exact reviewed Git blobs for markers, active TODO hashes and recent completed paths, records recent Git history, and accepts explicit source signals. signals.py validates CI, runtime/performance and user evidence; unavailable feedback is explicit, not fabricated. store.py validates concrete evidence/impact/area and supplies explicit UNESTIMATED file scope, lineage and duplicate identity. scout enforces proposal/category caps, all nine declared categories and evidence/validation requirements. scheduler records source/run provenance; no model is required by discovery. Source/fixture, unavailable-source and adversarial coverage plus accepted host receipts prove separation from implementation and protected investment state. See the review matrix for exact test references and CI. Initial on-demand capability remains available for isolated/operator use; production now deliberately requires a genuine timer under 0782. No production manual run was performed.

[Evidence matrix and retained receipt](../../docs/evidence/development-todo-review-20261109/README.md). Historical progress notes above describe their original dates; this review records final disposition. Supervised, autonomy, physical-device and overall certification remain separate.
