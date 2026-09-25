# Eastern-Time Operational Logs for Human Review

- **ID:** 0674
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** none

## Problem

Application logs generated for manual inspection show UTC times, requiring operators to mentally convert when correlating log events with market activity. Machine/audit timestamps must remain UTC; only the human-readable presentation layer should show Eastern context.

## Proposed approach

Do not alter timestamps required by external log infrastructure or structured logging systems.

For application logs generated directly for human review, add Eastern context alongside the UTC canonical value:

```
2026-09-24 20:42:15 EDT [2026-09-25T00:42:15Z]
```

Or configure a logging formatter that wraps log output with Eastern time while preserving canonical UTC in structured log fields. Log ordering must remain based on UTC, never on Eastern-formatted strings.

## Touches

- Logging configuration / formatter
- Any application-level log output intended for operator review

## Done when

- [x] Machine/audit timestamp remains UTC
- [x] Human-readable operational output can show Eastern time
- [x] Log ordering is based on UTC timestamps
- [x] No downstream parsing depends on Eastern-formatted prose
## Outcome

Implemented as part of 0668-0680 batch commit.
