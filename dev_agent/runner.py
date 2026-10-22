"""Bounded builder/reviewer orchestration with no arbitrary host execution."""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .discovery import git
from .evidence import source_hash, junit
from .guard import WorkspaceGuard
from .policy import PRINCIPLES, classify, engineering_checks, protected_graph
from .store import bounded, digest
from .providers import respond_bounded


class ContainerValidator:
    """Validation executes only in a disposable networkless Linux container.

    The image must be preinstalled by an operator and pinned by digest. No pulls,
    host shell, sockets, credentials or writable host source mounts are provided.
    """
    def __init__(self, image, timeout=120):
        if not re.fullmatch(r"[a-zA-Z0-9_./:-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("operator-provisioned digest-pinned image required")
        self.image, self.timeout = image, min(300, max(1, timeout))

    def run(self, root, name, command):
        if not command or command[:3] != ["python", "-m", "pytest"] or any(not re.fullmatch(r"[A-Za-z0-9_./:=+-]+", x) for x in command):
            raise ValueError("only structured pytest validation supported")
        if not shutil.which("docker"):
            return dict(name=name, command=command, exit_code=None, status="UNAVAILABLE", reason="sandbox runtime unavailable")
        root = Path(root)
        # Build a separate source copy. Container writes never touch source or host.
        with tempfile.TemporaryDirectory(prefix="dev-validation-") as temp:
            snapshot = Path(temp) / "source"; snapshot.mkdir()
            artifacts = Path(temp) / "artifacts"; artifacts.mkdir(); artifacts.chmod(0o777)
            guard = WorkspaceGuard(root, [])
            for rel in git(root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines():
                try: path = guard.resolve(rel)
                except ValueError: continue
                if not path.is_file() or path.stat().st_size > 2_000_000: continue
                target = snapshot / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes())
            container = "dev-validation-" + uuid.uuid4().hex
            args = ["docker", "run", "--pull=never", "--rm", "--name", container, "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=512m", "--cpus=1", "--user=65534:65534", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m,mode=1777", "--tmpfs", "/workspace:rw,nosuid,nodev,size=128m,mode=1777", "--mount", f"type=bind,src={snapshot},dst=/source,readonly", "--workdir=/workspace", self.image,
                    "python", "-c", "import shutil,subprocess,sys; shutil.copytree('/source','/workspace',dirs_exist_ok=True); sys.exit(subprocess.call(sys.argv[1:]))", *command, "--junitxml=/artifacts/results.xml"]
            args[args.index("--workdir=/workspace"):args.index("--workdir=/workspace")] = ["--mount", f"type=bind,src={artifacts},dst=/artifacts"]
            try:
                # Discard untrusted logs; pytest XML/count receipts may be exported
                # through a separately reviewed artifact protocol, never stdout claims.
                result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=self.timeout)
                xml = artifacts / "results.xml"
                if not xml.is_file() or xml.is_symlink() or xml.stat().st_size > 2_000_000:
                    return dict(name=name, command=command, exit_code=result.returncode, status="PARTIAL", reason="missing or oversized test inventory", image=self.image)
                inventory = junit(xml)
                return dict(name=name, command=command + ["--junitxml=/artifacts/results.xml"], exit_code=result.returncode, status="PASS" if result.returncode == 0 and inventory["total"] > 0 and not inventory["failures"] else "FAIL", inventory=inventory, artifact_hash=hashlib.sha256(xml.read_bytes()).hexdigest(), image=self.image)
            except subprocess.TimeoutExpired:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
                return dict(name=name, command=command, exit_code=None, status="FAIL", reason="timeout")


