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
    # Recover an older Go for the current main release without asking again.
    # Current-main association is only discovery; authorize independently checks it.
    main=client.read(f'repos/{client.repository}/branches/main').get('commit',{}).get('sha')
    if isinstance(main,str):
        associated=client.read(f'repos/{client.repository}/commits/{main}/pulls?per_page=100')
        if not isinstance(associated,list) or len(associated)>=100:raise ValueError('current release PR inventory unavailable')
        for pr in associated:
            number=pr.get('number')
            if type(number) is int and number>0 and pr.get('merge_commit_sha')==main:
                comments=client.read_all(f'repos/{client.repository}/issues/{number}/comments')
                if len(comments)>3000:raise ValueError('current release owner decision inventory unavailable')
                rows.extend(comments)
    chosen=[]
    for obj in rows:
        user=obj.get('user') or {};body=obj.get('body','');object_id=obj.get('id')
        if type(object_id) is not int or object_id<=0 or user.get('id')!=p['owner_id'] or user.get('login')!=p['owner_login'] or user.get('type')!='User' or not isinstance(body,str) or not body.startswith('OWNER-AUTHORIZATION solo-owner-3\n'):continue
        from dev_agent.github_owner import verified_object
        try:
            decision,context,origin=verified_object(client,object_id)
            from dev_agent.github_owner import validate_action
            validate_action(decision,'DEPLOY')
            if decision['decision']!='APPROVE' or client.pr_identity(context['pr']).get('state')!='MERGED':continue
            # Wait for CI without consuming an authorization or writing failure receipts.
            from .admission import authorize
            from dev_agent.store import Store
            authority=Store(Path(receipts)/'authority'/'development-control.sqlite3');authority.migrate()
            authorize(authority,client,object_id,mirror_owner=True)
        except (ValueError,KeyError):continue
        if not (Path(receipts)/f'deploy-{object_id}.json').exists():chosen.append(object_id)
    return sorted(set(chosen))[:1] # At most one static deployment invocation per poll.


def main():
    cfg=configuration();client=GitHub(cfg['repository']);queue=pending(client,cfg['receipts'])
    if not queue:print(json.dumps(dict(status='NO_PENDING_OWNER_DEPLOYMENT')));return 0
    return deploy_main(['--authorization-id',str(queue[0])])


if __name__=='__main__':raise SystemExit(main())
