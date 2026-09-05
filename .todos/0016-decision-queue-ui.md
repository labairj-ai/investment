# Add Decision Queue UI to Dashboard (Phase 7)

- **ID:** 0016
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0008, 0010, 0011, 0012

## Problem

The current dashboard leads with an AI Insight panel that the user must scroll to and manually interpret. There is no concept of "these items need your attention today, ranked by urgency." Without a Decision Queue, agent findings have nowhere to surface — they'd just be DB rows the user would never see. The queue is what makes the system feel agentic rather than analytical.

## Proposed approach

Add a "PORTFOLIO DECISION QUEUE" section at the top of the dashboard, above the existing AI Insight panel.

**Section header:**
- Count of open items + total positions reviewed today
- Timestamp of last agent run

**Each queue card (sorted by priority desc):**
- Badge: finding type (THESIS REVIEW / COVERED CALL / TAX / RISK / OPPORTUNITY)
- Priority score (top right, e.g., "Priority 91")
- Ticker + confidence percentage
- "Why now" — 1–2 sentences from agent
- Agent recommendation — action + 1 sentence rationale
- Critic verdict line — "Approved" / "Caution: [strongest_objection]" / "Challenged"
- For CC cards: show strike, expiration, CC alpha, regret %, IV richness inline
- Three buttons: **[Accept]** / **[Reject]** / **[Defer]**
  - Accept/Reject/Defer call `POST /api/agents/recommendations/{id}/decision`
  - On decision, card collapses or moves to a "Resolved today" section

**Below queue:** "No action: N other positions reviewed" — shows the system is working even on quiet days.

**Priority calculation** (deterministic):
`Priority = 0.35*I + 0.25*U + 0.25*C + 0.15*SF`
- I = financial/portfolio impact (from finding metrics)
- U = urgency (time-sensitivity: CC expiring, lot crossing LT, earnings tomorrow = high)
- C = confidence score
- SF = strategy fit (does this address a known layer deficit or thesis risk?)

Implementation: add to `generate_dashboard.py` as a new section rendered before the existing AI Insight. The section polls `GET /api/agents/recommendations?status=open` on page load and re-polls every 60s.

## Touches

`generate_dashboard.py`, `serve.py` (API from 0008), `agent_db.py`

## Done when

- [ ] Decision Queue section renders above AI Insight
- [ ] Cards display finding type, ticker, confidence, why-now, recommendation, critic verdict
- [ ] Accept/Reject/Defer buttons call the API and update card state without page reload
- [ ] "No action: N positions reviewed" footer present
- [ ] Empty queue shows "No items require attention" — not an error state
- [ ] CC cards show strike, expiration, CC alpha, regret %, IV richness
- [ ] Priority formula implemented and cards sorted correctly
- [ ] Browser QA (mandatory — do not skip): Trigger a dashboard refresh so at least one open recommendation exists. Open the dashboard in a browser and verify: (a) zero JS console errors, (b) Decision Queue renders above AI Insight with correct card fields (type, ticker, confidence, why-now, critic verdict), (c) Accept/Reject/Defer update card state without page reload, (d) 'No action: N positions reviewed' footer present, (e) empty queue shows 'No items require attention' (not an error). Do NOT check this box without completing live browser testing.

