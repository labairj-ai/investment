"""Advisor adapter over the existing deterministic vetoes and Critic model."""
import json
from .context import ReadView
from trade_engine.market_calendar import is_market_open
from time_utils import parse_timestamp
from agents.critic_review import CriticReviewInput


def review(proposal, context, conn, *, llm=None, allow_llm=True):
    from agents.critic_agent import _deterministic_veto, _llm_critique
    captured=parse_timestamp(context['captured_at'])
    inputs=dict(prices=context['prices'],avg_costs={},price_days={t:h.get('as_of') for t,h in context['holdings'].items()},
                today=context['as_of'],market_hours=is_market_open(captured),_conn=ReadView(conn))
    results=[]
    for leg in proposal.impact['legs']:
        if leg['side']=='NO_CHANGE': continue
        rec=CriticReviewInput(origin='advisor',ticker=leg['ticker'],action=leg['side'],
                 decision_kind='ALLOCATION_CHANGE',trade_impact=proposal.impact,
                 thesis=context['theses'].get(leg['ticker']),context_hash=proposal.context_hash,
                 layer_before=context.get('layer_weights',{}),
                 layer_after=proposal.impact.get('layer_weights_after',{})).to_dict()
        rec.update(why_now='Advisor-originated reference-price preview, not an execution instruction.',
                 rationale=json.dumps({'trade':leg,'thesis':context['theses'].get(leg['ticker']),
                                       'context_hash':proposal.context_hash},sort_keys=True),
                 action_payload_json=json.dumps(leg))
        try:
            veto,reason=_deterministic_veto(rec,context=inputs)
            if veto:
                results.append(dict(ticker=leg['ticker'],verdict='VETO',strongest_objection=reason,deterministic_veto=True,confidence_adjustment=-20))
                continue
            result=(llm or _llm_critique)(rec) if allow_llm else None
            if not isinstance(result,dict) or result.get('verdict') not in {'APPROVE','APPROVE_WITH_CAUTION','CHALLENGE','VETO'}:
                raise ValueError('CRITIC_UNAVAILABLE')
            adjustment=result.get('confidence_adjustment',0)
            if not isinstance(adjustment,int) or isinstance(adjustment,bool): raise ValueError('INVALID_CRITIC_ADJUSTMENT')
            results.append(dict(result,ticker=leg['ticker'],deterministic_veto=False,confidence_adjustment=max(-20,min(5,adjustment))))
        except Exception:
            results.append(dict(ticker=leg['ticker'],verdict='UNKNOWN',status='CRITIC_UNAVAILABLE',deterministic_veto=False))
    order={'VETO':4,'UNKNOWN':3,'CHALLENGE':2,'APPROVE_WITH_CAUTION':1,'APPROVE':0}
    verdict=max((r['verdict'] for r in results),key=lambda v:order[v],default='UNKNOWN')
    return dict(verdict=verdict,reviews=results,origin='advisor',learning_eligible=False)
