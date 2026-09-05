---
description: Capture a task into the .todos/ backlog as one NNNN-slug.md file
argument-hint: <one-line description of the task>
allowed-tools: Bash(date:*), Bash(mkdir:*), Read, Write, Glob, Grep
---

# Add a backlog item

Capture the task described in **$ARGUMENTS** as a single, well-formed backlog file.

**Do NOT implement anything.** This command only creates the entry. Do not open files
beyond what step 3 and step 5 need, and do not start a research pass on the codebase.

## Procedure

1. **Resolve the description.**
   - If `$ARGUMENTS` is empty, ask for a one-line task description and stop until you have it.
   - Derive a Title (imperative, ≤ ~10 words) and a kebab-case `slug`
     (lowercase, alphanumerics and dashes, no leading article, ≤ ~6 words).

2. **Locate the backlog.** Use `.todos/` at the repository root. Create it if it doesn't exist.

3. **Dedupe.** Glob `.todos/*.md` and read the first `# ` heading of each. If the new task
   clearly duplicates an existing entry, STOP and report which file already covers it.
   Near-misses are not duplicates — when unsure, create the new entry.

4. **Pick the next ID.** Highest existing `NNNN` prefix plus one, zero-padded to four digits.
   Start at `0001` for an empty backlog. Never reuse an ID, even if a file was deleted.

5. **Write `.todos/NNNN-slug.md`** using the template below. Get the date from `date +%F`.
   Fill in what you can infer from `$ARGUMENTS` plus at most a quick glance at the repo.
   Leave a field as `unknown` rather than guessing — especially `Touches` and `Depends`.

6. **Report** the path created and the title, in one line. Nothing else.

## Template

```markdown
# <Title>

- **ID:** NNNN
- **Status:** backlog
- **Created:** YYYY-MM-DD
- **Priority:** normal
- **Depends:** none

## Problem

<What's wrong, missing, or wanted. Two or three sentences. Written so it still
makes sense in three months with no memory of this conversation.>

## Proposed approach

<A sketch, not a design doc. Bullet points are fine. If there's a real open
question about the approach, write it down as a question rather than resolving it.>

## Touches

<Files or directories you'd expect to change, or `unknown`.>

## Done when

- [ ] <Observable acceptance criterion>
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced
```

## Field notes

- `Status` is one of: `backlog`, `in-progress`, `blocked`, `done`.
- `Priority` is one of: `low`, `normal`, `high`.
- `Depends` is either `none` or a comma-separated list of IDs (`0003, 0007`).
  Only record a dependency the user stated or that is structurally obvious.
