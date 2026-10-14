#!/usr/bin/env python3
"""Deterministic, non-persisted functional and mutation-safety production canary."""
import argparse
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.advisor.context import build_advisor_decision_context
from agents.advisor.contracts import ADVISOR_CONTRACT_VERSION, canonical, finite
from agents.advisor.service import run_decision
from agents.advisor import policy as decision_policy, request_parser
from agents.advisor.sqlite_guard import GuardedConnection, read_only
from time_utils import parse_timestamp

CANARY_CONTRACT = 'advisor-canary-v2'
STATES = {'ACTIONABLE','REVIEW_REQUIRED','RESEARCH_ONLY','BLOCKED'}


def protected_state(conn):
    """Counts AND canonical contents of every table (including learning/account state)."""
    schema=conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    result={'schema_hash':hashlib.sha256(canonical([list(r) for r in schema]).encode()).hexdigest(),'tables':{}}
    for name, in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted='"'+name.replace('"','""')+'"'
        values=[]
        for row in conn.execute('SELECT * FROM '+quoted):
            values.append(canonical([{'blob_hex':v.hex()} if isinstance(v,bytes) else v for v in row]))
        # Table content identity is independent of implicit retrieval order.
        values.sort()
        result['tables'][name]={'count':len(values),'hash':hashlib.sha256(canonical(values).encode()).hexdigest()}
    return result


def select_scenario(context):
    for ticker, holding in sorted(context.get('holdings',{}).items()):
        shares=holding.get('shares');price=context.get('prices',{}).get(ticker)
        if not finite(shares) or shares<0 or not finite(price) or price<=0: continue
        current=Decimal(str(shares))
        # Fractional holdings are preserved, never truncated: target is a whole
        # share above current; the equivalent explicit delta may be fractional.
        target=current.to_integral_value(rounding=ROUND_FLOOR)+17
        delta=target-current
        if not finite(float(target)) or not finite(float(delta)) or delta<=0: continue
        return {'ticker':ticker,'captured_shares':float(current),'reference_price':price,
                'target_shares':float(target),'expected_delta':float(delta),
                'target_request':f'Get {ticker} to {target:f} shares',
                'delta_request':f'Buy {delta:f} {ticker}',
                'fractional_shares_policy':'Preserve captured fraction; whole-share target, exact fractional delta.'}
    return None


