---
description: Show the .todos/ backlog and start work on one item
argument-hint: [item ID, slug, or nothing to see the list first]
---

# Work the backlog

## Procedure

1. **Read the backlog.** Glob `.todos/*.md`. Read only the header block of each
   (Title, ID, Status, Priority, Depends) — do not read bodies yet.

2. **If `$ARGUMENTS` is empty**, print a compact table (ID, Title, Status, Priority,
   Blocked-by) ordered: `in-progress` first, then unblocked `backlog` by priority then
   ID, then blocked items, then `done` last. Mark blocked rows with the specific
   unmet IDs. Then stop and ask which item to pick up — do not choose for the user.

3. **If `$ARGUMENTS` names an item** (ID like `0004`, or a slug fragment), resolve it to
   exactly one file. If ambiguous, list the candidates and stop.

4. **Check the gate.** If `Depends` lists any ID whose Status isn't `done`, say which
   ones and stop. Don't start blocked work unless the user explicitly says to anyway.

5. **Read the item in full**, then load context from `Touches` — but do NOT read large
   files whole. This repo has several thousand-line modules (`generate_dashboard.py`
   ~7.7k lines, `serve.py` ~5k, `portfolio_ai.py` ~1.6k, `covered_call_rec.py` ~1.2k).
   For any file over ~500 lines:
   - Grep for the specific symbols, constants, or route names the item concerns.
   - Read only the surrounding ranges you need.
   - Say which regions you loaded, so it's visible what you did and didn't look at.

   Files under ~500 lines can be read whole.

6. **Plan before editing.** Restate the Problem and the Done-when criteria in your own
   words, say what you intend to change, and wait for the go-ahead. If the item's
   Proposed approach is stale or wrong given what the code actually looks like now,
   say so plainly — do not quietly follow a plan that no longer fits.

7. **On the go-ahead**, set `Status: in-progress` in the item file, then do the work.

8. **When every Done-when box is genuinely satisfied**, set `Status: done`, check the
   boxes, and append an `## Outcome` section: what actually changed, and anything the
   next item should know. Leave the file in `.todos/` — the history is the point.

   If some boxes are met and others aren't, do not mark it done. Report which remain.

If new work surfaces that isn't part of this item, do not scope-creep into it.
Mention it and offer to file it with `/todo-add`.
