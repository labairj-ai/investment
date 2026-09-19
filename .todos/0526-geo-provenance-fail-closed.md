# Fail Closed on Geo Provenance in _geo_evidence_quality

- **ID:** 0526
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0522

## Problem

`_geo_evidence_quality()` has a fail-open corner case: if `source_date` is absent, the freshness check is skipped entirely, and a `confidence="high"` row still returns `"full"`. The intended policy is `high confidence + sufficiently recent source_date → full`, but missing or malformed dates bypass the freshness gate. Future geo rows ingested without a source date could silently become attribution-eligible. The existing medium-confidence seeds are currently safe (they return `"partial"`), but this is a future ingestion hole that should be closed before any high-confidence rows are added.

## Proposed approach

In `_geo_evidence_quality()`, make `source_date` required for `"full"`:

- `source_date` is None or empty string → return `"partial"` (not `"none"` — the record exists; it's just insufficiently documented for full attribution)
- `source_date` is present but unparseable → return `"partial"`
- `source_date` parses to a future date (year > today) → return `"partial"` (impossible date — treat as malformed)
- `source_date` parses and age > 18 months → return `"partial"` (stale)
- `confidence == "high"` AND valid non-future date AND age ≤ 18 months → return `"full"`
- `confidence != "high"` (e.g. "medium", "low", None) → return `"partial"` at best regardless of date

This means `"full"` is only reachable through two explicit gates: confidence AND freshness. Neither alone is sufficient.

Add a log line when a high-confidence row is downgraded due to missing/stale/malformed date, so operators know which rows need re-sourcing.

## Touches

- `portfolio_ai.py` — `_geo_evidence_quality()` only; tighten the date-absent and future-date branches

## Done when

- [ ] Missing `source_date` returns `"partial"`, never `"full"`, even for `confidence="high"`
- [ ] Unparseable `source_date` returns `"partial"`
- [ ] Future `source_date` (year > today) returns `"partial"`
- [ ] Only `confidence="high"` + valid + non-future + age ≤ 18 months returns `"full"`
- [ ] A log/print message is emitted when a high-confidence row is downgraded due to date issues
