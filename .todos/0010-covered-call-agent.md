# Build Covered Call Agent (Phase 2)

- **ID:** 0010
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005, 0006, 0007, 0008

## Problem

The current CC workflow is manual: the user selects a ticker, the dashboard fetches recommendations, the AI comments. There is no proactive scanning — the system doesn't surface "EW is your best CC opportunity right now" without the user already thinking to check EW. The agent should automatically scan all CC-eligible holdings, rank opportunities, and push the best candidate into the Decision Queue.

## Proposed approach

`agents/covered_call_agent.py` — thin wrapper around `covered_call_rec.analyze()`.

Flow:
1. Triggered by: holding ≥ 100 shares + no open CC + HV percentile or opportunity score threshold (from trigger engine).
2. Call `covered_call_rec.analyze(ticker, avg_cost, shares)` — Python calculates all contract math (CC alpha, annualized return, delta, regret probability, IV richness, liquidity, event risks, opp_score). Agent receives already-computed contracts.
3. Assign each contract a stable ID: `TICKER:YYYYMMDD:STRIKE` (e.g., `EW:20261016:105`).
4. Deterministic gating before LLM: live/ask-proxy/theoretical classification → confidence cap applied; if event severity = AVOID → VETO immediately without model call.
5. LLM receives contract IDs + pre-computed scores. It outputs only:
   ```json
   {
     "action": "SELL_CC",
     "contract_id": "EW:20261016:105",
     "why": "...",
     "main_tradeoff": "...",
     "no_call_case": "..."
   }
   ```
6. Python resolves `contract_id` back to actual strike/expiration/premium — LLM never outputs financial values.
7. Build `Recommendation` with Python-calculated numbers + LLM rationale. Calculate confidence via `confidence.py`. Send to Critic.

This eliminates the current bug where `serve.py` overwrites strike/expiration post-LLM.

## Touches

`agents/covered_call_agent.py` (new), `covered_call_rec.py` (add stable contract IDs), `agents/orchestrator.py`, `serve.py` (existing CC endpoint may be simplified)

## Done when

- [ ] Agent runs for an eligible holding and produces a `Recommendation` object
- [ ] LLM output contains only `contract_id`, `why`, `main_tradeoff`, `no_call_case` — no financial numbers
- [ ] AVOID-event holdings are vetoed before LLM call
- [ ] Contract with theoretical pricing receives confidence ≤ 45
- [ ] Recommendation persisted to `recommendations` table with full `action_payload_json`
- [ ] Existing manual CC flow from the dashboard still works (agent is additive, not replacement)
- [ ] QA (backend + browser regression): (a) Run the CC agent for one eligible holding and confirm a Recommendation row appears in the DB with full action_payload_json. (b) Open the dashboard in a browser: verify the existing manual CC flow still works (contract selector, submit button, modal). Check JS console shows zero errors. Do NOT check this box without completing the live browser regression check.

