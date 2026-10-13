# Wire Real Independent Confirmation Sources

- **ID:** 0606
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0600, 0604

## Problem

Three confirmation channels are not truly independent. (a) `guardian_flags` has no production writer — the Portfolio Guardian writes to `agent_findings` via `agent_db.insert_finding()`, not to `guardian_flags`. The AGENT_FINDINGS channel therefore casts zero real votes. (b) The THESIS channel does not check whether thesis health was evaluated before the current news snapshot. If Thesis Monitor runs after Holding News and consumes the same news, the vote is circular: news → thesis degradation → thesis confirms news. (c) CAPEX events are routed through the generic revenue-YoY branch of `_get_fundamentals_trend()`. Revenue is not a relevant fundamental metric for a CAPEX event; an unrelated revenue trend should not corroborate or contradict a capital-expenditure signal. Same problem applies to PRODUCT, MANAGEMENT, LITIGATION: no economically relevant metric → no FUNDAMENTALS vote.

## Proposed approach

**AGENT_FINDINGS (a):**
- Retire `guardian_flags` as a data source (leave the table; do not delete rows or schema).
- Rewrite `_get_agent_findings_flag()` to query `agent_findings JOIN agent_runs` where `agent_type='portfolio_guardian'`, `ticker=event_ticker`, `created_at < snapshot_captured_at`, finding not expired, and `finding_type IN ('position_risk', ...)` — types that are genuinely independent of news (Guardian runs from price/weight/covariance/concentration, not from news articles).
- Inspect `agent_db.py` and `agents/portfolio_guardian.py` to confirm the exact column names before writing the query.

**THESIS independence (b):**
- Fetch `thesis_health_evaluated_at` (or `updated_at`) alongside `health_score` in `_get_thesis_health()`.
- In `attach_confirmation()`, skip the THESIS vote if `thesis_health_evaluated_at >= snapshot_captured_at` (or if timestamp is unavailable).
- Store `{"health_score": ..., "evaluated_at": ..., "independent": True/False}` in `confirmation_signals["thesis_health"]` for auditability.

**FUNDAMENTALS dispatch (c):**
- Remove CAPEX from `_FUNDAMENTALS_REVENUE_EVENTS`. If `company_financials` carries a `free_cash_flow` column, compute `capex/FCF` or `capex/revenue` as the CAPEX metric; otherwise return `None` for CAPEX events.
- Return `None` for PRODUCT, MANAGEMENT, LITIGATION, and any other event type with no economically relevant column mapping — no spurious revenue vote.

## Touches

- `agents/news/intelligence.py` — `_get_agent_findings_flag()`, `_get_thesis_health()`, `attach_confirmation()`, `_get_fundamentals_trend()`, `_FUNDAMENTALS_REVENUE_EVENTS`
- `agent_db.py` — read-only inspection to confirm `agent_findings` schema
- `tests/test_news_intelligence.py` — AGENT_FINDINGS reads from `agent_findings`; THESIS vote skipped when evaluated after snapshot; CAPEX returns `None` from fundamentals

## Done when

- [ ] `_get_agent_findings_flag()` queries `agent_findings JOIN agent_runs` with `agent_type='portfolio_guardian'`; `guardian_flags` is no longer queried
- [ ] Guardian findings with `created_at >= snapshot_captured_at` are excluded (independence check)
- [ ] THESIS vote is skipped when `thesis_health_evaluated_at >= snapshot_captured_at`; `evaluated_at` stored in `confirmation_signals`
- [ ] CAPEX event type does not route through the revenue-YoY branch; returns `None` if no CAPEX-specific metric is available
- [ ] PRODUCT, MANAGEMENT, LITIGATION return `None` from `_get_fundamentals_trend()` (no spurious revenue signal)
- [ ] Existing tests pass; new tests cover all three gaps above
