# Exact release failure inventory (0710)

Baseline: `dfc011d`, reproduced on an unchanged checkout on 2026-10-13.
Prior independent reproduction: `b90b525`. First failing commits are not known;
these records do not pretend the first observation proves introduction history.
The original four signatures are retained. Two broker fixture failures are resolved
in this release and are never waived; only the two calibration failures remain active.
The machine inventory is `config/release_baseline_failures.json`. Full normalized
tracebacks and exact assertion/error signatures are stored for each failure.

Waiver owner: investment-maintainer. These are active fixture bugs with temporary
release debt acceptance, reviewed no later than **2026-11-12**. They do not waive
any covered-call-specific failure. Production safety gates must not be weakened
to make these fixtures pass.

## Failure 1

`tests/test_calibration.py::TestObserveShadowScoring0360::test_paper_active_gate_passes_with_mature_observations`

The fixture seeds legacy maturity dates without the current session/horizon
contract, so the expected eligible prospective cohort is absent. Remediation:
update fixtures to current session maturity fields and retain all live promotion
thresholds. Category: active test-fixture bug; subsystem: equity learning.

## Failure 2

`tests/test_calibration.py::TestStateSpecificPromotionGates0355::test_observe_to_paper_active_passes_after_14_days`

Same maturity/session fixture debt, with the observe-duration setup. Remediation:
use explicitly matured session-based rows rather than assuming elapsed calendar
time alone qualifies them. Category: active test-fixture bug; equity learning.

## Failure 3

`tests/test_fill_hardening.py::test_sync_fill_preserved_when_process_new_intents_halts[BrokerStateIntegrityError]`

Baseline market marks become stale when network refresh is unavailable; submission is blocked
before the injected halt path executes. Remediation: inject fresh marks and a
controlled clock in the fixture. **Resolved in this release:** the exact halt-path
test supplies fresh quote fixtures, so it no longer depends on network refresh.
Keep stale-mark submission protection in live code. Category: active test-fixture bug; broker fill hardening.

## Failure 4

`tests/test_fill_hardening.py::test_sync_fill_preserved_when_process_new_intents_halts[BrokerSubmissionIndeterminate]`

Same stale-mark fixture problem for the other indeterminate submission error.
Remediation: fresh market fixtures and controlled clock, preserving actual broker
halt behavior. **Resolved in this release:** the shared parametrized test now uses
explicit fresh quotes. Any recurrence fails the gate as a new regression. Category: active test-fixture bug; broker fill hardening.

## Release gate

```sh
venv/bin/python -m pytest tests --junitxml=/tmp/investment-tests.xml
venv/bin/python scripts/check_release_baseline.py /tmp/investment-tests.xml
```

A new failure, changed signature, expired waiver, duplicate/malformed inventory,
or a resolved failure still left in inventory fails the gate. A disappearing
failure is reported as an improvement requiring inventory cleanup. There are no
broad ignore patterns or xfail markers. CI always uploads the JUnit artifact and
uses this same gate after the full suite, even when pytest exits nonzero.