def review(root, original, base_files, provider, validation, declared_risk, timeout=60, prior_findings=()):
    guard = WorkspaceGuard(root, [])
    changed = {}
    for path, old in sorted(base_files.items()):
        try: new = guard.read(path)
        except FileNotFoundError: new = ""
        if old != new: changed[path] = (old, new)
    deterministic = engineering_checks(changed)
    risk = classify(changed, graphs=[protected_graph(root)], declared=int(declared_risk[1:]))
    before = source_hash(root)
    if deterministic:
        return dict(disposition="NEEDS_HUMAN", findings=deterministic, risk=risk, provider=provider.identity)
    if not validation or any(v["status"] != "PASS" or v["exit_code"] != 0 for v in validation):
        return dict(disposition="NEEDS_HUMAN", findings=[dict(id="validation", severity="HIGH", file="", requirement="fresh validation", evidence="missing or failed validation", principle="P3")], risk=risk, provider=provider.identity)
    try:
        response = respond_bounded(provider, dict(role="reviewer", todo=original, changes=changed, validation=validation, prior_findings=list(prior_findings), resolution_contract="Every prior finding requires either its same open ID or an explicit resolved entry with id, file and concrete evidence; conflicting findings require NEEDS_HUMAN.", principles=PRINCIPLES, principle_version="engineering-principles-1", contract=guard.read("AGENTS.md")), timeout)
        if response.get("disposition") not in {"PASS", "REQUEST_CHANGES", "NEEDS_HUMAN"} or not isinstance(response.get("findings"), list):
            raise ValueError("invalid reviewer output")
        for finding in response["findings"]:
            if not {"id", "severity", "file", "requirement", "evidence", "principle"} <= finding.keys() or finding["principle"] not in PRINCIPLES or finding["severity"] not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} or not finding["evidence"] or not finding["requirement"]:
                raise ValueError("untraceable finding")
        if len({f["id"] for f in response["findings"]}) != len(response["findings"]): raise ValueError("duplicate finding IDs")
        resolutions = response.get("resolved", [])
        if not isinstance(resolutions, list) or any(not all(r.get(k) for k in ("id", "file", "evidence")) for r in resolutions):
            raise ValueError("explicit resolution evidence required")
        prior_ids = {f["id"] for f in prior_findings}
        open_ids = {f["id"] for f in response["findings"]}
        resolved_ids = {r["id"] for r in resolutions}
        if prior_ids - open_ids - resolved_ids or open_ids & resolved_ids or response.get("conflicts"):
            raise ValueError("lost or conflicting review findings")
        if response["disposition"] == "PASS" and response["findings"]:
            raise ValueError("PASS with unresolved findings")
        if source_hash(root) != before: raise ValueError("reviewer changed workspace")
        return dict(response, risk=risk, provider=provider.identity)
    except Exception:
        return dict(disposition="NEEDS_HUMAN", findings=[dict(id="review-unavailable", severity="HIGH", file="", requirement="independent review", evidence="review failed or workspace changed", principle="P3")], risk=risk, provider=provider.identity)


