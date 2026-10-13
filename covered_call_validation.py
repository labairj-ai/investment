"""As-of simulator replay and immutable out-of-sample acceptance certification."""
from __future__ import annotations
import json
import subprocess
from collections import Counter
from datetime import timedelta
from statistics import mean, median
from pathlib import Path
from time_utils import now_utc_iso, parse_timestamp, TZ_EASTERN
from covered_call_outcomes import digest, latest, validate
from covered_call_virtual import (SIMULATOR_VERSION, SIMULATOR_CONTRACT_VERSION,
    management_contract, evaluate_snapshot, fill_model, simulator_contract_hash)

ROOT=Path(__file__).resolve().parent

# Incremented when classification logic changes — invalidates existing certifications
CADENCE_COMPARABILITY_POLICY_VERSION='cadence-v1'


def current_git_sha():
    return subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()


def _config_contract_hash(config):
    """Hash of the simulator-relevant config subset (cc_v3 section)."""
    from covered_call_virtual import _CONTRACT_CONFIG_KEYS
    cc_cfg = config.get('cc_v3', {})
    subset = {k: cc_cfg.get(k) for k in _CONTRACT_CONFIG_KEYS}
    return digest(subset)


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS cc_simulator_validation_runs (
      id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, simulator_version TEXT NOT NULL,
      config_hash TEXT NOT NULL, git_sha TEXT NOT NULL, run_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_simulator_certifications (
      id TEXT PRIMARY KEY, validation_run_id TEXT NOT NULL REFERENCES cc_simulator_validation_runs(id),
      timestamp TEXT NOT NULL, certificate_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_actual_fill_evidence (
      execution_id INTEGER PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES cc_decisions(id),
      timestamp TEXT NOT NULL, evidence_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_actual_policy_evaluations (
      id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES cc_decisions(id),
      timestamp TEXT NOT NULL, snapshot_id TEXT, evidence_json TEXT NOT NULL);
    ''')
    for table in ('cc_simulator_validation_runs','cc_simulator_certifications','cc_actual_policy_evaluations','cc_actual_fill_evidence'):
        for action in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable simulator certification'); END")


def normalize_action(action):
    return 'HOLD_CALL' if action in ('NO_ACTION','HOLD','HOLD_CALL','ALLOW_ASSIGNMENT') else action


_MARKET_OPEN_HOUR=9
_MARKET_CLOSE_HOUR=16


def _generate_cadence_slots(entry_ts, expiry_date, cadence_minutes):
    """Generate all expected virtual evaluation slots during the option period."""
    from datetime import datetime,date
    slots=[]
    cursor=parse_timestamp(entry_ts).astimezone(TZ_EASTERN)
    expiry_dt=datetime(expiry_date.year,expiry_date.month,expiry_date.day,16,0,tzinfo=TZ_EASTERN)
    step=timedelta(minutes=cadence_minutes)
    while cursor<=expiry_dt:
        if _MARKET_OPEN_HOUR<=cursor.hour<_MARKET_CLOSE_HOUR and cursor.weekday()<5:
            slots.append(cursor)
        cursor+=step
    return slots


def classify_cadence_comparability(actual_timestamps, entry_ts, expiry_date, cadence_minutes, tolerance_minutes=None):
    """Classify actual management observations against expected virtual cadence slots.

    Returns per-slot classification and summary counts for diagnostics.
    Classification values:
      COMPARABLE_DIRECT   — actual observation matches a cadence slot (within tolerance)
      VIRTUAL_ONLY        — cadence slot had no actual observation (→ VIRTUAL_EARLIER_OPPORTUNITY candidate)
      ACTUAL_ONLY         — actual observation has no corresponding cadence slot
    """
    tolerance=timedelta(minutes=tolerance_minutes if tolerance_minutes is not None else cadence_minutes)
    actual_parsed=sorted(parse_timestamp(t).astimezone(TZ_EASTERN) for t in actual_timestamps)
    slots=_generate_cadence_slots(entry_ts,expiry_date,cadence_minutes)
    slot_class=[]
    used_actual=set()
    for slot in slots:
        match=next((i for i,at in enumerate(actual_parsed) if i not in used_actual and abs((at-slot).total_seconds())<=tolerance.total_seconds()),None)
        if match is not None:
            used_actual.add(match);slot_class.append(dict(slot=slot.isoformat(),classification='COMPARABLE_DIRECT',actual_timestamp=actual_parsed[match].isoformat()))
        else:
            slot_class.append(dict(slot=slot.isoformat(),classification='VIRTUAL_ONLY'))
    actual_only=[dict(actual_timestamp=at.isoformat(),classification='ACTUAL_ONLY') for i,at in enumerate(actual_parsed) if i not in used_actual]
    comparable_n=sum(1 for s in slot_class if s['classification']=='COMPARABLE_DIRECT')
    virtual_only_n=sum(1 for s in slot_class if s['classification']=='VIRTUAL_ONLY')
    actual_only_n=len(actual_only)
    return dict(
        cadence_mode='STRICT_MATCHED_CADENCE',
        cadence_comparability_policy_version=CADENCE_COMPARABILITY_POLICY_VERSION,
        expected_cadence_slots=len(slots),
        actual_observation_n=len(actual_timestamps),
        comparable_n=comparable_n,
        virtual_only_n=virtual_only_n,
        actual_only_n=actual_only_n,
        pct_comparable=round(comparable_n/len(slots)*100,1) if slots else None,
        slots=slot_class,
        actual_only=actual_only,
    )


def compare(actual,simulated):
    """Metrics only; actual actions are passed AFTER independent replay completes."""
    spreads=[];absolute=[];fee_errors=[]
    for a,b in zip(actual.get('fills',[]),simulated.get('fills',[])):
        width=float(a['ask'])-float(a['bid'])
        absolute.append(abs(a['price']-b['price']))
        if width>0:spreads.append(abs(a['price']-b['price'])/width)
        elif abs(a['price']-b['price'])>1e-12:spreads.append(None)
        else:spreads.append(0.)
        fee_errors.append(abs(a.get('fees_total',0)-b.get('fees_total',0)))
    confusion=Counter();agreements=[];rolls=[];strike_errors=[];expiry_errors=[];overrides=[]
    first_a=first_b=None
    for i,(a,b) in enumerate(zip(actual.get('actions',[]),simulated.get('actions',[]))):
        aa,bb=normalize_action(a['action']),normalize_action(b['action'])
        if aa!='HOLD_CALL' and first_a is None:first_a=a.get('session_index',i)
        if bb!='HOLD_CALL' and first_b is None:first_b=b.get('session_index',i)
        if a.get('source')=='HUMAN_OVERRIDE':overrides.append(dict(actual=a,simulated=b));continue
        agreements.append(aa==bb)
        confusion[('HOLD' if aa=='HOLD_CALL' else 'INTERVENTION')+'->'+('HOLD' if bb=='HOLD_CALL' else 'INTERVENTION')]+=1
        if aa.startswith('ROLL_') and bb.startswith('ROLL_'):
            rolls.append(aa==bb)
            if a.get('strike') is not None and b.get('strike') is not None:strike_errors.append(b['strike']-a['strike'])
            if a.get('expiration') and b.get('expiration'):expiry_errors.append((parse_timestamp(b['expiration']+'T00:00:00Z')-parse_timestamp(a['expiration']+'T00:00:00Z')).days)
    if len(actual.get('actions',[]))!=len(simulated.get('actions',[])):
        agreements.extend([False]*abs(len(actual.get('actions',[]))-len(simulated.get('actions',[]))))
    alpha_error=abs(simulated['incremental_alpha']-actual['incremental_alpha'])
    return dict(metric_units={'fill_error':'USD_PER_SHARE','fee_error':'USD_TOTAL','pnl_difference':'USD_TOTAL','alpha_error':'USD_PER_SHARE','timing_error':'MARKET_SESSIONS'},entry_fill_absolute_error=absolute[0] if absolute else None,
        entry_fill_spread_error=spreads[0] if spreads else None,per_leg_fill_errors=absolute,
        fee_error=sum(fee_errors),action_agreement=sum(agreements)/len(agreements) if agreements else None,
        policy_action_n=len(agreements),intervention_confusion=dict(confusion),
        intervention_timing_error=first_b-first_a if first_a is not None and first_b is not None else 0 if first_a is first_b is None else None,
        roll_type_agreement=sum(rolls)/len(rolls) if rolls else None,roll_comparison_n=len(rolls),
        strike_differences=strike_errors,expiry_day_differences=expiry_errors,
        pnl_difference=simulated['total_option_pnl']-actual['total_option_pnl'],incremental_alpha_difference=simulated['incremental_alpha']-actual['incremental_alpha'],alpha_absolute_error=alpha_error,
        actual_alpha_absolute=abs(actual['incremental_alpha']),execution_cost_difference=simulated['execution_cost']-actual['execution_cost'],
        management_cost_difference=simulated['management_cost']-actual['management_cost'],human_overrides=overrides,
        net_roll_credit_difference=simulated.get('net_roll_credit',0)-actual.get('net_roll_credit',0),
        lookahead_violations=simulated.get('lookahead_violations',0),state_contamination=simulated.get('state_contamination',0))


def divergence_category(case):
    if case.get('human_overrides'):return 'DISCRETIONARY_HUMAN_ACTION'
    if case.get('lookahead_violations') or case.get('state_contamination'):return 'BUG'
    if case.get('entry_fill_spread_error') is None:return 'QUOTE_QUALITY'
    if case.get('action_agreement') is not None and case['action_agreement']<1:return 'POLICY_MISMATCH'
    # Intervention timing errors explained by cadence difference are a cadence effect, not a policy mismatch.
    cadence=case.get('cadence_comparability',{})
    if case.get('intervention_timing_error') and cadence.get('virtual_only_n',0)>0:return 'VIRTUAL_EARLIER_OPPORTUNITY'
    if case.get('intervention_timing_error'):return 'DATA_TIMING'
    if any(case.get('strike_differences',[])) or any(case.get('expiry_day_differences',[])):return 'POLICY_MISMATCH'
    if case.get('alpha_absolute_error') or case.get('entry_fill_spread_error') or case.get('fee_error'):return 'EXECUTION_MODEL_ERROR'
    return 'MATCH'


def acceptance(cases,policy):
    n=len(cases);failures=[]
    fill=[x['entry_fill_spread_error'] for x in cases if x.get('entry_fill_spread_error') is not None]
    action=[x['action_agreement'] for x in cases if x.get('action_agreement') is not None]
    timing=[abs(x['intervention_timing_error']) for x in cases if x.get('intervention_timing_error') is not None]
    roll=[x['roll_type_agreement'] for x in cases if x.get('roll_type_agreement') is not None]
    economics=[x['alpha_absolute_error']<=max(policy['maximum_alpha_absolute_error'],policy['maximum_alpha_relative_error']*x['actual_alpha_absolute']) for x in cases]
    metrics=dict(n=n,entry_spread_mae=mean(fill) if fill else None,action_agreement=mean(action) if action else None,
        median_timing_error=median(timing) if timing else None,roll_type_agreement=mean(roll) if roll else None,
        roll_n=len(roll),median_alpha_error=median([x['alpha_absolute_error'] for x in cases]) if cases else None,
        economic_error_pass_fraction=mean(economics) if economics else None,
        lookahead_violations=sum(x.get('lookahead_violations',0) for x in cases),state_contamination=sum(x.get('state_contamination',0) for x in cases))
    for passed,reason in [(n>=policy['minimum_n'],'MINIMUM_VALIDATION_N'),
        (len(fill)==n and bool(fill) and mean(fill)<=policy['maximum_entry_spread_error'],'ENTRY_FILL_ERROR'),
        (bool(action) and mean(action)>=policy['minimum_action_agreement'],'ACTION_AGREEMENT'),
        (bool(timing) and median(timing)<=policy['maximum_median_timing_sessions'],'INTERVENTION_TIMING'),
        (bool(roll) and mean(roll)>=policy['minimum_roll_type_agreement'],'ROLL_TYPE_AGREEMENT'),
        (bool(economics) and median([x['alpha_absolute_error']-max(policy['maximum_alpha_absolute_error'],policy['maximum_alpha_relative_error']*x['actual_alpha_absolute']) for x in cases])<=0,'ECONOMIC_ERROR'),
        (metrics['lookahead_violations']==0,'LOOKAHEAD'),(metrics['state_contamination']==0,'STATE_CONTAMINATION')]:
        if not passed:failures.append(reason)
    return dict(eligible=not failures,status='CERTIFIABLE' if not failures else 'INSUFFICIENT_EVIDENCE' if n<policy['minimum_n'] else 'FAILED',failures=failures,metrics=metrics)


def replay(origin,initial,snapshots):
    """Historical data only. No access to actual decisions or actual outcome fields."""
    current=dict(initial);actions=[]
    fills=[fill_model(origin['entry_quote_inputs'],current['contracts'],'SELL',origin['config'],origin['entry_timestamp'],origin['frozen_fill_fraction'])]
    for i,record in enumerate(sorted(snapshots,key=lambda r:parse_timestamp(r['evaluation_timestamp']))):
        proposal=evaluate_snapshot(origin,current,record['snapshot'],record['evaluation_timestamp'])
        action=proposal['action'];after=dict(current);prior_len=len(fills)
        if action=='BUY_TO_CLOSE' or action.startswith('ROLL_'):
            fills.append(fill_model(proposal['quote'],current['contracts'],'BUY',origin['config'],record['evaluation_timestamp']))
            after['management_cost_total']+=origin['config']['management_cost_per_contract']*current['contracts']
            if action.startswith('ROLL_'):
                target=proposal['target'];fills.append(fill_model(target,current['contracts'],'SELL',origin['config'],record['evaluation_timestamp'],origin['frozen_fill_fraction']))
                after.update(strike=target['strike'],expiration=target['expiration'],leg_entry_premium=fills[-1]['price'],roll_hops=current['roll_hops']+1)
            else:after.update(status='CLOSED_BTC',terminal_spot=proposal['snapshot']['spot'])
        elif action in ('ASSIGNED','EXPIRED_OTM'):
            after.update(status=action,terminal_spot=proposal['terminal_spot'])
            if action=='ASSIGNED':after['assignment_cost_total']+=max(0.,proposal['terminal_spot']-current['strike'])*current['contracts']*100
        # Only fills produced in this cycle contribute; never replay cumulative fills twice.
        for f in fills[prior_len:]:
            after['option_cash_total']+=f['cash_flow_total'];after['fees_total']+=f['fees_total'];after['execution_cost_total']+=f['execution_cost_total']
        after['replay_fills']=list(fills)
        actions.append(dict(action=action,session_index=record.get('session_index',i),strike=after['strike'],expiration=after['expiration']))
        current=after
        if after['status'] not in ('OPEN','AWAIT_ASSIGNMENT'):break
    if current['status'] in ('OPEN','AWAIT_ASSIGNMENT'):raise ValueError('replay chain incomplete')
    shares=current['contracts']*100;pnl=current['option_cash_total']-current['fees_total']
    return dict(actions=actions,fills=fills,state=current,incremental_alpha=(pnl-current['assignment_cost_total']-current['management_cost_total'])/shares,
                total_option_pnl=pnl,execution_cost=current['execution_cost_total']/shares,management_cost=current['management_cost_total']/shares,
                outcome_source='ESTIMATED_COUNTERFACTUAL',prospective=False,lookahead_violations=0,state_contamination=0)


def run_validation(config,path=None):
    from covered_call_ledger import connect,migrate as ledger_migrate,config_digest
    from covered_call_virtual import start_from_decision,state
    db=connect(path);ledger_migrate(db);migrate(db);db.commit()
    cases=[];excluded=Counter();details=[];cohort=[]
    # Actual original SELL_CC chains are enumerated, including legacy chains lacking episodes.
    try:actual_records=db.execute("SELECT DISTINCT r.id,r.action_payload_json FROM recommendations r JOIN executed_actions e ON e.recommendation_id=r.id WHERE r.action='SELL_CC'").fetchall()
    except Exception:actual_records=[]
    try:
        legacy_positions=[dict(r) for r in db.execute("SELECT id,ticker,strike,expiry,status FROM cc_positions WHERE status!='open' ORDER BY id DESC")]
    except Exception:legacy_positions=[]
    seen=set()
    for actual in actual_records:
        payload=json.loads(actual['action_payload_json'] or '{}');episode=payload.get('cc_episode_id')
        if not episode:excluded['NO_DECISION_EPISODE']+=1;continue
        if episode in seen:continue
        seen.add(episode)
        outcome=latest(db,episode,'champion')
        if not outcome:excluded['NO_RECONCILED_ACTUAL_OUTCOME']+=1;continue
        try:
            validate(outcome)
            if outcome['outcome_source']!='ACTUAL_EXECUTION' or not outcome.get('complete') or outcome.get('censored'):raise ValueError('incomplete actual')
            observations=db.execute('SELECT * FROM cc_actual_policy_evaluations WHERE episode_id=? ORDER BY timestamp',(episode,)).fetchall()
            if not observations:raise ValueError('missing historical as-of policy snapshots')
            snapshots=[];actual_actions=[]
            for observation in observations:
                evidence=json.loads(observation['evidence_json'])
                snapshot_row=db.execute('SELECT snapshot_json FROM cc_market_snapshots WHERE id=?',(observation['snapshot_id'],)).fetchone()
                if not snapshot_row:raise ValueError('missing option-chain snapshot')
                snapshots.append(dict(evaluation_timestamp=observation['timestamp'],snapshot=json.loads(snapshot_row[0]),session_index=evidence.get('session_index',len(snapshots))))
                actual_actions.append(evidence)
            # Replay entry is reconstructed from original quote, never actual entry action choices.
            with db:chain_id=start_from_decision(db,episode,arm='champion',replay=True)
            chain=db.execute('SELECT origin_json FROM cc_virtual_chains WHERE id=?',(chain_id,)).fetchone()
            origin=json.loads(chain[0])
            entry=db.execute('SELECT state_json FROM cc_virtual_positions WHERE chain_id=? AND sequence=0',(chain_id,)).fetchone()
            simulated=replay(origin,json.loads(entry[0]),snapshots)
            fills=[json.loads(r[0]) for r in db.execute('SELECT evidence_json FROM cc_actual_fill_evidence WHERE episode_id=? ORDER BY timestamp,execution_id',(episode,))]
            if not fills:fills=[json.loads(r[0]) for r in db.execute('SELECT payload_json FROM cc_fills WHERE episode_id=?',(episode,))]
            if not fills:raise ValueError('missing contemporaneous actual fill quotes')
            if len(fills)!=len(simulated['fills']):raise ValueError('missing actual leg quote evidence')
            actual_view=dict(actions=actual_actions,fills=[dict(price=f['fill'],bid=f['bid'],ask=f['ask'],fees_total=f['fees']) for f in fills],
                incremental_alpha=outcome['cc_incremental_alpha'],total_option_pnl=outcome['total_option_pnl'],
                execution_cost=outcome['realized_execution_cost'],management_cost=outcome['realized_management_cost'],net_roll_credit=outcome.get('roll_net_credit') or 0)
            from datetime import datetime
            expiry_date=datetime.strptime(origin['entry_quote_inputs']['expiration'],'%Y-%m-%d').date()
            cadence_cmp=classify_cadence_comparability(
                [s['evaluation_timestamp'] for s in snapshots],
                origin['entry_timestamp'],expiry_date,
                origin['config'].get('virtual',{}).get('cadence_minutes',30))
            case=compare(actual_view,simulated)
            case['cadence_comparability']=cadence_cmp
            cases.append(case);cohort.append(episode);details.append(dict(episode_id=episode,metrics=case,divergence_category=divergence_category(case),cadence_comparability=cadence_cmp))
        except Exception as exc:
            excluded[str(exc)]+=1;details.append(dict(episode_id=episode,exclusion=str(exc)))
    result=acceptance(cases,config['simulator_validation'])
    sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    cadence_summary=dict(
        cadence_mode='STRICT_MATCHED_CADENCE',
        cadence_comparability_policy_version=CADENCE_COMPARABILITY_POLICY_VERSION,
        total_comparable_n=sum(c.get('cadence_comparability',{}).get('comparable_n',0) for c in cases),
        total_virtual_only_n=sum(c.get('cadence_comparability',{}).get('virtual_only_n',0) for c in cases),
        total_actual_only_n=sum(c.get('cadence_comparability',{}).get('actual_only_n',0) for c in cases),
        virtual_earlier_opportunity_n=sum(1 for d in details if d.get('divergence_category')=='VIRTUAL_EARLIER_OPPORTUNITY'),
        cadence_divergence_n=sum(1 for d in details if d.get('divergence_category') in ('VIRTUAL_EARLIER_OPPORTUNITY','DATA_TIMING')),
        true_policy_mismatch_n=sum(1 for d in details if d.get('divergence_category')=='POLICY_MISMATCH'),
    )
    result.update(simulator_version=SIMULATOR_VERSION,config_hash=config_digest(config),git_sha=sha,
        simulator_contract_hash=simulator_contract_hash(config),simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        cadence_comparability_policy_version=CADENCE_COMPARABILITY_POLICY_VERSION,
        validation_policy_version=config['simulator_validation']['version'],management_contract=management_contract(),
        cohort_ids=cohort,cases=cases,total_actual_records=len(actual_records),legacy_completed_position_n=len(legacy_positions),
        legacy_case_review=[dict(r,category='MISSING_ASOF_EVIDENCE',review='Cannot replay or classify simulator divergence without original decision/options/policy snapshots') for r in legacy_positions[:10]],exclusions=dict(excluded),details=details,
        source_composition={'actual':'ACTUAL_EXECUTION','replay':'ESTIMATED_COUNTERFACTUAL'},out_of_sample=True,
        cadence_analysis=cadence_summary,
        simulator_bias=dict(n=len(cases),mean_alpha_error=mean(c['incremental_alpha_difference'] for c in cases) if cases else None,
            interpretation='OPTIMISTIC' if cases and mean(c['incremental_alpha_difference'] for c in cases)>0 else 'CONSERVATIVE' if cases and mean(c['incremental_alpha_difference'] for c in cases)<0 else 'MATCHED' if cases else 'UNAVAILABLE'),
        divergent_cases=[d for d in details if d.get('divergence_category') not in (None,'MATCH')],
        actual_divergent_review_available_n=sum(d.get('divergence_category') not in (None,'MATCH') for d in details))
    identifier=digest(result)
    with db:db.execute('INSERT OR IGNORE INTO cc_simulator_validation_runs VALUES(?,?,?,?,?,?)',(identifier,now_utc_iso(),SIMULATOR_VERSION,config_digest(config),sha,json.dumps(result,sort_keys=True)))
    result['id']=identifier;db.close();return result


def certify(run_id,config,path=None):
    from covered_call_ledger import connect,migrate as ledger_migrate,config_digest
    db=connect(path);ledger_migrate(db);migrate(db)
    row=db.execute('SELECT run_json FROM cc_simulator_validation_runs WHERE id=?',(run_id,)).fetchone()
    if not row:db.close();raise ValueError('unknown validation run')
    result=json.loads(row[0])
    checked=acceptance(result.get('cases',[]),config['simulator_validation'])
    mc=management_contract()
    contract_hash=simulator_contract_hash(config)
    # Validity: contract-relevant components must match; git SHA is provenance only.
    run_contract=result.get('simulator_contract_hash')
    if run_contract is not None and run_contract!=contract_hash:
        db.close();raise ValueError('simulator contract changed since validation run')
    if not checked['eligible'] or not result.get('eligible') or not result.get('out_of_sample') or result['simulator_version']!=SIMULATOR_VERSION or result['config_hash']!=config_digest(config) or result['management_contract']!=mc:
        db.close();raise ValueError('simulator validation gate not met')
    certified_git_sha=result.get('git_sha','')
    certificate=dict(
        validation_run_id=run_id,
        simulator_version=SIMULATOR_VERSION,
        simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        simulator_contract_hash=contract_hash,
        certified_at_git_sha=certified_git_sha,
        management_contract=mc,
        management_contract_hash=mc['engine_hash'],
        config_contract_hash=_config_contract_hash(config),
        config_hash=config_digest(config),
        validation_policy_version=config['simulator_validation']['version'],
        cadence_comparability_policy_version=CADENCE_COMPARABILITY_POLICY_VERSION,
        cohort_ids=result['cohort_ids'],
        metrics=result['metrics'],
        cadence_analysis=result.get('cadence_analysis'),
        git_sha=certified_git_sha,  # backward compat alias
    )
    identifier=digest(certificate)
    with db:db.execute('INSERT OR IGNORE INTO cc_simulator_certifications VALUES(?,?,?,?)',(identifier,run_id,now_utc_iso(),json.dumps(certificate,sort_keys=True)))
    db.close();return dict(certificate,id=identifier)


def certification(config,path=None):
    from covered_call_ledger import connect,migrate as ledger_migrate,config_digest
    db=connect(path);ledger_migrate(db);migrate(db)
    rows=db.execute('SELECT id,certificate_json FROM cc_simulator_certifications ORDER BY timestamp DESC').fetchall()
    db.close()
    contract_hash=simulator_contract_hash(config)
    mc=management_contract()
    for row in rows:
        c=json.loads(row['certificate_json'])
        # New certs: validate by simulator_contract_hash (git SHA is provenance only).
        # Legacy certs (no simulator_contract_hash): fall back to git_sha match.
        if c.get('simulator_contract_hash') is not None:
            contract_valid=c['simulator_contract_hash']==contract_hash
        else:
            contract_valid=c.get('git_sha')==current_git_sha()
        cadence_version_valid=c.get('cadence_comparability_policy_version',CADENCE_COMPARABILITY_POLICY_VERSION)==CADENCE_COMPARABILITY_POLICY_VERSION
        if contract_valid and cadence_version_valid and c.get('simulator_contract_version',SIMULATOR_CONTRACT_VERSION)==SIMULATOR_CONTRACT_VERSION and c['simulator_version']==SIMULATOR_VERSION and c['config_hash']==config_digest(config) and c['management_contract']==mc and c['validation_policy_version']==config['simulator_validation']['version']:
            return dict(c,id=row['id'],current_git_sha=current_git_sha())
    return None


def record_actual_evaluation(episode,timestamp,snapshot,actual_action,path=None):
    """Capture policy-aligned actual evaluation; replay never receives action data."""
    from covered_call_ledger import connect,migrate as ledger_migrate
    from covered_call_virtual import store_snapshot,enforce_asof
    enforce_asof(snapshot,timestamp)
    db=connect(path);ledger_migrate(db)
    try:
        if not db.execute('SELECT 1 FROM cc_decisions WHERE id=?',(episode,)).fetchone():
            raise ValueError('unknown actual evaluation episode')
        evidence=dict(actual_action,timestamp=timestamp,observation_source='ACTUAL_POLICY_EVALUATION')
        identifier=digest([episode,timestamp,evidence])
        with db:
            snapshot_id=store_snapshot(db,snapshot)
            db.execute('INSERT OR IGNORE INTO cc_actual_policy_evaluations VALUES(?,?,?,?,?)',
                (identifier,episode,timestamp,snapshot_id,json.dumps(evidence,sort_keys=True)))
        return identifier
    finally:db.close()


def record_actual_fill(execution_id,episode,timestamp,bid,ask,quote_timestamp,path=None):
    """Reconcile a real entry/BTC/roll leg to contemporaneous quote evidence."""
    import math
    from covered_call_ledger import connect,migrate as ledger_migrate
    at=parse_timestamp(timestamp);quoted=parse_timestamp(quote_timestamp)
    if abs((at-quoted).total_seconds())>300 or not all(math.isfinite(float(x)) for x in (bid,ask)) or bid<0 or ask<bid:
        raise ValueError('invalid contemporaneous actual quote')
    db=connect(path);ledger_migrate(db)
    try:
        decision=db.execute('SELECT champion_json FROM cc_decisions WHERE id=?',(episode,)).fetchone()
        chain=json.loads(decision[0]).get('trade_chain_id') if decision else None
        row=db.execute('SELECT e.* FROM executed_actions e JOIN recommendations r ON r.id=e.recommendation_id WHERE e.id=? AND r.trade_chain_id=?',(execution_id,chain)).fetchone()
        if row is None:raise ValueError('actual execution does not match episode chain')
        if row['execution_date'][:10]!=at.astimezone(__import__('time_utils').TZ_EASTERN).date().isoformat():raise ValueError('actual fill date mismatch')
        price=row['premium'] if row['premium'] is not None else row['execution_price']
        if price is None or row['contracts'] is None:raise ValueError('actual option leg economics missing')
        evidence=dict(outcome_source='ACTUAL_EXECUTION',execution_id=execution_id,execution_reconciled=True,broker_reconciled=False,
            episode_id=episode,chain_identifier=chain,execution_timestamp=timestamp,quote_timestamp=quote_timestamp,
            bid=bid,ask=ask,fill=price,fees=row['fees'],contracts=row['contracts'],action=row['action'],
            strike=row['strike'],expiration=row['expiration'],units='USD_PER_SHARE')
        with db:db.execute('INSERT INTO cc_actual_fill_evidence VALUES(?,?,?,?)',(execution_id,episode,timestamp,json.dumps(evidence,sort_keys=True)))
        return evidence
    finally:db.close()
