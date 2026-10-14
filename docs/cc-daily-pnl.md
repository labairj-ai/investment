# Tracked holdings daily P&L

The dashboard separates stock daily movement from a covered-call display estimate. It does not claim to reconcile brokerage account equity, cash, fees, other instruments, or intraday trades.

For an existing open call, the estimate is `(previous-session close - observed midpoint) × contracts × 100`. The previous close comes from the exact preceding NYSE session's unadjusted Yahoo contract history, with a nonzero-volume bar. Current prices come from the matched contract's bid/ask midpoint. Those valuation bases can differ from a brokerage's marks. No brokerage reference number is used in the calculation.

The `cc_daily_pnl_marks` table stores each position/session baseline separately from legacy `prev_mark`. Once established, a baseline is not replaced during refreshes. Changed position identity or conflicting baseline data makes the estimate unavailable. Legacy refresh-to-refresh marks are never promoted into prior closes.

Yahoo option chains do not provide an exchange timestamp for bid/ask. The display therefore distinguishes retrieval time from last-trade time, uses a conservative 30-minute last-trade activity/freshness limit, and labels computed values as estimates. Quotes before the current session, old observations, missing baselines, invalid quotes and unsupported same-session openings produce null daily P&L with a reason, not zero. After close, freshness is measured relative to session close; overnight and premarket refer to the last completed session. The existing NYSE calendar supplies holidays and early closes.

The headline is incomplete unless all tracked open calls are priced for the same session as the stock snapshot. Calls closed that session also make it incomplete because their intraday P&L is not yet reconstructed. Available rows retain their individual estimates, while the incomplete combined headline is hidden. The source/coverage disclosure shows timing and scope. A complete display is still a market-data estimate, not broker reconciliation.

Refreshes run through the existing newsletter pricing job. Deploy verification may call `fetch_cc_mtm()` alone; that refreshes marks without sending a newsletter or submitting trades. Read-only tracker requests calculate coverage from stored records and never fetch quotes.
