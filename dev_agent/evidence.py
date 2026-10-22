"""Immutable receipts bound to committed SHA and complete worktree contents."""
from __future__ import annotations

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .discovery import git
from .store import bounded, digest

STATUSES = {"PASS", "FAIL", "PARTIAL", "NOT_RUN", "UNAVAILABLE"}
REQUIRED = {"focused_tests", "full_suite", "release_baseline", "cc_contract", "agent_contract", "todo_consistency"}


def source_hash(root):
    root = Path(root).resolve()
    names = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"], timeout=30).decode().split("\0")
    sha = hashlib.sha256()
    for name in sorted(set(filter(None, names))):
        path = root / name
        sha.update(name.encode() + b"\0")
        if path.is_symlink():
            sha.update(b"symlink:" + str(path.readlink()).encode())
        elif path.is_file():
            sha.update(str(path.stat().st_mode & 0o777).encode() + b"\0" + path.read_bytes())
        else:
            sha.update(b"<deleted>")
    return sha.hexdigest()


def junit(path):
    tree = ET.parse(path)
    tests = list(tree.iter("testcase"))
    failures, skipped = [], []
    for test in tests:
        identity = test.get("classname", "") + "::" + test.get("name", "")
        if test.find("failure") is not None or test.find("error") is not None:
            failures.append(identity)
        if test.find("skipped") is not None:
            skipped.append(identity)
    return dict(total=len(tests), passed=len(tests) - len(failures) - len(skipped), failures=failures, skipped=skipped)


def receipt(root, candidate, todo, base, iteration, validations, review, risk, provider, contracts):
    if not validations or any(v.get("status") not in STATUSES or not isinstance(v.get("command"), list) or "exit_code" not in v for v in validations):
        raise ValueError("exact validation records required")
    labels = {v["name"] for v in validations}
    if len(labels) != len(validations): raise ValueError("duplicate validation labels")
    inventories = all(v.get("inventory", {}).get("total", 0) > 0 and not v["inventory"].get("failures") and "skipped" in v["inventory"] for v in validations if v["name"] in {"focused_tests", "full_suite"})
    passed = REQUIRED <= labels and inventories and all(v["status"] == "PASS" and v["exit_code"] == 0 for v in validations) and review.get("disposition") == "PASS"
    data = dict(version="dev-evidence-1", candidate=candidate, todo=todo, base=base, head=git(root, "rev-parse", "HEAD"), iteration=iteration,
                source_hash=source_hash(root), validations=validations, review=review, risk=risk, provider=provider, contracts=contracts,
                status="PASS" if passed else "PARTIAL")
    data["id"] = digest(data)
    return data


def verify(root, data):
    payload = {k: v for k, v in data.items() if k != "id"}
    return data.get("id") == digest(payload) and data.get("head") == git(root, "rev-parse", "HEAD") and data.get("source_hash") == source_hash(root)


def persist(directory, data):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (data["id"] + ".json")
    encoded = bounded(data) + "\n"
    try:
        with path.open("x") as stream: stream.write(encoded)
    except FileExistsError:
        if path.read_text() != encoded: raise ValueError("receipt collision/tamper")
    return path
