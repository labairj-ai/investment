# 0877 — Include all priced calls in portfolio value

Status: in-progress
Base: 5803c1b46775799a037c84e81b4b58a2cfcb136c
Risk: conservative L5 financial display; existing mark eligibility unchanged.

Problem: a missing quote discards the other verified call liabilities from display.
User authorization: calculate and show everything available, including covered calls,
without allowing one missing contract to suppress the rest.

Scope: retain the verified-call subtotal and per-position values; subtract the known
subtotal from stocks for headline and goal. Show stock and known CC amounts and
priced/open coverage. Missing liabilities remain unknown. Keep complete-net fields
nullable for existing financial consumers. Expiry removes only expired call values.
No new quote providers, SQL writes, P&L, recommendations or trading-policy changes.

Acceptance: multiple calls with missing, stale and restored quotes; verify each
known amount, multiplier, totals, coverage, per-call expiry and shared goal value.
Read-only valuation and nullable complete net remain protected. Generated synthetic
HTML/JS checks, focused tests, unchanged release gates, full CI and production QA.
Use the existing task-authorized owner release workflow; no additional user decision.
