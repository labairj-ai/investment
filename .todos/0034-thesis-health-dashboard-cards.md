# Add Thesis Health Cards to Holdings Dashboard

- **ID:** 0034
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0030, 0033

## Problem

After 0033 runs, `thesis_pillars.status`, `.score`, and `.reason` are populated but never shown to the user. The dashboard currently has no thesis-aware UI — a holding's thesis could be BROKEN and the user would only discover it by reading the Decision Queue. The goal is to surface thesis health inline on each holding's card so the user sees the signal at a glance, without having to navigate elsewhere.

## Proposed approach

**New API endpoint (`serve.py`):**
- `GET /api/theses/{ticker}/health` — returns: thesis status, composite health score (computed as `sum(pillar.importance * pillar.score / 100)`), per-pillar list (name, importance, status, score, reason, critical), last_evaluated_at. Returns 404 with `{"thesis": null}` if no ACTIVE thesis exists.

**Per-holding thesis card (`generate_dashboard.py`):**
- Thesis status badge: ACTIVE (grey), UNDER_REVIEW (yellow), BROKEN (red)
- Composite health score displayed as a number with colour coding: ≥80 green, 60–79 yellow, <60 red
- Collapsible pillar list — each row: status icon + pillar name + importance % + one-line reason
  - Status icons: STRONG ● green filled, HEALTHY ● green, WATCH ● yellow, WARNING ● orange, VIOLATED ● red, UNKNOWN ● grey
- If any `critical=1` pillar is VIOLATED: show a prominent red "CRITICAL VIOLATION" banner above the pillar list
- Holdings with no ACTIVE thesis: show a muted "No thesis — Create one" link pointing to the intake form (0032 flow)

**Newsletter integration (`portfolio_ai.py`):**
- When building the briefing context for a holding, fetch thesis health via `agent_db.get_thesis_pillars(thesis_id)` and include composite score + any VIOLATED pillars in the LLM prompt so the briefing agent can reference thesis health when discussing a position

## Touches

`serve.py` (new `/api/theses/{ticker}/health` endpoint), `generate_dashboard.py` (thesis card UI per holding), `portfolio_ai.py` (pass thesis health into briefing context)

## Done when

- [ ] `GET /api/theses/{ticker}/health` returns correct composite score and per-pillar breakdown
- [ ] Each holding card in the dashboard shows thesis status badge and composite health score
- [ ] Pillar list is collapsible and uses correct colour-coded status icons
- [ ] CRITICAL VIOLATION banner appears when a critical pillar is VIOLATED
- [ ] Holdings with no ACTIVE thesis show a "Create Thesis" link
- [ ] Daily briefing prompt includes thesis health data for holdings that have an ACTIVE thesis
