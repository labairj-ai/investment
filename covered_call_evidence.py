"""Strict matched prospective pairs, typed outcome migration and config lineage."""
from __future__ import annotations
import json
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from time_utils import now_utc, parse_timestamp, TZ_EASTERN
from covered_call_outcomes import base, contract, digest, persist, latest, validate, OutcomeSource

ROOT=Path(__file__).resolve().parent


def committed_policy(sha,config):
    from covered_call_ledger import config_digest
    result=subprocess.run(['git','show',sha+':config/strategy.json'],cwd=ROOT,capture_output=True,text=True)
    if result.returncode:return False
    stored=json.loads(result.stdout).get('covered_call_v3',{})
    return config_digest(stored)==config_digest(config)


def create_decision_contract(db,episode,rows,config,prospective,qa_only=False,recorded_at=None):
    from covered_call_virtual import SIMULATOR_VERSION, management_contract
    decision=db.execute('SELECT * FROM cc_decisions WHERE id=?',(episode,)).fetchone()
    recorded=recorded_at or now_utc()
    delay=(recorded-parse_timestamp(decision['timestamp'])).total_seconds()
    forward=bool(prospective and 0<=delay<=config.get('virtual',{}).get('creation_grace_seconds',300))
    snapshot_inputs=[{k:r.get(k) for k in ('contract_symbol','strike','expiration','spot','bid','ask','impliedVolatility','quote_timestamp','risk_events')} for r in rows]
    payload=dict(market_snapshot_lineage=digest(snapshot_inputs),recorded_at=recorded.isoformat(),
        forward_created=forward,qa_only=qa_only,promotion_policy_version=config['promotion']['version'],
        simulator_version=SIMULATOR_VERSION,policy_committed=committed_policy(decision['git_sha'],config),
        management_contract=management_contract(),legacy=False,
        origin_holding_shares=next((r.get('origin_holding_shares') for r in rows if r.get('origin_holding_shares') is not None),None))
    db.execute('INSERT INTO cc_decision_contracts VALUES(?,?)',(episode,json.dumps(payload,sort_keys=True)))
    return payload


CHAIN_FIELDS=('total_option_pnl','cc_incremental_alpha','realized_management_cost','realized_execution_cost',
              'rolled','assigned','btc','roll_hops','roll_net_credit','total_fees','assignment_policy_violation',
              'cc_strategy_return','chain_hold_return','measured_cost_evidence')


