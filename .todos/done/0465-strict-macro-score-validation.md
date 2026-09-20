# Enforce Strict Validation and Versioned Schema for Macro Scores

- **ID:** 0465
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0464

## Problem

Macro score JSON returned by the LLM is stored with minimal validation. `_score_val()` converts with `int()` but does not range-check, so an out-of-range value like 14 can be persisted silently. There is no enforcement that all four dimensions exist, that reason fields are present, or that the response conforms to a versioned schema. Separately, the two composite consumers handle missing dimensions inconsistently: the dashboard composite returns `None` if any dimension is absent while the weekly narrative composite silently averages whatever dimensions exist — the same data gap produces different behavior depending on the call site.

## Proposed approach

- Write a single `validate_macro_score_response(raw, ticker)` function that:
  - Asserts exactly four expected dimension keys are present
  - Asserts every score is an integer in [1, 10] (reject and log on failure)
  - Asserts every reason field is a non-empty string
  - Asserts no unexpected keys exist
  - Returns a typed dataclass or raises a structured validation error
- Version the expected schema (e.g. `macro_score_schema_version = "v1"`) and store it alongside each persisted row so future prompt changes are traceable
- Create one canonical `composite(scores)` function used by both dashboard and narrative; decide on one behavior for missing dimensions (fail-closed: return `None` and surface coverage gap)
- Replace all ad-hoc `int()`/dict-access call sites with the validated path

## Touches

- Macro scoring module (`portfolio_ai.py` or equivalent)
- `_score_val()` and any direct dict accessors on score responses
- Dashboard composite calculation
- Weekly narrative composite calculation
- DB schema (add `score_schema_version` column to `holding_macro_scores`)

## Done when

- [ ] A score outside [1, 10] is rejected at ingestion time and never written to the DB
- [ ] Missing any of the four dimension keys causes the entire response to be rejected (not partially stored)
- [ ] Dashboard composite and narrative composite use the same function with the same missing-dimension behavior
- [ ] Each stored row carries a `score_schema_version` field
