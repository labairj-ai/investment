# TODO 0807 — Tighten Risk Classification for Active HTML and SVG Content

- **ID:** 0807
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** medium
- **Depends:** 0746, 0794
- **Blocks:** future autonomous L2 presentation work

## Problem

`static/*.html` and `static/*.svg` are currently classified as L2 presentation surfaces.

HTML and SVG can contain executable or active browser behavior and should not automatically receive low-risk presentation classification.

## Scope and acceptance

- [ ] Separate passive presentation files from active browser content.
- [ ] CSS-only presentation changes may remain L2.
- [ ] Detect active HTML/SVG constructs including:
  - `<script>`
  - inline event handlers
  - `javascript:` URLs
  - forms
  - iframe/embed/object
  - external-resource loading
  - scriptable SVG constructs
  - dynamic module/script imports
- [ ] Escalate active HTML/SVG modifications to at least L3.
- [ ] Treat direct JavaScript modifications as human-started unless separately approved by future policy.
- [ ] Use whole-diff inspection, not file extension alone.
- [ ] Unknown/ambiguous active content must fail closed to higher risk.
- [ ] Record deterministic classification reasons.

## QA requirements

- [ ] CSS typography change remains L2.
- [ ] Passive HTML text change classified according to defined low-risk policy.
- [ ] Added `<script>` raises risk.
- [ ] Added `onclick=` raises risk.
- [ ] Added `javascript:` URL raises risk.
- [ ] Script-bearing SVG raises risk.
- [ ] External fetch/import behavior raises risk.
- [ ] Existing Development Agent mobile tests continue to pass.

## Implementation guardrails

- Do not rely on the coding model to decide whether HTML is active.
- Risk classifier must deterministically raise risk when uncertain.

## Source

User-supplied 2026-10-22 trust-boundary code-review follow-up. Backlog creation does not authorize implementation, promotion, pilot execution or autonomy activation.

## Implementation checkpoint — 2026-10-22

Implementation is on `codex/trust-boundary-0803-0809`; see the
[implementation plan](../docs/plans/development-agent-trust-boundaries-0803-0809.md)
and [trust-boundary contract](../docs/development-agent-trust-boundaries.md).
Source/fixture validation does not close environmental acceptance. This TODO remains
open pending its complete QA, required human decisions and exact-head CI evidence.
