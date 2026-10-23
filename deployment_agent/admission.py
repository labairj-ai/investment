"""Read-only admission of an explicit owner deployment object and merged main SHA."""
from __future__ import annotations
import json
import re
import time
from dev_agent.owner_review import policy,require,verify_merge_actor,allowed_owner_app
from scripts.check_owner_review import check


def authorize(store,client,object_id,*,emergency_stop=False,mirror_owner=False):
    if type(object_id) is not int or object_id<=0:raise ValueError('positive deployment authorization ID required')
    if emergency_stop:raise ValueError('deployment emergency stop active')
    p=policy();obj=client.read(f'repos/{client.repository}/issues/comments/{object_id}');user=obj.get('user') or {}
    if client.repository!=p['repository'] or obj.get('id')!=object_id or user.get('type')!='User' or user.get('id')!=p['owner_id'] or user.get('login')!=p['owner_login'] or not allowed_owner_app(obj,p):raise ValueError('owner deployment actor required')
    body=obj.get('body','');prefix='OWNER-DEPLOY deployment-1\n'
    if not isinstance(body,str) or len(body)>16000 or not body.startswith(prefix) or obj.get('created_at')!=obj.get('updated_at'):raise ValueError('unedited versioned deployment object required')
    from dev_agent.structured_json import loads
    data=loads(body[len(prefix):])
    required={'repository','pr','head','merge_sha','nonce','expires_at','rationale','execution_ack'}
    if not isinstance(data,dict) or set(data)!=required:raise ValueError('deployment authorization schema')
    if data['repository']!=client.repository or type(data['pr']) is not int or not re.fullmatch(r'[A-Za-z0-9-]{16,128}',str(data['nonce'])) or data['execution_ack'] is not True or not data['rationale'].strip():raise ValueError('explicit deployment scope and execution acknowledgment required')
    if not isinstance(data['expires_at'],(int,float)) or not time.time()<data['expires_at']<=time.time()+86400:raise ValueError('deployment authorization expired or excessive')
    if obj.get('issue_url')!=f'https://api.github.com/repos/{client.repository}/issues/{data["pr"]}':raise ValueError('deployment object PR mismatch')
    if obj.get('html_url')!=f'https://github.com/{client.repository}/pull/{data["pr"]}#issuecomment-{object_id}':raise ValueError('canonical deployment object URL required')
    if not all(re.fullmatch(r'[a-f0-9]{40}',str(data[k])) for k in ('head','merge_sha')):raise ValueError('exact deployment SHAs required')
    if mirror_owner:
        from dev_agent.github_owner import newest_review,ingest
        ingest(store,client,newest_review(client,data['pr'],data['head']))
    owner=check(store,client,data['pr'],data['head'])
    remote=client.pr_identity(data['pr'])
    if remote.get('state')!='MERGED' or remote.get('headRefOid')!=data['head'] or remote.get('baseRefName')!='main' or (remote.get('mergeCommit') or {}).get('oid')!=data['merge_sha']:raise ValueError('owner-approved merge does not match target')
    verify_merge_actor(client,data['pr'],data['head'],data['merge_sha'])
    for left,right in [(data['merge_sha'],'main'),(data['head'],data['merge_sha'])]:
        comparison=client.read(f'repos/{client.repository}/compare/{left}...{right}')
        if comparison.get('status') not in {'identical','ahead'}:raise ValueError('approved head/merge is not contained in main')
    runs=client.read(f'repos/{client.repository}/commits/{data["merge_sha"]}/check-runs?per_page=100')
    tests=[r for r in runs.get('check_runs',[]) if r.get('name')=='test' and r.get('head_sha')==data['merge_sha']]
    if runs.get('total_count',0)>100 or not tests or max(tests,key=lambda r:r['id']).get('conclusion')!='success':raise ValueError('merged main exact-SHA CI required')
    return dict(data,authorization_id=object_id,authorization_url=obj['html_url'],owner_review=owner['owner_review'],ci_url=owner.get('ci_url'),deployment_actor=user['login'])
