"""One persisted-state snapshot. No LLM, network, migration or decision writes."""
from __future__ import annotations
import json
import sqlite3
import re
from pathlib import Path
from datetime import datetime, timezone

from .contracts import ADVISOR_CONTRACT_VERSION, ADVISOR_POLICY_VERSION, SCORER_VERSION, digest
from portfolio_positions import _normalize
from strategy_config import LAYER_LABELS, LAYER_TARGETS
from time_utils import now_utc, TZ_EASTERN
from .sqlite_guard import read_only,READ_PRAGMAS
from .risk_snapshot import build_risk_snapshot


class ReadView:
    def __init__(self, conn): self.conn = conn
    @property
    def row_factory(self): return self.conn.row_factory
    @row_factory.setter
    def row_factory(self, value): self.conn.row_factory = value
    def execute(self, sql, parameters=()):
        token=sql.lstrip().split(None,1)[0].upper()
        if token not in {'SELECT','PRAGMA','WITH'}:
            raise ValueError('ADVISOR_READ_ONLY')
        if token=='PRAGMA':
            name=re.match(r'\s*PRAGMA\s+(\w+)',sql,re.I)
            if not name or name[1].lower() not in READ_PRAGMAS or '=' in sql:
                raise ValueError('ADVISOR_READ_ONLY_PRAGMA')
        return self.conn.execute(sql, parameters)


def rows(conn, table, suffix='', params=()):
    # Table names are internal constants, never request input.
    try:
        return [dict(r) for r in conn.execute('SELECT * FROM '+table+' '+suffix, params)]
    except sqlite3.OperationalError:
        return None


def semantic(value):
    if isinstance(value, dict):
        return {k:semantic(v) for k,v in value.items() if k not in {'captured_at','age_hours','since'}}
    if isinstance(value, list): return [semantic(v) for v in value]
    return value


def build_advisor_decision_context(conn, *, now=None, account_id=None):
    import portfolio_ai
    import agent_db
    from agents.opportunity_agent import rank_candidates
    previous_factory=conn.row_factory
    owns_snapshot=not conn.in_transaction
    if owns_snapshot: conn.execute('BEGIN')
    conn.row_factory=sqlite3.Row
    view=ReadView(conn)
    now=now or now_utc()
    try:
        with read_only(conn):
            return _build(view, now, account_id, portfolio_ai, agent_db, rank_candidates)
    finally:
        if owns_snapshot: conn.rollback()
        conn.row_factory=previous_factory


