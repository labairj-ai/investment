# Unit-type-aware Scout migration prestate (PR28)

Base: 233752ab76ddeabef2e5a2e9bb3e15288969bc60. Scope: 0852; PR19
remains unmerged and 0853 blocked.

PR27's real PLAN_ONLY failed at PREFLIGHT_VERIFIED with
SYSTEM_UNIT_STATE_INVALID. Read-only diagnosis proved the absent system timer
returned LoadState=not-found, DropInPaths empty and ActiveState=inactive, while
legitimately omitting MainPID and ControlPID. Both service units returned zero
PIDs. Parent protection and reviewed daily timer validation passed; no stamp or
target paths existed. Requiring service PID properties on a timer was the defect.

The migration now validates each fixed target through system_prestate. Every unit
must explicitly report not-found, empty DropInPaths and inactive. The two service
units must additionally report explicit zero MainPID and ControlPID; missing or
nonzero service PIDs fail closed. Timer PID fields are neither required nor
synthesized. Unit-specific allowlisted codes distinguish Scout service, Scout
timer and certification service failures, including manager query failures.
Protected-parent and daily timer failures retain SYSTEM_UNIT_STATE_INVALID.

The shared fixture now omits service-only fields from timers. The actual
Executor-checkout / real migration / real influence integration regression uses
the exact observed absent timer property shape, including omitted PID, execution
status and identity fields, and checks STOPPED_ROLLBACK PLAN_ONLY with zero
mutation. Adversarial cases reject missing/nonzero service PIDs, loaded or active
units, and nonempty or missing DropInPaths.

No host normalization is needed for the timer interface. No financial, execution,
Deployment Agent, observer, certification, acceptance or schedule behavior changes.
The exact daily 16:00 America/New_York calendar, persistent timer, 120-second
randomized delay, 15:50 cutoff, absent stamp and target path requirements remain.
Qualification still requires three genuine automatic daily slots; certification
has zero acceptance credit. No production migration is performed by these tests.
