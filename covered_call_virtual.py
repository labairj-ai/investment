"""Append-only prospective CC book. This module has no broker/write adapters.

Every policy input comes from an immutable as-of snapshot. Replays are separately
marked retrospective and cannot enter promotion. Actual tables are never written.
"""
from __future__ import annotations
import inspect
import json
import math
from datetime import date, timedelta
from types import SimpleNamespace
import pandas as pd
from time_utils import now_utc, now_utc_iso, parse_timestamp, TZ_EASTERN
from covered_call_outcomes import digest, base, persist, contract

SIMULATOR_VERSION = 'cc-virtual-1'
POLICY_VERSION = 'shared-live-management-asof-1'
# Incremented when the composition of simulator_contract_hash changes.
SIMULATOR_CONTRACT_VERSION = 'simulator-contract-1'
# Config keys whose values affect simulator behaviour.
_CONTRACT_CONFIG_KEYS = (
    'management_cost_per_contract', 'path_count', 'max_regret_probability',
    'utility_hurdle_annual_pct', 'fill_prior', 'fill_prior_strength',
    'fill_min_n', 'regime_enabled',
)


class DataUnavailable(ValueError):
    pass


def management_contract():
    import covered_call_rec as cc
    from covered_call_v3 import execution
    functions = (fill_model,evaluate_snapshot,missed_intervals,execution,cc.evaluate_cc_management_state, cc._check_assignment_eligible,
                 cc._suggest_next_call, cc._remaining_call_alpha, cc._friction_at_expiry,
                 cc.call_delta, cc.expected_upside_lost, cc.itm_prob_real, cc._exec_premium)
    return dict(engine_hash=digest([inspect.getsource(f) for f in functions]),
                tax_st_rate=cc.TAX_ST_RATE, tax_lt_rate=cc.TAX_LT_RATE,
                risk_free_rate=cc.RISK_FREE_RATE, exec_lambda=cc.EXEC_LAMBDA,
                assignment_tax_friction_threshold=cc.CC_ASSIGNMENT_TAX_FRICTION_THRESHOLD,
                policy_version=POLICY_VERSION)