def _build(conn, now, account_id, brief_api, thesis_api, rank_candidates):
    holdings_rows=rows(conn,'holding_day','WHERE day=(SELECT MAX(day) FROM holding_day) ORDER BY ticker')
    holdings={}
    layers={v:k for k,v in LAYER_LABELS.items()}
    for h in holdings_rows or []:
        ticker=_normalize(h['ticker'])
        holdings[ticker]=dict(h, ticker=ticker, layer_num=layers.get(h.get('layer')), as_of=h.get('day'))
    lots=rows(conn,'cost_lots','ORDER BY ticker,purchase_date,id')
    if lots is not None: lots=[dict(l,ticker=_normalize(l['ticker'])) for l in lots]
    candidates=rows(conn,'candidate_universe','ORDER BY ticker')
    if candidates is not None: candidates=[dict(c,ticker=_normalize(c['ticker'])) for c in candidates]
    cc=rows(conn,'cc_positions',"WHERE status='open' ORDER BY id")
    if cc is not None: cc=[dict(c,ticker=_normalize(c['ticker'])) for c in cc]
    accounts=rows(conn,'trading_accounts','WHERE account_id=? ORDER BY account_id',(account_id,))
    account=next((a for a in accounts or [] if a['account_id']==account_id),None)
    positions=rows(conn,'position_snapshots','WHERE account_id=? ORDER BY symbol',(account_id,)) if account else None
    layer_rows=rows(conn,'layer_day','WHERE day=(SELECT MAX(day) FROM layer_day) ORDER BY layer')
    layer_weights={layers[r['layer']]:r['weight_pct'] for r in layer_rows or [] if r['layer'] in layers}
    risk_tables=build_risk_snapshot(conn,account_id,now=now)
    intents=risk_tables['trade_intents'] if account else None
    theses={}
    for ticker in sorted(set(holdings)|{_normalize(c['ticker']) for c in candidates or []}):
        try: theses[ticker]=thesis_api.get_thesis(ticker,conn=conn)
        except sqlite3.Error: theses[ticker]=None
    pipeline=rows(conn,'watchdog_receipts',"WHERE component='agent_pipeline' AND status='COMPLETE' ORDER BY completed_at DESC LIMIT 1")
    completed=pipeline[0]['completed_at'] if pipeline else None
    if isinstance(completed,(float,int)):
        completed=datetime.fromtimestamp(completed,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        brief=brief_api.build_portfolio_brief_state(conn,now=now.timestamp(),snapshot_inputs={
      'holdings':[{'Stock':t} for t in holdings], 'pipeline_completed_at':completed,
      'execution_account_id':account['account_id'] if account else None})
    except (sqlite3.Error, KeyError) as error:
        brief=dict(brief_health='ERROR',brief_health_detail=['canonical_brief_unavailable'],error=type(error).__name__,
                   freshness={'overall':'UNAVAILABLE'},capability_state={},open_decisions=[],thesis_deltas=[],portfolio_risks=[])
    evidence=rows(conn,'buffett_winners','ORDER BY scanned_at DESC,ticker')
    # The screener is persisted in a separate DB in production. Read it in ro mode;
    # fixture DBs can supply the same table directly. Paths never enter identities.
    if evidence is None:
        location=conn.execute('PRAGMA database_list').fetchall()
        main=next((r[2] for r in location if r[1]=='main'), '')
        path=Path(main).parent/'buffett.db' if main else None
        if path and path.is_file():
            external=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            external.row_factory=sqlite3.Row
            try: evidence=rows(ReadView(external),'buffett_winners','ORDER BY scanned_at DESC,ticker')
            finally: external.close()
    # Preserve newest row per ticker rather than accidentally selecting the oldest.
    winner_map={}
    for item in evidence or []: winner_map.setdefault(_normalize(item['ticker']),dict(item,ticker=_normalize(item['ticker'])))
    ranks=rank_candidates(candidates or [],list(winner_map.values()),set(holdings),layer_weights,as_of=now)
    enriched=set(winner_map)
    for rank in ranks: rank['evidence_status']='AVAILABLE' if rank['ticker'] in enriched else 'UNAVAILABLE'
    prices={t:h.get('price') for t,h in holdings.items()}
    for t,w in winner_map.items():
        if t not in prices: prices[t]=w.get('price')
    for c in candidates or []:
        prices.setdefault(c['ticker'],c.get('price'))
    price_freshness={}
    for ticker in prices:
        stamp=holdings.get(ticker,{}).get('price_as_of') or winner_map.get(ticker,{}).get('scanned_at')
        account_mark=next((p for p in positions or [] if p['symbol']==ticker),None)
        if account_mark and account_mark.get('market_price') is not None:
            prices[ticker]=account_mark['market_price'];stamp=account_mark.get('price_as_of')
        price_freshness[ticker]=brief_api.source_freshness(stamp,now.timestamp(),24)
    nav_rows=rows(conn,'portfolio_day','ORDER BY day DESC LIMIT 1')
    nav=nav_rows[0].get('total_value') if nav_rows else None
    nav_scope='TRACKED_HOLDINGS_VALUE_CASH_UNAVAILABLE'
    account_matches=False
    if account and positions is not None:
        quantities={p['symbol']:p['qty'] for p in positions if p.get('qty')}
        account_matches=all(t in quantities and abs(float(quantities[t])-float(h['shares']))<1e-8 for t,h in holdings.items()) and set(quantities)==set(holdings)
        if account_matches and all(isinstance(p.get('market_price'),(float,int)) for p in positions):
            nav=account['current_cash']+sum(p['qty']*p['market_price'] for p in positions)
            nav_scope='CAPTURED_ACCOUNT_NAV'
    sources={
            'account_alignment':{'status':'AVAILABLE' if account_matches else 'UNAVAILABLE','authority':'REQUIRED','reason':None if account_matches else 'No matching captured risk account'},
      'holdings':{'status':'AVAILABLE' if holdings_rows is not None else 'UNAVAILABLE','authority':'REQUIRED','as_of':max((h['as_of'] for h in holdings.values()),default=None)},
      'layer_allocation':{'status':'AVAILABLE' if layer_rows else 'UNAVAILABLE','authority':'REQUIRED'},
      'cost_lots':{'status':'AVAILABLE' if lots is not None else 'UNAVAILABLE','authority':'REQUIRED'},
      'covered_calls':{'status':'AVAILABLE' if cc is not None else 'UNAVAILABLE','authority':'REQUIRED'},
      'candidates':{'status':'AVAILABLE' if candidates is not None else 'UNAVAILABLE','authority':'REQUIRED','scorer_version':SCORER_VERSION},
      'candidate_evidence':{'status':'AVAILABLE' if evidence is not None else 'UNAVAILABLE','authority':'REQUIRED'},
      'macro':{'status':'OBSERVE_ONLY','authority':'ADVISORY','production_influence':0},
      'learning':{'status':'OBSERVE_ONLY','authority':'EXPERIMENTAL','production_influence':0}}
    for name,entry in brief.get('freshness',{}).items():
        if isinstance(entry,dict): sources[name]=dict(entry,authority=brief_api.FRESHNESS_CRITICALITY.get(name,'REQUIRED'))
    sources['risk_state']={'authority':'REQUIRED','status':'AVAILABLE' if account and all(
        risk_tables[name] is not None for name in ('position_snapshots','orders','fills','trade_intents')) else 'UNAVAILABLE'}
    risk_policy=None
    if account:
        try:
            from trade_engine.policy import load_policy
            selected_policy=load_policy(account['account_id'])
            risk_policy=dict(version=selected_policy.policy_version,hash=selected_policy.policy_hash())
        except (ValueError,OSError): risk_policy={'status':'UNAVAILABLE'}
    result=dict(contract_version=ADVISOR_CONTRACT_VERSION,policy_version=ADVISOR_POLICY_VERSION,
      scorer_version=SCORER_VERSION,captured_at=now.isoformat(),as_of=now.astimezone(TZ_EASTERN).date().isoformat(),
      portfolio_state=brief,holdings=holdings,prices=prices,price_freshness=price_freshness,lots=lots,covered_calls=cc,
      layer_weights=layer_weights,layer_targets=LAYER_TARGETS,nav=nav,nav_scope=nav_scope,cash=account.get('current_cash') if account else None,
      candidates=candidates,candidate_ranks=ranks,theses=theses,sources=sources,open_intents=intents,
      account=account,account_positions=risk_tables['position_snapshots'] if account else None,
      risk_snapshot=risk_tables,risk_state_hash=digest(risk_tables),risk_policy=risk_policy,
      broker_capabilities={'tax_lot_selection':'UNKNOWN','execution_ready':False})
    result['context_hash']=digest(semantic(result))
    # Advisory values remain visible but cannot change the authorization identity.
    authorization=dict(result)
    authorization.pop('context_hash')
    authorization['portfolio_state']={k:v for k,v in brief.items() if k not in {'macro_state','learning_state','context_warnings'}}
    authorization['portfolio_state']['freshness']={k:v for k,v in brief.get('freshness',{}).items() if not isinstance(v,dict) or brief_api.FRESHNESS_CRITICALITY.get(k,'REQUIRED')=='REQUIRED'}
    authorization['sources']={k:v for k,v in sources.items() if v['authority']=='REQUIRED'}
    result['authorization_hash']=digest(semantic(authorization))
    return result
