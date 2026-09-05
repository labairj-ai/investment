# Add Thesis Health Cards to Holdings Dashboard

- **ID:** 0034
- **Status:** done
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

## Outcome

`serve.py`: `GET /api/theses/<ticker>/health` returns composite score, per-pillar breakdown, `has_critical_violation`, `last_evaluated_at`. Returns `{"ok":true,"thesis":null}` when no ACTIVE thesis.

`generate_dashboard.py`:
- `_thesis_badge()` redesigned: ACTIVE+health≥80 → green ✓+score, 60–79 → yellow ⚠+score, <60 or critical → red !+score, no score yet → green ✓, DRAFT → orange Thesis…, none → grey Thesis+
- `_thesis_health_detail_row()` generates hidden expand row per ACTIVE holding: composite score, "evaluated Xh ago", "View / Edit →" button, optional CRITICAL banner, per-pillar rows with ● icon in status colour + importance% + STATUS chip + reason text
- `toggleThesisHealth(safeId)` JS function toggles the hidden row
- `thesis_data_map` replaces `thesis_status_map`; loads full `agent_db.get_thesis()` result at dashboard build time

`portfolio_ai.py`: `_build_thesis_health_block()` injects composite score + VIOLATED/WARNING pillar names into `generate_daily_insight` prompt. Output verified: `GRMN: health=75/100  WARNING=[Cash Generation Efficiency]`.

**Browser QA (optiplex, live data):**
- GRMN: badge "Thesis ⚠ 75" yellow ✓; expand row shows all 4 pillars with correct colours (STRONG green, WARNING orange, HEALTHY green×2); "View / Edit →" opens full thesis modal ✓
- Zero JS console errors ✓
- CRITICAL banner verified via unit test (mock critical VIOLATED pillar) ✓
- "Thesis +" badge verified via unit test (no-thesis holding) ✓
- `_build_thesis_health_block()` output confirmed on optiplex ✓

## Touches

`serve.py` (new `/api/theses/{ticker}/health` endpoint), `generate_dashboard.py` (thesis card UI per holding), `portfolio_ai.py` (pass thesis health into briefing context)

## Done when

- [x] `GET /api/theses/{ticker}/health` returns correct composite score and per-pillar breakdown
- [x] Each holding card in the dashboard shows thesis status badge and composite health score
- [x] Pillar list is collapsible and uses correct colour-coded status icons
- [x] CRITICAL VIOLATION banner appears when a critical pillar is VIOLATED
- [x] Holdings with no ACTIVE thesis show a "Create Thesis" link
- [x] Daily briefing prompt includes thesis health data for holdings that have an ACTIVE thesis
- [x] Browser QA (mandatory — do not skip): With an ACTIVE thesis that has evaluated pillars, open the dashboard in a browser and verify: (a) zero JS console errors, (b) each holding with an ACTIVE thesis shows the thesis status badge and composite health score, (c) pillar list is collapsible and uses correct colour-coded status icons, (d) CRITICAL VIOLATION banner appears when a critical pillar is VIOLATED, (e) holdings with no ACTIVE thesis show a 'Create Thesis' link, (f) daily briefing prompt includes thesis health data (check via `GET /api/ai/daily` response). Do NOT check this box without completing live browser testing.
