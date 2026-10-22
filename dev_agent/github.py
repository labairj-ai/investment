"""GitHub handoff; never changes rulesets, merges or enables auto-merge."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from .discovery import git
from .evidence import REQUIRED, verify
from .store import bounded, digest
from .policy import whole_diff


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository): raise ValueError("repository")
        self.repository = repository

    def read(self, endpoint):
        result = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    def protections(self):
        try:
            data = self.read(f"repos/{self.repository}/branches/main/protection")
            identity = self.read("user")["login"]
            permission = self.read(f"repos/{self.repository}/collaborators/{identity}/permission")
            rulesets = self.read(f"repos/{self.repository}/rulesets?includes_parents=true")
            bypass = False
            for ruleset in rulesets:
                detail = self.read(f"repos/{self.repository}/rulesets/{ruleset['id']}")
                # Conservative: any active bypass actor requires a separately
                # audited identity/role resolution, so automated promotion stops.
                if detail.get("enforcement") == "active" and detail.get("bypass_actors"):
                    bypass = True
            data["agent_identity_no_bypass_verified"] = permission.get("permission") in {"write", "maintain"} and not bypass
            return verify_protections(data)
        except Exception:
            return dict(status="UNAVAILABLE", reason="GitHub protection could not be verified", auto_merge=False)

    def handoff(self, branch, title, body, draft):
        query = subprocess.run(["gh", "pr", "list", "--repo", self.repository, "--head", branch, "--state", "open", "--json", "number,url,isDraft"], check=True, capture_output=True, text=True, timeout=30)
        existing = json.loads(query.stdout)
        with tempfile.TemporaryDirectory(prefix="dev-pr-") as temp:
            path = Path(temp) / "body.md"; path.write_text(body)
            if existing:
                item = existing[0]
                subprocess.run(["gh", "pr", "edit", str(item["number"]), "--repo", self.repository, "--title", title, "--body-file", str(path)], check=True, capture_output=True, timeout=30)
                if draft and not item["isDraft"]:
                    subprocess.run(["gh", "pr", "ready", str(item["number"]), "--repo", self.repository, "--undo"], check=True, capture_output=True, timeout=30)
                    item = dict(item, isDraft=True)
                return item
            command = ["gh", "pr", "create", "--repo", self.repository, "--head", branch, "--base", "main", "--title", title, "--body-file", str(path)]
            if draft: command.append("--draft")
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            url = result.stdout.strip()
            return dict(url=url, number=int(url.rstrip("/").rsplit("/",1)[1]), isDraft=draft)


def verify_protections(data):
    checks = data.get("required_status_checks") or {}
    contexts = set(checks.get("contexts", [])) | {c["context"] for c in checks.get("checks", [])}
    reviews = data.get("required_pull_request_reviews") or {}
    restrictions = data.get("restrictions")
    failures = []
    if not checks.get("strict") or "test" not in contexts: failures.append("current-head required test check")
    if reviews.get("required_approving_review_count", 0) < 1 or not reviews.get("dismiss_stale_reviews") or not reviews.get("require_last_push_approval"):
        failures.append("fresh independent review")
    if (reviews.get("bypass_pull_request_allowances") or {}).get("users") or (reviews.get("bypass_pull_request_allowances") or {}).get("apps") or (reviews.get("bypass_pull_request_allowances") or {}).get("teams"):
        failures.append("review bypass identity")
    for key in ("enforce_admins", "required_conversation_resolution"):
        if not (data.get(key) or {}).get("enabled"): failures.append(key)
    for key in ("allow_force_pushes", "allow_deletions"):
        if (data.get(key) or {}).get("enabled"): failures.append(key)
    if restrictions is None: failures.append("restricted direct push")
    # This verifies branch protection. Identity membership in bypass rulesets is
    # a separate operator gate, never inferred from a successful API response.
    if not data.get("agent_identity_no_bypass_verified", False): failures.append("agent ruleset/identity bypass audit")
    return dict(status="PASS" if not failures else "FAIL", failures=failures, auto_merge=False, required_checks=sorted(contexts))


def prepare_pr(root, store, cid, data, client):
    if data.get("candidate") != cid: raise ValueError("receipt belongs to another candidate")
    if not verify(root, data): raise ValueError("stale/tampered receipt")
    if git(root, "status", "--porcelain"): raise ValueError("commit candidate before PR")
    branch = git(root, "branch", "--show-current")
    if not branch.startswith("agent/") or git(root, "rev-parse", "HEAD") == data["base"]: raise ValueError("isolated committed branch required")
    if client.protections().get("status") != "PASS": raise ValueError("repository protections unavailable/failed")
    records = data["validations"]
    mandatory = {r["name"] for r in records if r["status"] == "PASS" and r["exit_code"] == 0}
    if not REQUIRED <= mandatory or data["review"].get("disposition") != "PASS": raise ValueError("mandatory PR gates failed")
    candidate = store.get(cid)
    if candidate["state"] not in {"BUILDING", "PR_OPEN"}: raise ValueError("candidate not eligible for PR handoff")
    actual_risk = whole_diff(root, data["base"])
    if int(actual_risk["risk"][1:]) > int(data["risk"]["risk"][1:]): raise ValueError("complete diff risk increased")
    latest_plan = [e["payload"] for e in candidate["events"] if e["kind"] == "PLAN"][-1]
    if data["todo"] != latest_plan["context"]["todo"] or data["base"] != latest_plan["context"]["head"]: raise ValueError("receipt does not match original approved scope")
    body = f"Candidate {cid}; TODO {data['todo']}\n\n{candidate['problem']}\n\nScope: {candidate['outcome']}\n\nRisk: {data['risk']['risk']}; human merge approval required. No auto-merge.\n\nChanged files: {', '.join(candidate['files'])}\n\nAcceptance: see original TODO and immutable PLAN event.\n\nTests and review: {json.dumps(records)}; {data['review']['disposition']}\n\nEvidence: {data['id']}; tested head {data['head']}\n\nLimitations: no production deployment authorized.\n\nRollback: revert implementation through the reviewed deployment workflow.\n"
    bounded(body)
    result = client.handoff(branch, f"[agent][{data['risk']['risk']}] TODO {data['todo']}: {candidate['title']}", body, data["status"] != "PASS")
    with store.connect(True) as db:
        prior = store._state(db, cid)
        if prior not in {"BUILDING", "PR_OPEN"}: raise ValueError("candidate state changed during handoff")
        event = dict(result=result, head=data["head"], receipt=data["id"])
        store._append(db, cid, "PR", event, "pr:" + digest(event))
        if prior == "BUILDING": store._append(db, cid, "STATE", {"state": "PR_OPEN"}, "pr-state:" + data["head"])
    return result
