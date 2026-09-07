# Fix extreme_threshold to Use Primary Metric, Not Always P/E

- **ID:** 0116
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

In `_score_V()` (`sell_trim_agent.py`), the `extreme_threshold` from the thesis `valuation_framework` is always interpreted as a P/E threshold — even when the thesis's `primary_metric` is set to something else (e.g. `ev_fcf`, `ps`, `ev_ebit`). The code unconditionally computes `pe_check = current_price / ttm_eps` and compares it to `extreme_threshold`. If ANET's thesis says `primary_metric=ev_fcf, extreme_threshold=45`, the check fires when P/E > 45 rather than when EV/FCF > 45 — the wrong metric entirely.

## Proposed approach

- Initialize `_curr_ratio = None` at the top of the primary_metric routing block so it is available in scope for the extreme_threshold check.
- In the extreme_threshold block (after line ~466), branch on `_used_primary`:
  - If `_used_primary` is True and `_curr_ratio is not None`: compare `_curr_ratio > extreme_f` (uses the primary metric's ratio).
  - Otherwise: fall back to the existing P/E check (for theses with no primary metric or primary_metric = pe).
- Update the `notes` append to name the metric being compared.
- Add a unit test: thesis with `primary_metric=ev_fcf` and `extreme_threshold=30`; supply EV/FCF=35 → H floor raised. With P/E=25 (below threshold) → confirm the old P/E check does NOT fire.

## Touches

- `agents/sell_trim_agent.py`
- `tests/test_sell_trim_scores.py`

## Done when

- [ ] `extreme_threshold` is evaluated against the primary_metric ratio when one is set
- [ ] P/E fallback used only when no primary_metric or primary_metric = pe/trailing_pe/forward_pe
- [ ] Unit test passes confirming EV/FCF > extreme fires; P/E below threshold does not
