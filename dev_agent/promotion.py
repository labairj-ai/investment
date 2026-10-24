"""Owner-reviewable promotion recommendation; does not enable any authority."""
from .qualification import evaluate as qualifying_evidence


def report(root,store,now=None,*,protections=None,technical=None):
    evidence=qualifying_evidence(root,store,now,protections=protections,technical=technical)
    blockers=list(evidence['blockers'])
    if evidence['safety_configuration'].get('autonomous_implementation') is not False:
        blockers.append('promotion preparation requires autonomy disabled')
    reason=('emergency stop is active' if any('stop' in b for b in blockers) else 'validation is unavailable' if any('oracle' in b or 'certificate' in b for b in blockers) else 'discovery acceptance is incomplete' if any('scheduler' in b for b in blockers) else 'safe release evidence is still accumulating')
    owner_status='LOW-RISK AUTO-PR: NOT READY — '+reason if blockers else 'LOW-RISK AUTO-PR: READY'
    return dict(evidence,owner_status=owner_status,version='software-promotion-report-1',recommendation='NO-GO' if blockers else 'GO_FOR_OWNER_STAGE_REVIEW',recommended_stage='SHADOW' if blockers else 'BUILD_ONLY',blockers=blockers,enables_autonomy=False,grants_merge=False,grants_deployment=False,investment_performance_used=False)