def classify_label(db,episode,candidate,labels,source):
    """Append explicit classifications with supporting execution IDs, never infer P&L."""
    from covered_call_ledger import reconcile_chain
    decision=db.execute('SELECT * FROM cc_decisions WHERE id=?',(episode,)).fetchone()
    metadata=contract(db,episode)
    lineage=metadata['market_snapshot_lineage'] if metadata else digest([episode,'legacy-unverified'])
    path=base(episode,'MARKET_PATH_ONLY',decision['timestamp'],now_utc().isoformat(),lineage,source)
    path.update({k:v for k,v in labels.items() if k not in CHAIN_FIELDS and not k.startswith('estimated_')})
    path.update(execution_source='NONE',management_source='NONE',price_path_source=labels.get('path_source','OBSERVED_DAILY_OHLC'),
        cost_source='NONE',market_data_coverage_verified=bool(labels.get('path_coverage_verified')),
        complete=bool(labels.get('path_complete')),censored=not bool(labels.get('path_complete')),
        prospective=bool(decision['prospective']),chain_identifier=None)
    # Keep original provenance's authoritative fields after legacy label overlays.
    path.update(outcome_source='MARKET_PATH_ONLY',origin_episode=episode,units='USD_PER_SHARE')
    persist(db,episode,candidate,'path',path)
    estimated={k:v for k,v in labels.items() if k.startswith('estimated_')}
    if estimated:
        estimate=base(episode,'ESTIMATED_COUNTERFACTUAL',decision['timestamp'],now_utc().isoformat(),lineage,source)
        estimate.update(estimated,complete=bool(labels.get('path_complete')),censored=not bool(labels.get('path_complete')),
                        price_path_source='OBSERVED_DAILY_OHLC',execution_source='FORMULA_ONLY',management_source='NONE',cost_source='NONE')
        persist(db,episode,candidate,'estimate',estimate)
    if candidate!=_selected_id(db,episode,'selected_v2'):return
    chain,chain_id=reconcile_chain(db,episode)
    execution_ids=[x['execution_id'] for x in (chain or []) if x.get('actual') and x.get('execution_id')]
    if not execution_ids or not chain_id:return
    actual=base(episode,'ACTUAL_EXECUTION',decision['timestamp'],now_utc().isoformat(),lineage,dict(labels=labels,chain=chain,source=source))
    actual.update(labels,execution_ids=execution_ids,execution_reconciled=not labels.get('chain_censored',True),
        execution_source='RECONCILED_MANUAL_OR_BROKER',management_source='ACTUAL_TRADE_CHAIN',price_path_source='OBSERVED_DAILY_OHLC',
        cost_source='RECONCILED_OBSERVATION' if labels.get('measured_cost_evidence') else 'UNAVAILABLE',
        economic_share_basis='COVERED_SHARES',
        origin_holding_shares=metadata.get('origin_holding_shares') if metadata else None,
        covered_shares=sum(float(x.get('contracts') or 0)*100 for x in (chain or []) if x['action'] in ('SELL_CC','SELL_TO_OPEN') and x.get('recommendation_action','SELL_CC')=='SELL_CC'),
        prospective=bool(decision['prospective']),chain_identifier=chain_id,market_data_coverage_verified=bool(labels.get('path_coverage_verified')),
        complete=not labels.get('chain_censored',True) and not labels.get('censored',True) and all(labels.get(k) is not None for k in ('cc_incremental_alpha','realized_management_cost','realized_execution_cost','assignment_policy_violation')),
        censored=labels.get('chain_censored',True) or labels.get('censored',True),
        outcome_source='ACTUAL_EXECUTION',origin_episode=episode,units='USD_PER_SHARE',broker_reconciled=False,
        comparison_horizon=labels.get('chain_return_horizon') or (chain[-1]['execution_date'][:10] if chain else None))
    if actual['execution_reconciled']:persist(db,episode,candidate,'champion',actual)


def _selected_id(db,episode,field):
    row=db.execute(f'SELECT candidate_id FROM cc_candidates WHERE episode_id=? AND {field}=1',(episode,)).fetchone()
    return row[0] if row else None


def migrate_legacy(db):
    """Classifications are new rows; old decisions, features and labels never change."""
    count=0
    for decision in db.execute('SELECT * FROM cc_decisions').fetchall():
        episode=decision['id']
        if contract(db,episode) is None:
            metadata=dict(legacy=True,forward_created=False,policy_committed=False,qa_only=False,
                          market_snapshot_lineage=digest([episode,'legacy-unverified']),simulator_version=None,promotion_policy_version=None)
            db.execute('INSERT INTO cc_decision_contracts VALUES(?,?)',(episode,json.dumps(metadata,sort_keys=True)))
        for row in db.execute('''SELECT candidate_id,labels_json FROM cc_labels l WHERE episode_id=?
            AND id=(SELECT max(id) FROM cc_labels WHERE episode_id=l.episode_id AND candidate_id=l.candidate_id)''',(episode,)).fetchall():
            if latest(db,episode,'path',row['candidate_id']) is None:
                classify_label(db,episode,row['candidate_id'],json.loads(row['labels_json']),dict(legacy_label=row['labels_json']))
                count+=1
    return dict(classified_labels=count)


def no_call(decision,horizon):
    return dict(outcome_source='NO_CALL',cc_incremental_alpha=0.,rolled=False,roll_hops=0,
                realized_management_cost=0.,realized_execution_cost=0.,assignment_policy_violation=False,
                complete=True,censored=False,market_data_coverage_verified=True,comparison_horizon=horizon)


