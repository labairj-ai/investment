"""Read-only verifier for split solo-owner rulesets. No GitHub mutations."""
from .owner_review import policy


def verify(active_rules,rulesets,identity,repository,*,administrators,owner_check_app_id,classic=None):
    p=policy(); failures=[]
    if repository.get('full_name')!=p['repository'] or not isinstance(administrators,list) or type(owner_check_app_id) is not int or owner_check_app_id<=0:
        return dict(status='UNAVAILABLE',failures=['complete owner policy visibility required'],auto_merge=False)
    permissions=repository.get('permissions')
    if not isinstance(permissions,dict) or any(type(permissions.get(k)) is not bool for k in ('admin','maintain','push','pull')):
        return dict(status='UNAVAILABLE',failures=['complete operational permissions required'],auto_merge=False)
    if classic is not None:
        review=classic.get('required_pull_request_reviews') or {}
        if review.get('required_approving_review_count',0)>0 or review.get('require_last_push_approval'):failures.append('classic protection still requires a second account')
    owner=dict(id=p['owner_id'],login=p['owner_login'])
    actual_owner=repository.get('owner') or {}
    if actual_owner.get('id')!=owner['id'] or actual_owner.get('login')!=owner['login'] or actual_owner.get('type')!='User':failures.append('personal repository owner identity mismatch')
    if administrators!=[owner]: failures.append('owner must be sole repository administrator')
    if identity.get('id')==owner['id'] or identity.get('login')==owner['login'] or repository.get('permissions',{}).get('admin') or repository.get('permissions',{}).get('maintain'): failures.append('operational agent identity must be separate and non-administrative')
    ids={r.get('ruleset_id') for r in active_rules}
    relevant=[r for r in rulesets if r.get('enforcement')=='active' and r.get('id') in ids]
    if ids!={r.get('id') for r in relevant}:return dict(status='UNAVAILABLE',failures=['incomplete ruleset inventory'],auto_merge=False)
    baseline=[]; owner_only=False
    for r in relevant:
        if 'bypass_actors' not in r:return dict(status='UNAVAILABLE',failures=['bypass inventory unavailable'],auto_merge=False)
        bypass=r['bypass_actors']
        if not bypass:baseline.extend(r['rules'])
        elif bypass==[dict(actor_id=5,actor_type='RepositoryRole',bypass_mode='pull_request')] and {x['type'] for x in r['rules']}=={'update'}:owner_only=True
        else:failures.append('unreviewed ruleset bypass authority')
    kinds={r['type'] for r in baseline}
    required={'pull_request','required_status_checks','deletion','non_fast_forward'}
    if not required<=kinds:failures.append('missing non-bypass baseline controls')
    checks=set();owner_check=False;strict=False;pr_ok=False
    for r in baseline:
        params=r.get('parameters') or {}
        if r['type']=='required_status_checks':
            checks|={c['context'] for c in params.get('required_status_checks',[])}
            strict|=params.get('strict_required_status_checks_policy') is True and not params.get('do_not_enforce_on_create',False)
            owner_check|=any(c.get('context')=='owner-review' and c.get('integration_id')==owner_check_app_id for c in params.get('required_status_checks',[]))
        if r['type']=='pull_request':
            if params.get('required_approving_review_count',0)>0 or params.get('require_last_push_approval'):failures.append('second-account requirement remains')
            pr_ok|=params.get('required_approving_review_count')==0 and not params.get('require_last_push_approval',False) and params.get('required_review_thread_resolution') is True
    if not pr_ok:failures.append('solo-owner PR/conversation policy missing or second-account requirement present')
    if not strict or 'test' not in checks or not owner_check:failures.append('strict exact-head test and trusted owner-review checks required')
    if not owner_only:failures.append('owner-only pull-request update restriction missing')
    return dict(status='FAIL' if failures else 'PASS',failures=failures,effective={k:not failures for k in ('pr','checks','review','stale','last_push','conversation','no_force','no_delete','admin')},model='solo-owner-1',identity=identity.get('login'),owner=owner,auto_merge=False,required_human_merge=True,required_checks=sorted(checks),agent_capabilities={k:False if not failures else 'UNVERIFIED' for k in ('direct_push','merge','manage_rulesets','self_approve','bypass_review','bypass_checks','force_push','delete_ref','bypass_conversations')})
