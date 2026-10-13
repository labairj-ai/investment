"""TODO status/folder consistency check.

Rules:
  - Files under .todos/done/ must not declare an open-state status (backlog, in-progress).
  - Files under .todos/ (not done/) must not declare a completed-state status (done).
  - Non-TODO Markdown files (no ID front-matter) are silently skipped.

Exit 1 if any violations found; 0 otherwise.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODOS_DIR = ROOT / '.todos'
DONE_DIR = TODOS_DIR / 'done'

OPEN_STATES = {'backlog', 'in-progress'}
DONE_STATES = {'done', 'completed', 'resolved'}
STATUS_RE = re.compile(r'^\s*-\s*\*\*Status:\*\*\s*(\S+)', re.MULTILINE)
ID_RE = re.compile(r'^\s*-\s*\*\*ID:\*\*\s*(\d+)', re.MULTILINE)


def parse_todo_file(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    id_match = ID_RE.search(text)
    status_match = STATUS_RE.search(text)
    if not id_match or not status_match:
        return None  # not a structured TODO file
    return dict(
        path=path,
        todo_id=id_match.group(1),
        status=status_match.group(1).lower().strip(),
    )


def check_consistency(todos_dir=None, done_dir=None):
    todos_dir = todos_dir or TODOS_DIR
    done_dir = done_dir or DONE_DIR
    violations = []

    # Check done/ folder
    if done_dir.exists():
        for md in sorted(done_dir.glob('*.md')):
            meta = parse_todo_file(md)
            if meta is None:
                continue
            if meta['status'] in OPEN_STATES:
                violations.append(dict(
                    path=str(md.relative_to(ROOT)),
                    todo_id=meta['todo_id'],
                    status=meta['status'],
                    rule='DONE_FOLDER_OPEN_STATUS',
                    message=f"File in done/ has open-state status '{meta['status']}'; expected one of {sorted(DONE_STATES)}.",
                ))

    # Check open .todos/ folder (immediate children only, not done/)
    if todos_dir.exists():
        for md in sorted(todos_dir.glob('*.md')):
            meta = parse_todo_file(md)
            if meta is None:
                continue
            if meta['status'] in DONE_STATES:
                violations.append(dict(
                    path=str(md.relative_to(ROOT)),
                    todo_id=meta['todo_id'],
                    status=meta['status'],
                    rule='OPEN_FOLDER_DONE_STATUS',
                    message=f"File in .todos/ has completed-state status '{meta['status']}'; move to done/ or correct the status.",
                ))

    return dict(passed=not violations, violations=violations)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Output JSON')
    args = parser.parse_args()
    result = check_consistency()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result['passed']:
            print('[TODO_STATUS] OK — no folder/status mismatches found')
        else:
            print(f"[TODO_STATUS] FAIL — {len(result['violations'])} violation(s):")
            for v in result['violations']:
                print(f"  {v['rule']}: {v['path']} (status={v['status']})")
                print(f"    {v['message']}")
    sys.exit(0 if result['passed'] else 1)
