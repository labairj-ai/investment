"""Owner-promotion binding and fail-closed, current GitHub authorization adapter.

Shape checks grant no authority. Runtime requires deliberate owner objects from
an allowlisted connector, verified ingestion and independently reconstructed context.
"""
import re
import os
import time

PROTOCOL='autonomy-promotion-1'
FIELDS={'protocol','repository','harness_hash','activation_pr','head','stage','maximum_risk','daily_cap','owner_login','owner_id','created','nonce','rationale'}
BOUND={'repository','harness_hash','activation_pr','head','stage','maximum_risk','daily_cap','owner_login','owner_id'}


def validate_binding(record,context,now=None):
    """Validate future protocol binding only; explicitly grants no authority."""
    now=time.time() if now is None else now
    if not isinstance(record,dict) or set(record)!=FIELDS or record['protocol']!=PROTOCOL:raise ValueError('exact owner promotion protocol required')
    if not isinstance(context,dict) or not BOUND<=context.keys() or any(record[k]!=context[k] for k in BOUND):raise ValueError('stale or mismatched owner promotion binding')
    if not isinstance(record['repository'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',record['repository']) or not isinstance(record['owner_login'],str) or not re.fullmatch(r'[A-Za-z0-9-]+',record['owner_login']):raise ValueError('canonical repository and verified owner login required')
    if not re.fullmatch(r'[a-f0-9]{40}',str(record['head'])) or not re.fullmatch(r'[a-f0-9]{64}',str(record['harness_hash'])):raise ValueError('exact activation head/harness required')
    if type(record['activation_pr']) is not int or record['activation_pr']<=0 or type(record['owner_id']) is not int or record['owner_id']<=0:raise ValueError('verified PR/owner identity required')
    if record['stage'] not in {'SHADOW','BUILD_ONLY','PR'} or record['maximum_risk']!='L2' or type(record['daily_cap']) is not int or not 1<=record['daily_cap']<=3:raise ValueError('bounded promotion policy required')
    if type(record['created']) not in (int,float) or not 0<=now-record['created']<=86400:raise ValueError('fresh owner promotion required')
    if not re.fullmatch(r'[A-Za-z0-9-]{16,128}',str(record['nonce'])) or not isinstance(record['rationale'],str) or not record['rationale'].strip():raise ValueError('deliberate single-use owner decision required')
    return dict(binding_valid=True,authenticated=False,grants_authority=False)


def selected_pr():
    raw=os.environ.get('DEV_AGENT_PROMOTION_PR','')
    if not re.fullmatch(r'[1-9][0-9]{0,8}',raw):raise ValueError('operator-selected activation PR unavailable')
    return int(raw)


def authorization(root,store,*,now=None):
    # Selection is not authority: every result requires current GitHub verification.
    try:
        from .promotion_github import verify_current
        return verify_current(root,store,selected_pr(),now=now)
    except Exception as error:
        return dict(status='UNAVAILABLE',authenticated=False,fixture_only=False,protocol=PROTOCOL,
                    reason='authenticated owner autonomy promotion unavailable: '+type(error).__name__,grants_authority=False)


def require_runtime_binding(root,store,result,*,now=None):
    """Defense in depth against incomplete/generic adapter PASS responses."""
    from .promotion_github import context
    if (not isinstance(result,dict) or result.get('status')!='PASS'
            or result.get('authenticated') is not True or result.get('fixture_only') is not False
            or result.get('protocol')!=PROTOCOL or result.get('revocation_checked') is not True
            or result.get('replay_checked') is not True):
        raise ValueError('authenticated non-fixture contextual owner promotion required')
    expected=context(root,selected_pr())
    validate_binding(result.get('binding'),expected,now)
    # The context above is independently reconstructed, not copied from a result.
    if not isinstance(result.get('origin'),dict) or type(result['origin'].get('id')) is not int:
        raise ValueError('verified GitHub promotion origin required')
    from .promotion_github import verify_current
    if verify_current(root,store,expected['activation_pr'],now=now)!=result:
        raise ValueError('runtime owner promotion provenance mismatch')
    return True


def activation_authority(root,store,*,now=None):
    """Normal activation uses the activation PR's ordinary exact-head owner Go.

    Historical promotion objects are not consumed. Runtime source/configuration,
    repository, owner, connector, revocation and exact CI are reverified each time.
    """
    from .promotion_github import context
    from .owner_review import policy
    from .github import GitHub
    from scripts.check_owner_review import check
    from .operations import policy as runtime_policy
    from .store import digest
    cfg=runtime_policy(root)
    if cfg.get('autonomous_max_risk')!='L2' or type(cfg.get('daily_implementation_cap')) is not int or not 1<=cfg['daily_implementation_cap']<=3:
        raise ValueError('bounded activation policy required')
    client=GitHub(policy()['repository'])
    if os.environ.get('DEV_AGENT_PROMOTION_PR'):number=selected_pr()
    else:
        # Internal selection follows the installed approved release; owners never
        # select stages or maintain an activation-PR pointer after each release.
        from .git_exec import output
        local=output(root,'rev-parse','HEAD').strip()
        rows=client.read(f'repos/{client.repository}/commits/{local}/pulls?per_page=100')
        if not isinstance(rows,list) or len(rows)>=100:raise ValueError('current source PR inventory unavailable')
        numbers={r.get('number') for r in rows if r.get('merge_commit_sha')==local or (r.get('head') or {}).get('sha')==local}
        if len(numbers)!=1:raise ValueError('unambiguous approved runtime PR required')
        number=numbers.pop()
    expected=context(root,number,client)
    from .git_exec import output
    remote=client.pr_identity(number)
    merge=(remote.get('mergeCommit') or {}).get('oid')
    if remote.get('state')!='MERGED' or output(root,'rev-parse','HEAD').strip()!=merge:
        raise ValueError('activation requires the exact deployed owner merge')
    runs=client.read(f'repos/{client.repository}/commits/{merge}/check-runs?per_page=100')
    tests=[r for r in runs.get('check_runs',[]) if r.get('name')=='test' and r.get('head_sha')==merge]
    if runs.get('total_count',0)>100 or not tests:raise ValueError('activation merged-main CI unavailable')
    latest=max(tests,key=lambda r:r['id'])
    if latest.get('status')!='completed' or latest.get('conclusion')!='success':raise ValueError('activation merged-main CI must pass')
    from .owner_review import require_action
    require_action(store,client,number,'DEPLOY')
    approved=check(store,client,number,expected['head'])
    # owner_review.context enforces the deterministic risk floor, including L5
    # for configuration/governance changes. A later approved documentation-only
    # release does not require another autonomy-promotion decision.
    if context(root,number,client)!=expected:raise ValueError('activation source changed')
    return dict(status='PASS',binding=expected,owner_review_hash=digest(approved['owner_review']),
                origin=approved['owner_review'].get('origin'),grants_merge=False,grants_deployment=False)
