# Validation Lab Acceptance Contract with Synthetic Truth Tests

- **ID:** 0489
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0483, 0484, 0485, 0486, 0487, 0488

## Problem

The validation harness from 0479 tests that the scoring pipeline runs without error but does not verify correctness against known-truth inputs. Before macro signals can be connected to Learning Lab (even read-only), the harness must catch the specific defects identified in 0483–0488: reversed concordance, missing-data treated as benign, wrong provenance comparisons, and unsigned regime interaction.

## Proposed approach

- **Synthetic regression tests**: construct a dataset where `equity_return = -5 × yield_change + 2 × uup_return + noise`; assert recovered `rate_beta ≈ -5` (±1) and `usd_beta ≈ +2` (±1). Same for the market-control (SPY) regressor.
- **Concordance direction tests**: synthetic stock with `rate_beta = -12` should agree with `rate_sensitivity = 8`; `rate_beta = +1` should agree with `rate_sensitivity = 2`.
- **Regime direction tests**: `+100bps yield change → rate_stress > 0`; `-100bps → rate_stress ≤ 0`; `UUP +3% → dollar_stress > 0`; `UUP -3% → dollar_stress ≤ 0`; `None input → stress = None` (not 0).
- **Missing-data tests**: assert every regime classification returns `"UNKNOWN"` (not `"stable"`) when input series is None.
- **Provenance round-trip test**: score a frozen evidence snapshot; assert `scores["evidence_hash"]` matches the hash computed from the same evidence dict.
- **Ledger integrity test**: assert `expected_n == scored_n + failed_n` for every completed run in `macro_scoring_runs`.
- **Fund classification test**: assert VTSAX/VFIAX/MSTR are correctly typed; assert fund tickers get `evidence_quality = "unsupported"`.
- All tests run without a live LLM (mock or skip LLM-dependent modules). Exit 1 on any failure.

## Touches

- `scripts/validate_macro_scorer.py`
- `tests/test_macro_betas.py`, `tests/test_regime_stress.py` (new)

## Done when

- [ ] Synthetic regression truth test passes with recovered betas within tolerance
- [ ] Concordance direction test: negative beta agrees with high sensitivity, positive with low
- [ ] Regime direction tests: rising rates/dollar → positive stress; missing → None
- [ ] Provenance round-trip: `scores["evidence_hash"]` matches expected hash
- [ ] Ledger integrity: `expected == scored + failed` for all completed runs
- [ ] Fund classification: VTSAX=fund, MSTR=company, fund→evidence_quality=unsupported
- [ ] All tests pass without live LLM; exit 1 on failure
