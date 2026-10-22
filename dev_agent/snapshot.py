"""Authenticate an isolated backup; never open the authoritative runtime DB."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path

from .guard import WorkspaceGuard
from .store import digest

VERSION = 'production-backup-provenance-1'
SOURCE = 'optiplex/investment/out/investment.db'
MAX_AGE = 24 * 60 * 60
REQUIRED_TABLES = {'investment_theses', 'recommendations', 'trading_accounts', 'trade_intents', 'orders', 'fills'}


def schema_identity(db):
    rows = [tuple(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    tables = [r[1] for r in rows if r[0]=='table']
    columns = {name:[tuple(r) for r in db.execute('PRAGMA table_info('+json.dumps(name)+')')] for name in tables}
    return dict(schema_fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(), migration_fingerprint=hashlib.sha256(json.dumps(dict(user_version=db.execute('PRAGMA user_version').fetchone()[0], columns=columns),sort_keys=True).encode()).hexdigest(), tables=tables)


def sign_backup(snapshot, *, key, source_sha, source_identity=SOURCE, now=None):
    """Operator backup workflow only. Never exposed via Builder/agent CLI."""
    path=Path(snapshot).resolve(strict=True)
    if not isinstance(key, bytes) or len(key)<32: raise ValueError('operator backup signing key required')
    if source_identity!=SOURCE: raise ValueError('authoritative source required')
    with sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        identity=schema_identity(db)
    if integrity!='ok' or not REQUIRED_TABLES<=set(identity['tables']): raise ValueError('investment schema required')
    receipt=dict(version=VERSION, source_environment=source_identity, backup_timestamp=time.time() if now is None else now, backup_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), integrity=integrity, **identity, source_application_sha=source_sha, mechanism='sqlite-online-backup-1')
    receipt['signature']=hmac.new(key,json.dumps(receipt,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    return receipt


def check_snapshot(snapshot, workspace, provenance=None, *, key=None, now=None, max_age_hours=24):
    """HMAC verifier is trusted application config; callers cannot nominate a key via JSON."""
    result=dict(status='FAIL', investment_state_mutated=False, provenance_status='UNAVAILABLE')
    if provenance is None: return dict(result, reason='authenticated backup provenance required')
    if key is None:
        configured=os.environ.get('DEV_AGENT_BACKUP_SIGNING_KEY','')
        key=configured.encode() if configured else b''
    if not isinstance(key, bytes) or len(key)<32: return dict(result, status='UNAVAILABLE', reason='backup verifier not provisioned')
    payload={k:v for k,v in provenance.items() if k!='signature'}
    expected=hmac.new(key,json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(provenance.get('signature','')),expected): return dict(result, reason='backup provenance authentication failed')
    try:
        raw=Path(snapshot)
        if raw.is_symlink(): raise ValueError('symlink snapshot denied')
        snapshot=raw.resolve(strict=True)
        if snapshot.suffix!='.db' or snapshot.name=='investment.db' and snapshot.parent.name=='out' or str(snapshot).startswith('/home/optiplex/investment/'):
            raise ValueError('isolated snapshot required, never runtime database')
        if any(Path(str(snapshot)+suffix).exists() for suffix in ('-wal','-shm','-journal')): raise ValueError('consistent closed backup without WAL/journal required')
        now=time.time() if now is None else now
        stamp=provenance.get('backup_timestamp',0)
        if not isinstance(stamp,(int,float)) or not 0<=now-stamp<=min(MAX_AGE,max(1,max_age_hours)*3600): raise ValueError('backup expired or future dated')
        if provenance.get('source_environment')!=SOURCE or provenance.get('version')!=VERSION or provenance.get('mechanism')!='sqlite-online-backup-1' or provenance.get('integrity')!='ok': raise ValueError('backup source/mechanism mismatch')
        before=hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if before!=provenance.get('backup_sha256'): raise ValueError('backup hash mismatch')
        with sqlite3.connect(snapshot.as_uri()+'?mode=ro&immutable=1',uri=True) as db:
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
            identity=schema_identity(db)
            if not REQUIRED_TABLES<=set(identity['tables']) or any(identity[k]!=provenance.get(k) for k in identity): raise ValueError('canonical schema identity mismatch')
            denied=False
            try: db.execute('CREATE TABLE development_agent_must_not_write(x)')
            except sqlite3.OperationalError: denied=True
        action_denied=False
        try: WorkspaceGuard(workspace,[]).write(str(snapshot),'forbidden')
        except ValueError: action_denied=True
        after=hashlib.sha256(snapshot.read_bytes()).hexdigest()
        return dict(result,status='PASS' if before==after and integrity=='ok' and denied and action_denied else 'FAIL',provenance_status='PASS',backup_timestamp=stamp,source_environment=SOURCE,schema_fingerprint=identity['schema_fingerprint'],migration_fingerprint=identity['migration_fingerprint'],snapshot_sha256_before=before,snapshot_sha256_after=after,readonly_sql_denied=denied,runner_write_denied=action_denied)
    except (ValueError,OSError,sqlite3.Error,TypeError) as exc:
        return dict(result,reason=str(exc))
