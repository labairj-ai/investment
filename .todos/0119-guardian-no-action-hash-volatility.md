# Add Volatility and Risk-Contribution Buckets to Guardian NO ACTION Hash

- **ID:** 0119
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0093

## Problem

The Portfolio Guardian NO ACTION hash currently includes only `max_weight_bucket` (nearest 0.5%) and `layer_drift_flag` (bool: any layer > target+5%). The reviewer identified two additional state dimensions that can change Guardian's recommendation without touching price, thesis version, or financial quarter:

- **Position volatility**: a high-beta holding's risk contribution can shift materially due to realized or implied volatility changes without the price or weight moving enough to cross the existing bucket boundaries.
- **Risk contribution**: the marginal contribution of a position to total portfolio variance (requires a covariance estimate or a simplified beta × weight proxy) can move independently of weight.

Without these in the hash, the Guardian can silently re-run and produce a NO_ACTION duplicate even when the portfolio's actual risk profile has changed significantly.

## Proposed approach

- Compute a simplified `risk_contrib_bucket` per position: `weight_pct × abs(beta_proxy)` where `beta_proxy` is stored in the thesis or estimated from 3m price correlation with a benchmark. Round to nearest 0.5 to bucket.
- Compute a `vol_bucket` using the coefficient of variation of recent daily prices from `holding_day` (e.g. 20d rolling stddev / mean price), rounded to nearest 0.005.
- Add both to `_compute_no_action_state_extras()` for `portfolio_guardian` in `orchestrator.py`.
- If beta or sufficient price history is unavailable, emit `"unknown"` for the bucket (triggers a new hash, same as ESTIMATE_REVISION unknown treatment).

Open question: should `vol_bucket` be portfolio-level (total portfolio volatility from daily returns) or per-position? Per-position is simpler but portfolio-level is more economically meaningful.

## Touches

- `agents/orchestrator.py` (`_compute_no_action_state_extras`)
- `agent_db.py` (possibly a helper to compute rolling vol from `holding_day`)
- `tests/test_agent_db.py` or `tests/test_lifecycle.py` (guardian hash changes on vol shift)

## Done when

- [ ] Guardian NO ACTION hash includes a vol-derived bucket
- [ ] Guardian NO ACTION hash includes a risk-contribution bucket
- [ ] A test confirms the Guardian hash changes when vol crosses a bucket boundary
- [ ] Unavailable data emits `"unknown"` rather than raising
