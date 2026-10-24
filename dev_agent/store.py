"""Dedicated, append-only development ledger; no portfolio tables or migrations."""
from __future__ import annotations

import hashlib
import json
import re
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

STATES = {
    "DISCOVERED": {"PLANNED", "REJECTED", "DEFERRED"},
    "PLANNED": {"APPROVED", "REJECTED", "DEFERRED"},
    "APPROVED": {"BUILDING", "DEFERRED", "NEEDS_HUMAN"},
    "BUILDING": {"PR_OPEN", "NEEDS_HUMAN"},
    "NEEDS_HUMAN": {"PLANNED", "REJECTED", "DEFERRED"},
    "DEFERRED": {"PLANNED", "REJECTED"},
    "PR_OPEN": {"DEPLOYED", "NEEDS_HUMAN"},
    "DEPLOYED": {"ROLLED_BACK", "CLOSED", "NEEDS_HUMAN"},
    "ROLLED_BACK": {"CLOSED"}, "REJECTED": set(), "CLOSED": set(),
}
CATEGORIES = {"FIX", "SIMPLIFY", "REMOVE", "CONSOLIDATE", "REFACTOR", "OPTIMIZE", "TEST", "DOCUMENT", "ADD"}
SOURCES = {"user", "ci", "test", "telemetry", "error", "todo", "architecture", "performance", "accessibility", "discovery", "git"}
SECRET = re.compile(r"(?i)(?:bearer\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+|gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,})")


