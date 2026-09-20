# Geo Evidence Provenance: Source, Date, Confidence, Hash

- **ID:** 0516
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0508

## Problem

The `company_geo_profile` seeds for ITOCF and MITSF were inserted with `INSERT OR IGNORE` and no provenance fields — no source, source date, retrieval date, confidence level, or evidence hash. Manual seeds can persist indefinitely without any way to know when the data was collected, how reliable it is, or whether it needs refreshing. Formal geopolitical attribution must remain disabled until geo facts are sourced and dated.

## Proposed approach

Add provenance columns to `company_geo_profile`:
- `data_source TEXT` — "manual_seed" / "company_filing" / "bloomberg" / "manual_research"
- `source_date TEXT` — date the underlying data was valid (e.g. "2026-09" for a Q2 filing)
- `retrieved_at TEXT` — ISO timestamp when this row was written
- `confidence TEXT` — "high" / "medium" / "low" / "estimate"
- `evidence_hash TEXT` — SHA-256 of the material fields for change detection
- `notes TEXT` — free-text rationale

Update the ITOCF and MITSF seed rows to include all fields:
```python
("ITOCF", ..., "manual_research", "2026-09", datetime.utcnow().isoformat(),
 "medium", hash_of_fields, "Ito Corporation — Japanese general trading company; EM/Asia exposure estimated from annual report"),
("MITSF", ..., "manual_research", "2026-09", datetime.utcnow().isoformat(),
 "medium", hash_of_fields, "Mitsubishi Corporation — diversified Japanese conglomerate; global operations per IR materials"),
```

Change `INSERT OR IGNORE` to `INSERT OR REPLACE` with a retrieval date update so stale seeds can be refreshed.

Geopolitical attribution remains disabled (requires `geo_evidence_quality = "full"` per 0512) until at least one ticker has confidence="high" or "medium" with a sourced date. Add a note in `macro_attribution.py` indicating the disable condition.

## Touches

- `portfolio_ai.py` — `_init_ai_tables()` (new columns), seed data
- `scripts/macro_attribution.py` — geo disable-until condition documented

## Done when

- [ ] `company_geo_profile` has `data_source`, `source_date`, `retrieved_at`, `confidence`, `evidence_hash`, `notes`
- [ ] ITOCF and MITSF seeds include all provenance fields with source and date
- [ ] `INSERT OR REPLACE` used so stale seeds can be refreshed
- [ ] Geo attribution remains disabled until at least one ticker has sourced, dated geo evidence
- [ ] Attribution script documents the geo disable condition explicitly
