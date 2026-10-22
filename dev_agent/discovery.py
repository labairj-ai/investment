"""Read-only discovery, explainable prioritization and collision-safe planning."""
from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from datetime import date

from time_utils import today_eastern

from .policy import classify, protected_graph
from .store import CATEGORIES, SOURCES, bounded, digest

SCORE_VERSION = "value-risk-1"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=30).rstrip("\n")


def score(candidate, risk):
    dimensions = candidate.get("dimensions", {})
    values = {}
    for name in ("impact", "severity", "reliability", "maintainability", "performance", "accessibility", "strategic_fit", "complexity", "uncertainty", "rollback_difficulty", "breadth"):
        v = dimensions.get(name, 0)
        if not isinstance(v, (int, float)) or not 0 <= v <= 5:
            raise ValueError("score dimension out of range")
        values[name] = v
    benefit = sum(values[k] for k in ("impact", "severity", "reliability", "maintainability", "performance", "accessibility", "strategic_fit"))
    penalty = sum(values[k] for k in ("complexity", "uncertainty", "rollback_difficulty", "breadth"))
    bonus = 3 if candidate["category"] in {"SIMPLIFY", "REMOVE", "CONSOLIDATE"} and candidate.get("evidence") else 0
    evidence = bool(candidate.get("evidence"))
    total = round(max(0, min(100, (benefit + bonus - penalty) * 100 / 38)), 3)
    level = int(risk["risk"][1:])
    disposition = "REJECT" if not evidence else "HUMAN_REVIEW" if level >= 3 else "RECOMMEND" if total >= 35 else "DEFER"
    return dict(version=SCORE_VERSION, components=values, bonus=bonus, score=total, confidence="EVIDENCED" if evidence else "UNAVAILABLE", disposition=disposition, risk=risk, rationale="bounded benefit minus complexity/uncertainty; risk gates independent")


