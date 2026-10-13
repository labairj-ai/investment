# Clean Resolved Release-Baseline Failures and Restore Green CI

- **ID:** 0717
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0710

## Problem

GitHub Actions is red even though the test suite passes. The release-baseline gate correctly treats resolved known failures as stale inventory, and two previously waived calibration tests now pass. Because they remain in `config/release_baseline_failures.json`, `scripts/check_release_baseline.py` fails after pytest succeeds.

## Proposed approach

Remove only the entries that are now demonstrably resolved. Preserve the existing exact-failure contract:

- new failure => fail
- changed signature => fail
- expired waiver => fail
- resolved known failure still inventoried => fail
- exact active approved failure => known debt

Do not weaken `scripts/check_release_baseline.py`.

## Implementation guardrails

- Do not add new waivers in this TODO unless independently reproduced baseline debt requires one.
- Do not mark passing tests `xfail`.
- Do not make `resolved_stale_inventory` non-blocking.
- Do not broaden signatures or use wildcard test IDs.
- Do not remove still-failing inventory entries merely to obtain green CI.
- Covered-call-specific waivers remain prohibited.
- Preserve exact-node and exact-signature behavior.

## Touches

- `config/release_baseline_failures.json`
- Existing tests for `scripts/check_release_baseline.py`
- GitHub Actions verification

## Acceptance tests

- [ ] The two currently passing tests are removed from active inventory.
- [ ] Full pytest JUnit output has no stale-inventory entries for those tests.
- [ ] A synthetic new failure still fails the gate.
- [ ] A changed known-failure signature still fails.
- [ ] A resolved test left in fixture inventory still fails as stale inventory.
- [ ] An expired waiver still fails.
- [ ] An exact active approved failure still reports known debt.
- [ ] Duplicate IDs, missing fields, and CC-specific waivers remain rejected.

## QA requirements

- [ ] Run full `pytest tests/` and save JUnit output.
- [ ] Run `python scripts/check_release_baseline.py test-results.xml`.
- [ ] Confirm pytest and release-baseline gate both pass.
- [ ] Confirm only resolved inventory entries changed.
- [ ] Verify GitHub Actions is green without new skips/waivers.

## Done when

- [ ] CI is green on unchanged application behavior
- [ ] Stale resolved failures are removed
- [ ] Release-baseline strictness is unchanged
