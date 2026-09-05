---
description: Show only backlog items whose dependencies are all satisfied
allowed-tools: Read, Glob, Grep
---

# What can I start right now?

Read-only. Do not edit any file, and do not start implementing anything.

## Procedure

1. Glob `.todos/*.md` and read only the header block of each: Title, ID, Status,
   Priority, Depends.

2. Build the set of IDs with `Status: done`.

3. An item is **ready** when its Status is `backlog` and every ID in its `Depends`
   is in the done set (`Depends: none` is always satisfied).

4. Print three sections, in this order. Omit any section that's empty.

   **In progress** — anything with `Status: in-progress`, so unfinished work is
   visible before new work gets picked up.

   **Ready to start** — the ready set, sorted by priority (high, normal, low) then
   ID. Show ID, Title, Priority.

   **Blocked** — everything else, one line each: ID, Title, and the specific unmet
   dependency IDs. Sort by number of unmet deps ascending, so the items that are
   closest to becoming available sit at the top.

5. Close with a single line: the count ready, the count blocked, and — if exactly one
   item is ready — nothing more. Do not recommend which to pick.

6. If nothing is ready and nothing is in progress, say so directly and name the item
   with the fewest unmet dependencies. That's the bottleneck.

Do not read item bodies. This is a triage view, not a briefing.
