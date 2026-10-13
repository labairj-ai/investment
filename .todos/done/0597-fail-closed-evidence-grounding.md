# Fail-Closed Evidence Grounding

- **ID:** 0597
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0596

## Problem

Article ID validation in `extract_events_llm()` is not strict enough. (a) `valid_ids` is the set of all portfolio article IDs, so if the LLM puts a MSFT article ID into an ANET event it passes — cross-ticker IDs are not rejected. (b) An event with zero validated `article_ids` is still accepted, and the code falls back to LLM-provided title strings, reintroducing the hallucinated-evidence path that 0589 was supposed to eliminate. (c) The returned event ticker is not validated against the supplied ticker universe, so the LLM can invent new tickers that are not in the portfolio.

## Proposed approach

Implement fail-closed validation in `extract_events_llm()`:
- Unknown ticker (not in `by_ticker` input keys) → reject entire event.
- Returned article ID belonging to a different ticker (`manifest[aid]["ticker"] != event_ticker`) → reject that ID.
- Zero valid same-ticker article IDs remaining after filtering → reject entire event.
- Remove the `titles` string fallback for structured events. Prose display can remain backward-compatible, but structured intelligence events must have verified evidence.

Adversarial test cases:
- LLM response contains unknown ticker → event not in output.
- LLM returns zero article_ids → event not in output.
- LLM references article_id from a different ticker → that ID stripped; if all stripped, event rejected.
- LLM returns valid ID for correct ticker → event accepted.

## Touches

- `agents/news/intelligence.py` — `extract_events_llm()` validation block
- `tests/test_news_intelligence.py` — adversarial test class

## Done when

- [ ] Unknown ticker in LLM response → event rejected, not in `events_by_ticker`
- [ ] Event with zero validated article_ids → rejected
- [ ] Cross-ticker article ID → ID stripped; event rejected if all IDs stripped
- [ ] No title-string fallback in structured event path
- [ ] All four adversarial test cases pass
