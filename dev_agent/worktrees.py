"""Pinned development worktrees with crash-recoverable manifests."""
from __future__ import annotations

import fcntl
import json
import re
import subprocess
import uuid
from pathlib import Path

from .discovery import git


class Worktrees:
    def __init__(self, repo, directory):
        self.repo = Path(repo).resolve(strict=True)
        self.directory = Path(directory).resolve()
        if str(self.repo).startswith("/home/optiplex/investment") or self.directory.is_relative_to(self.repo):
            raise ValueError("production/in-repository worktrees denied")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def create(self, todo, base):
        if not re.fullmatch(r"\d{4}", todo) or not re.fullmatch(r"[a-f0-9]{40}", base):
            raise ValueError("explicit TODO and full base SHA required")
        if git(self.repo, "rev-parse", base + "^{commit}") != base or git(self.repo, "status", "--porcelain"):
            raise ValueError("unverified base or dirty checkout")
        with (self.directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            run = uuid.uuid4().hex; path = self.directory / run
            record = dict(todo=todo, base=base, branch=f"agent/{todo}/{run}", path=str(path), run=run, status="CREATING")
            manifest = self.directory / (run + ".json")
            manifest.write_text(json.dumps(record, sort_keys=True))
            subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-b", record["branch"], str(path), base], check=True, capture_output=True, timeout=30)
            record["status"] = "READY"; manifest.write_text(json.dumps(record, sort_keys=True))
            return record

    def verify(self, record):
        if not re.fullmatch(r"[a-f0-9]{32}", record.get("run", "")) or not re.fullmatch(r"\d{4}", record.get("todo", "")):
            raise ValueError("invalid worktree identity")
        path = Path(record["path"])
        if path.parent.resolve() != self.directory or path.name != record["run"] or path.is_symlink() or record["branch"] != f"agent/{record['todo']}/{record['run']}":
            raise ValueError("foreign worktree")
        manifest = self.directory / (record["run"] + ".json")
        persisted = json.loads(manifest.read_text())
        if persisted != record or record["status"] != "READY":
            raise ValueError("worktree record mismatch")
        if git(path, "branch", "--show-current") != record["branch"] or not record["branch"].startswith("agent/"):
            raise ValueError("writable branch mismatch")
        if git(path, "rev-parse", "HEAD") != record["base"]:
            raise ValueError("unexpected head; fresh approval required")
        return path

    def recover(self):
        result = []
        for manifest in sorted(self.directory.glob("*.json")):
            record = json.loads(manifest.read_text())
            if record.get("status") == "CREATING" and Path(record["path"]).exists():
                proposed = dict(record, status="READY")
                manifest.write_text(json.dumps(proposed, sort_keys=True))
                try:
                    self.verify(proposed)
                except Exception:
                    manifest.write_text(json.dumps(record, sort_keys=True))
                    raise
                record = proposed
            record["observed"] = "PRESENT" if Path(record["path"]).exists() else "ABSENT"
            result.append(record)
        return result

    def cleanup(self, record):
        path = self.verify(record)
        if git(path, "status", "--porcelain"):
            raise ValueError("dirty worktree retained with evidence")
        # Never force removal or delete branches/evidence automatically.
        subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", str(path)], check=True, capture_output=True, timeout=30)
        record = dict(record, status="RETIRED")
        (self.directory / (record["run"] + ".json")).write_text(json.dumps(record, sort_keys=True))
