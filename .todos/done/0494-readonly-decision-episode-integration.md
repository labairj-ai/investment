# Capture Macro Risk Snapshot into Decision Episodes (Read-Only)

- **ID:** 0494
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0490

## Problem

Decision Episodes currently capture Q/V/PF/C/EC scores and challenger/base recommendations but have no macro context. Once 0490's validation acceptance record passes, macro features should be snapshotted into each episode so that Learning Lab can eventually test whether macro variables explain future alpha, MAE/MFE, or challenger-vs-base outcomes. This must be strictly read-only: no change to rankings, sizing, recommendations, risk gates, or any trading-adjacent decision.

## Proposed approach

At Decision Episode capture time, attach a `macro_context` JSON blob containing:
- Per-holding structural scores (rate_sensitivity, dollar_sensitivity, inflation_hedge, geopolitical_risk) and their evidence quality flags
- Deterministic betas (rate_beta_100bp_return_pct, usd_beta_1pct_return_pct) and confidence tier
- Raw regime values (yield_10y_63d_chg_bps, dollar_63d_pct, vix_level, curve_state)
- Signed regime interaction values per dimension
- Regime UNKNOWN flags (which dimensions are missing/stale)
- run_id, model_version, schema_version, evidence_hash, prompt_hash, scored_at from the latest scoring run
- `macro_supported: true/false` — false for unsupported funds

Store as a new `macro_snapshot` column (TEXT/JSON) in `decision_episodes`. For unsupported funds, the snapshot is `{"macro_supported": false, "reason": "fund/etf — no constituent evidence"}` — never null features masquerading as zero.

The macro snapshot must never influence episode scoring, challenger selection, opportunity ranking, or any downstream logic in this implementation.

## Touches

- `portfolio_ai.py` — Decision Episode capture path, `macro_snapshot` column in `decision_episodes`
- `_init_ai_tables()` — ALTER TABLE to add `macro_snapshot` column

## Done when

- [ ] 0490 acceptance record shows PASS before this is activated
- [ ] `macro_snapshot` column added to `decision_episodes`
- [ ] Each new episode carries macro context blob at capture time
- [ ] Unsupported funds get `{"macro_supported": false}` — not zero scores
- [ ] No change to Q/V/PF/C/EC, rankings, recommendations, or risk gates
- [ ] Learning Lab sweep can read `macro_snapshot` from episode rows
