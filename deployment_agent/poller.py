"""Outbound-only fixed deployment queue. No self-hosted arbitrary job execution."""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from dev_agent.github import GitHub
from dev_agent.owner_review import policy
from .__main__ import configuration,main as deploy_main


def pending(client,receipts,*,now=None):
    now=time.time() if now is None else now;p=policy();since=datetime.fromtimestamp(now,tz=timezone.utc)-timedelta(hours=24);rows=[]
    for page in range(1,5):
        batch=client.read(f'repos/{client.repository}/issues/comments?'+urlencode(dict(since=since.isoformat(),per_page=30,page=page)))
        if not isinstance(batch,list):raise ValueError('deployment queue visibility unavailable')
        rows.extend(batch)
        if len(batch)<30:break
    else:raise ValueError('deployment queue exceeds bounded complete inventory')
    chosen=[]
    for obj in rows:
        user=obj.get('user') or {};body=obj.get('body','');object_id=obj.get('id')
        if type(object_id) is not int or object_id<=0 or user.get('id')!=p['owner_id'] or user.get('login')!=p['owner_login'] or user.get('type')!='User' or not isinstance(body,str) or not body.startswith('OWNER-DEPLOY deployment-1\n'):continue
        if not (Path(receipts)/f'deploy-{object_id}.json').exists():chosen.append(object_id)
    return sorted(set(chosen))[:1] # At most one static deployment invocation per poll.


def main():
    cfg=configuration();client=GitHub(cfg['repository']);queue=pending(client,cfg['receipts'])
    if not queue:print(json.dumps(dict(status='NO_PENDING_OWNER_DEPLOYMENT')));return 0
    return deploy_main(['--authorization-id',str(queue[0])])


if __name__=='__main__':raise SystemExit(main())
