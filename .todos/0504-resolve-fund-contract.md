# Resolve Fund Scoring Contract: Unsupported vs Display-Only

- **ID:** 0504
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0486

## Problem

There is a production contract inconsistency: `_fetch_company_evidence()` marks fund tickers as `evidence_quality = "unsupported"` across all four dimensions, but the weekly macro scorer still sends fund tickers to the LLM and persists their 1–10 scores. This means funds appear in the repeatability test and produce unstable scores, and those scores could silently enter Decision Episode macro snapshots as if they were validated structural features. This directly caused the 15 WARNs in the live acceptance run — several were funds (VVIAX, VTMGX, VTSAX).

## Proposed approach

Choose one contract and enforce it consistently:

**Preferred approach** — funds are fully unsupported:
- In `generate_holding_macro_scores()`, skip fund tickers entirely (do not send to LLM, do not store 1–10 scores)
- Dashboard shows `"Unsupported — fund/ETF"` instead of a score card with AI estimates
- `_build_macro_snapshot()` for fund tickers returns `{"macro_supported": false, "coverage_state": "fund_unsupported"}`
- Fund tickers do not appear in repeatability tests

**Alternative** — display-only estimates (only if dashboard display is important):
- Score funds but tag every output with `"display_only_estimate": true, "macro_supported": false`
- Never include display-only scores in Decision Episode formal features
- Never include them in Learning Lab attribution
- Dashboard clearly labels them: "AI estimate — display only, not validated"

If the preferred approach breaks the dashboard visually for fund-heavy portfolios, use the alternative with strict tagging — but never mix with company scores.

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()` — skip or tag fund tickers
- `generate_dashboard.py` — fund holding macro card (show "unsupported" or labelled estimate)
- `scripts/validate_macro_scorer.py` — exclude fund tickers from repeatability test tickers

## Done when

- [ ] Fund tickers either skipped entirely or tagged `display_only_estimate=true` in the scorer
- [ ] Fund scores never appear as `macro_supported=true` in Decision Episode snapshots
- [ ] Funds excluded from live repeatability test (no unstable fund scores in acceptance run)
- [ ] Dashboard shows appropriate label for fund holdings (not a bare 1–10 score)
