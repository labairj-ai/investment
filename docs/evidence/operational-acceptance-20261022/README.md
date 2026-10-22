# Operational acceptance checkpoint

Base: clean main `6cb6fde0471c207cdec48e648331caff8d8e68c0`.
Task branch: `codex/operational-acceptance-0795`.

## Scope and acceptance

Resolve 0795 first, then integrate the existing hardening branch and prove exact-head
CI for 0796. Preserve financial safeguards, all release gates and the skipped-test
inventory. No production data changes, deployment, pilot starts or autonomy activation
are included in this checkpoint. A model contract migration needs human acknowledgment
and independent investment-sensitive review before merge.

## Diagnosis

Clean-main reproduction: **327 passed, seven failed** using Python 3.12.12 and
`pytest tests/test_cc_behavior_fingerprint.py tests/test_cc_release_security.py
-q --tb=short`. Exact test names and messages are in [the captured output](clean-main-focused.txt).

| Failing test | Cause and classification |
|---|---|
| `test_independent_inventory_and_all_guarded_functions_classified` | Incomplete release integration: two new guarded helpers were unclassified. |
| `test_unclassified_addition_requires_deliberate_classification` | Same unclassified helpers contaminate the otherwise valid fixture. |
| `test_source_proven_definition_migration_keeps_runtime_versions` | Same classification findings reject the legitimate fixture migration. |
| `test_definition_migration_requires_trusted_git_source` | Same classification findings reject the positive fixture setup. |
| `test_cli_inventory_reports_all_canonical_component_names` | Valid fail-closed CLI rejects the unrecorded behavioral transition. |
| `test_cli_exact_event_sha[push]` | Valid fail-closed CLI rejects baseline/source mismatch without a versioned manifest. |
| `test_cli_exact_event_sha[pull_request]` | Same mismatch; exact event authority works correctly. |

Affected sources: `agents/covered_call_agent.py` changes in `6a4ade9` and `6cb6fde`,
the missing helper registrations in `covered_call_fingerprint.py`, and the unchanged
model release identity/baseline. These are explained release integration failures,
not reasons to weaken tests or claim an environment failure.

The old engine hash is `bfdf6e9d15d452d82426975483d009b57d17827d5da9866883da1e67bd4d0193`.
Main computes `68ac6cf2d11d825c…`. The simulator hash remains
`b8be3b06388cb68c7be9e53488ca6f473cc3bee15f81ed93461c802e951ce8f2`.
[The semantic source inventory](semantic-source-inventory.json) identifies exactly
two added helpers and two changed entry/management functions. JSON safety changes
recommendation availability and persisted evidence, so treating these helpers as
nonbehavioral would hide protected behavior.

## Implemented and proposed

Both helpers now enter the model registry and independent golden inventory. Existing
parameterized mutation tests consequently cover each helper. Nine new regression
cases prove non-finite values become null, finite values remain intact, strict JSON
works for nested payloads, and inputs are not mutated. No runtime investment source
or safety configuration was edited.

The [migration proposal](proposed-cc-migration.md) and
[proposed baseline](proposed-cc-baseline.json) are review artifacts outside the active
manifest/baseline locations. They advance cc-v3.3 to cc-v3.4, reset prospective promotion
eligibility, retain VERSION_CENSORED, and leave the simulator unchanged. Acknowledgment
is explicitly false. The active baseline remains untouched.

After acknowledgment, apply the reviewed manifest and version transition, then run
the focused tests, full suite and unchanged CC contract gate again. Independent
human review remains necessary before merge. Current red gates are never certification
evidence.

## Remaining dependency gates

0796 cannot close until 0795 and exact-head GitHub Actions are green. 0797 requires
a human administrator to configure main protection and provision a separate nonadmin
operational identity; agent code may only inspect it. 0798 requires a selected isolated
host and an approved prebuilt digest-pinned image. 0799 requires an operator-generated,
authenticated production backup, with signing material kept outside the agent.
0800 requires real PASS from all three environmental components. 0801 must then
accumulate three real human-reviewed pilots spanning seven New York calendar days.
0802 is a separate human activation decision. All these tasks remain open.

## Validation result

Candidate focused: **342 passed, three failed**. Full repository suite: **2685 passed,
three failed, 18 skipped**. All three failures reject the pending migration; none
were waived. The complete skipped inventory and reasons are in
[full-suite-inventory.json](full-suite-inventory.json). TODO consistency and the
repository agent contract pass. The release baseline and CC contract correctly
remain FAIL; no CI or readiness success is claimed.

## Acknowledged deployment candidate

The user explicitly acknowledged the proposed transition after authorizing deployment.
The active manifest is now `cc_change_manifests/20261022-cc-json-missing-metrics.md`;
the runtime is cc-v3.4 and the baseline matches the reviewed classified source.
The proposal files and earlier failure logs above are historical evidence.
The exact trusted-prior CC gate passes against main `6cb6fde`.
Release fixtures now derive a future model version from the runtime version, preserving
all positive/negative release assertions after cc-v3.4 becomes current.
The existing deployed hardening code is integrated, preventing a dashboard/harness downgrade.
Fresh focused/full-suite and exact-head CI evidence are required before deployment.
Independent review remains required before any merge; this operator-authorized branch
deployment does not activate autonomy or count as a supervised pilot.

## Verified rollout — 2026-10-22

Deployed `0c775008ad9ec0fa8ed32cc61a1d9c3215ce80ce` on OptiPlex.
[Exact-head CI](https://github.com/labairj-ai/investment/actions/runs/39817307304)
is SUCCESS. Local and CI test inventories match: **2852 passed, 18 skipped, zero
failures**; all required release gates pass. See [green validation](green-validation.json),
[complete full-suite output](green-full-suite.txt), and [deployment receipt](deployment.json).

Service active; normal HTTPS endpoint 200; authenticated API 200 and unauthenticated
API 403. Read-only Advisor health, mutation-safety and functional-contract checks PASS.
Holdings, development ledger and service configuration hashes remain unchanged.
Backups and rollback source are retained outside the HTTP root in the receipt's
backup directory. No live data restoration or autonomy activation occurred.

The agent dashboard continues to report missing operational certification, effective
GitHub protection, authenticated snapshot and sandbox evidence. The pilot history
and seven-day requirement remain unmet. This deployment is not technical certification
or a supervised pilot. Independent PR review remains outstanding before merge.
