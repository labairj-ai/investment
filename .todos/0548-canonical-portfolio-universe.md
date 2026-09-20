# Use One Canonical Portfolio Universe for Certification

- **ID:** 0548
- **Status:** in-progress
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0544

## Problem

Production derives the portfolio universe from `_load_holdings_csv()`, while validation currently derives it from rows already present in `holding_macro_scores`. New holdings can therefore be omitted and sold holdings can remain included in formal certification.

## Proposed approach

- Extract `_current_holdings_universe()` in `portfolio_ai.py`.
- Normalize, deduplicate, and hash holdings through that shared helper in both production scoring and validation.
- Return one representation containing `tickers`, `count`, and `hash`; production snapshots it once at run start.
- Require certification `portfolio_n` and `portfolio_universe_hash` to match the actual current holdings universe.
- Preserve the existing full-refresh and current-contract requirements.

## Touches

- `portfolio_ai.py` holdings-universe helper and scoring path
- `scripts/validate_macro_scorer.py` certification reference universe
- Portfolio-universe regression tests

## Done when

- [ ] Validator and production use the same canonical holdings helper.
- [ ] A new holding with no prior score changes the expected certification universe.
- [ ] A sold holding lingering in `holding_macro_scores` is excluded.
- [ ] A one-holding incremental run is rejected for full-portfolio certification.
- [ ] The 28-holding run is COMPLETE with zero failures and matching provenance.

**Blocks:** 0545, 0535

## Implementation verification — 2026-09-20

Per-ticker terminal states commit atomically with score and history writes. Stale reconciliation reconstructs supported, unsupported, and failed counts and preserves non-certifiable STALE_FAILED status. Production and validation share the normalized holdings universe; certification requires full-refresh scope, matching universe provenance, and expected count equal to portfolio count. Fifteen recovery/universe regression tests pass, including commit-boundary failures, immediate interruption, legacy recovery, new/sold holdings, and incremental-run rejection. Production rollout verification is pending.
