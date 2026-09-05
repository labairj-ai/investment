# Build Thesis AI Proposal Engine

- **ID:** 0031
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0030, 0020

## Problem

The intake form (0020) collects user intent but the user should not have to specify financial thresholds — that is analytical work the system can do better. There is no code that takes user-provided thesis pillars and produces concrete, data-grounded metric definitions (healthy/warning/violation bands, persistence periods, qualitative signals). Without this engine, the intake UI has nowhere to send the user's inputs and 0020 cannot be completed.

## Proposed approach

New file `thesis_engine.py` with a single primary function:

```python
def draft_thesis(ticker: str, intake_dict: dict) -> dict:
    ...
```

**Steps inside `draft_thesis`:**
1. Query `company_financials` for the ticker — pull recent revenue growth, margins, FCF yield, debt ratios, EPS trend, and any other available metrics.
2. Build a structured prompt that includes:
   - User's `why`, pillar names, sell/trim conditions, conviction, holding period from `intake_dict`
   - Actual financial data so the LLM grounds thresholds in real ranges (not generic rules of thumb)
3. Call the LLM via `ollama_client.py` (MLX endpoint at Mac Studio 100.73.128.40:8080). Request JSON output.
4. Parse and validate the response:
   - Pillar importance weights must sum to 100 (renormalise if close, reject if wildly off)
   - All threshold values must be numeric — flag any metric key the LLM invented that doesn't exist in `company_financials`
   - Qualitative signal severity must be HIGH / MEDIUM / LOW
5. Return a dict that maps directly onto the schema from 0030 (pillars list, metrics list, rules list, valuation_framework, covered_call_policy, review_triggers, key_risks, catalysts) — nothing written to DB yet.

**Open questions:**
- Should the LLM propose valuation zone percentiles (very_attractive / attractive / fair / expensive / extreme) or should those come from a separate deterministic calculation? Probably deterministic is safer — LLM proposes primary valuation metrics only.
- What token budget is needed for a full thesis draft? Portfolio outlook uses 2500, this will likely need 3000–4000.

## Touches

`thesis_engine.py` (new), `ollama_client.py` (may need a `generate_json()` helper if not already present), `financials_fetcher.py` (read path only)

## Done when

- [x] `draft_thesis("ANET", {...})` returns a valid structured dict without DB writes
- [x] Returned pillars have importance weights that sum to 100
- [x] All metric keys in returned metrics exist in the `company_financials` table for that ticker (or are flagged as unverified)
- [x] LLM is called via the existing MLX endpoint (not hardcoded URL — reads from env/config)
- [x] Function raises a clear error if `company_financials` has no data for the ticker
- [x] QA (backend): Call `draft_thesis('ANET', {...})` with a minimal intake dict and confirm a valid structured dict is returned, importance weights sum to 100, and no DB writes occurred. Also confirm a clear error is raised when `company_financials` has no data for the ticker. Log the actual returned dict before checking this box — do NOT check based on reading the code.

## Outcome

New file `thesis_engine.py` (235 lines). No other files changed.

- `KNOWN_METRIC_KEYS` frozenset of 17 derivable metrics (growth rates, margins, balance sheet ratios)
- `_make_metric_rules(metric)` converts `{healthy_threshold, violation_threshold, direction}` to the three `rule_json` strings the 0030 CRUD helpers expect
- `draft_thesis(ticker, intake_dict)` raises `ValueError` on missing financials, calls `ollama_client.generate_structured` at 3500 tokens, normalises importance to 100, returns `{ticker, pillars, rules, key_risks, catalysts}` with no DB writes
- QA run against MCO on optiplex (ANET has no financials in the live DB): 3 pillars summing to 100, all metric keys in KNOWN_METRIC_KEYS, ADD/TRIM/EXIT rules with valid JSON, ValueError raised for unknown ticker
- Note: `LLM_URL` must be set in env when running outside the systemd unit; the systemd override already handles this for the live service

**Next:** 0032 (Thesis Intake UI Full Schema) is now unblocked.
