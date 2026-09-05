---
description: Show the .todos/ backlog and start work on one item
argument-hint: [item ID, slug, or nothing to see the list first]
---

# Work the backlog

## Procedure

1. **Read the backlog.** Glob `.todos/*.md`. For each file, read the Title, Status,
   Priority, and Depends fields only — do not read whole bodies yet.

2. **If `$ARGUMENTS` is empty**, print the backlog as a compact table
   (ID, Title, Status, Priority, Depends), ordered: `in-progress` first, then
   `backlog` by priority then ID, then `blocked`, then `done` last. Then stop and
   ask which item to pick up. Do not choose for the user.

3. **If `$ARGUMENTS` names an item** (ID like `0004`, or a slug fragment), resolve it
   to exactly one file. If it's ambiguous, list the candidates and stop.

4. **Check the gate.** If the item's `Depends` lists any ID whose Status isn't `done`,
   say so and stop — don't start blocked work without the user saying to anyway.

5. **Read the full item**, then read the files listed under `Touches`.

6. **Plan before editing.** Restate the Problem and the Done-when criteria in your own
   words, say what you intend to change, and wait for the go-ahead. If the item's
   Proposed approach is stale or wrong given what you now see in the code, say so —
   don't quietly follow a plan that no longer fits.

7. **On the go-ahead**, set `Status: in-progress` in the item file, then do the work.

8. **When the Done-when boxes are all genuinely checked**, set `Status: done`,
   check the boxes, and append a `## Outcome` section: what actually changed and
   anything you learned that the next item should know. Leave the file in `.todos/` —
   the history is the point.

If new work surfaces along the way that isn't part of this item, do not scope-creep
into it. Mention it and offer to file it with `/todo-add`.
