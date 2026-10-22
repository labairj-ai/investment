# Make Development Agent Review Mobile Friendly

- **ID:** 0762
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** medium
- **Depends:** 0761

## Problem

The user frequently reviews the Investment Dashboard from mobile devices, so candidate/PR triage must remain usable at narrow widths rather than becoming a desktop-only agent console.

## Scope and acceptance

- [ ] Design the candidate queue and detail views mobile-first for ~360–430px widths with no horizontal page scrolling.
- [ ] Use stacked cards or responsive tables that preserve candidate title, risk, stage and action-needed state at a glance.
- [ ] Ensure tap targets meet practical mobile sizing and that expandable evidence/reviewer details do not require hover.
- [ ] Collapse secondary metadata behind progressive disclosure while keeping high-risk warnings and failed gates always visible.
- [ ] Support long TODO titles, SHA/PR identifiers and error text without layout overflow.
- [ ] Preserve desktop information density at wider breakpoints without maintaining separate feature logic.
- [ ] Add accessibility labels/focus order for review controls introduced later.

## QA requirements

- [ ] Browser viewport tests cover 360, 390, 430 and representative desktop widths.
- [ ] Manual/physical-device acceptance remains explicitly open until observed on iPhone and Android.
- [ ] No horizontal overflow at required mobile widths for fixture data.
- [ ] Full suite passes.

## Implementation guardrails

- Do not hide risk warnings to save space.
- Do not rely on color alone for status/risk.
- Mobile work must not alter candidate governance semantics.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
