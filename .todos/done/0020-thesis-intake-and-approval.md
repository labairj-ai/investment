# Build Thesis Intake Form, AI Draft, and Approval Workflow (Phase 2)

- **ID:** 0020
- **Status:** done
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

- [x] Thesis intake form renders in dashboard for any held ticker
- [x] AI draft is generated from intake + real financial data (not generic)
- [x] Draft is editable inline before approval
- [x] Approved thesis writes `status=ACTIVE`, `version=1`, `approved_by=USER` to DB
- [x] Thesis Agent cannot write directly to `thesis_claims` for active theses — only via THESIS_CHANGE_PROPOSAL
- [x] THESIS_CHANGE_PROPOSAL creates a Decision Queue recommendation with Accept/Reject
- [x] Accepting a proposal increments thesis version and records change
- [x] QA evaluation conducted: functionality verified working, no regressions introduced

## Outcome

**Files changed:**
- `agent_db.py` — added `approved_by`, `intake_json`, `draft_json` columns to `investment_theses` via safe ALTER TABLE; added `save_thesis_draft`, `get_thesis_full`, `approve_thesis`, `create_thesis_change_proposal`, `accept_thesis_change_proposal` helpers
- `agents/thesis_intake.py` (new) — `draft_thesis(ticker, intake)` calls `financials_fetcher.get_financial_summary()` + `ollama_client.generate_structured()` with structured claim schema; normalises importance sum to 100
- `serve.py` — added `do_PUT` method; added `/api/theses/<ticker>` (GET), `/api/theses/<ticker>/draft` (POST async job + GET job poll), `/api/theses/<ticker>/draft` (PUT), `/api/theses/<ticker>/approve` (POST), `/api/theses/<ticker>/accept-proposal` (POST); `_thesis_jobs` dict for async draft tracking
- `generate_dashboard.py` — imports `agent_db`; loads `thesis_status_map` for all holdings; adds `_thesis_badge()` helper; adds "Thesis" column to holdings table header and rows; adds thesis modal HTML (3-state: intake form / draft review / active + proposals); adds ~250 lines of JS (openThesisModal, submitThesisIntake, approveThesis, acceptThesisProposal, polling loop)

**Guard enforcement:** `save_thesis_draft` only matches `status='DRAFT'` rows — ACTIVE theses are never touched. Agents must call `create_thesis_change_proposal` which writes to `recommendations` (action='THESIS_CHANGE_PROPOSAL'), which surfaces in the modal Accept/Reject UI.

**Schema note:** intake + draft are stored as JSON blobs (`intake_json`, `draft_json`). 0030 migrates claims into the relational pillar/metrics/rules tables — these blobs are the source of truth until then.

**Next items unblocked by 0020:** 0019 (Sell/Trim Agent), 0031 (Thesis AI Proposal Engine), 0032 (Thesis Intake UI Full Schema).

