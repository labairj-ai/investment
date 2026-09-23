# Tighten Confirmation Freshness and Fail-Closed Semantics

- **ID:** 0609
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0606

## Problem

Three confirmation channels have correctness gaps that allow stale or non-independent signals to cast votes. (a) Guardian findings with `expires_at IS NULL` are accepted indefinitely, so a finding from months ago can confirm today's news. (b) Thesis independence fails open: if either timestamp is missing, the thesis is treated as independent and votes. Missing provenance should produce no vote, not a free pass. (c) `_get_fundamentals_trend()` still has a generic revenue fallback in its `else` branch — any event type not matched by the whitelist silently becomes a revenue-YoY vote. REGULATORY is also explicitly routed through the net-debt branch despite no reliable economic link.

## Proposed approach

- **Guardian freshness:** Find the latest completed `portfolio_guardian` run with `started_at < snap_ts` and `status='done'`; only accept ticker findings from that specific run. This ensures that if yesterday's Guardian sweep no longer flagged a ticker, older findings cannot continue voting. Also whitelist qualifying finding types: `position_risk` and `risk_contribution` are genuinely ticker-level independent signals; `sector_concentration`, `portfolio_beta`, `correlation_cluster`, `layer_drift` are portfolio-level and should not count as ticker confirmation.
- **Thesis fail-closed:** Change `thesis_independent = (th_eval_at is None or snap_ts is None or th_eval_at < snap_ts)` to `thesis_independent = (th_eval_at is not None and snap_ts is not None and th_eval_at < snap_ts)`. When timestamps are missing, store health as contextual info but cast no vote.
- **Fundamentals whitelist:** Replace the `else` fallback with `return None`. Only the three explicitly mapped branches vote: `DEMAND/GUIDANCE_CHANGE/EARNINGS → revenue`, `MARGIN/PRICING → gross margin`, `CREDIT_DEBT → net debt`. Remove `REGULATORY` from `_FUNDAMENTALS_DEBT_EVENTS` → `None`.

## Touches

- `agents/news/intelligence.py` — `_get_agent_findings_flag()` (latest-run scoping + type whitelist); `attach_confirmation()` (thesis_independent formula); `_get_fundamentals_trend()` (remove else fallback; remove REGULATORY from debt set)
- `tests/test_news_intelligence.py` — test old Guardian finding not accepted when newer run exists with no flag; test missing thesis timestamps produce no vote; test REGULATORY returns None

## Done when

- [ ] `_get_agent_findings_flag()` only uses findings from the latest completed pre-snapshot Guardian run
- [ ] Only `position_risk` and `risk_contribution` finding types qualify as ticker confirmation
- [ ] `thesis_independent` is False when either `th_eval_at` or `snap_ts` is None (fail closed)
- [ ] `_get_fundamentals_trend()` returns None for all event types not in the explicit whitelist
- [ ] REGULATORY returns None from `_get_fundamentals_trend()`
- [ ] All new behaviors covered by tests
