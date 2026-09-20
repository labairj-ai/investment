# Canonical Evidence Quality Enum: Standardize good/limited/none to full/partial/none

- **ID:** 0518
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0517

## Problem

`_fetch_company_evidence()` returns `"good"` / `"limited"` / `"none"`, but the gate dict `_EV_MIN_FOR_USABILITY` expects `{"full", "partial"}`. Because `"good"` and `"limited"` are never in `{"full", "partial"}`, every dimension evaluates `usable_for_attribution = False` on every ticker. The two-gate attribution filter never accumulates any formally usable data — the mismatch silently breaks the entire Learning Lab pipeline.

`MACRO_SCORE_SCHEMA_VERSION` is currently `"v2"`. After this fix the stored vocabulary changes, which makes existing stored score blobs incompatible with new attribution reads, so a schema version bump to `"v3"` is required.

## Proposed approach

**Standardize the vocabulary to `full` / `partial` / `none` / `unsupported`:**

- `"good"` → `"full"` (strong or well-sourced evidence)
- `"limited"` → `"partial"` (thin or estimated evidence)
- `"none"` → `"none"` (no evidence found — dimension not attributable)
- `"unsupported"` — new literal for fund/unsupported tickers (already bypassed before this gate, but explicit is better than silent)

Change `_fetch_company_evidence()` to return the new literals everywhere:
```python
if strong_evidence:
    return "full"
elif thin_evidence:
    return "partial"
else:
    return "none"
```

Update `_EV_MIN_FOR_USABILITY` (which already uses `{"full","partial"}`) — the gate dict is now correct once the producer matches.

**Schema v3**: bump `MACRO_SCORE_SCHEMA_VERSION = "v3"`. The schema change is:
- All `*_evidence_quality` fields now carry `full`/`partial`/`none`/`unsupported` literals
- Attribution script skips episodes with `schema_version != "v3"` by default; `--include-legacy` allows v2

**Attribution script**: add `--include-legacy` already exists from 0513; extend it to also admit v2 episodes when `--include-legacy` is passed. Add a check:
```python
if e["macro"].get("schema_version") not in {"v2","v3"}:
    ...  # already handled by 0513 gate
```

## Touches

- `portfolio_ai.py` — `_fetch_company_evidence()`, `MACRO_SCORE_SCHEMA_VERSION`
- `scripts/macro_attribution.py` — schema version gate extended to v3
- Any test fixtures or acceptance records that store `"good"`/`"limited"` literals

## Done when

- [ ] `_fetch_company_evidence()` returns only `full`/`partial`/`none`/`unsupported`
- [ ] `_EV_MIN_FOR_USABILITY` values match new vocabulary (no change needed — already correct)
- [ ] `MACRO_SCORE_SCHEMA_VERSION = "v3"`
- [ ] Attribution script admits `schema_version == "v3"` as the current gate
- [ ] At least one test ticker shows `rate_sensitivity_usable_for_attribution = True` after fix
