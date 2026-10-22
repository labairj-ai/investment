"""Read-only canary on an operator-provided isolated production snapshot."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .guard import WorkspaceGuard


def check_snapshot(snapshot, workspace):
    snapshot = Path(snapshot).resolve(strict=True)
    if snapshot.suffix != ".db" or str(snapshot).startswith("/home/optiplex/investment/"):
        raise ValueError("isolated snapshot required, never runtime database")
    if Path(str(snapshot)+"-wal").exists(): raise ValueError("consistent backup without live WAL required")
    before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    db = sqlite3.connect(snapshot.as_uri()+"?mode=ro&immutable=1", uri=True)
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        denied = False
        try: db.execute("CREATE TABLE development_agent_must_not_write(x)")
        except sqlite3.OperationalError: denied = True
    finally: db.close()
    guard = WorkspaceGuard(workspace, [])
    action_denied = False
    try: guard.write(str(snapshot), "forbidden")
    except ValueError: action_denied = True
    after = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    return dict(status="PASS" if before == after and integrity == "ok" and denied and action_denied else "FAIL", snapshot_sha256_before=before, snapshot_sha256_after=after, table_count=len(names), readonly_sql_denied=denied, runner_write_denied=action_denied, investment_state_mutated=False)
