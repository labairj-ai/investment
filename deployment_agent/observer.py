"""Fixed local post-deploy health observer; exports only signed software metadata."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import time
from dev_agent.result_collector import canonical
from .service import protected_matches


def observe(executor,receipt,*,key,now=None,window=300):
    now=time.time() if now is None else now
    if not isinstance(key,bytes) or len(key)<32 or not 60<=window<=3600:raise ValueError('operator observation key/window required')
    if receipt.get('status') not in {'DEPLOYED_VERIFIED','ROLLED_BACK','DEPLOYED_DEGRADED','FAILED_PRECHECK'} or not all(receipt.get(k) for k in ('head','pr','merge_sha','finished')):raise ValueError('verified deployment receipt required')
    if receipt['status']=='DEPLOYED_VERIFIED' and now-receipt['finished']<window:return dict(status='OBSERVATION_PENDING',remaining=window-(now-receipt['finished']))
    head='0'*40;available=True
    try:
        head=executor.git('rev-parse','HEAD');health=executor.health();same_state=protected_matches(executor,receipt.get('holdings_after',receipt.get('holdings_before')),executor.protected())
    except Exception:
        available=False;health=dict(checks=dict(observation_available=False));same_state=False
    healthy=receipt['status']=='DEPLOYED_VERIFIED' and available and head==receipt['merge_sha'] and all(health['checks'].values()) and same_state
    payload=dict(protocol='software-observation-1',repository=receipt['repository'],pr=receipt['pr'],head=receipt['head'],deployment_intent_id=receipt['authorization_id'],merge_sha=receipt['merge_sha'],deployed_sha=head,environment='OptiPlex',deployed_at=receipt['finished'],observed_at=now,window_seconds=window,metrics=dict(observation_available=available,service_healthy=all(health['checks'].values()),protected_state_unchanged=same_state),evidence=['deployment-receipt:'+hashlib.sha256(canonical(receipt)).hexdigest()],status='HEALTHY' if healthy else 'DEGRADED')
    return dict(observation=payload,signature=hmac.new(key,canonical(payload),hashlib.sha256).hexdigest())


def export(directory,signed):
    """Only signed software status/SHA metadata is readable by the agent role.

    Full backups, receipts, holdings hashes, credentials and canary payloads remain
    in the separate private deployment directory.
    """
    path=Path(directory)
    if path.is_symlink():raise ValueError('symlink observation export denied')
    path.mkdir(mode=0o755,parents=True,exist_ok=True)
    name='observation-'+hashlib.sha256(canonical(signed)).hexdigest()+'.json';target=path/name
    try:fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o644)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes()!=canonical(signed)+b'\n':raise ValueError('observation export conflict')
        return target
    with os.fdopen(fd,'wb') as stream:stream.write(canonical(signed)+b'\n');stream.flush();os.fsync(stream.fileno())
    return target


def main():
    from .__main__ import configuration
    from .executor import Executor
    cfg=configuration();key_path=Path(os.environ['INVESTMENT_DEPLOY_OBSERVATION_KEY_FILE']);info=key_path.lstat()
    if key_path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode&0o077:raise ValueError('private deployment observer key required')
    executor=Executor(cfg['root'],cfg['receipts'],cfg['ledger']);key=key_path.read_bytes()
    files=sorted(executor.receipts.glob('deploy-*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]
    for path in files:
        if path.is_symlink() or path.stat().st_size>100000:raise ValueError('bounded private deployment receipt required')
        receipt=json.loads(path.read_text())
        if all(receipt.get(k) for k in ('head','pr','merge_sha','finished')):
            marker=executor.receipts/f'observed-{receipt["authorization_id"]}.json'
            if marker.exists():continue
            result=observe(executor,receipt,key=key)
            if 'observation' in result:
                target=export(os.environ['INVESTMENT_DEPLOY_OBSERVATION_EXPORT'],result)
                from dev_agent.result_collector import write_final
                write_final(executor.receipts,'observed-'+str(receipt['authorization_id']),dict(status=result['observation']['status'],export_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),created=time.time()))
            print(json.dumps(dict(status=result.get('status',result.get('observation',{}).get('status')))));return 0
    print(json.dumps(dict(status='NO_VERIFIED_DEPLOYMENT')));return 0


if __name__=='__main__':raise SystemExit(main())