class Runner:
    def __init__(self, store, builder, reviewer, validator, max_iterations=3, max_seconds=300, max_lines=400):
        if builder is reviewer: raise ValueError("independent reviewer context required")
        self.store, self.builder, self.reviewer, self.validator = store, builder, reviewer, validator
        self.iterations = min(5, max(1, max_iterations)); self.seconds = min(600, max(1, max_seconds)); self.lines = min(1000, max(1, max_lines))

    def recover(self, cid):
        """Crash recovery preserves iterations; requires replan/approval to retry."""
        interrupted = self.store.query_runs(candidate=cid, status="RUNNING")
        for run in interrupted:
            self.store.run_event(cid, run["run_id"], run["role"], "NEEDS_HUMAN", dict(reason="interrupted process; prior iterations retained"), run["parent"])
        if interrupted and self.store.get(cid)["state"] == "BUILDING":
            self.store.transition(cid, "NEEDS_HUMAN", dict(reason="interrupted run"))
        return dict(recovered=[r["run_id"] for r in interrupted], status="NEEDS_HUMAN" if interrupted else "UNCHANGED")

    def run(self, cid, context, worktrees, record, validation_commands, *, certification, protections):
        # Certification cannot be replaced by a boolean/model assertion. A verifier
        # supplied by the trusted application must check exact harness source hash.
        if not certification() or protections.get("status") != "PASS":
            return dict(status="NEEDS_HUMAN", reason="current certification and protections required")
        root = worktrees.verify(record)
        if git(root, "status", "--porcelain") or context["head"] != record["base"]:
            raise ValueError("dirty/unapproved worktree")
        candidate = self.store.get(cid)
        plans = [e["payload"] for e in candidate["events"] if e["kind"] == "PLAN"]
        if not plans or plans[-1]["context"] != context: raise ValueError("stale plan")
        todo_path = plans[-1]["path"]
        original = (root / todo_path).read_text()
        if digest(original) != context["acceptance_hash"]: raise ValueError("acceptance changed")
        allowed = candidate["files"]
        if todo_path in allowed or "AGENTS.md" in allowed:
            raise ValueError("requirements and authority are immutable to builder")
        risk = classify(allowed, graphs=[protected_graph(root)])
        if int(risk["risk"][1:]) > int(context["risk"][1:]): raise ValueError("risk increased; fresh approval required")
        if int(risk["risk"][1:]) >= 4:
            return dict(status="NEEDS_HUMAN", reason="protected financial/governance work requires supervised human workflow")
        guard = WorkspaceGuard(root, allowed)
        base_files = {name: guard.read(name) if (root / name).exists() else "" for name in allowed}
        run_id = str(uuid.uuid4()); self.store.begin(cid, context, run_id)
        self.store.run_event(cid, run_id, "builder", "RUNNING", dict(base=record["base"], worktree=record, provider=self.builder.identity))
        start = time.monotonic(); unresolved = set(); seen = set(); final = {}; cumulative = 0
        try:
            for iteration in range(1, self.iterations + 1):
                if time.monotonic() - start >= self.seconds: raise ValueError("wall-time budget exhausted")
                response = respond_bounded(self.builder, dict(role="builder", todo=original, files={name: guard.read(name) if (root / name).exists() else "" for name in allowed}, contract=guard.read("AGENTS.md"), principles=PRINCIPLES, principle_version="engineering-principles-1", findings=final.get("findings", [])), self.seconds - (time.monotonic()-start))
                actions = response.get("actions")
                if not isinstance(actions, list) or len(actions) > 20: raise ValueError("invalid/action budget")
                for action in actions:
                    cumulative += len(action.get("content", "").splitlines())
                    if cumulative > self.lines: raise ValueError("cumulative diff budget exhausted")
                    guard.apply(action)
                if time.monotonic() - start >= self.seconds: raise ValueError("wall-time budget exhausted")
                actual = git(root, "status", "--porcelain", "--untracked-files=all")
                changed = {line[3:] for line in actual.splitlines()}
                if changed - set(allowed): raise ValueError("scope expanded")
                validations = []
                for name, cmd in validation_commands:
                    remaining = self.seconds - (time.monotonic()-start)
                    if remaining <= 0: raise ValueError("wall-time budget exhausted")
                    if isinstance(self.validator, ContainerValidator): self.validator.timeout = min(self.validator.timeout, remaining)
                    validations.append(self.validator.run(root, name, cmd))
                final = review(root, original, base_files, self.reviewer, validations, context["risk"], self.seconds - (time.monotonic()-start), final.get("findings", []))
                current = {f["id"] for f in final["findings"]}
                event = dict(iteration=iteration, source_hash=source_hash(root), changed_files=sorted(changed), actions_summary=["write:"+a["path"] for a in actions], validations=validations, review=final, resolved=sorted(unresolved-current), new=sorted(current-unresolved), cumulative_lines=cumulative)
                self.store.event(cid, "ITERATION", event, f"{run_id}:{iteration}")
                if final["disposition"] == "PASS":
                    self.store.run_event(cid, run_id, "builder", "PASS", dict(head=git(root, "rev-parse", "HEAD"), evidence=event))
                    return dict(status="REVIEW_PASS", run_id=run_id, validation=validations, review=final, iterations=iteration)
                fingerprint = digest(final["findings"])
                high = {f["id"] for f in final["findings"] if f["severity"] in {"HIGH", "CRITICAL"}}
                if final["disposition"] == "NEEDS_HUMAN" or fingerprint in seen or high & unresolved:
                    raise ValueError("review unresolved or repeated high-severity findings")
                seen.add(fingerprint); unresolved = current
            raise ValueError("iteration budget exhausted")
        except Exception as error:
            reason = str(error)[:200] if isinstance(error, ValueError) else type(error).__name__
            self.store.run_event(cid, run_id, "builder", "NEEDS_HUMAN", dict(reason=reason))
            self.store.transition(cid, "NEEDS_HUMAN", dict(reason=reason))
            return dict(status="NEEDS_HUMAN", reason=reason, run_id=run_id)
