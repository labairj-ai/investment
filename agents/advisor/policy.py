"""Only deterministic evidence can establish advisor decision state."""
from .contracts import ADVISOR_POLICY_VERSION


def evaluate(request,impact,tax,critic,risk,context):
    blocked=[]; review=[]; research=[]
    if request.needs_clarification:
        review.extend(request.issues)
    elif not impact['valid']:
        blocked.extend(impact['errors'])
    if request.intent=='RESEARCH': research.append('RESEARCH_REQUEST')
    for name,source in context.get('sources',{}).items():
        if source.get('authority')!='REQUIRED': continue
        if source.get('status')=='ERROR': blocked.append('REQUIRED_SOURCE_ERROR:'+name)
        elif source.get('status') not in {'AVAILABLE','CURRENT','HEALTHY'}: review.append('REQUIRED_SOURCE_NOT_CURRENT:'+name)
    brief=context.get('portfolio_state',{})
    if not brief or brief.get('error'): blocked.append('CANONICAL_BRIEF_UNAVAILABLE')
    if brief.get('thesis_status')=='ERROR': blocked.append('THESIS_SOURCE_ERROR')
    if brief.get('execution_state',{}).get('status')=='ERROR': blocked.append('EXECUTION_SOURCE_ERROR')
    active={c['ticker'] for c in context.get('candidates') or [] if c.get('status') in {'active','watch'}}
    for leg in impact['legs']:
        price_state=context.get('price_freshness',{}).get(leg['ticker'],{}).get('status','UNKNOWN')
        if price_state!='CURRENT': review.append('REFERENCE_PRICE_NOT_CURRENT:'+leg['ticker'])
        thesis=context.get('theses',{}).get(leg['ticker'])
        if thesis and (thesis.get('status')=='VETOED' or (thesis.get('has_critical_violation') and leg['side']=='BUY')):
            blocked.append('THESIS_VETO:'+leg['ticker'])
        if leg['side']=='BUY':
            if leg['ticker'] not in context['holdings'] and leg['ticker'] not in active:
                research.append('OUTSIDE_CANDIDATE_UNIVERSE:'+leg['ticker'])
            if leg['ticker'] not in context['holdings'] and not any(r['ticker']==leg['ticker'] and r.get('evidence_status')=='AVAILABLE' for r in context.get('candidate_ranks',[])):
                research.append('CANDIDATE_EVIDENCE_UNAVAILABLE:'+leg['ticker'])
            if not thesis or thesis.get('status')!='ACTIVE' or not thesis.get('approved_at'):
                research.append('APPROVED_THESIS_REQUIRED:'+leg['ticker'])
        if leg['side']=='SELL' and (not tax.get(leg['ticker']) or not all(r.get('valid') for r in tax[leg['ticker']].values())):
            review.append('EXACT_TAX_LOTS_UNAVAILABLE:'+leg['ticker'])
    if critic.get('verdict')=='VETO': blocked.append('CRITIC_VETO')
    elif critic.get('verdict') not in {'APPROVE','APPROVE_WITH_CAUTION'}: review.append('CRITIC_REVIEW_REQUIRED')
    if risk.get('decision')=='REJECTED': blocked.append('RISK_REJECTED')
    elif risk.get('decision')!='PREVIEW_PASS': review.append('RISK_PREVIEW_REQUIRED')
    state='BLOCKED' if blocked else 'RESEARCH_ONLY' if research else 'REVIEW_REQUIRED' if review else 'ACTIONABLE'
    return dict(decision_state=state,reasons=sorted(set(blocked+research+review)),policy_version=ADVISOR_POLICY_VERSION,
                execution_ready=False,meaning='Decision-grade for user review; never automatic execution approval.')
