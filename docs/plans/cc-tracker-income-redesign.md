# CC tracker income redesign

## Problem and intended result

The tracker mixes closed-position net income with open-position gross premium in a stacked chart. Gains, losses, and pending premium compete visually; labels cannot explain the distinction at a glance.

## Implementation plan

1. Replace the stacked canvas with a semantic monthly table and proportional signed bars. Each month has exactly one net realized value. The decorative bar extends left for losses and right for gains from a shared zero line. Keep amounts in fixed columns, outside bars.
2. Put four readable summary cards first: current-month net realized income, YTD net realized income, open premium collected, and open option P&L. State explicitly that open premium is not realized profit. Preserve the established YTD inclusion of historical imports and disclose that inclusion.
3. Keep open premium in a separate monthly column, grouped by opening month. Realized income uses closing date, falling back to expiry. Historical placeholder entries stay excluded from the monthly view. Explain grouping under the view.
4. Provide 6-month, 12-month, and all-history ranges. Include zero-activity months, newest first. Range changes affect the monthly view, not headline totals. Retain selection on refresh.
5. Use restrained green/red realized values, neutral open premium, readable tabular dollar amounts, a current-month marker, responsive two-column summary cards, keyboard-accessible range controls, and numeric monthly values on mobile. Remove Chart.js dependencies from this component and show an informative empty state.
6. Leave position actions and detailed rows intact below the summary. Do not alter recommendation, scoring, accounting, or simulator behavior.

## Verification and deployment

Execute the JavaScript with mixed gains/losses, negative and zero months, hidden calendar gaps, historical imports, missing dates/marks, year boundaries, and all range controls. Confirm one realized value per month and that open premium never contributes to it. Generate the production dashboard only on OptiPlex, check all emitted script blocks with Node, verify responsive markup and served HTML, and run the CC contract gate. Visually inspect desktop/mobile if a browser is available; otherwise explicitly report that limitation.