def bounded(value):
    def inspect(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if re.search(r"(?i)(api[_-]?key|password|secret|authorization|cookie|credential|^token$)", str(key)):
                    raise ValueError("secret-bearing metadata key")
                inspect(child)
        elif isinstance(item, (list, tuple)):
            for child in item: inspect(child)
    inspect(value)
    raw = json.dumps(value, sort_keys=True, allow_nan=False)
    if len(raw.encode()) > 32768 or SECRET.search(raw):
        raise ValueError("secret-bearing or oversized development metadata")
    return raw


def digest(value):
    return hashlib.sha256(bounded(value).encode()).hexdigest()


class Store:
    def __init__(self, path):
        raw_path = Path(path).expanduser()
        if raw_path.is_symlink(): raise ValueError("symlink ledger denied")
        self.path = raw_path.resolve()
        # Exact filename boundary prevents accidentally opening investment.db, even
        # when the parent directory is configured incorrectly.
        if self.path.name != "development-control.sqlite3" or self.path.is_symlink():
            raise ValueError("dedicated development-control.sqlite3 required")

    @contextmanager
    def connect(self, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            os.chmod(self.path, 0o600)
        else:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def migrate(self):
        with self.connect(True) as db:
            existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing - {"dev_candidates", "dev_events"}:
                raise ValueError("foreign database; migration refused")
            db.execute("CREATE TABLE IF NOT EXISTS dev_candidates (id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS dev_events (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, candidate TEXT REFERENCES dev_candidates(id), kind TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL)")
            for table in ("dev_candidates", "dev_events"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only development ledger'); END")

    def discover(self, proposal):
        required = {"source", "title", "problem", "evidence", "outcome", "files", "category"}
        if not required <= proposal.keys() or proposal["source"] not in SOURCES or proposal["category"] not in CATEGORIES:
            raise ValueError("invalid candidate")
        if not proposal["evidence"] or any(not proposal[k] for k in ("title", "problem", "outcome")):
            raise ValueError("concrete evidence and outcome required")
        if not isinstance(proposal["title"], str) or any(c in proposal["title"] for c in "\r\n\x00") or len(proposal["title"]) > 1000 or not isinstance(proposal["files"], list):
            raise ValueError("bounded title and explicit scope required")
        from .policy import safe_relative
        for name in proposal["files"]: safe_relative(name)
        identity = digest({k: proposal[k] for k in ("source", "problem", "files", "evidence")})
        proposal = dict({"estimated_scope":{"files":proposal["files"],"effort":"UNESTIMATED"}, "value_score":None, "risk_score":None, "lineage":[]}, **proposal)
        payload = bounded(proposal)
        with self.connect(True) as db:
            old = db.execute("SELECT id FROM dev_candidates WHERE identity=?", (identity,)).fetchone()
            if old:
                return old[0]
            cid = str(uuid.uuid4())
            db.execute("INSERT INTO dev_candidates VALUES (?,?,?,?)", (cid, identity, time.time(), payload))
            self._append(db, cid, "STATE", {"state": "DISCOVERED"}, "discover:" + cid)
            return cid

    @staticmethod
    def _append(db, cid, kind, payload, key):
        encoded = bounded(payload)
        old = db.execute("SELECT candidate,kind,payload FROM dev_events WHERE event_id=?", (key,)).fetchone()
        if old:
            if tuple(old) != (cid, kind, encoded):
                raise ValueError("idempotency key conflict")
            return
        db.execute("INSERT INTO dev_events(event_id,candidate,kind,created,payload) VALUES (?,?,?,?,?)", (key, cid, kind, time.time(), encoded))

    @staticmethod
    def _state(db, cid):
        row = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='STATE' ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
        if not row:
            raise KeyError(cid)
        return json.loads(row[0])["state"]

    def event(self, cid, kind, payload, key=None):
        if kind in {"STATIC_VALIDATION", "MERGE", "OWNER_MERGE", "AUTONOMY_RESUME", "STAGE_OBSERVATION", "AUTONOMY_PAUSE", "BUILD_POLICY", "POLICY_ADMISSION", "PIPELINE", "SCHEDULER_OBSERVATION", "OWNER_REVIEW", "OWNER_AUTONOMY_PROMOTION", "STATE", "APPROVAL", "VALIDATION", "VALIDATION_BATCH", "SUPPLEMENTAL_VALIDATION", "RECEIPT", "OPERATIONAL_SUCCESS", "AUTHORIZATION", "START_AUTHORIZATION", "TECHNICAL_CERTIFICATION", "PROTECTION"}:
            raise ValueError("use transition/decide")
        with self.connect(True) as db:
            self._append(db, cid, kind, payload, key or str(uuid.uuid4()))

    def transition(self, cid, target, context=None):
        # Approval and deployment require their specialized, evidence-bound paths.
        if target in {"APPROVED", "DEPLOYED", "ROLLED_BACK", "CLOSED", "PR_OPEN"}:
            raise ValueError("specialized gate required")
        with self.connect(True) as db:
            prior = self._state(db, cid)
            if target not in STATES[prior]:
                raise ValueError(f"invalid transition {prior} -> {target}")
            if target == "BUILDING":
                raise ValueError("runner must consume exact approval")
            self._append(db, cid, "STATE", {"state": target, "context": context or {}}, str(uuid.uuid4()))

    def get(self, cid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM dev_candidates WHERE id=?", (cid,)).fetchone()
            if not row:
                raise KeyError(cid)
            events = [dict(r) for r in db.execute("SELECT * FROM dev_events WHERE candidate=? ORDER BY seq", (cid,))]
            for e in events:
                e["payload"] = json.loads(e["payload"])
            return dict(id=cid, created=row["created"], **json.loads(row["payload"]), state=self._state(db, cid), events=events)

    def events(self,kind,limit=1000):
        if not isinstance(kind,str) or not kind.isidentifier():raise ValueError('event kind required')
        if not self.path.exists():return []
        with self.connect() as db:
            rows=db.execute('SELECT kind,created,payload FROM dev_events WHERE kind=? ORDER BY seq DESC LIMIT ?',(kind,min(1000,max(1,limit)))).fetchall()
        return [dict(kind=r[0],created=r[1],payload=json.loads(r[2])) for r in rows]

    def list(self, limit=100, **filters):
        if not self.path.exists():
            return []
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM dev_candidates ORDER BY created DESC,id")]
        results = [self.get(cid) for cid in ids]
        return [r for r in results if all(r.get(k) == v for k, v in filters.items())][:max(0, min(int(limit), 500))]

    def decide(self, cid, decision, actor, context, nonce, rationale="", *, identity=None):
        if decision not in {"approve", "reject", "defer"} or not actor or not nonce:
            raise ValueError("explicit human decision required")
        if not {"todo", "head", "scope_hash", "risk", "acceptance_hash"} <= context.keys():
            raise ValueError("incomplete approval context")
        if not re.fullmatch(r"L[0-5]", str(context["risk"])) or not re.fullmatch(r"[a-f0-9]{40}", str(context["head"])):
            raise ValueError("invalid risk or head")
        with self.connect(True) as db:
            plan = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='PLAN' ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
            if not plan or json.loads(plan[0])["context"] != context:
                raise ValueError("stale plan or scope")
            prior = self._state(db, cid)
            target = {"approve": "APPROVED", "reject": "REJECTED", "defer": "DEFERRED"}[decision]
            if target not in STATES[prior] or db.execute("SELECT 1 FROM dev_events WHERE event_id=?", ("decision:" + nonce,)).fetchone():
                raise ValueError("stale or replayed decision")
            if int(context["risk"][1:]) >= 3 and not rationale.strip():
                raise ValueError("high-risk rationale required")
            payload = dict(actor=actor, decision=decision, context=context, prior=prior, rationale=rationale)
            if identity is not None:
                from .identity import HumanIdentity
                if type(identity) is not HumanIdentity: raise ValueError('authenticated human identity required')
                payload.update(identity.audit())
                payload['decision_nonce']=nonce
            self._append(db, cid, "APPROVAL", payload, "decision:" + nonce)
            self._append(db, cid, "STATE", {"state": target}, str(uuid.uuid4()))

    def begin(self, cid, context, run_id):
        with self.connect(True) as db:
            row = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind IN ('APPROVAL','POLICY_ADMISSION') ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
            if self._state(db, cid) != "APPROVED" or not row or json.loads(row[0])["context"] != context:
                raise ValueError("fresh exact approval required")
            self._append(db, cid, "STATE", {"state": "BUILDING", "run_id": run_id}, "begin:" + run_id)

    def review_decision(self, cid, stage, decision, actor, context, nonce, rationale, *, identity=None):
        """Review dispositions are audit annotations, never merge/deploy authority."""
        if stage not in {"REVIEW_OVERRIDE", "ESCALATION", "PR_DISPOSITION", "OUTCOME_ACCEPTANCE"} or decision not in {"accept", "reject", "defer", "escalate"}:
            raise ValueError("invalid human review decision")
        if not actor or not nonce or not rationale.strip(): raise ValueError("explicit human rationale required")
        with self.connect(True) as db:
            plan = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='PLAN' ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
            proof = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='RECEIPT' ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
            if not plan: raise ValueError("missing scope")
            expected = json.loads(plan[0])["context"]
            if proof: expected = dict(expected, head=json.loads(proof[0])["receipt"]["head"])
            if context != expected or db.execute("SELECT 1 FROM dev_events WHERE event_id=?", ("review-decision:"+nonce,)).fetchone():
                raise ValueError("stale/replayed review")
            close = stage == "OUTCOME_ACCEPTANCE" and decision == "accept"
            if close:
                prior = self._state(db, cid)
                outcome = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='DEPLOYMENT' ORDER BY seq DESC LIMIT 1", (cid,)).fetchone()
                if prior not in {"DEPLOYED", "ROLLED_BACK"} or not outcome or json.loads(outcome[0])["status"] not in {"HEALTHY", "ROLLED_BACK"}:
                    raise ValueError("observed healthy/rollback outcome required before closure")
            audit={}
            if identity is not None:
                from .identity import HumanIdentity
                if type(identity) is not HumanIdentity: raise ValueError('authenticated human identity required')
                audit=identity.audit()
            self._append(db, cid, "HUMAN_REVIEW", dict(stage=stage, decision=decision, actor=audit.get('actor',actor), context=context, rationale=rationale, decision_nonce=nonce, grants_merge=False, grants_deployment=False, **{k:v for k,v in audit.items() if k!='actor'}), "review-decision:"+nonce)
            if close: self._append(db, cid, "STATE", {"state":"CLOSED"}, "close:"+nonce)

    def run_event(self, cid, run_id, role, status, data, parent=None):
        if role not in {"planner", "builder", "reviewer", "validation", "scout"} or status not in {"RUNNING", "PASS", "FAIL", "NEEDS_HUMAN"}:
            raise ValueError("invalid run contract")
        with self.connect(True) as db:
            previous = db.execute("SELECT payload,candidate FROM dev_events WHERE kind='RUN' AND json_extract(payload,'$.run_id')=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
            payload = dict(run_id=run_id, role=role, status=status, parent=parent, data=data)
            old = json.loads(previous[0]) if previous else None
            if previous and previous[1] != cid: raise ValueError("run identity belongs to another candidate")
            if old and old["status"] in {"PASS", "FAIL", "NEEDS_HUMAN"}:
                if old["role"] == role and old["status"] == status and old["parent"] == parent and all(old["data"].get(k)==v for k,v in data.items()):
                    return
                raise ValueError("finalized run")
            payload["started_at"] = old["started_at"] if old else time.time()
            payload["ended_at"] = time.time() if status != "RUNNING" else None
            if old: payload["data"] = dict(old["data"], **data)
            self._append(db, cid, "RUN", payload, str(uuid.uuid4()))

    def query_runs(self, *, candidate=None, todo=None, sha=None, status=None, start=0, end=float("inf")):
        with self.connect() as db:
            rows = list(db.execute("SELECT * FROM dev_events WHERE kind='RUN' AND created>=? AND created<=? ORDER BY seq", (start, end)))
        latest = {}
        for row in rows:
            payload = json.loads(row["payload"])
            latest[payload["run_id"]] = dict(payload, candidate=row["candidate"], created=row["created"], sequence=row["seq"])
        result=[]
        for run in latest.values():
            if candidate and run["candidate"] != candidate: continue
            if status and run["status"] != status: continue
            if sha and sha not in {run["data"].get("base"), run["data"].get("head")}: continue
            if todo:
                plans = [e["payload"] for e in self.get(run["candidate"])["events"] if e["kind"] == "PLAN"]
                if not plans or plans[-1]["context"]["todo"] != todo: continue
            result.append(run)
        return sorted(result, key=lambda r:r["sequence"])
