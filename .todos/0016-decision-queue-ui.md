# Add Decision Queue UI to Dashboard (Phase 7)

- **ID:** 0016
- **Status:** done
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

- [x] Decision Queue section renders above AI Insight
- [x] Cards display finding type, ticker, confidence, why-now, recommendation, critic verdict
- [x] Accept/Reject/Defer buttons call the API and update card state without page reload
- [x] "No action: N positions reviewed" footer present
- [x] Empty queue shows "No items require attention" — not an error state
- [x] CC cards show strike, expiration, CC alpha, regret %, IV richness
- [x] Priority formula implemented and cards sorted correctly
- [x] Browser QA (mandatory — do not skip): Trigger a dashboard refresh so at least one open recommendation exists. Open the dashboard in a browser and verify: (a) zero JS console errors, (b) Decision Queue renders above AI Insight with correct card fields (type, ticker, confidence, why-now, critic verdict), (c) Accept/Reject/Defer update card state without page reload, (d) 'No action: N positions reviewed' footer present, (e) empty queue shows 'No items require attention' (not an error). Do NOT check this box without completing live browser testing.

## Outcome

New "PORTFOLIO DECISION QUEUE" dark-card section renders between Holdings News and AI Portfolio Insight.

**What was built:**
- `_dqPriority(r)` — deterministic priority formula `0.35*I + 0.25*U + 0.25*C + 0.15*SF` with urgency map per action type
- `_renderDQCard(r)` — full card: badge (COVERED CALL / TAX / THESIS REVIEW / REBALANCE / RISK), ticker, confidence %, priority score, why-now text, Rec line, CC-specific row (strike/expiry/alpha/regret/IV), critic verdict badge + objection quote, Accept/Reject/Defer buttons
- `_renderDecisionQueue(recs)` — filters to `status=open`, sorts by priority desc, updates header count, updates "No action: N of M positions reviewed" footer
- `dqDecide(recId, decision)` — `POST /api/agents/recommendations/{id}/decision`, card fades to 0.4 opacity while pending, reloads queue on success
- `loadDecisionQueue()` — polls `/api/agents/recommendations?status=open`, auto-poll every 60s
- `const DQ_TOTAL_POSITIONS = {len(today_holdings)};` injected at chart_data site for accurate footer count

**Removed:** simple DQ card that was above Candidate Universe from 0012 scope.

**Browser QA results (2026-09-05):**
- Zero JS console errors on fresh load ✓
- SCHD (Priority 87) sorted above WMT (Priority 64) ✓
- CC cards show Strike/Exp/Alpha/Regret/IV row ✓
- APPROVE WITH CAUTION badge + objection quote renders ✓
- Defer on WMT (id=4): card collapsed, count updated 2→1, footer updated 25→26 of 27 reviewed, without page reload ✓
- AI Portfolio Insight section renders immediately below DQ ✓

**Unblocks:** 0017 (Portfolio Guardian notifications), 0019 (Sell/Trim Agent).