def pair_outcomes(db,decision,metadata,as_of):
    champion=json.loads(decision['champion_json']);challenger=json.loads(decision['challenger_json'])
    a=latest(db,decision['id'],'champion') if champion['action']=='SELL_CC' else None
    b=latest(db,decision['id'],'challenger') if challenger['action']=='SELL_CC' else None
    # A hold baseline compares on the executed/virtual arm's terminal horizon.
    terminal=[x['source_timestamp_end'] for x in (a,b) if x and x.get('complete')]
    horizon=max(terminal,key=parse_timestamp) if terminal else decision['timestamp']
    if champion['action']=='NO_CALL':a=no_call(champion,horizon)
    if challenger['action']=='NO_CALL':b=no_call(challenger,horizon)
    for name,value,expected in (('CHAMPION',a,'ACTUAL_EXECUTION'),('CHALLENGER',b,'PROSPECTIVE_VIRTUAL')):
        if value is None:return None,'MISSING_'+name+'_OUTCOME'
        if value['outcome_source']=='NO_CALL':continue
        try:validate(value)
        except (ValueError,KeyError):return None,'INVALID_'+name+'_PROVENANCE'
        if value['outcome_source']!=expected:return None,'WRONG_'+name+'_SOURCE'
        if not value.get('complete') or value.get('censored') or value.get('chain_censored') or value.get('data_quality_unresolved'):
            return None,'CENSORED_'+name
        if not value.get('market_data_coverage_verified'):return None,'UNVERIFIED_'+name+'_COVERAGE'
        if value.get('market_snapshot_lineage')!=metadata['market_snapshot_lineage']:return None,'SNAPSHOT_LINEAGE_MISMATCH'
        if parse_timestamp(value['source_timestamp_end'])>as_of:return None,'FUTURE_'+name+'_OUTCOME'
        if name=='CHALLENGER' and (value.get('simulator_version')!=metadata['simulator_version'] or value.get('config_hash')!=decision['config_hash'] or not value.get('prospective')):
            return None,'CHALLENGER_VERSION_MISMATCH'
        required=('cc_incremental_alpha','realized_management_cost','realized_execution_cost','assignment_policy_violation','rolled','roll_hops')
        if any(value.get(k) is None for k in required):return None,'INCOMPLETE_'+name+'_ECONOMICS'
        original=metadata.get('origin_holding_shares')
        if not original or not value.get('covered_shares') or value.get('covered_shares')>original or value.get('origin_holding_shares')!=original or value.get('economic_share_basis')!='COVERED_SHARES':
            return None,'UNKNOWN_'+name+'_SHARE_BASIS'

    # Different terminal dates require a separately reconciled common-horizon
    # valuation. Do not compare different holding periods silently.
    if a['outcome_source']!='NO_CALL' and b['outcome_source']!='NO_CALL':
        if a['source_timestamp_end'][:10]!=b['source_timestamp_end'][:10]:
            if not (a.get('comparison_horizon')==b.get('comparison_horizon') and a.get('comparison_horizon')):
                return None,'COMPARISON_HORIZON_MISMATCH'
    normalized=[]
    for value in (a,b):
        item=dict(value)
        if value['outcome_source']!='NO_CALL':
            factor=value['covered_shares']/value['origin_holding_shares']
            for key in ('cc_incremental_alpha','realized_management_cost','realized_execution_cost'):item[key]=value[key]*factor
        item['economic_share_basis']='ORIGIN_HOLDING_SHARES';normalized.append(item)
    return tuple(normalized),None