def validate_result(result, scenario, kind, captured_context):
    failures=[]
    def check(name, ok):
        if not ok: failures.append(kind+':'+name)
    check('STRUCTURED_RESULT',isinstance(result,dict))
    if not isinstance(result,dict): return failures,None
    check('CONTRACT_VERSION',result.get('contract_version')==ADVISOR_CONTRACT_VERSION)
    check('EXECUTION_DISABLED',result.get('execution_ready') is False)
    check('CANARY_ORIGIN',result.get('origin')=='canary_preview')
    check('LEARNING_DISABLED',result.get('learning_eligible') is False)
    for field in ('request','policy','impact','critic','risk_preview','context'):
        check('STRUCTURED_'+field.upper(),isinstance(result.get(field),dict))
    request=result.get('request') or {}; impact=result.get('impact') or {}
    policy=result.get('policy') or {}; context=result.get('context') or {}
    check('POLICY_STATE',policy.get('decision_state') in STATES)
    check('POLICY_EXECUTION_DISABLED',policy.get('execution_ready') is False)
    check('CONTEXT_IDENTITY',all(isinstance(context.get(k),str) and len(context[k])==64 for k in ('context_hash','authorization_hash','risk_state_hash')))
    check('CAPTURED_CONTEXT_IDENTITY',context.get('authorization_hash')==captured_context.get('authorization_hash'))
    semantics='TARGET_POSITION' if kind=='target' else 'TRADE_DELTA'
    check('REQUEST_INTENT',request.get('intent')==semantics and request.get('needs_clarification') is False)
    legs=request.get('legs')
    check('REQUEST_LEG',isinstance(legs,list) and len(legs)==1)
    if isinstance(legs,list) and len(legs)==1 and isinstance(legs[0],dict):
        leg=legs[0]
        expected_quantity=scenario['target_shares'] if kind=='target' else scenario['expected_delta']
        check('QUANTITY_SEMANTICS',leg.get('semantics')==semantics and leg.get('ticker')==scenario['ticker'])
        check('REQUEST_QUANTITY',finite(leg.get('quantity')) and math.isclose(leg['quantity'],expected_quantity,rel_tol=0,abs_tol=1e-8))
    check('VALID_IMPACT',impact.get('valid') is True)
    trade_legs=impact.get('legs')
    check('TRADE_LEG',isinstance(trade_legs,list) and len(trade_legs)==1)
    observed=None
    if isinstance(trade_legs,list) and len(trade_legs)==1 and isinstance(trade_legs[0],dict):
        leg=trade_legs[0];observed=leg.get('delta_shares')
        check('TRADE_TICKER',leg.get('ticker')==scenario['ticker'])
        check('TRADE_SIDE',leg.get('side')=='BUY')
        check('EXPECTED_DELTA',finite(observed) and math.isclose(observed,scenario['expected_delta'],rel_tol=0,abs_tol=1e-8))
        check('CAPTURED_SHARES',leg.get('before_shares')==scenario['captured_shares'])
        check('TARGET_SHARES',finite(leg.get('after_shares')) and math.isclose(leg['after_shares'],scenario['target_shares'],rel_tol=0,abs_tol=1e-8))
    # UNKNOWN Critic is expected with models disabled. Risk may be unavailable
    # when no matching account was explicitly selected; neither grants approval.
    risk=result.get('risk_preview') or {};critic=result.get('critic') or {}
    check('CRITIC_CONTRACT',critic.get('verdict') in {'APPROVE','APPROVE_WITH_CAUTION','CHALLENGE','VETO','UNKNOWN'} and isinstance(critic.get('reviews'),list))
    check('RISK_CONTRACT',risk.get('decision') in {'UNKNOWN','REJECTED','PREVIEW_PASS'} and risk.get('preview_only') is True and risk.get('execution_ready') is False)
    # Reuse governance, never duplicate its economic rules. A valid-state label
    # alone is insufficient if it no longer follows the captured evidence.
    if all(isinstance(result.get(k),dict) for k in ('impact','critic','risk_preview','tax_lots')):
        expected=decision_policy.evaluate(
            request_parser.parse_request(scenario[kind+'_request'],captured_context,use_llm=False),
            impact,result['tax_lots'],critic,risk,captured_context)
        check('POLICY_EVIDENCE_CONSISTENCY',policy==expected)
    def unauthorized(value):
        if isinstance(value,dict):
            return any((k in {'execution_ready','execution_authorized'} and v is True) or unauthorized(v) for k,v in value.items())
        return isinstance(value,list) and any(unauthorized(v) for v in value)
    check('NO_EXECUTION_AUTHORIZATION',not unauthorized(result))
    return failures,observed


