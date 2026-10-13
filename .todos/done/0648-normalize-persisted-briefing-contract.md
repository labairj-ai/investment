# Normalize the Persisted Briefing Contract

- **ID:** 0648
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0644

## Problem

`_enforce_brief_health()` only corrects `portfolio_state` when it detects a STABLE/health mismatch. It does not normalize missing or invalid `portfolio_state` values. An output with no `portfolio_state` key at all passes through, and downstream callers supply their own defaults inconsistently. The persisted `ai_insights` row can therefore contain an incomplete contract object. Each consumer having its own fallback means a silent divergence is possible between what the UI shows and what provenance records.

## Proposed approach

The central policy function should own the full output contract postcondition:

- `portfolio_state` must be one of: `STABLE`, `ATTENTION`, `URGENT`, `UNKNOWN`
- Missing → `UNKNOWN`
- Any other value (e.g. `null`, empty string, unrecognized word) → `UNKNOWN`
- This normalization runs unconditionally at the bottom of `_enforce_brief_health()` (or its successor `_apply_brief_policy()`) before anything is returned or persisted

After this, every persisted `ai_insights` row is guaranteed to carry a valid `portfolio_state`. Consumers can rely on it being one of the four values without their own fallback logic.

## Touches

- `portfolio_ai.py` — `_enforce_brief_health()`: add unconditional `portfolio_state` normalization
- `tests/` — parameterized test: null, missing, garbage string, empty string all → `UNKNOWN`; valid values pass through unchanged

## Done when

- [ ] `_enforce_brief_health()` normalizes `portfolio_state` to one of `{STABLE, ATTENTION, URGENT, UNKNOWN}` unconditionally
- [ ] Missing `portfolio_state` → `UNKNOWN`
- [ ] Invalid/unrecognized value → `UNKNOWN`
- [ ] Parameterized test covers null, missing, garbage, empty, and each of the four valid values
- [ ] No consumer needs its own `portfolio_state` default fallback after this
