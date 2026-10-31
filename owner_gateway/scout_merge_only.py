"""Fixed owner-side bootstrap; no CLI, deployment import or production access.

Run only in the isolated authenticated owner connector from the separately
reviewed governance bundle. This module grants no authority to install that bundle.
"""
from dev_agent.owner_review import context,policy
from .core import owner_actor,record_decision,advance_approved

REPOSITORY='labairj-ai/investment'
PR=34
HEAD='1f25e72001db978228050c6f342bc5bcfe477843'
BASE='a27bed1ebd3a69df5723212784842df456e153b3'


def inspect(client):
    owner_actor(client)
    if client.repository!=REPOSITORY or policy().get('authorized_actions')!=['MERGE_ONLY']:
        raise ValueError('fixed repository and merge-only bootstrap policy required')
    current=context(client,PR,risk='L5');remote=client.pr_identity(PR)
    main=client.read('repos/'+REPOSITORY+'/branches/main')
    raw=client.read('repos/'+REPOSITORY+'/pulls/'+str(PR))
    if (current['head']!=HEAD or remote.get('state')!='OPEN' or remote.get('isDraft') is not False
            or raw.get('base',{}).get('sha')!=BASE or main.get('commit',{}).get('sha')!=BASE
            or raw.get('mergeable') is not True):
        raise ValueError('exact unchanged Scout head/base and mergeability required')
    comments=client.read_all('repos/'+REPOSITORY+'/issues/34/comments')
    if not isinstance(comments,list) or len(comments)>3000:raise ValueError('complete bootstrap approval inventory required')
    # Old pollers cannot see v3 revocation. An older generic approval for this
    # head must therefore be absent, rather than merely superseded by v3.
    from dev_agent.github_owner import HEADER
    if any(isinstance(c.get('body'),str) and c['body'].startswith(HEADER) for c in comments):
        raise ValueError('legacy owner object present; merge-only isolation not proven')
    runs=client.read('repos/'+REPOSITORY+'/commits/'+HEAD+'/check-runs?per_page=100')
    if type(runs.get('total_count')) is not int or runs['total_count']!=len(runs.get('check_runs',[])) or runs['total_count']>100:
        raise ValueError('complete exact-head CI inventory required')
    for name in ('native-systemd255','test'):
        matching=[r for r in runs['check_runs'] if r.get('name')==name and r.get('head_sha')==HEAD]
        if not matching:raise ValueError('required Scout proof missing')
        latest=max(matching,key=lambda r:r['id'])
        if latest.get('status')!='completed' or latest.get('conclusion')!='success':raise ValueError('latest exact-head Scout CI must pass')
    return current


def merge_once(store,client,reviewed,*,deliberate_action,nonce,rationale,financial_ack,execution_ack):
    # Caller must be the trusted authenticated owner connector, never a model or
    # production agent. Owner action is supplied, never inferred/generated here.
    if deliberate_action!='MERGE_ONLY' or financial_ack is not True or execution_ack is not True:
        raise ValueError('deliberate merge-only L5 decision required')
    if inspect(client)!=reviewed:raise ValueError('bootstrap context changed')
    recorded=record_decision(store,client,reviewed,decision='APPROVE',action='MERGE_ONLY',nonce=nonce,
                             rationale=rationale,financial_ack=True,execution_ack=True)
    # Recheck main/CI/context after issuance, immediately before exact-head merge.
    if inspect(client)!=reviewed:raise ValueError('bootstrap changed after owner action; no merge')
    result=advance_approved(store,client,PR)
    main=client.read('repos/'+REPOSITORY+'/branches/main')
    if main.get('commit',{}).get('sha')!=result['merge_sha']:raise ValueError('merge completed but main identity changed; stop and investigate')
    return dict(result,owner_receipt=recorded,deployment_authorized=False,transition_authorized=False)
