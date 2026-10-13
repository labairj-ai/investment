# Independent Confirmation Signals

- **ID:** 0592
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0585

## Problem

`attach_confirmation()` has two bugs. (a) `_get_price_alpha()` constructs ticker prices and SPY prices as independent series then aligns them by DataFrame index position. If SPY is missing a date that the ticker has (or vice versa), the index positions shift and the alpha calculation is wrong — e.g., ticker day N is compared to SPY day N-1. (b) Trend recurrence (ACCELERATING or CONFIRMING trend status) is counted as a corroborating confirmation signal (`corroborating += 1`). But trend recurrence already inflates the score via `novelty_weight` (lower for recurring events) and `persistence_adj` (higher for ACCELERATING) inside `signal_strength`. Counting it again as an independent confirmation signal triple-counts its effect.

## Proposed approach

- Fix price alignment: build `(date, ticker_pct_change, spy_pct_change)` triplets joined on trading date before computing alpha. Reject any date not present in both series.
- Remove trend status from the confirmation signal list entirely. Confirmation channels must be independent from signal_strength inputs: price/alpha, fundamental metric change (from financial pipeline), thesis health score, macro state exposure, and agent findings. These are the only valid corroborating channels.
- Preserve CONTRADICTED classification (news is negative but price/fundamentals are strong, or vice versa) and its skepticism_note.
- The SOFT (1–2 corroborating) / MULTI_SIGNAL (3+) / CONTRADICTED boundary counts remain as-is once trend is removed.

## Touches

- `agents/news/intelligence.py` — `attach_confirmation()`, `_get_price_alpha()` inner function

## Done when

- [ ] `_get_price_alpha()` aligns ticker and SPY prices by date, not by index position
- [ ] Trend status (ACCELERATING/CONFIRMING) is no longer a confirmation corroboration signal
- [ ] Confirmation channels are: price alpha, fundamental metric trend, thesis health, macro exposure, agent findings only
- [ ] CONTRADICTED classification and skepticism_note still fire correctly
- [ ] SOFT / MULTI_SIGNAL thresholds remain unchanged (1–2 / 3+)