def run_canary(conn):
    if not isinstance(conn,GuardedConnection):
        # The canary must record denied attempts even if a helper catches them.
        # Unknown callbacks on a plain connection cannot be safely replaced.
        return dict(canary_contract=CANARY_CONTRACT,health='FAIL',mutation_safety='FAIL',
                    functional_contract='FAIL',read_only=True,network_free=True,
                    production_state_unchanged=True,execution_ready=False,
                    failed_invariants=['GUARDED_CONNECTION_REQUIRED'],outcomes=[],selected_scenario=None)
    denied=[];failures=[];outcomes=[];scenario=None;context={}
    owns_snapshot=not conn.in_transaction
    if owns_snapshot: conn.execute('BEGIN')
    try:
        with read_only(conn,denied=denied):
            before=protected_state(conn);changes=conn.total_changes
            try:
                context=build_advisor_decision_context(conn)
                scenario=select_scenario(context)
                if scenario is None: failures.append('NO_VALID_HOLDING_AND_MARK')
                else:
                    for kind in ('target','delta'):
                        try:
                            result=run_decision(conn,scenario[kind+'_request'],persist=False,allow_llm=False,
                                                now=parse_timestamp(context['captured_at']))
                            violations,observed=validate_result(result,scenario,kind,context)
                            failures.extend(violations)
                            outcomes.append({'scenario':kind,'request':scenario[kind+'_request'],
                                'contract_version':result.get('contract_version') if isinstance(result,dict) else None,
                                'execution_ready':result.get('execution_ready') if isinstance(result,dict) else None,
                                'intent':result.get('request',{}).get('intent') if isinstance(result,dict) else None,
                                'state':result.get('policy',{}).get('decision_state') if isinstance(result,dict) else None,
                                'reasons':result.get('policy',{}).get('reasons',[]) if isinstance(result,dict) else [],
                                'observed_delta':observed,'failed_invariants':violations})
                        except Exception as error:
                            failures.append(kind+':PIPELINE_EXCEPTION')
                            if isinstance(error,sqlite3.DatabaseError) and ('readonly' in str(error).lower() or 'not authorized' in str(error).lower()):
                                denied.append({'error':'SQLITE_WRITE_DENIED'})
                            outcomes.append({'scenario':kind,'exception':type(error).__name__})
                    if len(outcomes)!=2 or any(not finite(o.get('observed_delta')) for o in outcomes) or outcomes[0].get('observed_delta')!=outcomes[1].get('observed_delta'):
                        failures.append('TARGET_DELTA_EQUIVALENCE')
            except Exception as error:
                failures.append('CONTEXT_EXCEPTION:'+type(error).__name__)
                if isinstance(error,sqlite3.DatabaseError) and ('readonly' in str(error).lower() or 'not authorized' in str(error).lower()):
                    denied.append({'error':'SQLITE_WRITE_DENIED'})
            after=protected_state(conn)
            unchanged=before==after and changes==conn.total_changes
            mutation='PASS' if unchanged and not denied else 'FAIL'
            functional='PASS' if not failures else 'FAIL'
            return dict(canary_contract=CANARY_CONTRACT,health='PASS' if mutation==functional=='PASS' else 'FAIL',
                mutation_safety=mutation,functional_contract=functional,read_only=True,network_free=True,
                execution_ready=False,captured_at=context.get('captured_at'),
                production_state_unchanged=unchanged,denied_mutations=denied,
                failed_invariants=sorted(set(failures+(['MUTATION_ATTEMPT_DENIED'] if denied else [])+(['PROTECTED_STATE_CHANGED'] if not unchanged else []))),
                protected_state_before=before,protected_state_after=after,
                context_hash=context.get('context_hash'),source_health=context.get('portfolio_state',{}).get('brief_health','UNAVAILABLE'),
                expected_unavailability=['Critic LLM disabled','Risk account not selected; account alignment remains unavailable'],
                selected_scenario=scenario,outcomes=outcomes)
    except Exception as error:
        return dict(canary_contract=CANARY_CONTRACT,health='FAIL',mutation_safety='FAIL',
                    functional_contract='FAIL',read_only=True,network_free=True,
                    production_state_unchanged=None,execution_ready=False,
                    denied_mutations=denied,failed_invariants=['CANARY_STATE_UNAVAILABLE:'+type(error).__name__],
                    selected_scenario=scenario,outcomes=outcomes)
    finally:
        if owns_snapshot: conn.rollback()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=Path(__file__).resolve().parents[1]/'out'/'investment.db')
    args=parser.parse_args()
    conn=sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True,factory=GuardedConnection)
    conn.row_factory=sqlite3.Row
    try: result=run_canary(conn)
    finally: conn.close()
    print(json.dumps(result,sort_keys=True,indent=2))
    return 0 if result['health']=='PASS' else 1


if __name__=='__main__': raise SystemExit(main())
