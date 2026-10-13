"""Immutable covered-call evidence, actual fills, path labels and promotion state.

Features never change. Append-only outcome revisions remain separate. Counterfactual
expiry economics are estimated; actual chain economics require reconciled fills.
"""
from __future__ import annotations
import hashlib
import json
import math
from time_utils import today_eastern, now_utc
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, date, timezone
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parent


def clean(value):
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)): return [clean(v) for v in value]
    if isinstance(value,float): return value if math.isfinite(value) else None
    if hasattr(value,'item'): return clean(value.item())
    return value


def config_digest(config):
    return hashlib.sha256(encode({k:v for k,v in config.items() if k!='mode'}).encode()).hexdigest()


def encode(value): return json.dumps(clean(value),sort_keys=True,allow_nan=False,separators=(',',':'))


def connect(path=None):
    if path is None:
        import agent_db
        path=agent_db.DB_PATH
    db=sqlite3.connect(str(path),timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS cc_decisions(
      id TEXT PRIMARY KEY, ticker TEXT NOT NULL, run_id TEXT, timestamp TEXT NOT NULL,
      cohort_key TEXT NOT NULL, git_sha TEXT NOT NULL, config_hash TEXT NOT NULL,
      model_version TEXT NOT NULL, policy_json TEXT NOT NULL, config_json TEXT NOT NULL,
      champion_json TEXT NOT NULL, challenger_json TEXT NOT NULL, divergence TEXT NOT NULL,
      prospective INTEGER NOT NULL DEFAULT 1);
    CREATE INDEX IF NOT EXISTS cc_decisions_cohort ON cc_decisions(cohort_key);
    CREATE TABLE IF NOT EXISTS cc_candidates(
      episode_id TEXT NOT NULL REFERENCES cc_decisions(id), candidate_id TEXT NOT NULL,
      features_json TEXT NOT NULL, selected_v2 INTEGER NOT NULL, selected_v3 INTEGER NOT NULL,
      PRIMARY KEY(episode_id,candidate_id));
    CREATE TABLE IF NOT EXISTS cc_labels(
      id INTEGER PRIMARY KEY, episode_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
      labeled_at TEXT NOT NULL, labels_json TEXT NOT NULL, source_hash TEXT NOT NULL,
      UNIQUE(episode_id,candidate_id,source_hash),
      FOREIGN KEY(episode_id,candidate_id) REFERENCES cc_candidates(episode_id,candidate_id));
    CREATE TABLE IF NOT EXISTS cc_fills(
      id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      FOREIGN KEY(episode_id,candidate_id) REFERENCES cc_candidates(episode_id,candidate_id));
    CREATE TABLE IF NOT EXISTS cc_chain_costs(
      id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES cc_decisions(id),
      trade_chain_id TEXT NOT NULL, timestamp TEXT NOT NULL, evidence_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cc_scorer_state(
      singleton INTEGER PRIMARY KEY CHECK(singleton=1), scorer TEXT NOT NULL,
      snapshot_json TEXT NOT NULL);
    INSERT OR IGNORE INTO cc_scorer_state VALUES(1,'v2','{}');
    CREATE TABLE IF NOT EXISTS cc_promotions(
      id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, snapshot_json TEXT NOT NULL);
    ''')
    for table in ('cc_decisions','cc_candidates','cc_labels','cc_fills','cc_promotions','cc_chain_costs'):
        for action in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable CC evidence'); END")
    db.commit()


def record_episode(ticker,run_id,rows,champion,challenger,policy,config,timestamp=None,path=None):
    from covered_call_v3 import VERSION,divergence
    db=connect(path);migrate(db)
    timestamp=timestamp or now_utc().isoformat()
    sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    cfg_hash=config_digest(config)
    episode=str(uuid.uuid4())
    champion=dict(champion)
    if champion.get('action')=='SELL_CC':
        champion['trade_chain_id']=f"cc-{ticker}-{int(champion['strike'])}-{champion['expiration']}-{episode}"
    cohort=f'{ticker}:{timestamp[:10]}'
    def selected(row,decision):
        return int(decision.get('action')=='SELL_CC' and row['strike']==decision.get('strike') and row['expiration']==decision.get('expiration'))
    with db:
        db.execute('INSERT INTO cc_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
            (episode,ticker,str(run_id),timestamp,cohort,sha,cfg_hash,VERSION,encode(policy),encode(config),encode(champion),encode(challenger),divergence(champion,challenger)))
        for r in rows:
            cid=f"{ticker}:{r['expiration'].replace('-','')}:{float(r['strike']):g}"
            features=dict(r,champion_contracts=champion.get('contracts',0) if selected(r,champion) else None,
                          champion_overwrite_fraction=champion.get('overwrite_fraction') if selected(r,champion) else None,
                          selected_action='SELL_CC' if selected(r,champion) else 'ALTERNATIVE')
            db.execute('INSERT INTO cc_candidates VALUES(?,?,?,?,?)',(episode,cid,encode(features),selected(r,champion),selected(r,challenger)))
    db.close();return episode


def surface_history(ticker,path=None):
    db=connect(path);migrate(db)
    rows=db.execute('SELECT c.features_json FROM cc_candidates c JOIN cc_decisions d ON d.id=c.episode_id WHERE d.ticker=? ORDER BY d.timestamp DESC LIMIT 10000',(ticker,)).fetchall()
    db.close();return [json.loads(r[0]) for r in rows]


def execution_history(path=None):
    db=connect(path);migrate(db)
    rows=[json.loads(r[0]) for r in db.execute('SELECT payload_json FROM cc_fills')]
    db.close();return rows


def record_fill(fill_id,episode,candidate,fill,bid,ask,execution_timestamp,fees=0.,
                underlying_at_rec=None,underlying_at_fill=None,quote_timestamp=None,path=None,connection=None):
    """Actual broker/manual fill only, against a contemporaneous execution quote."""
    from covered_call_v3 import execution
    values=(fill,bid,ask,fees)
    if not all(math.isfinite(float(v)) for v in values) or ask<bid or bid<=0 or fees<0:
        raise ValueError('invalid actual fill quote')
    if not quote_timestamp: raise ValueError('contemporaneous quote_timestamp required')
    et=datetime.fromisoformat(execution_timestamp); qt=datetime.fromisoformat(quote_timestamp)
    if et.tzinfo is None or qt.tzinfo is None or abs((et-qt).total_seconds())>300:
        raise ValueError('execution quote must be timezone-aware and within 5 minutes of fill')
    fraction=(fill-bid)/(ask-bid) if ask>bid else None
    bucket=execution(dict(bid=bid,ask=ask))['execution_bucket']
    db=connection or connect(path)
    if connection is None:migrate(db)
    candidate_row=db.execute('SELECT features_json FROM cc_candidates WHERE episode_id=? AND candidate_id=?',(episode,candidate)).fetchone()
    if candidate_row is None:
        if connection is None:db.close()
        raise ValueError('unknown CC fill candidate')
    rec_features=json.loads(candidate_row[0])
    payload=dict(recommendation_features={k:rec_features.get(k) for k in ('bid','ask','mid','dte','delta','otm_pct','impliedVolatility','openInterest','volume','quote_timestamp')},actual=True,fill=fill,bid=bid,ask=ask,mid=(bid+ask)/2,
                 fill_fraction=fraction,bucket=bucket,execution_timestamp=execution_timestamp,
                 quote_timestamp=quote_timestamp,fees=fees,underlying_at_rec=underlying_at_rec,
                 underlying_at_fill=underlying_at_fill,underlying_move=underlying_at_fill-underlying_at_rec if underlying_at_fill is not None and underlying_at_rec is not None else None)
    db.execute('INSERT INTO cc_fills VALUES(?,?,?,?)',(str(fill_id),episode,candidate,encode(payload)))
    if connection is None:db.commit();db.close()
    return payload


def label_path(features,bars,as_of=None,chain=None,chain_id=None):
    """Daily observed high/low; delta is reconstructed at daily closes with entry IV.

    Missing sessions or incomplete chains are censored. A daily high does not
    identify intraday delta; reconstructed threshold events are labeled separately.
    """
    from covered_call_rec import call_delta
    as_of=as_of or today_eastern()
    expiry=date.fromisoformat(features['expiration'])
    start=date.fromisoformat(features['quote_timestamp'][:10])
    # Decision-day daily high may precede the decision; never use it as future data.
    path=[b for b in bars if start<date.fromisoformat(str(b['date'])[:10])<=min(as_of,expiry)]
    complete=bool(path and date.fromisoformat(str(path[-1]['date'])[:10])>=expiry)
    expected_sessions=sum((start.toordinal()+i and date.fromordinal(start.toordinal()+i).weekday()<5) for i in range(1,(min(as_of,expiry)-start).days+1))
    # Provider marks verified exchange-session coverage (weekdays alone include holidays).
    coverage=bool(path and all(b.get('coverage_verified',False) for b in path))
    complete=complete and coverage
    # If a path starts ITM, the initial touch and delta events are already known.

    high=max((float(b['high']) for b in path),default=None)
    low=min((float(b['low']) for b in path),default=None)
    def event(barrier):
        hits=[b for b in path if float(b['high'])>=barrier]
        if features['spot'] >= barrier:return True,0
        return (True if hits else False if complete else None,
                (date.fromisoformat(str(hits[0]['date'])[:10])-start).days if hits else None)
    touched,first=event(features['strike'])
    regret,_=event(features['strike']+features['exec_premium'])
    deltas=[(b,call_delta(float(b['close']),features['strike'],max(0,(expiry-date.fromisoformat(str(b['date'])[:10])).days)/365,features['impliedVolatility'])) for b in path]
    output=dict(censored=not complete,path_complete=complete,path_coverage_verified=coverage,
        observed_sessions=len(path),expected_weekdays=expected_sessions,
        maximum_underlying_price=high,minimum_underlying_price=low,
        strike_touched=touched,regret_barrier_touched=regret,ever_itm=touched,
        days_to_first_touch=first,maximum_reconstructed_delta=max((d for _,d in deltas),default=None),
        delta_source='RECONSTRUCTED_DAILY_CLOSE_ENTRY_IV',path_source='OBSERVED_DAILY_OHLC',
        label_model_version='cc-path-label-1',trade_chain_id=chain_id)
    for threshold in (.30,.50):
        hits=[b for b,d in deltas if d>=threshold]
        initial=call_delta(features['spot'],features['strike'],max(0,(expiry-start).days)/365,features['impliedVolatility'])>=threshold
        output[f'delta{int(threshold*100)}_event']=True if initial or hits else False if complete else None
        output[f'days_to_delta{int(threshold*100)}']=0 if initial else (date.fromisoformat(str(hits[0]['date'])[:10])-start).days if hits else None
    if complete:
        final=float(path[-1]['close']);spot=features['spot'];premium=features['exec_premium']
        alpha=premium-max(0.,final-features['strike'])
        output.update(estimated_expiry_incremental_alpha=alpha,
            estimated_hold_return=final/spot-1,
            estimated_cc_return=(min(final,features['strike'])+premium)/spot-1,
            maximum_forgone_upside=max(0.,high-features['strike']-premium),expired_otm=final<features['strike'])
    output.update(rolled=None,assigned=None,btc=None,total_option_pnl=None,cc_incremental_alpha=None,
                  chain_censored=True,roll_hops=None,roll_net_credit=None,total_fees=None,days_to_roll=None)
    if chain is not None:
        rolls=[x for x in chain if x['action'] in ('ROLL_CC','ROLL_UP','ROLL_OUT','ROLL_UP_AND_OUT')]
        terminal=any(x['action'] in ('ASSIGNED','EXPIRED') or (x['action'] in ('BTC','BUY_TO_CLOSE') and x.get('recommendation_action') not in ('ROLL_UP','ROLL_OUT','ROLL_UP_AND_OUT')) for x in chain)
        # Cash legs must be reconciled; never use recommendation estimates as fills.
        roll_legs=[x for x in chain if x in rolls or x.get('recommendation_action') in ('ROLL_CC','ROLL_UP','ROLL_OUT','ROLL_UP_AND_OUT')]
        reconciled=terminal and all(x.get('actual') and x.get('option_cash_flow') is not None and x.get('fees') is not None for x in chain)
        output.update(rolled=bool(rolls),roll_hops=len(rolls),assigned=any(x['action']=='ASSIGNED' for x in chain),
            btc=any(x['action'] in ('BTC','BUY_TO_CLOSE') for x in chain),chain_censored=not reconciled,
            days_to_roll=(date.fromisoformat(rolls[0]['execution_date'][:10])-start).days if rolls else None,
            roll_net_credit=sum(x['option_cash_flow'] for x in roll_legs) if roll_legs and all(x.get('option_cash_flow') is not None for x in roll_legs) else None,
            total_fees=sum(x['fees'] for x in chain) if reconciled else None)
        if reconciled:
            pnl=sum(x['option_cash_flow']-x['fees'] for x in chain)
            output['total_option_pnl']=pnl
            # Actual assignment equity cost must be supplied/reconciled too.
            assigned=output['assigned']
            assigned_costs=[x.get('equity_opportunity_cost') for x in chain if x['action']=='ASSIGNED']
            delivered_shares=(features.get('champion_contracts') or features.get('recommended_contracts') or 0)*100
            if not delivered_shares:delivered_shares=features.get('shares_potentially_delivered',0)
            if delivered_shares>0 and (not assigned or all(x is not None for x in assigned_costs)):
                output['cc_incremental_alpha']=(pnl-sum(assigned_costs))/delivered_shares
                terminal_price=chain[-1].get('underlying_price')
                if terminal_price is not None:
                    output['chain_hold_return']=terminal_price/features['spot']-1
                    output['cc_strategy_return']=output['cc_incremental_alpha']/features['spot']+output['chain_hold_return']
                    output['chain_return_horizon']=chain[-1]['execution_date']
    return output


def record_chain_costs(episode,chain_id,management_cost,execution_cost,assignment_cost,
                       assignment_policy_violation,shares,terminal_underlying_price,source,
                       timestamp=None,path=None):
    """Reconciled measured costs, dollars TOTAL, with explicit human/broker source.

    Execution cost includes fees and measured slippage; assignment cost is equity
    opportunity cost against holding at chain close. No defaults for unknown costs.
    """
    values=(management_cost,execution_cost,assignment_cost,shares,terminal_underlying_price)
    if not source or any(x is None or not math.isfinite(float(x)) for x in values):
        raise ValueError('complete reconciled cost evidence and source required')
    if management_cost<0 or shares<=0 or terminal_underlying_price<=0 or not isinstance(assignment_policy_violation,bool):
        raise ValueError('invalid reconciled chain evidence')
    db=connect(path);migrate(db)
    decision=db.execute('SELECT champion_json FROM cc_decisions WHERE id=?',(episode,)).fetchone()
    if decision is None or json.loads(decision[0]).get('trade_chain_id')!=chain_id:
        db.close();raise ValueError('chain must match originating decision')
    evidence=dict(management_cost_total=management_cost,execution_cost_total=execution_cost,
        assignment_cost_total=assignment_cost,assignment_policy_violation=assignment_policy_violation,
        shares=shares,terminal_underlying_price=terminal_underlying_price,source=source,
        units='USD_TOTAL',cost_source='RECONCILED_OBSERVATION')
    stamp=timestamp or now_utc().isoformat()
    with db:db.execute('INSERT INTO cc_chain_costs VALUES(?,?,?,?,?)',(str(uuid.uuid4()),episode,chain_id,stamp,encode(evidence)))
    db.close();return evidence


def append_label(episode,candidate,labels,source,path=None):
    db=connect(path);migrate(db)
    h=hashlib.sha256(encode({'source':source,'labels':labels}).encode()).hexdigest()
    with db:db.execute('INSERT OR IGNORE INTO cc_labels(episode_id,candidate_id,labeled_at,labels_json,source_hash) VALUES(?,?,?,?,?)',
        (episode,candidate,now_utc().isoformat(),encode(labels),h))
    db.close()


def calibration(samples,predicted,event,min_n=20):
    usable=[(float(f[predicted]),bool(l[event])) for f,l in samples if f.get(predicted) is not None and l.get(event) is not None and not l.get('censored',True)]
    buckets=[]
    for i in range(5):
        rows=[(p,y) for p,y in usable if min(4,int(p*5))==i]
        n=len(rows)
        buckets.append(dict(band=[i/5,(i+1)/5],n=n,predicted=sum(p for p,y in rows)/n if n else None,
                            frequency=sum(y for p,y in rows)/n if n else None,minimum_n_met=n>=min_n))
    n=len(usable)
    return dict(n=n,minimum_n=min_n,minimum_n_met=n>=min_n,brier=sum((p-y)**2 for p,y in usable)/n if n else None,
                reliability_error=sum(b['n']*abs(b['predicted']-b['frequency']) for b in buckets if b['n'])/n if n else None,buckets=buckets)


def report(path=None,limit=100):
    db=connect(path);migrate(db)
    decisions=[];samples=[];cohorts=defaultdict(list)
    # All rows feed cohort metrics, only detail output is bounded.
    rows=db.execute('SELECT * FROM cc_decisions ORDER BY timestamp DESC').fetchall()
    seen=set()
    for d in rows:
        decision=dict(d);decision['champion']=json.loads(d['champion_json']);decision['challenger']=json.loads(d['challenger_json'])
        candidates=[]; independent=d['cohort_key'] not in seen;seen.add(d['cohort_key'])
        decision['independent_cohort']=independent
        for r in db.execute('SELECT * FROM cc_candidates WHERE episode_id=?',(d['id'],)):
            f=json.loads(r['features_json'])
            l=db.execute('SELECT labels_json FROM cc_labels WHERE episode_id=? AND candidate_id=? ORDER BY id DESC LIMIT 1',(d['id'],r['candidate_id'])).fetchone()
            labels=json.loads(l[0]) if l else {'censored':True}
            candidates.append(dict(id=r['candidate_id'],features=f,labels=labels,selected_v2=bool(r['selected_v2']),selected_v3=bool(r['selected_v3'])))
            # Avoid counting all correlated alternatives as independent outcomes.
            if independent and r['selected_v2']:
                samples.append((f,labels))
                for key,value in [('dte',f"{int(f['dte'])//15*15}-{int(f['dte'])//15*15+14}"),
                    ('delta',f"{int(f['delta']*10)/10:.1f}"),('otm',f"{int(f.get('otm_pct',0)*20)*5}%"),
                    ('overwrite',str(decision['champion'].get('overwrite_fraction'))),
                    ('vrp',str(round(f.get('vrp_estimate') or 0,1))),('strategy',f.get('policy_snapshot',{}).get('strategy')),
                    ('regime',f.get('regime_state')),('divergence',d['divergence'])]:
                    cohorts[(key,value)].append((f,labels))
        decision['candidates']=candidates
        if len(decisions)<limit: decisions.append(decision)
    cohort_rows=[]
    for (key,value),items in cohorts.items():
        roll=[l['rolled'] for f,l in items if l.get('rolled') is not None and not l.get('chain_censored',True)]
        alpha=[l['cc_incremental_alpha'] for f,l in items if l.get('cc_incremental_alpha') is not None and not l.get('chain_censored',True)]
        cohort_rows.append(dict(dimension=key,bucket=value,n=len(items),eligible_n=sum(bool(f['eligible']) for f,l in items),
            censored_n=sum(l.get('censored',True) for f,l in items),roll_n=len(roll),roll_rate=sum(roll)/len(roll) if roll else None,
            alpha_n=len(alpha),incremental_alpha=sum(alpha)/len(alpha) if alpha else None))
    state=dict(db.execute('SELECT * FROM cc_scorer_state').fetchone());db.close()
    return dict(mode='observe_only' if state['scorer']=='v2' else 'promoted_v3',state=state,decisions=decisions,decision_n=len(rows),independent_n=len(seen),
        cohorts=cohort_rows,calibration={p:calibration(samples,p,e) for p,e in (
            ('strike_touch_prob','strike_touched'),('regret_barrier_touch_prob','regret_barrier_touched'),
            ('delta30_touch_prob','delta30_event'),('delta50_touch_prob','delta50_event'),('management_risk','rolled'))},
        management_risk_semantics='bounded management proxy; roll-frequency comparison is diagnostic, not a calibrated roll probability',
        sample_policy='latest decision per ticker/session; champion selected contract; management risk is a proxy, compared diagnostically with roll frequency')


def active_scorer(config,path=None):
    if config.get('mode')=='observe_only': return 'v2'
    if config.get('mode')!='evidence_gated': raise ValueError('invalid CC mode')
    db=connect(path);migrate(db)
    state=db.execute('SELECT * FROM cc_scorer_state').fetchone();db.close()
    if state['scorer']!='v3': return 'v2'
    snap=json.loads(state['snapshot_json'])
    sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    config_hash=config_digest(config)
    return 'v3' if snap.get('git_sha')==sha and snap.get('config_hash')==config_hash else 'v2'


def promotion_evidence(config,path=None):
    """Paired prospective same-opportunity comparisons, deduplicated by session.

    A missing challenger/hold outcome cannot count as a successful comparison.
    Evidence must match the current config and scorer before an explicit transition.
    """
    data=report(path,limit=100000);gate=config['promotion'];pairs=[]
    current_hash=config_digest(config)
    for d in data['decisions']:
        if not d['prospective'] or not d['independent_cohort'] or d['config_hash']!=current_hash or d['model_version']!=__import__('covered_call_v3').VERSION:continue
        selected={name:next((c for c in d['candidates'] if c['selected_'+key]),None) for name,key in [('champion','v2'),('challenger','v3')]}
        def outcome(name):
            if d[name]['action']=='NO_CALL':return dict(cc_incremental_alpha=0,rolled=False,expected_management_cost=0,assignment_policy_violation=False)
            c=selected[name]
            if not c or c['labels'].get('chain_censored',True) or c['labels'].get('censored',True):return None
            l=c['labels']
            required=('cc_incremental_alpha','realized_management_cost','assignment_policy_violation','realized_execution_cost')
            if any(l.get(k) is None for k in required):return None
            return l
        a,b=outcome('champion'),outcome('challenger')
        if a is not None and b is not None:
            pairs.append((d,a,b))
    n=len(pairs);divergent=sum(d['divergence'] not in ('SAME_NO_CALL','SAME_CONTRACT') for d,a,b in pairs)
    delta=sum(b['cc_incremental_alpha']-a['cc_incremental_alpha'] for d,a,b in pairs)/n if n else None
    roll_delta=sum(bool(b['rolled'])-bool(a['rolled']) for d,a,b in pairs)/n if n else None
    cost_delta=sum(b.get('realized_management_cost',0)-a.get('realized_management_cost',0) for d,a,b in pairs)/n if n else None
    violations=sum(bool(b.get('assignment_policy_violation')) for d,a,b in pairs)
    days=(date.fromisoformat(max(d['timestamp'][:10] for d,a,b in pairs))-date.fromisoformat(min(d['timestamp'][:10] for d,a,b in pairs))).days if n else 0
    calibrated=[(c['features'],c['labels']) for d,a,b in pairs for c in d['candidates'] if c['selected_v3']]
    cal=calibration(calibrated,'strike_touch_prob','strike_touched')
    failures=[]
    for ok,reason in [(n>=gate['minimum_n'],'MINIMUM_N'),(divergent>=gate['minimum_divergent_n'],'DIVERGENT_N'),(days>=gate['minimum_days'],'PROSPECTIVE_DURATION'),
        (delta is not None and delta>gate['minimum_alpha_improvement'],'ALPHA_IMPROVEMENT'),
        (roll_delta is not None and roll_delta<=gate['max_roll_rate_increase'],'ROLL_REGRESSION'),
        (cost_delta is not None and cost_delta<=gate['max_management_cost_increase'],'MANAGEMENT_COST_REGRESSION'),
        (violations<=gate['max_assignment_violations'],'ASSIGNMENT_VIOLATIONS'),
        (cal['n']>=gate['minimum_n'] and cal['brier'] is not None and cal['brier']<=gate['max_brier'],'CALIBRATION')]:
        if not ok:failures.append(reason)
    return dict(eligible=not failures,failures=failures,n=n,divergent_n=divergent,prospective_days=days,
                alpha_improvement=delta,roll_rate_delta=roll_delta,management_cost_delta=cost_delta,
                assignment_violations=violations,calibration=cal,config_hash=current_hash,
                gate_version=gate['version'],cohort_ids=[d['id'] for d,a,b in pairs])


def transition(scorer,config,path=None):
    if scorer not in ('v2','v3'):raise ValueError('unknown scorer')
    evidence=promotion_evidence(config,path)
    if scorer=='v3' and (config.get('mode')!='evidence_gated' or not evidence['eligible']):
        raise ValueError('V3 promotion gate not met: '+','.join(evidence['failures']))
    sha=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    snapshot=dict(evidence,scorer=scorer,git_sha=sha,model_version=__import__('covered_call_v3').VERSION)
    db=connect(path);migrate(db)
    with db:
        db.execute('INSERT INTO cc_promotions VALUES(?,?,?)',(str(uuid.uuid4()),now_utc().isoformat(),encode(snapshot)))
        db.execute('UPDATE cc_scorer_state SET scorer=?,snapshot_json=? WHERE singleton=1',(scorer,encode(snapshot)))
    db.close();return snapshot


def reconcile_chain(db,episode):
    """Join all actual executions through the originating SELL_CC trade_chain_id."""
    try:
        recs=db.execute("SELECT id,trade_chain_id,action_payload_json FROM recommendations WHERE action='SELL_CC'").fetchall()
        rec=next((r for r in recs if json.loads(r['action_payload_json'] or '{}').get('cc_episode_id')==episode),None)
        if rec is None:return None,None
        chain_id=rec['trade_chain_id']
        if not chain_id:return None,None
        rows=db.execute('''SELECT e.*,r.action AS recommendation_action FROM executed_actions e
            JOIN recommendations r ON r.id=e.recommendation_id
            WHERE r.trade_chain_id=? ORDER BY e.execution_date,e.id''',(chain_id,)).fetchall()
        chain=[]
        for r in rows:
            action=r['action'];premium=r['premium'] if r['premium'] is not None else r['execution_price']
            n=r['contracts']
            cash=None
            if action in ('SELL_CC','SELL_TO_OPEN') and premium is not None and n:cash=float(premium)*int(n)*100
            elif action=='BUY_TO_CLOSE' and premium is not None and n:cash=-float(premium)*int(n)*100
            elif action=='ALLOW_ASSIGNMENT':cash=0.;action='ASSIGNED'
            item=dict(action=action,actual=True,option_cash_flow=cash,fees=r['fees'],execution_date=r['execution_date'],
                      execution_id=r['id'],recommendation_action=r['recommendation_action'],
                      strike=r['strike'],contracts=n)
            chain.append(item)
        # Roll ledger has separate BTC/STO legs; identify a hop without counting terminal BTC.
        for item in chain:
            if item['recommendation_action'] in ('ROLL_UP','ROLL_OUT','ROLL_UP_AND_OUT') and item['action']=='SELL_TO_OPEN':
                item['action']=item['recommendation_action']
        # An explicit closed/expired position can establish terminal expiry; do not
        # infer expiry from elapsed time alone (position state is authoritative).
        if chain and not any(x['action'] in ('ASSIGNED',) or (x['action']=='BUY_TO_CLOSE' and x['recommendation_action'] not in ('ROLL_UP','ROLL_OUT','ROLL_UP_AND_OUT')) for x in chain):
            last=rows[-1]
            positions=db.execute("SELECT * FROM cc_positions WHERE ticker=? AND strike=? AND expiry=?",(last['ticker'],last['strike'],last['expiration'])).fetchall()
            pos=next((p for p in positions if p['status']=='expired' or p['close_type']=='EXPIRE'),None)
            if pos:chain.append(dict(action='EXPIRED',actual=True,option_cash_flow=0.,fees=0.,execution_date=pos['closed_date'] or pos['expiry']))
        return chain,chain_id
    except sqlite3.OperationalError:
        return None,None


def refresh_labels(path=None,as_of=None,fetch=None,dry_run=False):
    """Scheduled forward labels; SPY sessions verify daily coverage and holidays."""
    import yfinance as yf
    from datetime import timedelta
    as_of=as_of or today_eastern()
    def default_fetch(ticker,start,end):
        df=yf.Ticker(ticker).history(start=start.isoformat(),end=(end+timedelta(days=1)).isoformat(),auto_adjust=False)
        return [dict(date=idx.date().isoformat(),high=float(r['High']),low=float(r['Low']),close=float(r['Close'])) for idx,r in df.iterrows()]
    fetch=fetch or default_fetch
    db=connect(path);migrate(db);cache={};written=0;errors=[]
    rows=db.execute('SELECT c.*,d.ticker FROM cc_candidates c JOIN cc_decisions d ON d.id=c.episode_id').fetchall()
    for row in rows:
        try:
            f=json.loads(row['features_json'])
            if f.get('raw_quote_only'):continue
            start=date.fromisoformat(f['quote_timestamp'][:10]);expiry=date.fromisoformat(f['expiration'])
            if start>=as_of:continue
            # An existing complete label remains immutable; don't keep refetching.
            prior=db.execute('SELECT labels_json FROM cc_labels WHERE episode_id=? AND candidate_id=? ORDER BY id DESC LIMIT 1',(row['episode_id'],row['candidate_id'])).fetchone()
            if prior:
                prev=json.loads(prior[0])
                latest_cost=db.execute('SELECT evidence_json FROM cc_chain_costs WHERE episode_id=? ORDER BY timestamp DESC LIMIT 1',(row['episode_id'],)).fetchone()
                latest_evidence=json.loads(latest_cost[0]) if latest_cost else None
                if not prev.get('censored',True) and not prev.get('chain_censored',True) and prev.get('measured_cost_evidence')==latest_evidence:continue
            end=min(expiry,as_of-timedelta(days=1))
            key=(row['ticker'],start,end)
            if key not in cache:cache[key]=fetch(row['ticker'],start,end)
            spykey=('SPY',start,end)
            if spykey not in cache:cache[spykey]=fetch('SPY',start,end)
            reference={str(b['date'])[:10] for b in cache[spykey] if start.isoformat()<str(b['date'])[:10]<=end.isoformat()}
            observed={str(b['date'])[:10] for b in cache[key] if start.isoformat()<str(b['date'])[:10]<=end.isoformat()}
            verified=bool(reference) and reference<=observed
            bars=[dict(b,coverage_verified=verified) for b in cache[key]]
            chain,chain_id=reconcile_chain(db,row['episode_id']) if row['selected_v2'] else (None,None)
            measured=db.execute('SELECT evidence_json FROM cc_chain_costs WHERE episode_id=? ORDER BY timestamp DESC LIMIT 1',(row['episode_id'],)).fetchone()
            cost_evidence=json.loads(measured[0]) if measured else None
            if chain and cost_evidence:
                assignments=[x for x in chain if x['action']=='ASSIGNED']
                if assignments:
                    assignments[-1]['equity_opportunity_cost']=cost_evidence['assignment_cost_total']
                    for assignment in assignments[:-1]:assignment['equity_opportunity_cost']=0.
                chain[-1]['underlying_price']=cost_evidence['terminal_underlying_price']
            labels=label_path(f,bars,as_of,chain,chain_id)
            # Expiry may be holiday/weekend: last verified market session suffices.
            if end>=expiry and verified and reference and max(observed)>=max(reference):
                labels=label_path(f,bars,date.fromisoformat(max(reference)),chain,chain_id)
                # label_path's strict expiry check is deliberately relaxed only
                # with a verified reference session calendar, retaining provenance.
                if date.fromisoformat(max(reference))<expiry:
                    adjusted=dict(f,expiration=max(reference))
                    labels=label_path(adjusted,bars,as_of,chain,chain_id)
                    labels['expiry_calendar_adjustment']=max(reference)
            if cost_evidence and not labels.get('chain_censored',True):
                shares=cost_evidence['shares']
                labels.update(realized_management_cost=cost_evidence['management_cost_total']/shares,
                    realized_execution_cost=cost_evidence['execution_cost_total']/shares,
                    assignment_policy_violation=cost_evidence['assignment_policy_violation'],
                    measured_cost_evidence=cost_evidence)
                # Total option cash flows already include fees and execution fills.
                # Management labor is an additional economic cost, not another
                # deduction of measured execution slippage from actual cash flows.
                if labels.get('cc_incremental_alpha') is not None:
                    labels['cc_incremental_alpha']-=cost_evidence['management_cost_total']/shares
                    if labels.get('cc_strategy_return') is not None:
                        labels['cc_strategy_return']-=cost_evidence['management_cost_total']/shares/f['spot']
            if not dry_run:
                append_label(row['episode_id'],row['candidate_id'],labels,dict(bars=bars,chain=chain),path)
            written+=1
        except Exception as exc:
            errors.append(dict(episode=row['episode_id'],error=str(exc)))
    db.close();return dict(labeled=written,errors=errors,dry_run=dry_run)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['report','label','promotion','promote','rollback'])
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    from strategy_config import CC_V3_CONFIG
    if args.command=='report':result=report()
    elif args.command=='label':result=refresh_labels(dry_run=args.dry_run)
    elif args.command=='promotion':result=promotion_evidence(CC_V3_CONFIG)
    else:result=transition('v3' if args.command=='promote' else 'v2',CC_V3_CONFIG)
    print(json.dumps(result,indent=2))
