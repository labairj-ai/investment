# Prevent Narrative Contradiction on Policy Override

- **ID:** 0649
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0648

## Problem

`_enforce_brief_health()` corrects the structured `portfolio_state` field but leaves the LLM-generated `headline` and `key_question` unchanged. When a policy override fires (e.g. STABLE → UNKNOWN due to ERROR health), the user sees a contradictory brief: the headline may say "Portfolio stable with no material concerns" while `portfolio_state` reads UNKNOWN. The headline is what most users read first. The machine field is correct; the human-facing claim is false.

Do not attempt to regex-patch LLM text. The corrected language must be deterministically generated from `brief_health_detail` so it is internally consistent and never optimistic.

## Proposed approach

- When a policy override fires, replace `headline` and `key_question` with deterministic text derived from `brief_health_detail`:
  - Example headline: `"Portfolio assessment incomplete — execution state unavailable; stability cannot be confirmed."`
  - Example key_question: `"Resolve execution-state availability before relying on today's brief."`
  - The detail text comes from the `brief_health_detail` list already present in the output
- Add a `policy_overrides` audit field to the persisted output — a list of objects: `{field, from_value, to_value, reason}`. Example: `{"field": "portfolio_state", "from_value": "STABLE", "to_value": "UNKNOWN", "reason": "brief_health=ERROR: execution state unavailable"}`. This makes it visible in provenance exactly what the policy changed and why.
- The LLM's original text should be preserved in a separate field (e.g. `llm_portfolio_state`, `llm_headline`) for debugging, but these fields must not be shown in the UI.
- Only replace narrative when the policy actually overrode a value. If the LLM already returned ATTENTION and health is DEGRADED, no contradiction exists and the original headline stands.

## Touches

- `portfolio_ai.py` — `_enforce_brief_health()`: deterministic headline/key_question replacement on override; `policy_overrides` field; preserve original LLM fields under `llm_*` keys
- `generate_dashboard.py` — UI must never render `llm_headline` or `llm_portfolio_state`; render `policy_overrides` in evidence footer if non-empty
- `tests/` — test: STABLE→UNKNOWN override replaces headline and key_question with deterministic text; `policy_overrides` is non-empty; `llm_headline` is preserved; test: no override → `policy_overrides` is empty, original headline unchanged

## Done when

- [ ] When `portfolio_state` is overridden from STABLE → UNKNOWN, `headline` and `key_question` are replaced with deterministic text derived from `brief_health_detail`
- [ ] Original LLM headline is preserved under `llm_headline` (not rendered in UI)
- [ ] `policy_overrides` field is present in persisted output; lists each override with `field`, `from_value`, `to_value`, `reason`
- [ ] No override → `policy_overrides` is empty list, original headline is unchanged
- [ ] Dashboard evidence footer shows a policy-override indicator when `policy_overrides` is non-empty
- [ ] Tests cover the override path and the no-override path
