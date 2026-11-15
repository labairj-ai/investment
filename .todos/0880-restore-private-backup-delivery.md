# 0880 — Restore private backup delivery

Status: in-progress
Base: daba23d63263fb40760d94e470cc03c542e4b1c4

Learning Lab's red watchdog component is backup delivery. The runtime database is
290 MB, beyond regular GitHub file limits, with 74 unpushed backup commits and
120-second wrapper timeouts. Keep the existing private destination and consistent
SQLite snapshot. Compress the database for Git, serialize backup writers, bound
Git network waits, verify the destination, and preserve original unpushed history
locally before a normal fast-forward compressed-backup commit. Never force-push,
delete historical receipts, or suppress health failures. No new backup service.

Validate compressed restore integrity and timeout/destination behavior, unchanged
watchdog regression tests, full release checks and a genuine private-backup success
receipt. Preserve source data, account state and notification policy.
