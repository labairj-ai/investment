# Tracked holdings daily P&L

The dashboard separates stock daily movement from a covered-call display estimate. It does not claim to reconcile brokerage account equity, cash, fees, other instruments, or intraday trades.

For an existing open call, the estimate is `(previous-session close - observed midpoint) × contracts × 100`. The previous close comes from the exact preceding NYSE session's unadjusted Yahoo contract history, with a nonzero-volume bar. Current prices come from the matched contract's bid/ask midpoint. Those valuation bases can differ from a brokerage's marks. No brokerage reference number is used in the calculation.

The `cc_daily_pnl_marks` table stores each position/session baseline separately from legacy `prev_mark`. Once established, a baseline is not replaced during refreshes. Changed position identity or conflicting baseline data makes the estimate unavailable. Legacy refresh-to-refresh marks are never promoted into prior closes.

Yahoo option chains do not provide an exchange timestamp for bid/ask. The display distinguishes retrieval time from last-trade time, applies a 30-minute retrieval-freshness limit, and labels values as estimates. A standing spread does not require a recent trade: old or absent last-trade metadata alone never disqualifies an observed quote. Quotes from a different session, old observations, missing baselines, invalid quotes and unsupported same-session openings produce null daily P&L with a reason, not zero. After close, freshness is measured relative to session close; overnight and premarket refer to the last completed session. The existing NYSE calendar supplies holidays and early closes.

The headline is incomplete unless all tracked open calls are priced for the same session as the stock snapshot. Calls closed that session also make it incomplete because their intraday P&L is not yet reconstructed. Available rows retain their individual estimates, while the incomplete combined headline is hidden. The source/coverage disclosure shows timing and scope. A complete display is still a market-data estimate, not broker reconciliation.

Refreshes run through the existing newsletter pricing job and a bounded display-only quarter-hour worker during NYSE sessions, including one post-close slot. The worker waits for the next slot on restart and invokes no models, mail, brokers or execution/account actions. Deploy verification may call `fetch_cc_mtm()` alone; that refreshes marks without sending a newsletter or submitting trades. Read-only tracker requests calculate coverage from stored records and never fetch quotes.

## Tracked net value

The dashboard's tracked net estimate is gross stocks minus short-call midpoint liabilities (`mark × contracts × 100`). It requires a dated, identity-matched, recent quote for every open call, aligned with the stock snapshot session. Snapshot generation dates are retained separately from their effective regular-market session: premarket and weekend snapshots are matched to the prior trading session. Missing tables, failed feeds, stale quotes and invalid contract quantities make net value unavailable. Legacy `current_mark`, entry premium and zero substitutions cannot complete coverage. The disclosure lists quote observations and missing positions; cash, fees and untracked instruments are excluded, so this is not brokerage account equity.

Reported provider marks take priority when available with current dated evidence. Otherwise a valid bid/ask midpoint is used, including zero-bid/positive-ask spreads. Last trade price is not substituted for a position mark. Bid, ask, mark basis and retrieval time are saved. Append-only `cc_display_quote_observations` retains each observation and seeds legacy dated rows; a later failed refresh cannot erase earlier evidence. A still-fresh last-good observation can bridge a transient failure.

The headline and portfolio goal subtract every available verified call liability from gross stocks, even when another call cannot be priced. The visible component line shows stocks and known CC liability; incomplete coverage is labelled with the priced/open call count. The disclosure includes each priced contract's liability and lists missing positions. Target progress and growth projections use the same partial estimate. Expiry removes only expired call values and retains independently fresh quotes. The fully adjusted net value and total liability remain null until coverage is complete; net-value dividend yield retains its existing nullable denominator. No missing quote is assumed to have zero liability. Stock allocation and historical stock returns retain gross-stock denominators. Daily percentage uses the verified prior value for the same known components, as described below.

Failure to obtain the previous session's option history does not discard a valid current midpoint. Daily P&L remains unavailable until its separate previous-close requirements pass. Refresh failures continue to leave legacy marks untouched for existing consumers; those marks cannot qualify the net estimate.


## Historical tracked net values

The historical value chart is a read-only projection of original stock snapshots less the liabilities of calls logged as open at each date's end. It uses reported marks, exact-session contract daily closes, then saved midpoint observations for that same reporting session. Midpoints may be intraday estimates; their original dates, references and observations remain available. Gaps remain when any required call lacks evidence. Today's quote is never carried backward. Stock-only return calculations and raw stock snapshots remain unchanged; this is not a reconstructed brokerage equity or net total-return series.

Sources include dated display records, append-only observations, exact-contract option quote snapshots, live prospective candidate quote evidence and explicitly backfilled daily bars. These are read only; decision, simulator, fill and learning evidence is never relabelled or rewritten. Closing/expiry dates bound each position's lifetime, and calls closed during a date are excluded at end of day.

`venv/bin/python scripts/backfill_cc_display_history.py --db out/investment.db` is a read-only dry run. The explicitly authorized `--apply` mode stores append-only `cc_display_historical_marks` after a separate production backup. It requests only exact standard contract symbols, unadjusted completed-session bars with nonzero volume, and excludes dates before opening/after closing and incomplete current-session bars. It does not overwrite any `portfolio_day` row or old evidence. Expired/unavailable histories remain explicit gaps; brokerage statements or dated quote imports are required to fill unsupported dates. Reruns are idempotent, while changed provider bars create new evidence revisions.

## Broker evidence for a contract missing from Yahoo

A dated user-supplied broker bid/ask may fill a missing **current display valuation**
through `out/cc-broker-quotes.json`. This sidecar is separate from investment.db;
position rows, daily P&L baselines and historical valuations are never modified.
Valid Yahoo observations retain precedence. Missing feed coverage does not change
an expiration or make the contract invalid.

`scripts/import_cc_broker_quote.py --db out/investment.db --input quote.json
--evidence screenshot.png` defaults to a read-only dry run. Input JSON must contain
`position_id`, `ticker`, `strike`, `expiry`, `contracts`, `opened_date`, `bid`, `ask`,
and a timezone-qualified `quoted_at`. Identity must exactly match the open position.
The importer hashes the evidence file and records quote time separately from receipt
time. `--apply` appends dated evidence to the display sidecar and atomically updates
the existing valuation JSON using its labelled stock snapshot. It never opens the
authoritative database writable. Serialize imports with the provided CLI.

Only a valid regular-session spread is accepted. The original quote time is subject
to the existing 30-minute freshness limit relative to session close; a closing quote
lasts until the next market open. Reimport does not refresh time. New sessions need
new quotes if Yahoo remains unavailable. An invalid/stale input is rejected before
artifact writes; later generation revalidates all evidence and position identities.
The headline and live goal share the resulting nullable estimate. Source/coverage
explicitly identifies any user-supplied broker midpoint; this is not an automatic
broker feed or account-equity reconciliation. Entry premium and last trade remain
ineligible substitutes for a missing mark.

Daily P&L shows its dollar amount and percentage on the card. Component amounts,
coverage, timing and estimate notes are inside Sources & coverage. The percentage
uses prior stock value minus the verified prior liability of exactly the same calls
included in the dollar change. A partial dollar total has a partial percentage over
the same known components; missing calls are not fabricated. When only stock change
is available its percentage uses prior stock value. Missing or nonpositive matching
prior capital leaves the percentage unavailable. This is a display estimate, not a
cash-flow-adjusted brokerage account return.
