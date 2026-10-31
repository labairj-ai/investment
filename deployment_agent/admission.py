"""Read-only admission of an original exact-head owner Go and merged main SHA."""
from __future__ import annotations
import re
from dev_agent.owner_review import verify_merge_actor
from scripts.check_owner_review import check


def authorize(store,client,object_id,*,emergency_stop=False,mirror_owner=False):
    if type(object_id) is not int or object_id<=0:raise ValueError('positive deployment authorization ID required')
    if emergency_stop:raise ValueError('deployment emergency stop active')
    # The original exact-head owner review is the sole human authority.
    # Derive release identity from current GitHub, never a second deployment act.
    from dev_agent.github_owner import verified_object,ingest
    decision,current,origin=verified_object(client,object_id)
    from dev_agent.github_owner import validate_action
    validate_action(decision,'DEPLOY')
    if decision['decision']!='APPROVE':raise ValueError('owner No-Go blocks deployment')
    if mirror_owner:ingest(store,client,object_id)
    owner=check(store,client,current['pr'],current['head'])
    if owner['owner_review'].get('origin')!=origin:
        raise ValueError('deployment must consume the current exact owner Go')
    remote=client.pr_identity(current['pr'])
    data=dict(repository=client.repository,pr=current['pr'],head=current['head'],
              merge_sha=(remote.get('mergeCommit') or {}).get('oid'),nonce=decision['nonce'])
    if not re.fullmatch(r'[a-f0-9]{40}',str(data['merge_sha'])):raise ValueError('exact merge SHA required')
    remote=client.pr_identity(data['pr'])
    if remote.get('state')!='MERGED' or remote.get('headRefOid')!=data['head'] or remote.get('baseRefName')!='main' or (remote.get('mergeCommit') or {}).get('oid')!=data['merge_sha']:raise ValueError('owner-approved merge does not match target')
    verify_merge_actor(client,data['pr'],data['head'],data['merge_sha'])
    for left,right in [(data['merge_sha'],'main'),(data['head'],data['merge_sha'])]:
        comparison=client.read(f'repos/{client.repository}/compare/{left}...{right}')
        if comparison.get('status') not in {'identical','ahead'}:raise ValueError('approved head/merge is not contained in main')
    runs=client.read(f'repos/{client.repository}/commits/{data["merge_sha"]}/check-runs?per_page=100')
    tests=[r for r in runs.get('check_runs',[]) if r.get('name')=='test' and r.get('head_sha')==data['merge_sha']]
    if runs.get('total_count',0)>100 or not tests or max(tests,key=lambda r:r['id']).get('conclusion')!='success':raise ValueError('merged main exact-SHA CI required')
    from .evidence import ci_record
    main=client.read(f'repos/{client.repository}/branches/main')
    if main.get('commit',{}).get('sha')!=data['merge_sha']:raise ValueError('current main differs from owner-authorized merge')
    latest=max(tests,key=lambda r:r['id'])
    if latest.get('status')!='completed':raise ValueError('merged main CI is not complete')
    head_ci=ci_record(client.repository,data['head'],owner.get('ci_url'))
    merge_ci=ci_record(client.repository,data['merge_sha'],latest.get('html_url'))
    return dict(data,action=decision['action'],authorization_contract='solo-owner-3',action_authorization=decision,main_sha=data['merge_sha'],head_ci=head_ci,merge_ci=merge_ci,authorization_id=object_id,authorization_url=origin['url'],owner_review=owner['owner_review'],ci_url=owner.get('ci_url'),deployment_actor=current['owner_login'])
