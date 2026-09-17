# Learning Metrics Semantic Cleanup

- **ID:** 0347
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0338, 0343

## Problem

Three distinct semantic mismatches accumulated across 0338 and 0343 that make the dashboard misleading:

1. **Risk Gate Audit still uses raw `alpha`, not `decision_alpha`.** The endpoint computes `losses_avoided = alpha < 0` and `alpha_missed = alpha > 0` using the underlying price-return alpha. After 0338, `risk_counterfactual_outcomes` now has a `decision_alpha` column that accounts for action direction (a rejected SELL where price subsequently falls is a *good* gate decision, not a loss avoided). The UI can still label it backwards.

2. **Bootstrap CI interval is 80%, labeled as 90%.** The current code takes the 10th–90th percentile of the bootstrap distribution. That is an 80% interval. The dashboard labels or implies it as "90% CI." Fix: either use 5th/95th percentiles for a true 90% CI, or relabel the existing result explicitly as "80% interval."

3. **Ranking spread is labeled as "Expected Alpha."** The metric being bootstrapped is `top_vs_bottom_quintile_alpha` — the alpha spread between the top and bottom quintile of the model's *ranking*. That is a measure of ranking power, not the expected alpha on an individual recommended stock. Calling it "Expected Alpha CI" or displaying it as the model's predicted return implies individual-level precision that does not exist. Rename to "Out-of-Sample Ranking Alpha Spread" or similar.

4. **Reliability conflates precision with evidence of positive edge.** A very tight interval around −4% to −3% would display as "HIGH reliability" because the band width is small. That is high precision but the model is reliably bad. Separate into two independent assessments: **Precision** (HIGH/MEDIUM/LOW by band width) and **Edge** (POSITIVE/INCONCLUSIVE/NEGATIVE, e.g. ci_low > 0 → POSITIVE; ci_high < 0 → NEGATIVE; else INCONCLUSIVE).

## Proposed approach

- **Risk Gate Audit:** add `decision_alpha` to the endpoint query; display both `Underlying Alpha` and `Decision Alpha` columns; recompute `losses_avoided` / `alpha_missed` using `decision_alpha`; add a note explaining the distinction
- **Bootstrap CI:** change from (10th, 90th) → (5th, 95th) percentiles, or relabel clearly as "80% interval"; update dashboard label to match
- **Rename ranking spread metric:** update `_bootstrap_alpha_ci` return key names and dashboard display; label as "Ranking Alpha Spread" and clarify it is model ranking power, not individual expected return
- **Split reliability:** return `alpha_precision` (HIGH/MEDIUM/LOW by band width) and `alpha_edge_evidence` (POSITIVE/INCONCLUSIVE/NEGATIVE by whether CI crosses zero); update dashboard card to show both

## Touches

- `agents/learning/calibration.py` — `_bootstrap_alpha_ci()`: use 5th/95th percentiles; return `alpha_precision` + `alpha_edge_evidence` instead of single `alpha_reliability`; rename `alpha_ci_*` keys to `ranking_spread_ci_*` or similar for clarity
- `serve.py` — `_handle_learning_stats()`: update active model card fields; `_handle_champion_challenger()`: Risk Gate Audit query add `decision_alpha`; recompute gate stats with `decision_alpha`
- `generate_dashboard.py` — update model card display: show ranking-spread label, 90% or 80% interval label, precision, and edge evidence separately; update Risk Gate Audit table to include both alpha columns
- `tests/test_calibration.py` — update CI tests to assert 5th/95th semantics; assert `alpha_precision` and `alpha_edge_evidence` keys present; test NEGATIVE edge case (all negative spreads → edge=NEGATIVE)

## Done when

- [ ] Risk Gate Audit endpoint uses `decision_alpha` for `losses_avoided` / `alpha_missed`; both `alpha` and `decision_alpha` visible in dashboard table
- [ ] Bootstrap CI uses 5th/95th percentiles (90% interval) or clearly labeled as 80% — no discrepancy between code and label
- [ ] Metric renamed from "Expected Alpha CI" to "Ranking Alpha Spread" (or equivalent clear name) at code and dashboard level
- [ ] `alpha_reliability` replaced by `alpha_precision` (band-width-based) + `alpha_edge_evidence` (zero-crossing-based)
- [ ] Dashboard model card displays precision and edge evidence as separate labeled fields
- [ ] `python -m pytest tests/` passes with no regressions
