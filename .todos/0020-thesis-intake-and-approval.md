# Build Thesis Intake Form, AI Draft, and Approval Workflow (Phase 2)

- **ID:** 0020
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** 0004, 0003

## Problem

The basic thesis data model (0013) stores theses but has no defined path for creating them. The user should not have to manually specify financial thresholds — that's analytical grunt work the system should do. The user provides the philosophical layer (why I own this, what needs to remain true, when I'd sell). The AI drafts the analytical layer (specific metric thresholds, warning/violation bands, persistence periods). The user approves before any thesis becomes active. And critically: the agent can never silently rewrite an approved thesis. This item supersedes and expands the thesis creation aspect of 0013.

## Proposed approach

**Thesis intake fields (UI form per ticker):**

| Field | Type | Example |
|---|---|---|
| Why do I own this? | Free text | "Durable earnings growth driven by..." |
| Portfolio role | Enum | Core / Income / Growth / Speculative / Tactical |
| Expected holding period | Enum | 1–3 yr / 5+ yr / Indefinite |
| Key thesis conditions | List (3–5 items) | "Revenue growth remains strong" |
| What would make me sell? | Free text | "Competitive advantage materially deteriorates..." |
| What would make me trim? | Free text | "Position > 10% or valuation becomes extreme" |
| Conviction | 1–5 | 5 |
| Max comfortable position % | Float | 10.0 |
| Special considerations | Free text | "Prefer CC-friendly, LT tax treatment" |

**AI thesis drafting flow:**
1. User submits intake form via `POST /api/theses/{ticker}/draft`
2. System fetches current financials, historical ranges, analyst estimates for the ticker
3. LLM receives intake + financial data and drafts detailed thesis with:
   - Per-claim measurements with `metric`, `healthy`/`warning`/`violation` thresholds, `persistence` periods
   - Importance weights per claim (sum to 100)
   - Suggested falsification criteria grounded in actual historical ranges
4. Draft returned to dashboard as `DRAFT` status — not persisted yet

**Example AI-drafted claim:**
```json
{
  "claim": "Revenue growth remains strong",
  "importance": 25,
  "measurements": [
    {
      "metric": "revenue_growth_yoy",
      "healthy": "> 10%",
      "warning": "5%-10%",
      "violation": "< 5%",
      "persistence": "2 quarters"
    }
  ]
}
```

**Approval workflow:**
- Dashboard shows: "Proposed [TICKER] Investment Thesis — You can modify anything"
- User can edit any claim, threshold, weight, or condition inline
- `POST /api/theses/{ticker}/approve` — sets `status=ACTIVE`, `version=1`, `approved_by=USER`, `approved_at=now`
- Once active, **the agent cannot modify the thesis directly**

**THESIS_CHANGE_PROPOSAL mechanism:**
- If the Thesis Agent believes a claim should be updated, it creates a `THESIS_CHANGE_PROPOSAL` recommendation (not an automatic change)
- This surfaces in the Decision Queue like any other recommendation: user sees claim, proposed change, reason, and can Accept/Reject
- Only on Accept does thesis version increment and claim update

**API endpoints:**
- `POST /api/theses/{ticker}/draft` — triggers AI drafting, returns draft
- `PUT /api/theses/{ticker}/draft` — user edits draft
- `POST /api/theses/{ticker}/approve` — activates draft as version N
- `GET /api/theses/{ticker}` — current active thesis + claim statuses
- `GET /api/theses/{ticker}/history` — all versions

## Touches

`agents/thesis_agent.py` (expand from 0013), `investment_theses` + `thesis_claims` tables (from 0004), `serve.py` (new endpoints), `generate_dashboard.py` (thesis intake UI + draft review UI), `financials_fetcher.py`

## Done when

- [ ] Thesis intake form renders in dashboard for any held ticker
- [ ] AI draft is generated from intake + real financial data (not generic)
- [ ] Draft is editable inline before approval
- [ ] Approved thesis writes `status=ACTIVE`, `version=1`, `approved_by=USER` to DB
- [ ] Thesis Agent cannot write directly to `thesis_claims` for active theses — only via THESIS_CHANGE_PROPOSAL
- [ ] THESIS_CHANGE_PROPOSAL creates a Decision Queue recommendation with Accept/Reject
- [ ] Accepting a proposal increments thesis version and records change
