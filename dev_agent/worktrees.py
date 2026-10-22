"""Pinned development worktrees with crash-recoverable manifests."""
from __future__ import annotations

from .git_exec import run as git_run, output as git_output

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
            record['git_intent']=dict(operation='worktree-add',branch=record['branch'],base=base,hooks_disabled=True,ambient_config_disabled=True)
            manifest = self.directory / (run + ".json")
            manifest.write_text(json.dumps(record, sort_keys=True))
            git_run(self.repo, "worktree", "add", "-b", record["branch"], str(path), base)
            record["status"] = "READY"; manifest.write_text(json.dumps(record, sort_keys=True))
            return record

    def verify(self, record, allow_committed=False):
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
            if not allow_committed:
                raise ValueError("unexpected head; fresh approval required")
            git_run(path, "merge-base", "--is-ancestor", record["base"], "HEAD")
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
        path = self.verify(record, allow_committed=True)
        if git(path, "status", "--porcelain"):
            raise ValueError("dirty worktree retained with evidence")
        # Never force removal or delete branches/evidence automatically.
        final_head = git(path, "rev-parse", "HEAD")
        git_run(self.repo, "worktree", "remove", str(path))
        record = dict(record, status="RETIRED", final_head=final_head)
        (self.directory / (record["run"] + ".json")).write_text(json.dumps(record, sort_keys=True))
