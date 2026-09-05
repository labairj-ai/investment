# Rebuild Thesis Monitor Agent for Full Pillar Schema

- **ID:** 0033
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0013, 0030, 0031, 0032

## Problem

The thesis monitor agent stub in 0013 was scoped around the old flat `thesis_claims` model (one claim, one metric, one threshold). The full schema from 0030 introduces `thesis_pillars`, `thesis_metrics`, and `thesis_rules` — a richer structure that supports multi-metric pillars, warning bands, persistence periods, qualitative signals, and explicit exit/trim/add rules. The agent needs to be rebuilt from scratch to evaluate this structure correctly, including a critical-pillar override that can fire THESIS_CRITICAL_VIOLATION independent of the aggregate score.

## Proposed approach

**Agent entry point:** `agents/thesis_agent.py`, registered as `thesis_monitor` in the orchestrator.

**Evaluation loop (per active thesis):**
1. Load all `thesis_pillars` + `thesis_metrics` + `thesis_rules` for the ticker via `agent_db` helpers from 0030
2. If trigger is earnings-related, call `financials_fetcher.fetch(ticker, force=True)` before any evaluation
3. **Deterministic metric pass:** for each `thesis_metrics` row, pull value from `company_financials`; apply operator from `healthy_rule_json` / `warning_rule_json` / `violation_rule_json`; check persistence across last N periods (query last N rows ordered by date)
4. **Qualitative signal pass:** read `QUALITATIVE_SIGNAL` rows from `thesis_rules`; build a prompt with recent news/transcript snippets and the signal description; call LLM to return present/absent + severity
5. **Pillar status resolution:** combine deterministic + qualitative results for each pillar → assign STRONG / HEALTHY / WATCH / WARNING / VIOLATED / UNKNOWN; map to score (95/80/65/40/10/50); write `thesis_pillars.status`, `.score`, `.confidence`, `.reason`, `.last_evaluated_at`
6. **Composite health:** `sum(pillar.importance * pillar.score / 100)` — computed inline, not stored
7. **Critical pillar check:** any `pillar.critical=1` reaching VIOLATED → emit `THESIS_CRITICAL_VIOLATION` finding (severity 90) and create EXIT_REVIEW recommendation immediately, skip remaining rule evaluation
8. **Exit rule evaluation:** read EXIT rules from `thesis_rules`; evaluate conditions (violated_pillar count, composite score below threshold, persistence); if triggered → EXIT_REVIEW recommendation
9. **Trim/Add rule evaluation:** read TRIM / ADD rules; evaluate conditions; create TRIM or BUY recommendations as appropriate

**Write boundary:** the agent may only write to `thesis_pillars` (status, score, confidence, reason, last_evaluated_at) and `agent_findings` / `recommendations`. It must never modify `thesis_metrics`, `thesis_rules`, or `thesis_pillars.importance` / `.critical` / `.name` / `.description`.

**THESIS_CHANGE_PROPOSAL:** if the LLM believes a threshold should be updated, create a `THESIS_CHANGE_PROPOSAL` recommendation — not a direct DB write. User accepts/rejects via Decision Queue (0020 mechanism).

## Touches

`agents/thesis_agent.py` (full rewrite from 0013 stub), `agent_db.py` (read helpers from 0030), `financials_fetcher.py` (force-refresh path), `agents/orchestrator.py` (ensure thesis_monitor is registered)

## Done when

- [ ] Agent loads pillars/metrics/rules from 0030 tables for any ACTIVE thesis
- [ ] Deterministic metric evaluation produces correct HEALTHY/WARNING/VIOLATED per metric using actual `company_financials` data
- [ ] Persistence check correctly requires N consecutive periods before confirming a violation
- [ ] LLM qualitative pass returns present/absent per QUALITATIVE_SIGNAL rule
- [ ] Pillar status and score written to `thesis_pillars` after each run
- [ ] Critical pillar VIOLATED triggers THESIS_CRITICAL_VIOLATION finding and EXIT_REVIEW regardless of composite score
- [ ] EXIT rules with composite score threshold and violated-pillar count correctly generate EXIT_REVIEW recommendations
- [ ] Earnings trigger forces financials refresh before evaluation
- [ ] Agent does not write to thesis_metrics, thesis_rules, or structural pillar fields
- [ ] QA (backend): With an ACTIVE thesis (with pillars/metrics from 0030 tables), run the Thesis Monitor agent and confirm: (a) `thesis_pillars.status` and `score` updated in DB for each pillar, (b) persistence check requires N consecutive periods (test with N=2 and only 1 violation — no flag), (c) a critical pillar violation generates a THESIS_CRITICAL_VIOLATION finding and EXIT_REVIEW rec, (d) agent does NOT write to thesis_metrics or thesis_rules (grep agent output). Show DB rows before checking this box.
