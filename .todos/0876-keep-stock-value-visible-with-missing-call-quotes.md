# 0876 — Keep stock value and portfolio goal visible with missing call quotes

Status: in-progress
Base: d82aa1032eca0d0255d2531e690ab6e1676a9284
Risk: financial display only, conservative L5; no valuation eligibility changes.

Problem: one missing or expired call quote hides the entire headline and goal.
Scope: show verified gross-stock snapshot while the fully adjusted net is unknown;
label Stock value · option adjustment incomplete. Headline, goal and target progress
share the display basis. Restore net and its label when complete quotes return.
Keep net_value/totalValue and missing liability null. Dividend net yield and financial
consumers retain their existing nullable net value; no SQL, pricing, P&L or policy
change. Show unavailable only if stock value itself is unavailable.

Acceptance: synthetic initial incomplete, expired, failed-feed and restored-feed
UI cases; zero stock value remains visible; invalid stock data remains unavailable;
real JS checks and generated fixture checks; unchanged required gates and full CI.
Use PR and applicable owner release controls; keep TODO open until QA is complete.