def promotion_report(config,path=None,as_of=None):
    from covered_call_ledger import connect,migrate,config_digest,calibration
    from covered_call_virtual import SIMULATOR_VERSION
    from covered_call_v3 import VERSION
    from covered_call_validation import certification
    db=connect(path);migrate(db)
    current_hash=config_digest(config);gate=config['promotion'];as_of=as_of or now_utc()
    certificate=certification(config,path)
    pairs=[];excluded=Counter();composition=Counter();seen=set();details=[]
    decisions=db.execute('SELECT * FROM cc_decisions ORDER BY timestamp,id').fetchall()
    for decision in decisions:
        meta=contract(db,decision['id']);reason=None
        session_key=(decision['ticker'],parse_timestamp(decision['timestamp']).astimezone(TZ_EASTERN).date())
        if not decision['prospective'] or not meta or not meta.get('forward_created'):reason='NOT_PROSPECTIVE'
        elif meta.get('qa_only'):reason='QA_ONLY'
        elif decision['config_hash']!=current_hash:reason='CONFIG_MISMATCH'
        elif decision['model_version']!=VERSION:reason='MODEL_MISMATCH'
        elif meta.get('promotion_policy_version')!=gate['version']:reason='PROMOTION_POLICY_MISMATCH'
        elif meta.get('simulator_version')!=SIMULATOR_VERSION:reason='SIMULATOR_MISMATCH'
        elif not meta.get('policy_committed'):reason='POLICY_NOT_PRECOMMITTED'
        elif session_key in seen:reason='DUPLICATE_TICKER_SESSION'
        else:seen.add(session_key)
        outcomes=None
        if reason is None:
            outcomes,reason=pair_outcomes(db,decision,meta,as_of)
        if reason is None and certificate is None:reason='SIMULATOR_UNCERTIFIED'
        if reason:
            excluded[reason]+=1;details.append(dict(episode_id=decision['id'],reason=reason));continue
        a,b=outcomes
        pairs.append((decision,a,b));composition['champion:'+a['outcome_source']]+=1;composition['challenger:'+b['outcome_source']]+=1
    n=len(pairs)
    def mean_delta(key):return sum(b[key]-a[key] for _,a,b in pairs)/n if n else None
    alpha=mean_delta('cc_incremental_alpha');roll=sum(bool(b['rolled'])-bool(a['rolled']) for _,a,b in pairs)/n if n else None
    management=mean_delta('realized_management_cost');execution=mean_delta('realized_execution_cost')
    violations=sum(bool(b['assignment_policy_violation']) for _,_,b in pairs)
    divergent=sum(d['divergence'] not in ('SAME_NO_CALL','SAME_CONTRACT') for d,_,_ in pairs)
    days=(max(parse_timestamp(d['timestamp']).date() for d,_,_ in pairs)-min(parse_timestamp(d['timestamp']).date() for d,_,_ in pairs)).days if n else 0
    samples=[]
    for d,_,_ in pairs:
        cid=_selected_id(db,d['id'],'selected_v3')
        if cid:
            f=db.execute('SELECT features_json FROM cc_candidates WHERE episode_id=? AND candidate_id=?',(d['id'],cid)).fetchone()
            label=db.execute('SELECT labels_json FROM cc_labels WHERE episode_id=? AND candidate_id=? ORDER BY id DESC LIMIT 1',(d['id'],cid)).fetchone()
            if label:samples.append((json.loads(f[0]),json.loads(label[0])))
    cal=calibration(samples,'strike_touch_prob','strike_touched')
    failures=[]
    checks=[(certificate is not None,'SIMULATOR_UNCERTIFIED'),(n>=gate['minimum_n'],'MINIMUM_N'),
        (divergent>=gate['minimum_divergent_n'],'DIVERGENT_N'),(days>=gate['minimum_days'],'PROSPECTIVE_DURATION'),
        (alpha is not None and alpha>gate['minimum_alpha_improvement'],'ALPHA_IMPROVEMENT'),
        (roll is not None and roll<=gate['max_roll_rate_increase'],'ROLL_REGRESSION'),
        (management is not None and management<=gate['max_management_cost_increase'],'MANAGEMENT_COST_REGRESSION'),
        (execution is not None and execution<=gate.get('max_execution_cost_increase',0),'EXECUTION_COST_REGRESSION'),
        (violations<=gate['max_assignment_violations'],'ASSIGNMENT_VIOLATIONS'),
        (cal['n']>=gate['minimum_n'] and cal['brier'] is not None and cal['brier']<=gate['max_brier'],'CALIBRATION')]
    for passed,reason in checks:
        if not passed:failures.append(reason)
    db.close()
    from covered_call_calibration import all_calibration_skills
    return dict(eligible=not failures,failures=failures,n=n,divergent_n=divergent,prospective_days=days,
        alpha_improvement=alpha,roll_rate_delta=roll,management_cost_delta=management,execution_cost_delta=execution,
        assignment_violations=violations,calibration=cal,calibration_skill=all_calibration_skills(samples),
        config_hash=current_hash,gate_version=gate['version'],
        promotion_policy_version=gate['version'],model_version=VERSION,simulator_version=SIMULATOR_VERSION,
        simulator_certification_id=certificate['id'] if certificate else None,cohort_ids=[d['id'] for d,_,_ in pairs],
        source_composition=dict(composition),excluded_n=sum(excluded.values()),exclusions=dict(excluded),exclusion_details=details,
        total_opportunities=len(decisions),units='USD_PER_SHARE',economic_share_basis='ORIGIN_HOLDING_SHARES',independence_policy='FIRST_FORWARD_OPPORTUNITY_PER_TICKER_EASTERN_SESSION')
