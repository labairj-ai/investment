# Run the Actual Live Acceptance Validation (N=20)

- **ID:** 0498
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0490, 0497

## Problem

The non-live PASS from 0490 validates harness software correctness only. The real gate — "does the deployed LLM produce sufficiently repeatable structural scores from identical frozen evidence?" — has not been answered. A non-live PASS must not satisfy this gate. Until a live 20-repeat run completes and produces a PASS record, Macro Risk cannot be considered validated evidence for Learning Lab.

## Proposed approach

On the optiplex (where the live model runs), execute:
```bash
cd ~/investment && venv/bin/python scripts/validate_macro_scorer.py \
  --live --n-repeats 20 \
  --out out/macro_validation_acceptance_$(date +%Y%m%d_%H%M%S).json
```

The run:
- Freezes current macro context snapshot (no re-fetch during the 20 repeats)
- Scores 3-5 tickers from actual portfolio with company evidence (not funds)
- For each ticker × dimension, records all 20 scores; computes mean, stddev, range
- Flags any dimension where range > 1 as UNSTABLE
- Checks all pre-committed thresholds from `validation_config.json`
- Writes immutable acceptance record with commit SHA, model identity, raw stats, PASS/BLOCK

If result is PASS: update `macro_acceptance_state` table (triggers 0497 ACCEPTED tagging for future episodes).

If result is BLOCK: document which threshold failed; do not activate ACCEPTED status; investigate score instability before proceeding.

Expected outcome: if LLM score variability is higher than threshold (range > 1), that does not kill the system — it may mean structural scores should be represented as distributions (modal + stddev) rather than point estimates. That would be a new todo, not a blocker for observation.

## Touches

- `scripts/validate_macro_scorer.py` (already has `--live` flag from 0490)
- `out/macro_validation_acceptance_TIMESTAMP.json` — immutable output
- `macro_acceptance_state` table (from 0497) — updated on PASS

## Done when

- [ ] Live run completes with N=20 on real model and frozen evidence (not mocks)
- [ ] Immutable acceptance record written with commit SHA, model identity, raw per-dim stats
- [ ] PASS: `macro_acceptance_state` updated; future episodes tagged ACCEPTED
- [ ] BLOCK: instability documented; new todo created for distribution representation if needed
