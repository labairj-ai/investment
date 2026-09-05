# Add Candidate Comparison and Portfolio-Relative Ranking

- **ID:** 0022
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0014, 0021

## Problem

When multiple Buffett screen winners or manual candidates exist simultaneously, the system evaluates them independently and may surface all of them as roughly equivalent opportunities. This misses the key portfolio question: "If I were deploying $X into one of these today, which one actually improves my portfolio the most?" Ranking candidates relative to each other — with portfolio fit as a first-class signal — produces a qualitatively better answer than independent scores.

## Proposed approach

Extend the Opportunity Hunter (0014) with a comparison mode that activates when ≥ 2 candidates have `status=active` in `candidate_universe`.

**Composite candidate score:**
`CandidateScore = Quality + Valuation + ExpectedReturn + PortfolioFit + Risk + EvidenceConfidence`

All components scored 0–100 and weighted (weights configurable in `strategy_config`).

- **Quality** — from Buffett screener composite
- **Valuation** — from Buffett screener valuation metrics
- **ExpectedReturn** — analyst consensus target vs. current price, adjusted for holding period
- **PortfolioFit** — layer deficit bonus, sector/factor correlation penalty vs. existing holdings, concentration penalty if adding would breach `max_single_position_pct`
- **Risk** — leverage, earnings variability, macro sensitivity for current regime
- **EvidenceConfidence** — from `confidence.py`, based on data freshness and completeness

**Comparison output (dashboard table):**

| Candidate | Fundamental | Valuation | Portfolio Fit | Confidence | Rank |
|---|---|---|---|---|---|
| INGR | 87 | 82 | 91 | 89 | 1 |
| SCSC | 84 | 88 | 76 | 85 | 2 |
| TGT | 73 | 91 | 79 | 92 | 3 |

**LLM role (narrow):** receives top 3 by composite score + current portfolio context. Answers which of the 3 best fits the portfolio and why. Does not generate the scores. Output is a single RESEARCH recommendation naming the top-ranked candidate with rationale.

**Trigger:** runs when ≥ 2 candidates are active, or when a new candidate is added via manual add that creates a comparison opportunity.

## Touches

`agents/opportunity_agent.py` (add comparison mode), `candidate_universe` table (from 0021), `generate_dashboard.py` (comparison table UI), `serve.py` (`GET /api/candidates/comparison` endpoint)

## Done when

- [ ] Comparison table renders in dashboard when ≥ 2 active candidates exist
- [ ] All 6 score dimensions calculated deterministically per candidate
- [ ] Portfolio Fit penalizes candidates redundant with existing holdings
- [ ] LLM receives ≤ 3 candidates (top-ranked by composite score)
- [ ] Single RESEARCH recommendation produced naming the top candidate
- [ ] Table sortable by any column in the UI
- [ ] Browser QA (mandatory — do not skip): With ≥ 2 active candidates in the universe, open the dashboard in a browser and verify: (a) zero JS console errors, (b) comparison table renders with all 6 score columns, (c) table is sortable by clicking column headers, (d) a single RESEARCH recommendation names the top-ranked candidate. Do NOT check this box without completing live browser testing.