def simulator_contract_hash(config):
    """Deterministic hash of all simulator-relevant code and config.

    Changes when and only when CC virtual book behaviour can change.
    Unrelated commits (docs, dashboard copy, etc.) do not affect this hash.
    """
    mc = management_contract()
    cc_cfg = config.get('cc_v3', {})
    config_subset = {k: cc_cfg.get(k) for k in _CONTRACT_CONFIG_KEYS}
    return digest({
        'simulator_contract_version': SIMULATOR_CONTRACT_VERSION,
        'simulator_version': SIMULATOR_VERSION,
        'management_contract_hash': mc['engine_hash'],
        'policy_version': mc['policy_version'],
        'config_contract_hash': digest(config_subset),
    })


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS cc_market_snapshots(
      id TEXT PRIMARY KEY, ticker TEXT NOT NULL, captured_at TEXT NOT NULL,
      available_at TEXT NOT NULL, snapshot_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_virtual_chains(
      id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES cc_decisions(id),
      candidate_id TEXT NOT NULL, arm TEXT NOT NULL, simulation_kind TEXT NOT NULL,
      created_at TEXT NOT NULL, origin_json TEXT NOT NULL,
      UNIQUE(episode_id,arm,simulation_kind));
    CREATE TABLE IF NOT EXISTS cc_virtual_positions(
      id TEXT PRIMARY KEY, chain_id TEXT NOT NULL REFERENCES cc_virtual_chains(id),
      sequence INTEGER NOT NULL, timestamp TEXT NOT NULL, state_json TEXT NOT NULL,
      UNIQUE(chain_id,sequence));
    CREATE TABLE IF NOT EXISTS cc_virtual_actions(
      id TEXT PRIMARY KEY, chain_id TEXT NOT NULL REFERENCES cc_virtual_chains(id),
      evaluation_timestamp TEXT NOT NULL, snapshot_id TEXT NOT NULL,
      action TEXT NOT NULL, action_json TEXT NOT NULL,
      UNIQUE(chain_id,evaluation_timestamp));
    CREATE TABLE IF NOT EXISTS cc_virtual_fills(
      id TEXT PRIMARY KEY, chain_id TEXT NOT NULL REFERENCES cc_virtual_chains(id),
      action_id TEXT NOT NULL, leg TEXT NOT NULL, fill_json TEXT NOT NULL,
      UNIQUE(action_id,leg));
    CREATE TABLE IF NOT EXISTS cc_virtual_intervals(
      id TEXT PRIMARY KEY, chain_id TEXT NOT NULL REFERENCES cc_virtual_chains(id),
      evaluation_timestamp TEXT NOT NULL, snapshot_id TEXT, reason TEXT NOT NULL,
      details_json TEXT NOT NULL, UNIQUE(chain_id,evaluation_timestamp,reason));
    CREATE INDEX IF NOT EXISTS cc_virtual_position_chain ON cc_virtual_positions(chain_id,sequence);
    ''')
    for table in ('cc_market_snapshots', 'cc_virtual_chains', 'cc_virtual_positions',
                  'cc_virtual_actions', 'cc_virtual_fills', 'cc_virtual_intervals'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable virtual CC record'); END")


def stamp(value):
    return parse_timestamp(value).isoformat()


def enforce_asof(snapshot, evaluation):
    """Filter future observations; never let them enter the policy's object graph."""
    at = parse_timestamp(evaluation)
    for key in ('captured_at', 'available_at', 'underlying_timestamp'):
        if not snapshot.get(key) or parse_timestamp(snapshot[key]) > at:
            raise DataUnavailable('SNAPSHOT_NOT_AVAILABLE_ASOF_'+key.upper())
    max_age = float(snapshot.get('maximum_quote_age_seconds', 900))
    if (at - parse_timestamp(snapshot['underlying_timestamp'])).total_seconds() > max_age:
        raise DataUnavailable('STALE_UNDERLYING')
    if not math.isfinite(float(snapshot.get('spot', 0))) or snapshot['spot'] <= 0:
        raise DataUnavailable('INVALID_UNDERLYING')
    quotes = []
    for quote in snapshot.get('options', []):
        observed = quote.get('observed_at') or quote.get('quote_timestamp')
        available = quote.get('available_at') or observed
        if not observed or not available:
            continue
        if parse_timestamp(observed) > at or parse_timestamp(available) > at:
            continue
        if (at - parse_timestamp(observed)).total_seconds() > max_age:
            continue
        values = [quote.get(k) for k in ('strike', 'bid', 'ask', 'impliedVolatility')]
        if any(x is None or not math.isfinite(float(x)) for x in values):
            continue
        if quote['bid'] < 0 or quote['ask'] < quote['bid'] or quote['ask'] <= 0 or quote['impliedVolatility'] <= .01:
            continue
        quotes.append({k:quote[k] for k in ('strike','bid','ask','impliedVolatility','expiration','observed_at','quote_timestamp','available_at','openInterest','volume') if k in quote})
    events = [dict(e) for e in snapshot.get('events', []) if e.get('known_at') and parse_timestamp(e['known_at']) <= at]
    out = {k: snapshot[k] for k in ('spot','captured_at','available_at','underlying_timestamp')}
    out.update(options=quotes, events=events,
               coverage_verified=bool(snapshot.get('coverage_verified')),
               quote_timing_verified=bool(snapshot.get('quote_timing_verified')))
    if snapshot.get('forecast_available_at') and parse_timestamp(snapshot['forecast_available_at'])<=at:
        for key in ('hv_forecast','mu_center'):
            if snapshot.get(key) is not None and math.isfinite(float(snapshot[key])):out[key]=float(snapshot[key])
    # Actual action/terminal outcome/human instructions are never policy inputs.
    return out


def store_snapshot(db, snapshot):
    payload = json.dumps(snapshot, sort_keys=True, allow_nan=False)
    identifier = digest(snapshot)
    # Validate availability against its own capture completion time.
    enforce_asof(snapshot, snapshot['available_at'])
    db.execute('INSERT OR IGNORE INTO cc_market_snapshots VALUES(?,?,?,?,?)',
               (identifier,snapshot['ticker'],stamp(snapshot['captured_at']),stamp(snapshot['available_at']),payload))
    return identifier


def state(db, chain_id):
    row = db.execute('SELECT state_json FROM cc_virtual_positions WHERE chain_id=? ORDER BY sequence DESC LIMIT 1',(chain_id,)).fetchone()
    return json.loads(row[0]) if row else None


def write_state(db, chain_id, timestamp, value):
    sequence = db.execute('SELECT COALESCE(max(sequence),-1)+1 FROM cc_virtual_positions WHERE chain_id=?',(chain_id,)).fetchone()[0]
    db.execute('INSERT INTO cc_virtual_positions VALUES(?,?,?,?,?)',
               (digest([chain_id,sequence]),chain_id,sequence,stamp(timestamp),json.dumps(value,sort_keys=True,allow_nan=False)))


def fill_model(quote, contracts, side, config, timestamp, frozen_fraction=None):
    from covered_call_v3 import execution
    cfg = dict(config)
    if frozen_fraction is not None:
        cfg['fill_prior'] = float(frozen_fraction)
    model = execution(quote, (), cfg)
    if side=='BUY' and all(math.isfinite(float(quote[k])) for k in ('bid','ask')) and quote['bid']>=0 and quote['ask']>=quote['bid'] and quote['ask']>0:
        model=dict(model,execution_available=True)
    if not model.get('execution_available'):
        raise DataUnavailable('INVALID_FILL_QUOTE')
    price = model['expected_fill'] if side == 'SELL' else float(quote['ask'])
    shares = contracts * 100
    fees = float(config['fee_per_contract']) * contracts
    mid = (float(quote['bid']) + float(quote['ask'])) / 2
    cash = price * shares * (1 if side == 'SELL' else -1)
    slippage = (mid-price if side == 'SELL' else price-mid)*shares
    return dict(side=side,price=price,contracts=contracts,shares=shares,fees_total=fees,
                cash_flow_total=cash,execution_cost_total=slippage+fees,
                modeled_slippage_total=slippage,timestamp=stamp(timestamp),quote_inputs=dict(quote),
                execution_model_version=model['execution_model_version'],simulator_version=SIMULATOR_VERSION,
                config_hash=__import__('covered_call_ledger').config_digest(config),config_version=config['config_version'],
                execution_parameters=dict(fill_fraction=cfg['fill_prior'],fee_per_contract=config['fee_per_contract']),
                fill_price_units='USD_PER_SHARE',units='USD_TOTAL',
                outcome_source='PROSPECTIVE_VIRTUAL',broker_reconciled=False)


def start_from_decision(db, episode, created_at=None, arm='challenger', replay=False):
    """Called in the decision transaction. Idempotent, no actual table writes."""
    decision = db.execute('SELECT * FROM cc_decisions WHERE id=?',(episode,)).fetchone()
    choice = json.loads(decision[arm+'_json'])
    if choice.get('action') != 'SELL_CC':
        return None
    kind = 'RETROSPECTIVE_REPLAY' if replay else 'PROSPECTIVE'
    existing = db.execute('SELECT id FROM cc_virtual_chains WHERE episode_id=? AND arm=? AND simulation_kind=?',(episode,arm,kind)).fetchone()
    if existing:
        return existing[0]
    metadata = contract(db,episode)
    if not replay and (not metadata or not metadata.get('forward_created')):
        return None  # Never retroactively create a prospective book.
    candidate = db.execute('SELECT candidate_id,features_json FROM cc_candidates WHERE episode_id=? AND '+('selected_v3' if arm=='challenger' else 'selected_v2')+'=1',(episode,)).fetchone()
    if not candidate:
        raise ValueError('selected virtual candidate missing')
    features = json.loads(candidate['features_json'])
    config = json.loads(decision['config_json'])
    entry = parse_timestamp(decision['timestamp'])
    quote_at = parse_timestamp(features.get('quote_timestamp') or decision['timestamp'])
    if quote_at > entry or (entry-quote_at).total_seconds()>config.get('virtual',{}).get('maximum_quote_age_seconds',900):
        return None
    n = int(choice['contracts'])
    if n<=0 or n>int(features.get('eligible_contracts_max',n)):
        raise ValueError('virtual coverage invalid')
    chain_id = 'virtual-cc-'+digest([episode,arm,kind])[:32]
    _mc=management_contract()
    origin = dict(episode_id=episode,candidate_id=candidate['candidate_id'],ticker=decision['ticker'],
        entry_timestamp=decision['timestamp'],entry_spot=features['spot'],contracts=n,
        origin_holding_shares=features.get('origin_holding_shares'),
        policy=json.loads(decision['policy_json']),config=config,config_hash=decision['config_hash'],
        model_version=decision['model_version'],simulator_version=SIMULATOR_VERSION,
        simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        simulator_contract_hash=simulator_contract_hash(config),
        entry_quote_inputs={k:features.get(k) for k in ('bid','ask','strike','expiration','impliedVolatility','quote_timestamp')},
        origin_git_sha=decision['git_sha'],market_snapshot_lineage=metadata['market_snapshot_lineage'] if metadata else digest(features),
        management_contract=_mc,lot_schedule=features.get('assignment_lot_schedule',[]),
        tax_data_available=bool(features.get('tax_data_available')),
        mu=features.get('mu_center',.08),hv_forecast=features.get('hv_forecast',.3),
        frozen_fill_fraction=features.get('expected_fill_fraction',config['fill_prior']),
        prospective=not replay,simulation_kind=kind,
        promotion_policy_version=config['promotion']['version'],creation_timestamp=stamp(created_at or now_utc()))
    fill = fill_model(features,n,'SELL',config,decision['timestamp'],origin['frozen_fill_fraction'])
    if replay:fill['outcome_source']='ESTIMATED_COUNTERFACTUAL'
    action_id=chain_id+':ENTRY'
    db.execute('INSERT INTO cc_virtual_chains VALUES(?,?,?,?,?,?,?)',
        (chain_id,episode,candidate['candidate_id'],arm,kind,origin['creation_timestamp'],json.dumps(origin,sort_keys=True)))
    current=dict(status='OPEN',strike=features['strike'],expiration=features['expiration'],contracts=n,
        leg_entry_premium=fill['price'],leg_entry_timestamp=decision['timestamp'],
        option_cash_total=fill['cash_flow_total'],fees_total=fill['fees_total'],
        execution_cost_total=fill['execution_cost_total'],management_cost_total=0.,
        assignment_cost_total=0.,roll_hops=0,coverage_censored=False,
        assignment_policy_violation=False,last_evaluation=decision['timestamp'],interval_errors=0,
        first_intervention=None,entry_timestamp=decision['timestamp'],entry_spot=features['spot'])
    db.execute('INSERT INTO cc_virtual_actions VALUES(?,?,?,?,?,?)',
        (action_id,chain_id,decision['timestamp'],origin['market_snapshot_lineage'],'SELL_CC',
         json.dumps(dict(action='SELL_CC',reason='prospective challenger entry',state_before=None,state_after=current,
             policy_snapshot=origin['policy'],simulator_version=SIMULATOR_VERSION,origin_git_sha=origin['origin_git_sha'],
             outcome_source=fill['outcome_source'],modeled_fill_inputs=features),sort_keys=True)))
    db.execute('INSERT INTO cc_virtual_fills VALUES(?,?,?,?,?)',(action_id+':STO',chain_id,action_id,'STO',json.dumps(fill,sort_keys=True)))
    write_state(db,chain_id,decision['timestamp'],current)
    return chain_id


def context_for(origin,current,snapshot,evaluation):
    from covered_call_rec import ManagementPolicyContext, call_delta, _friction_at_expiry, TaxFrictionDetail
    at=parse_timestamp(evaluation).astimezone(TZ_EASTERN).date()
    expiry=date.fromisoformat(current['expiration'])
    quote=next((q for q in snapshot['options'] if q['expiration']==current['expiration'] and float(q['strike'])==current['strike']),None)
    if quote is None:raise DataUnavailable('CURRENT_CONTRACT_QUOTE_UNAVAILABLE')
    mark=(quote['bid']+quote['ask'])/2
    dte=(expiry-at).days
    delta=call_delta(snapshot['spot'],current['strike'],max(0,dte)/365,quote['impliedVolatility'])
    extrinsic=max(0.,mark-max(0.,snapshot['spot']-current['strike']))
    events=[e for e in snapshot['events'] if at<date.fromisoformat(e['date'])<=expiry]
    policy=origin['policy']
    friction=_friction_at_expiry(origin['lot_schedule'],current['strike'],expiry) if origin['tax_data_available'] else 0
    # Match live friction's minimum-dollar and LT-transition window semantics.
    from tax_utils import days_until_lt
    soonest=min((days_until_lt(date.fromisoformat(l['purchase_date']),expiry) for l in origin['lot_schedule'] if days_until_lt(date.fromisoformat(l['purchase_date']),expiry)>0),default=99999)
    from strategy_config import CC_ASSIGNMENT_TAX_FRICTION_THRESHOLD
    if friction<CC_ASSIGNMENT_TAX_FRICTION_THRESHOLD or soonest>90:friction=0.
    detail=TaxFrictionDetail(friction,'ST tax friction' if friction else '',origin['tax_data_available'],origin['lot_schedule'])
    ctx=ManagementPolicyContext(ticker=origin['ticker'],current_price=snapshot['spot'],strike=current['strike'],dte=dte,
        delta=delta,remaining_extrinsic=extrinsic,pct_captured=(1-mark/current['leg_entry_premium'])*100,
        has_avoid=any(e.get('severity')=='avoid' for e in events),risk_events=events,contracts=current['contracts'],
        assignment_price_floor=policy.get('acceptable_assignment_min_price'),assignment_policy=policy.get('assignment_policy') or {},
        current_weight_pct=policy.get('portfolio_weight'),max_position_pct=policy.get('max_position_pct'),
        conviction=policy.get('conviction'),thesis_health=policy.get('thesis_health'),
        assignment_tax_friction=friction,tax_friction_reason=detail.reason,tax_friction_available=detail.available,
        tax_friction_detail=detail,expiry_date=expiry)
    return ctx,quote


def evaluate_snapshot(origin,current,raw_snapshot,evaluation):
    """Pure transition proposal shared by forward processing and historical replay."""
    from covered_call_rec import evaluate_cc_management_state, _suggest_next_call, _check_assignment_eligible
    if origin['simulator_version']!=SIMULATOR_VERSION or origin['management_contract']!=management_contract():
        raise DataUnavailable('FROZEN_ENGINE_CONFIG_MISMATCH')
    snapshot=enforce_asof(raw_snapshot,evaluation)
    at=parse_timestamp(evaluation).astimezone(TZ_EASTERN).date()
    expiry=date.fromisoformat(current['expiration'])
    expired=at>expiry or (at==expiry and parse_timestamp(evaluation).astimezone(TZ_EASTERN).hour>=16)
    if expired and raw_snapshot.get('settlement'):
        settlement=raw_snapshot['settlement']
        if settlement['expiration']!=current['expiration'] or parse_timestamp(settlement['available_at'])>parse_timestamp(evaluation) or parse_timestamp(settlement['timestamp'])>parse_timestamp(evaluation) or not settlement.get('coverage_verified'):
            raise DataUnavailable('EXPIRY_SETTLEMENT_UNAVAILABLE')
        spot=float(settlement['price'])
        assigned=spot>=current['strike']
        # Terminal assignment is mechanical, and policy violations are reported.
        floor=origin['policy'].get('acceptable_assignment_min_price')
        allowed=(origin['policy'].get('assignment_policy') or {}).get('allowed',True)
        violation=assigned and (not allowed or (floor is not None and current['strike']<floor))
        return dict(action='ASSIGNED' if assigned else 'EXPIRED_OTM',reason='verified expiry settlement',
            quote=None,snapshot=snapshot,terminal_spot=spot,assignment_policy_violation=violation,
            policy_action='ALLOW_ASSIGNMENT' if assigned else 'HOLD_CALL')
    if expired:raise DataUnavailable('EXPIRY_SETTLEMENT_UNAVAILABLE')
    ctx,quote=context_for(origin,current,snapshot,evaluation)
    action,reason=evaluate_cc_management_state(ctx)
    target=None
    if action.startswith('ROLL_'):
        expirations=sorted({q['expiration'] for q in snapshot['options'] if action!='ROLL_OUT' or q['expiration']>current['expiration']})
        stock=SimpleNamespace(options=expirations,option_chain=lambda exp:SimpleNamespace(calls=pd.DataFrame([q for q in snapshot['options'] if q['expiration']==exp])))
        avoid_dates=[date.fromisoformat(e['date']) for e in ctx.risk_events if e.get('severity')=='avoid']
        selected=_suggest_next_call(stock,snapshot['spot']*1.03 if action=='ROLL_OUT' else max(current['strike'],snapshot['spot']*1.01),
            snapshot['spot'],hv_forecast=snapshot.get('hv_forecast',origin['hv_forecast']),mu=snapshot.get('mu_center',origin['mu']),existing_call_mark=(quote['bid']+quote['ask'])/2,
            roll_type=action,risk_event_date=max(avoid_dates) if avoid_dates else None,
            existing_expiry_date=expiry,existing_strike=current['strike'],lot_schedule=origin['lot_schedule'],
            current_tax_friction=ctx.assignment_tax_friction,assignment_price=current['strike'],as_of=at)
        if selected is None:raise DataUnavailable('ROLL_TARGET_UNAVAILABLE')
        target=next(q for q in snapshot['options'] if q['expiration']==selected['expiry'] and q['strike']==selected['strike'])
    # ALLOW_ASSIGNMENT means allow eventual expiry; it is not an early exercise prediction.
    return dict(action=action,reason=reason,quote=quote,target=target,snapshot=snapshot,
                policy_context={k:(v.isoformat() if isinstance(v,date) else v) for k,v in vars(ctx).items() if k!='tax_friction_detail'},policy_action=action)


def record_interval(db,chain_id,evaluation,snapshot_id,reason,details):
    db.execute('INSERT OR IGNORE INTO cc_virtual_intervals VALUES(?,?,?,?,?,?)',
        (digest([chain_id,stamp(evaluation),reason]),chain_id,stamp(evaluation),snapshot_id,reason,json.dumps(details,sort_keys=True)))


def terminal_outcome(db,origin,current,chain_id,snapshot_id,evaluation):
    shares=current['contracts']*100
    cash_pnl=current['option_cash_total']-current['fees_total']
    alpha=(cash_pnl-current['assignment_cost_total']-current['management_cost_total'])/shares
    intervals=db.execute('SELECT count(*) FROM cc_virtual_intervals WHERE chain_id=?',(chain_id,)).fetchone()[0]
    source='PROSPECTIVE_VIRTUAL' if origin['prospective'] else 'ESTIMATED_COUNTERFACTUAL'
    version_censored=current['status']=='VERSION_CENSORED'
    data_censored=bool(intervals or current['coverage_censored'])
    any_censored=bool(version_censored or data_censored)
    outcome=base(origin['episode_id'],source,origin['entry_timestamp'],stamp(evaluation),origin['market_snapshot_lineage'],
                 dict(state=current,snapshot_id=snapshot_id,intervals=intervals))
    outcome.update(chain_identifier=chain_id,simulator_version=origin['simulator_version'],model_version=origin['model_version'],
        config_hash=origin['config_hash'],promotion_policy_version=origin['promotion_policy_version'],origin_git_sha=origin['origin_git_sha'],
        simulator_contract_hash=origin.get('simulator_contract_hash'),
        simulator_contract_version=origin.get('simulator_contract_version'),
        execution_source='VIRTUAL_MODEL',management_source='SHARED_DETERMINISTIC_POLICY',price_path_source='CAPTURED_ASOF_SNAPSHOTS',
        cost_source='VERSIONED_MODEL',assignment_source='MODELED_EXPIRY_SETTLEMENT',
        prospective=origin['prospective'],complete=True,censored=any_censored,
        version_censored=version_censored,promotion_eligible=not any_censored,
        censor_source='SIMULATOR_CONTRACT_CHANGE' if version_censored else ('DATA_QUALITY' if data_censored else None),
        market_data_coverage_verified=not data_censored,
        chain_censored=any_censored,data_quality_unresolved=data_censored,
        terminal_state=current['status'],total_option_pnl=cash_pnl,economic_share_basis='COVERED_SHARES',
        covered_shares=shares,origin_holding_shares=origin.get('origin_holding_shares'),
        cc_incremental_alpha=alpha,realized_execution_cost=current['execution_cost_total']/shares,
        realized_management_cost=current['management_cost_total']/shares,assignment_policy_violation=current['assignment_policy_violation'],
        roll_hops=current['roll_hops'],rolled=current['roll_hops']>0,total_fees=current['fees_total'],
        comparison_horizon=parse_timestamp(evaluation).astimezone(TZ_EASTERN).date().isoformat(),
        chain_hold_return=current.get('terminal_spot',origin['entry_spot'])/origin['entry_spot']-1,
        cc_strategy_return=current.get('terminal_spot',origin['entry_spot'])/origin['entry_spot']-1+alpha/origin['entry_spot'],
        source_snapshot_ids=[r[0] for r in db.execute('SELECT snapshot_id FROM cc_virtual_actions WHERE chain_id=?',(chain_id,))])
    if source=='ESTIMATED_COUNTERFACTUAL':
        return outcome
    persist(db,origin['episode_id'],origin['candidate_id'],origin.get('arm','challenger'),outcome)
    return outcome


def censor_version_mismatch(db,chain_id,current_contract_hash,evaluation):
    """Close an open chain because the simulator contract changed.

    Idempotent: if the chain is already not OPEN/AWAIT_ASSIGNMENT, does nothing.
    Exactly one VERSION_CENSORED action is written; subsequent scheduler runs see
    terminal=True and skip the chain.
    """
    evaluation=stamp(evaluation)
    with db:
        current=state(db,chain_id)
        if current['status'] not in ('OPEN','AWAIT_ASSIGNMENT'):
            return dict(terminal=True)
        chain=db.execute('SELECT * FROM cc_virtual_chains WHERE id=?',(chain_id,)).fetchone()
        origin=json.loads(chain['origin_json']);origin['arm']=chain['arm']
        after=dict(current,status='VERSION_CENSORED')
        action_id=digest([chain_id,evaluation,'VERSION_CENSORED'])
        audit=dict(action='VERSION_CENSORED',reason='simulator_contract_changed',
            evaluation_timestamp=evaluation,state_before=current,state_after=after,
            origin_contract_hash=origin.get('simulator_contract_hash',''),
            current_contract_hash=current_contract_hash,
            censor_source='SIMULATOR_CONTRACT_CHANGE',promotion_eligible=False,
            outcome_source='PROSPECTIVE_VIRTUAL',simulator_version=origin['simulator_version'],
            model_version=origin['model_version'],config_hash=origin['config_hash'])
        db.execute('INSERT OR IGNORE INTO cc_virtual_actions VALUES(?,?,?,?,?,?)',
            (action_id,chain_id,evaluation,'','VERSION_CENSORED',json.dumps(audit,sort_keys=True)))
        write_state(db,chain_id,evaluation,after)
        terminal_outcome(db,origin,after,chain_id,None,evaluation)
    return dict(action='VERSION_CENSORED',chain_id=chain_id,status='VERSION_CENSORED')


def missed_intervals(db,chain_id,start,end,cadence):
    """Conservative weekday scheduler calendar; uncertain closures stay censored."""
    first=parse_timestamp(start).astimezone(TZ_EASTERN)
    last=parse_timestamp(end).astimezone(TZ_EASTERN)
    observed=[parse_timestamp(r[0]).astimezone(TZ_EASTERN) for r in db.execute('SELECT evaluation_timestamp FROM cc_virtual_actions WHERE chain_id=?',(chain_id,))]
    missing=[];day=first.date()
    from datetime import datetime
    while day<=last.date():
        if day.weekday()<5:
            minute=9*60+15
            while minute<=16*60+15:
                tick=datetime(day.year,day.month,day.day,minute//60,minute%60,tzinfo=TZ_EASTERN)
                if first<tick<last-timedelta(minutes=5) and not any(abs((o-tick).total_seconds())<=300 for o in observed):missing.append(tick)
                minute+=max(1,cadence)
        day+=timedelta(days=1)
    return missing


def advance(db,chain_id,snapshot_id,evaluation,cycle_key=None):
    evaluation=stamp(evaluation)
    db.execute('BEGIN IMMEDIATE')
    try:
        existing=db.execute('SELECT action_json FROM cc_virtual_actions WHERE chain_id=? AND evaluation_timestamp=?',(chain_id,evaluation)).fetchone()
        if cycle_key is not None:
            previous=db.execute("SELECT action_json FROM cc_virtual_actions WHERE chain_id=? AND json_extract(action_json,'$.cycle_key')=?",(chain_id,cycle_key)).fetchone()
            if previous:existing=previous
        if existing:db.rollback();return dict(duplicate=True,action=json.loads(existing[0])['action'])
        chain=db.execute('SELECT * FROM cc_virtual_chains WHERE id=?',(chain_id,)).fetchone()
        origin=json.loads(chain['origin_json']);origin['arm']=chain['arm']
        current=state(db,chain_id)
        if current['status'] not in ('OPEN','AWAIT_ASSIGNMENT'):db.rollback();return dict(terminal=True)
        if parse_timestamp(evaluation)<=parse_timestamp(current['last_evaluation']):raise DataUnavailable('NON_FORWARD_TIMESTAMP')
        record=db.execute('SELECT snapshot_json FROM cc_market_snapshots WHERE id=?',(snapshot_id,)).fetchone()
        if not record:raise DataUnavailable('MISSING_MARKET_SNAPSHOT')
        raw=json.loads(record[0])
        if raw['ticker']!=origin['ticker']:raise DataUnavailable('SNAPSHOT_TICKER_MISMATCH')
        proposal=evaluate_snapshot(origin,current,raw,evaluation)
        missing=missed_intervals(db,chain_id,origin['entry_timestamp'],evaluation,origin['config']['virtual']['cadence_minutes'])
        if missing:
            record_interval(db,chain_id,missing[0].isoformat(),None,'MISSED_SCHEDULED_INTERVAL',{'missing_n':len(missing),'last_missing':missing[-1].isoformat(),'calendar':'weekday-conservative-1','censored':True})
        after=dict(current)
        after['last_evaluation']=evaluation
        action=proposal['action']
        fills=[]
        if action=='BUY_TO_CLOSE' or action.startswith('ROLL_'):
            fills.append(('BTC',fill_model(proposal['quote'],current['contracts'],'BUY',origin['config'],evaluation)))
            if after['first_intervention'] is None:after['first_intervention']=evaluation
            after['management_cost_total']+=origin['config']['management_cost_per_contract']*current['contracts']
            if action.startswith('ROLL_'):
                target=proposal['target']
                fills.append(('STO',fill_model(target,current['contracts'],'SELL',origin['config'],evaluation,origin['frozen_fill_fraction'])))
                after.update(strike=target['strike'],expiration=target['expiration'],leg_entry_premium=fills[-1][1]['price'],leg_entry_timestamp=evaluation,roll_hops=current['roll_hops']+1,status='OPEN')
            else:after.update(status='CLOSED_BTC',terminal_spot=proposal['snapshot']['spot'])
        elif action in ('ASSIGNED','EXPIRED_OTM'):
            after.update(status=action,terminal_spot=proposal['terminal_spot'],assignment_policy_violation=proposal['assignment_policy_violation'])
            if action=='ASSIGNED':after['assignment_cost_total']+=max(0.,proposal['terminal_spot']-current['strike'])*current['contracts']*100
        elif action=='ALLOW_ASSIGNMENT':after['status']='AWAIT_ASSIGNMENT'
        for leg,fill in fills:
            after['option_cash_total']+=fill['cash_flow_total'];after['fees_total']+=fill['fees_total']
            after['execution_cost_total']+=fill['execution_cost_total']
        after['coverage_censored']=bool(after['coverage_censored'] or not proposal['snapshot']['coverage_verified'] or not proposal['snapshot']['quote_timing_verified'])
        action_id=digest([chain_id,evaluation])
        audit=dict(cycle_key=cycle_key,action=action,reason=proposal['reason'],evaluation_timestamp=evaluation,
            state_before=current,state_after=after,policy_snapshot=origin['policy'],policy_context=proposal.get('policy_context'),
            simulator_version=origin['simulator_version'],model_version=origin['model_version'],config_hash=origin['config_hash'],
            origin_git_sha=origin['origin_git_sha'],snapshot_id=snapshot_id,outcome_source='PROSPECTIVE_VIRTUAL' if origin['prospective'] else 'ESTIMATED_COUNTERFACTUAL',
            resulting_strike=after['strike'],resulting_expiration=after['expiration'],modeled_fill_inputs=[f for _,f in fills])
        db.execute('INSERT INTO cc_virtual_actions VALUES(?,?,?,?,?,?)',(action_id,chain_id,evaluation,snapshot_id,action,json.dumps(audit,sort_keys=True)))
        for leg,fill in fills:db.execute('INSERT INTO cc_virtual_fills VALUES(?,?,?,?,?)',(action_id+':'+leg,chain_id,action_id,leg,json.dumps(fill,sort_keys=True)))
        write_state(db,chain_id,evaluation,after)
        if after['status'] not in ('OPEN','AWAIT_ASSIGNMENT'):terminal_outcome(db,origin,after,chain_id,snapshot_id,evaluation)
        db.commit()
        return dict(action=action,chain_id=chain_id,status=after['status'])
    except DataUnavailable as exc:
        db.rollback()
        with db:record_interval(db,chain_id,evaluation,snapshot_id,str(exc),{'outcome_source':'PROSPECTIVE_VIRTUAL','censored':True})
        return dict(unavailable=True,reason=str(exc),chain_id=chain_id)
    except Exception:
        db.rollback()
        raise


def metrics(db):
    chains=[]
    for row in db.execute('SELECT * FROM cc_virtual_chains WHERE simulation_kind="PROSPECTIVE" ORDER BY created_at DESC'):
        current=state(db,row['id'])
        origin=json.loads(row['origin_json'])
        intervals=[dict(r) for r in db.execute('SELECT * FROM cc_virtual_intervals WHERE chain_id=?',(row['id'],))]
        chains.append(dict(chain_id=row['id'],episode_id=row['episode_id'],ticker=origin['ticker'],state=current,
                          outcome_source='PROSPECTIVE_VIRTUAL',simulator_version=origin['simulator_version'],
                          simulator_contract_hash=origin.get('simulator_contract_hash'),
                          simulator_contract_version=origin.get('simulator_contract_version'),
                          config_hash=origin['config_hash'],origin_git_sha=origin['origin_git_sha'],censored_intervals=len(intervals),
                          actions=[json.loads(r[0]) for r in db.execute('SELECT action_json FROM cc_virtual_actions WHERE chain_id=? ORDER BY evaluation_timestamp',(row['id'],))]))
    completed_outcomes=[]
    from covered_call_outcomes import latest
    for chain in chains:
        outcome=latest(db,chain['episode_id'],'challenger')
        if outcome and outcome['outcome_source']=='PROSPECTIVE_VIRTUAL':completed_outcomes.append(outcome)
    eligible=[o for o in completed_outcomes if o.get('complete') and not o.get('censored')]
    version_censored_n=sum(bool(o.get('version_censored')) for o in completed_outcomes)
    return dict(virtual_economics=dict(outcome_source='PROSPECTIVE_VIRTUAL',n=len(eligible),censored_n=sum(bool(o.get('censored')) for o in completed_outcomes),
                version_censored_n=version_censored_n,
                modeled_incremental_alpha_mean=sum(o['cc_incremental_alpha'] for o in eligible)/len(eligible) if eligible else None,units='USD_PER_SHARE'),
                open_chains=sum(c['state']['status'] in ('OPEN','AWAIT_ASSIGNMENT') for c in chains),
                completed_chains=sum(c['state']['status'] not in ('OPEN','AWAIT_ASSIGNMENT') for c in chains),
                version_censored_chains=sum(c['state']['status']=='VERSION_CENSORED' for c in chains),
                censored_intervals=sum(c['censored_intervals'] for c in chains),
                errors=db.execute("SELECT count(*) FROM cc_virtual_intervals WHERE reason='CAPTURE_OR_CYCLE_ERROR'").fetchone()[0],chains=chains,
                simulator_version=SIMULATOR_VERSION,simulator_contract_version=SIMULATOR_CONTRACT_VERSION)
