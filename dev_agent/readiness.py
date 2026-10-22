"""Read-only readiness projection from exact-hash receipts and operational lineage."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from .certification import harness_hash, technical_current, current
from .operations import policy, certificates, eligibility, operational_runs


def readiness(root,store,now=None):
    now=time.time() if now is None else now
    config=policy(root);certs=certificates(store);bound=harness_hash(root)
    latest=certs[-1] if certs else {}
    technical=technical_current(root,certs,now)
    evidence=latest.get('evidence',{})
    protection=evidence.get('github',{})
    if not 0<=now-protection.get('created',0)<=min(300,config.get('github_evidence_max_age_seconds',300)):
        protection=dict(status='UNAVAILABLE',failures=['fresh effective-protection evidence unavailable'])
    snapshot=evidence.get('snapshot',{})
    if not 0<=now-snapshot.get('backup_timestamp',0)<=86400:
        snapshot=dict(status='UNAVAILABLE',reason='authenticated recent backup unavailable')
    progress=eligibility(root,store,now)
    blockers=[]
    if not technical: blockers.append('technical certification missing, failed, expired or stale')
    if protection.get('status')!='PASS': blockers+=protection.get('failures',['GitHub protection unavailable'])
    if snapshot.get('status')!='PASS': blockers.append(snapshot.get('reason','production snapshot provenance not PASS'))
    runtime='PASS' if technical and evidence.get('sandbox',{}).get('status')=='PASS' and shutil.which('docker') else 'UNAVAILABLE'
    if runtime!='PASS': blockers.append('sandbox runtime unavailable')
    kill=config.get('emergency_stop',False) or os.environ.get('DEV_AGENT_KILL_SWITCH','').lower() not in {'','0','false'}
    if kill: blockers.append('emergency stop enabled')
    enabled=config.get('autonomous_implementation',False)
    if not blockers:
        status='AUTONOMY_ELIGIBLE' if enabled and progress['eligible'] else ('SUPERVISED_ONLY' if progress['completed'] else 'READY_FOR_SUPERVISED')
    else:
        status='UNAVAILABLE' if runtime=='UNAVAILABLE' or protection.get('status')=='UNAVAILABLE' else 'BLOCKED'
    return dict(status=status,harness_hash=bound,technical_certification='PASS' if technical else ('STALE' if latest and latest.get('harness_hash')!=bound else 'EXPIRED' if latest and now-latest.get('created',0)>86400 else 'NOT_RUN' if not latest else 'FAIL'),certification_stale=bool(latest and latest.get('harness_hash')!=bound),sandbox_runtime=runtime,production_snapshot={k:v for k,v in snapshot.items() if k in {'status','reason','backup_timestamp','schema_fingerprint','source_environment'}},github_protection={k:v for k,v in protection.items() if k in {'status','failures','created','identity'}},supervised=progress,operational_runs=operational_runs(root,store,now),autonomous_implementation=enabled,autonomous_starts_allowed=not blockers and current(root,certs,now,store=store),auto_merge=False,scheduled_discovery=dict(policy='daily discovery only',installation='UNAVAILABLE: scheduler installation is not observed'),blockers=blockers+([] if enabled else ['autonomous implementation disabled'])+progress['blockers'])
