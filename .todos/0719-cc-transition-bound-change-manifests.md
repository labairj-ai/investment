# Bind CC Change Manifests to the Exact Behavioral Contract Transition

- **ID:** 0719
- **Status:** backlog
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0718

## Problem

The current manifest check treats the existence of any non-template file in `cc_change_manifests/` as sufficient. An old manifest could therefore authorize a later unrelated behavioral change.

A manifest must authorize exactly one transition from one approved contract state to one proposed state.

## Proposed approach

Keep the human-readable Markdown manifest, but add a fixed machine-readable metadata block/front matter containing:

- `manifest_id`
- `date`
- `category`
- `author`
- `related_commit_or_pr`
- prior model/simulator/contract versions and hashes
- proposed model/simulator/contract versions and hashes
- `cohort_reset_required`
- `open_chain_policy`
- `operator_acknowledged`

The checker must locate exactly one applicable manifest whose prior state matches the committed baseline and whose proposed state matches current contract state.

## Implementation guardrails

- `has_manifest = bool(manifests)` is no longer sufficient.
- Never select by newest filename/date alone.
- Match exact prior/current contract identity.
- Duplicate applicable manifests fail.
- Mismatched hashes/versions do not qualify.
- Historical manifests remain immutable and cannot authorize future changes.
- Template never qualifies.
- Operator acknowledgment must be explicit.
- Non-behavioral unchanged contracts do not require behavioral manifests.

## Touches

- `cc_change_manifests/.template.md`
- `covered_call_change_control.py`
- `scripts/check_cc_contract.py`
- manifest parser/helper
- tests

## Acceptance tests

- [ ] Exact baseline A -> current B manifest qualifies.
- [ ] Old A -> B manifest does not authorize B -> C.
- [ ] Correct versions but wrong engine hash fails.
- [ ] Correct hashes but wrong simulator contract version fails.
- [ ] Wrong prior baseline state fails.
- [ ] Two applicable manifests cause ambiguity failure.
- [ ] Missing ID/category/prior/proposed hashes/operator acknowledgment fails.
- [ ] Duplicate manifest IDs fail.
- [ ] Template is ignored.
- [ ] Behavioral drift with only unrelated historical manifest fails.
- [ ] Non-behavioral unchanged contract passes without manifest.

## QA requirements

- [ ] Parse valid and malformed sample manifests.
- [ ] Test duplicate IDs and duplicate transition authorization.
- [ ] Exercise disposable A -> B with exact manifest.
- [ ] Exercise B -> C while only A -> B exists and confirm failure.
- [ ] Add exact B -> C manifest and confirm manifest requirement passes.
- [ ] Contract-check output prints selected manifest ID/path and short prior/proposed hashes.

## Done when

- [ ] Each manifest authorizes exactly one transition
- [ ] Old manifests cannot authorize new changes
- [ ] CI reports the exact applicable manifest
- [ ] Manifest history remains auditable