def architecture_signals(root, exclusions=None):
    root = Path(root); exclusions = exclusions or {}
    for path, exception in exclusions.items():
        if not isinstance(exception, dict) or not all(exception.get(k) for k in ("owner", "rationale", "expires")) or date.fromisoformat(exception["expires"]) < today_eastern():
            raise ValueError("architecture exclusions require owner, rationale and current expiry")
    signals = []; graph = protected_graph(root); duplicate_bodies = {}
    for rel in sorted(graph):
        if rel.startswith("tests/") or rel in exclusions:
            continue
        path = root / rel; text = path.read_text(errors="replace"); lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(node.body) >= 5:
                signature = hashlib.sha256(json.dumps([ast.dump(n) for n in node.body]).encode()).hexdigest()
                duplicate_bodies.setdefault(signature, []).append((rel, node.name, node.lineno))
        handlers = [ast.dump(n.type) if n.type else "bare" for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        repeated = max(Counter(handlers).values(), default=0)
        todo_count = len(re.findall(r"(?m)^\s*#\s*(?:TODO|FIXME)\b", text))
        # Size alone does not trigger a refactor proposal.
        if len(lines) > 1500 and (repeated >= 10 or todo_count >= 5):
            signals.append(dict(source="architecture", category="REFACTOR", title=f"Review exception boundaries in {rel}", problem=f"{len(lines)} lines with {repeated} repeated exception types and {todo_count} debt markers", files=[rel], evidence=[f"{rel}:1"], outcome="Reduce repeated failure handling with measured behavior parity", validation="focused regression and full suite"))
    # Deterministic cycle detection, bounded to one report per cycle.
    visiting, done, cycles = [], set(), set()
    def visit(node):
        if node in visiting:
            cycle = tuple(sorted(visiting[visiting.index(node):]))
            cycles.add(cycle); return
        if node in done: return
        visiting.append(node)
        for dep in sorted(graph.get(node, ())): visit(dep)
        visiting.pop(); done.add(node)
    for node in sorted(graph): visit(node)
    for cycle in sorted(cycles):
        signals.append(dict(source="architecture", category="CONSOLIDATE", title="Review import cycle", problem="Import cycle: " + " -> ".join(cycle), files=list(cycle), evidence=list(cycle), outcome="Remove initialization-order coupling without behavior changes", validation="import-order and regression tests"))
    for signature, locations in sorted(duplicate_bodies.items()):
        if len({p for p,_,_ in locations}) < 2: continue
        signals.append(dict(source="architecture",category="CONSOLIDATE",title="Review duplicated helper implementation",problem="Identical nontrivial function bodies can diverge when maintained separately",files=sorted({p for p,_,_ in locations}),evidence=[f"{p}:{line}:{name}" for p,name,line in locations],outcome="Confirm common semantics before consolidating duplicate logic",validation="shared-helper parity and regression tests"))
    return signals


def scout(root, signals=(), cap=5, exclusions=None, suppressed=()):
    root = Path(root).resolve(); head = git(root, "rev-parse", "HEAD")
    proposals = []
    tracked = git(root, "ls-files").splitlines()
    for rel in tracked:
        if not rel.endswith(".py") or rel.startswith("tests/"):
            continue
        path = root / rel
        if path.is_symlink(): continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            marker = re.match(r"\s*#\s*(TODO|FIXME)\s*:?\s*(.{8,})", line)
            if marker:
                proposals.append(dict(source="todo", category="FIX" if marker[1] == "FIXME" else "SIMPLIFY", title=marker[2][:120], problem=marker[2], evidence=[f"{head}:{rel}:{number}"], files=[rel], outcome="Resolve the cited source marker with regression evidence", validation="focused regression and full suite"))
    proposals.extend(architecture_signals(root, exclusions))
    proposals.extend(signals)
    chosen, seen, per_category = [], set(), Counter()
    for proposal in sorted(proposals, key=lambda p: (p.get("category") == "ADD", p.get("category", ""), p.get("title", ""))):
        if proposal.get("category") not in CATEGORIES or proposal.get("source") not in SOURCES or not proposal.get("evidence") or not proposal.get("validation"):
            continue
        bounded(proposal)
        identity = digest({k: proposal.get(k) for k in ("source", "problem", "files", "evidence")})
        if identity in seen or identity in suppressed or per_category[proposal["category"]] >= max(1, cap // 2): continue
        seen.add(identity); per_category[proposal["category"]] += 1; chosen.append(proposal)
        if len(chosen) >= max(0, cap): break
    active_todos = []
    for path in sorted((root / ".todos").glob("*.md")):
        text = path.read_text()
        if "**Status:** backlog" in text or "**Status:** in-progress" in text:
            active_todos.append(dict(path=str(path.relative_to(root)), hash=digest(text)))
    recent = git(root, "log", "-5", "--format=%H %s").splitlines()
    completed = [str(p.relative_to(root)) for p in sorted((root / ".todos/done").glob("*.md"))[-10:]]
    return dict(head=head, proposals=chosen if cap > 0 else [], context=dict(active_todos=active_todos, recent_commits=recent, recent_completed=completed), unavailable=["CI", "telemetry", "performance", "user_feedback"], source="tracked repository plus explicitly supplied signals")


def task_index(root):
    records = {}
    for p in sorted((Path(root) / ".todos").rglob("*.md")):
        text = p.read_text(); match = re.search(r"\*\*ID:\*\*\s*(\d+)", text)
        if not match: continue
        tid = match[1]
        if tid in records: raise ValueError("duplicate TODO ID " + tid)
        status = re.search(r"\*\*Status:\*\*\s*(\S+)", text)
        dep = re.search(r"\*\*Depends:\*\*\s*([^\n]+)", text)
        records[tid] = dict(path=p, status=status[1] if status else "unknown", depends=re.findall(r"\b\d{4}\b", dep[1]) if dep else [])
    complete = set()
    def visit(tid, stack):
        if tid in stack: raise ValueError("dependency cycle")
        if tid not in records: raise ValueError("unknown dependency " + tid)
        if tid in complete: return
        if records[tid]["status"] in {"done", "completed", "resolved"}:
            complete.add(tid)
            return
        for dep in records[tid]["depends"]: visit(dep, stack | {tid})
        complete.add(tid)
    for tid in records: visit(tid, set())
    return records


def plan(root, store, cid, criteria, dependencies=()):
    root = Path(root).resolve(); candidate = store.get(cid)
    if candidate["state"] not in {"DISCOVERED", "DEFERRED", "NEEDS_HUMAN"}:
        raise ValueError("candidate is not plannable")
    if not criteria or any(not isinstance(c, str) or len(c) < 15 or "\n" in c for c in criteria):
        raise ValueError("externally verifiable criteria required")
    risk = classify(candidate["files"], graphs=[protected_graph(root)])
    head = git(root, "rev-parse", "HEAD")
    directory = root / ".todos"; directory.mkdir(exist_ok=True)
    # Reservation lock covers index, allocation and exclusive durable file write.
    with (directory / ".allocation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = store.get(cid)
        if current["state"] == "PLANNED":
            return [e["payload"]["context"] for e in current["events"] if e["kind"] == "PLAN"][-1]
        if current["state"] not in {"DISCOVERED", "DEFERRED", "NEEDS_HUMAN"}:
            raise ValueError("candidate state changed during planning")
        records = task_index(root)
        if any(dep not in records for dep in dependencies): raise ValueError("unknown dependency")
        common = Path(git(root, "rev-parse", "--git-common-dir"))
        repository = digest(str((root / common).resolve()))
        with store.connect(True) as db:
            reserved = [json.loads(r[0])["todo"] for r in db.execute("SELECT payload FROM dev_events WHERE kind='TODO_RESERVATION' AND json_extract(payload,'$.repository')=?", (repository,))]
            tid = f"{max([int(k) for k in records] + [int(k) for k in reserved] + [0]) + 1:04d}"
            store._append(db, None, "TODO_RESERVATION", dict(todo=tid, repository=repository, candidate=cid), f"todo-reservation:{repository}:{tid}")
        slug = re.sub(r"[^a-z0-9]+", "-", candidate["title"].lower()).strip("-")[:80] or "improvement"
        path = directory / f"{tid}-{slug}.md"
        body = f"# {candidate['title']}\n\n- **ID:** {tid}\n- **Status:** backlog\n- **Created:** {today_eastern().isoformat()}\n- **Priority:** high\n- **Depends:** {', '.join(dependencies) or 'none'}\n\n## Problem\n\n{candidate['problem']}\n\n## Scope and acceptance\n\n" + "\n".join("- [ ] " + c for c in criteria)
        body += f"\n\n## QA requirements\n\n- [ ] Focused tests, full suite and release gates pass with fresh evidence.\n\n## Implementation guardrails\n\nRisk {risk['risk']}; human scope and merge approval required. AGENTS.md and engineering-principles-1 apply.\n\n## Source\n\nDevelopment candidate {cid}. Evidence: {json.dumps(candidate['evidence'])}\n"
        with path.open("x") as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        context = dict(todo=tid, head=head, scope_hash=digest(candidate["files"]), risk=risk["risk"], acceptance_hash=digest(body))
        store.event(cid, "PLAN", dict(context=context, path=str(path.relative_to(root)), criteria=criteria, risk=risk))
        store.transition(cid, "PLANNED")
    return context


def refresh_plan(root, store, cid):
    """Bind a human-authored/committed plan to its actual clean base commit."""
    root = Path(root).resolve()
    if git(root, "status", "--porcelain"): raise ValueError("commit plan before binding approval")
    candidate = store.get(cid)
    if candidate["state"] != "PLANNED": raise ValueError("plan must await approval")
    old = [e["payload"] for e in candidate["events"] if e["kind"] == "PLAN"][-1]
    path = root / old["path"]
    risk = classify(candidate["files"], graphs=[protected_graph(root)])
    context = dict(todo=old["context"]["todo"], head=git(root, "rev-parse", "HEAD"), scope_hash=digest(candidate["files"]), risk=risk["risk"], acceptance_hash=digest(path.read_text()))
    store.event(cid, "PLAN", dict(old, context=context, risk=risk))
    return context
