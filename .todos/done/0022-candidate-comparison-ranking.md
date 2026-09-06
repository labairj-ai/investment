# Add Candidate Comparison and Portfolio-Relative Ranking

- **ID:** 0022
- **Status:** done
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

## Outcome

- `agents/opportunity_agent.py`: Added `_score_risk()` (inverse value-trap risk + quality stability), `_composite_6()` (Q25/V20/Fit20/Cat15/Safety10/Ev10), `_llm_compare()`, and public `score_for_comparison()`. Cross-references `candidate_universe` rows with `buffett_winners` for scoring data; falls back to buffett_score-only for manual candidates not in the screener.
- `serve.py`: `GET /api/candidates/comparison` calls `score_for_comparison`, returns `{comparison_available, candidates, recommendation}`.
- `generate_dashboard.py`: Comparison card above Candidate Universe table. 10 columns (# Ticker Quality Valuation Fit Catalyst Safety Evidence Composite Sector), color-coded bar charts, sortable by clicking any header, top rank gets 🏆, Research Pick callout below table. Card hidden when < 2 eligible candidates.
- Browser QA (2026-09-05): zero JS errors; table rendered with all 6 score columns; sorted by Valuation confirmed working; INCY ranked #1 (composite 75), Research Pick showing.
- Note for 0027/0014: `score_for_comparison()` is importable from `agents.opportunity_agent` for any future use.
- ExpectedReturn dimension: mapped to Valuation (PE/P-FCF/EV-EBITDA) — no analyst target data in buffett_winners. Risk mapped to new `_score_risk()`.

## Touches

`agents/opportunity_agent.py` (add comparison mode), `candidate_universe` table (from 0021), `generate_dashboard.py` (comparison table UI), `serve.py` (`GET /api/candidates/comparison` endpoint)

## Done when

- [x] Comparison table renders in dashboard when ≥ 2 active candidates exist
- [x] All 6 score dimensions calculated deterministically per candidate
- [x] Portfolio Fit penalizes candidates redundant with existing holdings
- [x] LLM receives ≤ 3 candidates (top-ranked by composite score)
- [x] Single RESEARCH recommendation produced naming the top candidate
- [x] Table sortable by any column in the UI
- [x] Browser QA (mandatory — do not skip): With ≥ 2 active candidates in the universe, open the dashboard in a browser and verify: (a) zero JS console errors, (b) comparison table renders with all 6 score columns, (c) table is sortable by clicking column headers, (d) a single RESEARCH recommendation names the top-ranked candidate. Do NOT check this box without completing live browser testing.

