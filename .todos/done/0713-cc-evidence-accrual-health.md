# Add CC Evidence Accrual Health and Promotion Progress Monitoring

- **ID:** 0713
- **Status:** backlog
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0706, 0707, 0712

## Problem

Evidence can appear to be accumulating while usable N remains flat because observations are excluded for missing snapshots, missing fills, version censoring, incomplete chains, or duplicate sessions. There is currently no single view that makes simulator-certification progress and V3 promotion progress measurable and debuggable at a glance.

## Proposed approach

Create one **CC Evidence Accrual Health** report exposed via API and rendered in the Learning Lab dashboard, with three sections:

- **Simulator certification progress:** required N, usable N, completed actual chains, excluded N broken out by exact reason (missing decision episode, missing fill evidence, missing as-of snapshot, data-quality censor, version-censored replay), chains awaiting terminal completion, simulator contract version/hash, certification status.
- **Promotion progress:** eligible paired N / required N, divergent N / required divergent N, prospective elapsed days / required days, total forward opportunities, and all exclusion buckets (duplicate ticker/session, version/config mismatch, uncertified simulator, censored/version-censored virtual chains, champion/challenger incomplete, horizon mismatch, share-basis mismatch). Preliminary economic deltas labeled `PRELIMINARY` until all gates pass.
- **Evidence velocity:** new forward opportunities last 7 and 30 days, new completed paired outcomes last 7 and 30 days, new divergent opportunities last 7 and 30 days, virtual chains opened/completed/censored last 7 and 30 days, estimated days-to-minimum-N based on trailing velocity (diagnostic only, must not influence scoring or promotion).

## Touches

- New report module or extension of existing promotion/certification module
- `serve.py` (new API endpoint)
- Learning Lab dashboard panel
- Tests

## Done when

- [ ] Single endpoint returns simulator certification progress and promotion progress as structured data
- [ ] Every displayed count reconciles to underlying episode IDs
- [ ] Exclusion reasons are mutually exclusive per episode (no double-counting unless documented)
- [ ] 7-day and 30-day velocity counts are date-bounded correctly and exclude retrospective/QA-only episodes
- [ ] Estimated days-to-N is absent when velocity is zero or cohort version changed
- [ ] Preliminary economic deltas are labeled `PRELIMINARY — NOT PROMOTION ELIGIBLE` until all gates pass
- [ ] Dashboard shows certification and promotion progress in separate panels, each with current / required
- [ ] Warning fires if eligible N has not increased for 30 days despite new CC opportunities
