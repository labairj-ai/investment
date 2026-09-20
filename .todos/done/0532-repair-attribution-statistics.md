# Fix Bootstrap and Divergence Bugs in Attribution Statistics

- **ID:** 0532
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

The bootstrap resampling path uses `float(e["macro"].get("rate_interaction") or 0)` to assign interaction sign, which coerces missing/malformed values to `0` and places them in the negative group. The observed-contrast grouping excludes those same missing values, so the population used to compute the observed statistic differs from the population used to build its confidence interval — a genuine statistical bug that invalidates the CI. Separately, episodes without a valid `captured_at` are merged into a single empty-string pseudo-cohort in the bootstrap, divergence analysis has no minimum subgroup size so 2–3 episodes can produce a reported win rate, and ties (`challenger_alpha == base_alpha`) are silently counted as base wins rather than reported as a distinct outcome. The `high_stress`/`low_stress` label is also a misnomer — the grouping is actually by rate-interaction sign, not macro stress level.

## Proposed approach

- Add `_rate_interaction_sign(episode) -> Literal["positive", "negative"] | None` helper; use it in every place that groups by interaction sign: observed grouping, bootstrap draw, divergence subgroup filters.
- `None` return always means the episode is excluded from that analysis — never coerced to a group.
- Exclude episodes without a parseable `captured_at` from the cohort bootstrap entirely (do not bin them under `""`).
- Add a `MIN_SUBGROUP_N` constant (suggest 10); skip subgroup win-rate reporting when `n < MIN_SUBGROUP_N`.
- Replace binary win/loss with explicit win/loss/tie; propagate tie counts through all reporting surfaces.
- Rename `high_stress`/`low_stress` labels to `high_rate_sensitivity`/`low_rate_sensitivity` (or equivalent) wherever they appear in code and output artifacts.

Open question: should malformed `rate_interaction` values log a warning or be silently dropped? A warning counter in the run summary seems reasonable.

## Touches

- Attribution analysis module (bootstrap resampling, observed grouping, divergence analysis — likely in or near `validate_macro_scorer.py` or a dedicated attribution file)
- Any output artifact or dashboard display that surfaces `high_stress`/`low_stress` labels
- Test suite (new tests for: missing interaction values excluded from both paths, tie handling, subgroup minimum enforcement, malformed `captured_at` exclusion)

## Done when

- [x] `_rate_interaction_sign()` helper exists and is used in all observed/bootstrap/divergence grouping paths
- [x] Missing or malformed `rate_interaction` values are excluded (not coerced to a group) in both observed and bootstrap paths
- [x] Episodes without a valid `captured_at` are excluded from cohort bootstrap rather than binned under `""`
- [x] Win/loss/tie are reported as three distinct outcomes; ties are never silently counted as base wins
- [x] Divergence subgroup win rates are suppressed when subgroup `n < MIN_SUBGROUP_N`
- [x] `high_stress`/`low_stress` labels replaced with rate-sensitivity terminology throughout
- [x] Tests confirm each of the above behaviors independently

## Review — 2026-09-20

Partially implemented in 4dbb0c0. Sign grouping, subgroup suppression, and ties are implemented. Cohort timestamps are only sliced and length-checked, so malformed strings of length 10 or more remain accepted instead of being parsed and excluded. Required timestamp-exclusion coverage is absent.

## Completion — 2026-09-20

Completed remaining implementation and behavioral coverage in `tests/test_macro_contract_completion.py`. Numeric thresholds, full-N gating, frozen evidence/prompt provenance, contract invalidation, UUID run persistence, timestamp exclusion, and atomic activation are verified. Historical review notes above describe the prior implementation.
