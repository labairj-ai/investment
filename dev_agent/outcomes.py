"""Software deployment observations, never investment-return rewards."""
from __future__ import annotations

import re
import time
from collections import Counter

from .store import digest

VERSION = "software-effectiveness-1"


def observe(store, cid, observation):
    required = {"merge_sha", "deployed_sha", "environment", "deployed_at", "observed_at", "window_seconds", "metrics", "evidence", "status"}
    if not required <= observation.keys(): raise ValueError("incomplete deployment observation")
    if any(re.search(r"(?i)(pnl|return|alpha|profit|portfolio)", key) for key in observation["metrics"]):
        raise ValueError("investment performance is not a software outcome")
    for key in ("merge_sha", "deployed_sha"):
        if not re.fullmatch(r"[a-f0-9]{40}", observation[key]): raise ValueError("full SHA required")
    candidate = store.get(cid)
    prs = [e["payload"] for e in candidate["events"] if e["kind"] == "PR"]
    if not prs: raise ValueError("PR linkage required")
    links = [e["payload"] for e in candidate["events"] if e["kind"] == "MERGE"]
    if not links or links[-1].get("merge_sha") != observation["merge_sha"]: raise ValueError("verified merge linkage required")
    if observation["status"] not in {"HEALTHY", "DEGRADED", "ROLLED_BACK", "NOT_DEPLOYED", "INSUFFICIENT_DATA"}: raise ValueError("unknown observation")
    status = observation["status"]
    if observation["deployed_sha"] != observation["merge_sha"] or not observation["evidence"] or not observation["metrics"]:
        status = "INSUFFICIENT_DATA"
    elapsed = observation["observed_at"] - observation["deployed_at"]
    if elapsed < 0 or observation["observed_at"] > time.time() + 60 or observation["window_seconds"] <= 0:
        raise ValueError("invalid observation clock/window")
    if status == "HEALTHY" and elapsed < observation["window_seconds"] and not observation.get("human_acceptance"):
        status = "INSUFFICIENT_DATA"
    if status == "ROLLED_BACK" and not (observation.get("rollback_cause") and re.fullmatch(r"[a-f0-9]{40}", observation.get("rollback_target", ""))):
        raise ValueError("rollback cause and target required")
    result = dict(observation, status=status, pr=prs[-1]["result"])
    with store.connect(True) as db:
        key = "deployment:" + digest(result)
        store._append(db, cid, "DEPLOYMENT", result, key)
        prior = store._state(db, cid)
        if status in {"HEALTHY", "DEGRADED", "ROLLED_BACK"} and observation["deployed_sha"] == observation["merge_sha"]:
            if prior == "PR_OPEN":
                store._append(db, cid, "STATE", {"state":"DEPLOYED"}, key+":deployed")
                prior = "DEPLOYED"
            if status == "ROLLED_BACK" and prior == "DEPLOYED":
                store._append(db, cid, "STATE", {"state":"ROLLED_BACK"}, key+":rollback")
    return result


def effectiveness(candidate, observation, dimensions):
    required = {"acceptance", "recurrence", "review_findings", "health", "user_acceptance", "maintenance"}
    if observation.get("status") == "INSUFFICIENT_DATA" or not required <= dimensions.keys() or any(dimensions[k] is None for k in required):
        return dict(version=VERSION, status="INSUFFICIENT_DATA", score=None)
    if any(not isinstance(dimensions[k], (int, float)) or not 0 <= dimensions[k] <= 1 for k in required): raise ValueError("bounded effectiveness dimensions")
    if observation.get("status") == "ROLLED_BACK": value = 0
    elif observation.get("status") == "HEALTHY":
        value = 100 * (dimensions["acceptance"] + 1-dimensions["recurrence"] + 1-dimensions["review_findings"] + dimensions["health"] + dimensions["user_acceptance"] + dimensions["maintenance"]) / 6
    else: return dict(version=VERSION, status="INSUFFICIENT_DATA", score=None)
    return dict(version=VERSION, status="MEASURED", score=round(value, 2), category=candidate["category"], source=candidate["source"], dimensions=dimensions, governance_effect="NONE")


def aggregate(records, minimum=5):
    measured = [r for r in records if r.get("status") == "MEASURED"]
    if len(measured) < minimum: return dict(status="INSUFFICIENT_DATA", n=len(measured), prioritization_weight=0)
    return dict(status="MEASURED", n=len(measured), mean=round(sum(r["score"] for r in measured)/len(measured), 2), categories=dict(Counter(r["category"] for r in measured)), prioritization_weight=0.1, governance_effect="NONE")
