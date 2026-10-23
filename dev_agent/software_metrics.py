"""Read-only software delivery metrics; no investment outcomes or P&L inputs."""
from __future__ import annotations
import statistics


def summary(store):
    candidates=store.list(100);reviewed=0;rejected=0;iterations=[];first_pass=[];rollbacks=0;deployed=0;post_errors=0;signal_to_pr=[];pr_to_deploy=[];acceptance=[];recurrences=0;ready=0
    for c in candidates:
        events=c['events'];prs=[e for e in events if e['kind']=='PR'];deploys=[e for e in events if e['kind']=='DEPLOYMENT'];runs=[e['payload'] for e in events if e['kind']=='RUN' and e['payload'].get('role')=='reviewer']
        if prs:ready+=1;signal_to_pr.append(max(0,prs[0]['created']-c['created']))
        reviewed+=len(runs);rejected+=sum(r.get('status') in {'FAIL','NEEDS_HUMAN'} for r in runs)
        loops=[e['payload'].get('iteration',0) for e in events if e['kind']=='ITERATION']
        if loops:iterations.append(max(loops))
        batches=[e['payload'] for e in events if e['kind']=='VALIDATION_BATCH']
        if batches:
            rows=[e['payload'] for e in events if e['kind']=='VALIDATION' and e['payload'].get('batch')==batches[0]['batch']]
            if rows:first_pass.append(all(r.get('status')=='PASS' for r in rows))
        if deploys:
            deployed+=1;rollbacks+=deploys[-1]['payload'].get('status')=='ROLLED_BACK';post_errors+=deploys[-1]['payload'].get('status') in {'DEGRADED','ROLLED_BACK'} or any(e['kind']=='AUTONOMY_PAUSE' and e['payload'].get('reason')=='signed deployment outcome abnormal' for e in events)
            if prs:pr_to_deploy.append(max(0,deploys[0]['created']-prs[0]['created']))
        observations=[e['payload'] for e in events if e['kind']=='SIGNAL_OBSERVATION']
        if observations:recurrences+=max(0,max(e.get('recurrence',1) for e in observations)-1)
        for e in events:
            if e['kind']=='EFFECTIVENESS':
                value=e['payload'].get('dimensions',{}).get('user_acceptance')
                if isinstance(value,(int,float)) and 0<=value<=1:acceptance.append(value)
    owner={}
    for e in reversed(store.events('OWNER_REVIEW')):
        p=e['payload'];context=p['context'];owner[(context['repository'],context['pr'],context['head'])]=p['decision']
    ratio=lambda n,d:round(n/d,4) if d else None
    mean=lambda rows:round(statistics.mean(rows),3) if rows else None
    return dict(window_candidates=len(candidates),candidate_pr_rate=ratio(ready,len(candidates)),reviewer_rejection_rate=ratio(rejected,reviewed),average_iterations=mean(iterations),ci_first_pass_rate=mean(first_pass),owner_approval_rate=ratio(sum(d=='APPROVE' for d in owner.values()),len(owner)),rollback_rate=ratio(rollbacks,deployed),post_deployment_error_candidates=post_errors,observed_recurrences=recurrences,user_acceptance=mean(acceptance),signal_to_pr_seconds=mean(signal_to_pr),pr_to_deployment_seconds=mean(pr_to_deploy),investment_performance_used=False,authority_effect='NONE')
