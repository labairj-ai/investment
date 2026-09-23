"""0572–0574: fail-closed ownership, shared economics, invocation telemetry.

The paper canary uses an independent broker ledger; it never sends network orders.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
import uuid

import pytest

from trade_engine import execution_engine as eng, risk_engine, runner
from trade_engine.broker_adapter import BrokerAdapter
from trade_engine.broker_types import BrokerAccountState, BrokerFill, BrokerOrder, BrokerOrderEvent, BrokerPosition
from trade_engine.fill_economics import calculate_fill_economics
from trade_engine.models import TradingAccount, RuleResult, Fill, Order, Side
from trade_engine.reconciliation import reconcile
from trade_engine.shadow_broker import ShadowBroker
from test_trade_engine import _make_conn, _make_policy, _make_intent, _insert_intent, _seed_order_and_pos

ACCOUNT = 'AGENTIC_ALPACA_01'


class PaperLedger(BrokerAdapter):
    """Independent deterministic paper broker, with no local DB access."""
    def __init__(self):
        self.orders = {}
        self.fills = []
        self.events = []
        self.positions = {}
        self.cash = 10000.0
        self.lookup_error = None
        self.client_lookup_error = None
        self.ledger_lag = False
        self._recent_api_calls = []

    def get_account_id(self): return ACCOUNT
    def get_broker_account(self, account_id):
        return BrokerAccountState(account_id, self.cash, self.cash, self.cash)
    def get_positions(self, account_id): return list(self.positions.values())
    def get_open_orders(self, account_id):
        return [o for o in self.orders.values() if o.state in ('WORKING', 'PARTIALLY_FILLED')]
    def get_order(self, order_id):
        if self.lookup_error: raise self.lookup_error
        return self.orders.get(order_id)
    def find_order_by_client_order_id(self, cid):
        if self.client_lookup_error: raise self.client_lookup_error
        return next((o for o in self.orders.values() if o.client_order_id == cid), None)
    def get_fills(self, account_id, since=None): return [] if self.ledger_lag else list(self.fills)
    def get_fills_for_order(self, broker_order_id):
        return [f for f in self.fills if f.broker_order_id == broker_order_id]
    def poll_order_events(self, account_id, quote=None):
        events, self.events = self.events, []
        return events
    def get_quote(self, symbol): return None
    def submit_order(self, intent, client_order_id=None): raise AssertionError('canary does not send orders')
    def cancel_order(self, order_id, reason=''): raise AssertionError('unexpected cancel')
    def attempt_fill(self, order, quote): raise AssertionError('broker fills are authoritative')
    def get_market_clock(self): return {'is_open': True}

    def stage(self, fill, cid='manual-order'):
        self.fills.append(fill)
        self.orders[fill.broker_order_id] = BrokerOrder(
            fill.broker_order_id, fill.symbol, fill.side, fill.qty, fill.qty, 'FILLED', client_order_id=cid)


@pytest.fixture
def setup(monkeypatch):
    conn = _make_conn()
    conn.execute("UPDATE trading_accounts SET account_id=?, mode='paper', broker='alpaca'", (ACCOUNT,))
    conn.commit()
    policy = _make_policy({'account_id': ACCOUNT})
    monkeypatch.setattr(eng, 'load_policy', lambda _: policy)
    yield conn, PaperLedger()
    conn.close()


def fill(side='BUY', qty=1, price=100, fee=0, oid=None, symbol='AAPL'):
    return BrokerFill(str(uuid.uuid4()), oid or str(uuid.uuid4()), symbol, side, qty, price,
                      datetime.now(timezone.utc).isoformat(), fee, account_id=ACCOUNT)


def local_order(conn, bf, pending=False):
    """Seed engine lineage without settling anything or fabricating broker evidence."""
    iid, oid = str(uuid.uuid4()), str(uuid.uuid4())
    cid = f'{ACCOUNT}:{iid}'
    conn.execute('''INSERT INTO trade_intents
        (intent_id,account_id,instrument_type,symbol,side,quantity,order_type,limit_price,time_in_force,valid_until,status,created_at)
        VALUES (?,?, 'EQUITY',?,?,?,'LIMIT',?,'GTC','2099-01-01T00:00:00+00:00','APPROVED',?)''',
        (iid, ACCOUNT, bf.symbol, bf.side, bf.qty, bf.price, bf.filled_at))
    conn.execute('''INSERT INTO orders
        (order_id,intent_id,account_id,symbol,side,quantity,order_type,state,fill_qty,fill_cash,client_order_id,broker_order_id,submitted_at,updated_at)
        VALUES (?,?,?,?,?,?,'LIMIT',?,0,0,?,?,?,?)''',
        (oid,iid,ACCOUNT,bf.symbol,bf.side,bf.qty,'PENDING_SUBMIT' if pending else 'WORKING',cid,
         None if pending else bf.broker_order_id,bf.filled_at,bf.filled_at))
    conn.commit()
    return oid, cid


def seed_position(conn, qty=10, avg=100):
    conn.execute("INSERT INTO position_snapshots(account_id,symbol,qty,avg_cost,instrument_type,as_of) VALUES (?,'AAPL',?,?,'EQUITY','2026-09-22')", (ACCOUNT,qty,avg))
    conn.commit()


def test_pending_lookup_timeout_with_fill_present_halts_before_settlement(setup):
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn,bf,pending=True)
    broker.stage(bf,cid)
    broker.client_lookup_error = TimeoutError('lookup unavailable')
    assert eng.initialize_trading_session(ACCOUNT,conn,broker) == eng.TradingReadyState.HALTED
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 0
    assert conn.execute('SELECT state FROM orders WHERE order_id=?',(oid,)).fetchone()[0] == 'PENDING_SUBMIT'
    assert conn.execute('SELECT current_cash FROM trading_accounts').fetchone()[0] == 10000


@pytest.mark.parametrize('kind', ['timeout','missing','engine_unknown','other_engine','identity_mismatch'])
def test_unresolved_ownership_is_quarantined_without_economic_mutation(setup,kind):
    conn,broker = setup
    bf = fill()
    broker.stage(bf)
    if kind == 'timeout': broker.lookup_error = TimeoutError('offline')
    if kind == 'missing': broker.orders.clear()
    if kind in ('engine_unknown','other_engine'):
        cid = (ACCOUNT if kind == 'engine_unknown' else 'AGENTIC_OTHER_01') + ':lost-intent'
        broker.orders[bf.broker_order_id] = broker.orders[bf.broker_order_id]._replace(client_order_id=cid)
    if kind == 'identity_mismatch':
        broker.orders[bf.broker_order_id] = broker.orders[bf.broker_order_id]._replace(symbol='WRONG')
    with pytest.raises(eng.BrokerStateIntegrityError):
        eng.apply_broker_fill(bf,ACCOUNT,conn,broker=broker)
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM position_snapshots').fetchone()[0] == 0
    assert conn.execute('SELECT current_cash FROM trading_accounts').fetchone()[0] == 10000


def test_per_fill_lookup_recovers_pending_order_to_filled(setup):
    conn,broker = setup
    bf = fill()
    oid,cid = local_order(conn,bf,pending=True)
    broker.stage(bf,cid)
    assert eng.apply_broker_fill(bf,ACCOUNT,conn,broker=broker) == eng.FillResult.APPLIED
    row = conn.execute('SELECT state,fill_qty,broker_order_id FROM orders WHERE order_id=?',(oid,)).fetchone()
    assert tuple(row) == ('FILLED',1,bf.broker_order_id)
    assert conn.execute('SELECT origin FROM fills').fetchone()[0] == 'ENGINE'


@pytest.mark.parametrize('origin', ['engine','external','shadow'])
@pytest.mark.parametrize('qty,price,fee,basis,pnl,pct,left', [
    (5,120,1,500,99,19.8,5), (10,60,2,1000,-402,-40.2,0), (2.5,100,0.25,250,-0.25,-0.1,7.5),
])
def test_equity_economics_identical_across_paths(origin,qty,price,fee,basis,pnl,pct,left):
    conn = _make_conn()
    oid = str(uuid.uuid4())
    _seed_order_and_pos(conn,oid,side='SELL',qty=10,price=100)
    bf = fill('SELL',qty,price,fee,oid=oid)._replace(account_id='AGENTIC_SHADOW_01')
    if origin == 'shadow':
        order = Order.from_db_row(conn.execute('SELECT * FROM orders WHERE order_id=?',(oid,)).fetchone())
        f = Fill(bf.broker_fill_id,oid,bf.account_id,bf.symbol,Side.SELL,qty,price,fee,'shadow',bf.filled_at)
        ShadowBroker(conn)._apply_fill(order,f)
    else:
        broker = PaperLedger()
        if origin == 'external': bf = bf._replace(broker_order_id='manual-123')
        broker.stage(bf)
        eng.apply_broker_fill(bf,bf.account_id,conn,broker=broker)
    row = conn.execute('SELECT cost_basis,realized_pnl,realized_pnl_pct FROM fills').fetchone()
    assert tuple(row) == pytest.approx((basis,pnl,pct))
    assert conn.execute('SELECT current_cash FROM trading_accounts').fetchone()[0] == pytest.approx(10000+qty*price-fee)
    pos = conn.execute('SELECT qty,avg_cost FROM position_snapshots').fetchone()
    assert (pos['qty'] if pos else 0) == left
    if pos: assert pos['avg_cost'] == 100
    before = tuple(row)
    assert eng.apply_broker_fill(bf,bf.account_id,conn) == eng.FillResult.ALREADY_APPLIED
    assert tuple(conn.execute('SELECT cost_basis,realized_pnl,realized_pnl_pct FROM fills').fetchone()) == before
    conn.close()


def test_buy_and_zero_basis_percentage_conventions():
    buy = calculate_fill_economics('BUY',2,120,1,3,100)
    assert (buy.cost_basis,buy.realized_pnl,buy.realized_pnl_pct) == (None,None,None)
    assert (buy.new_qty,buy.new_avg_cost,buy.cash_delta) == (5,108,-241)
    sell = calculate_fill_economics('SELL',1,100,1,1,0)
    assert (sell.cost_basis,sell.realized_pnl,sell.realized_pnl_pct) == (0,99,None)


@pytest.mark.parametrize("origin", ["engine", "external"])
def test_alpaca_loss_trips_daily_loss_limit(setup, origin):
    conn,broker = setup
    bf = fill('SELL',10,60,1)
    if origin == "engine": local_order(conn,bf)
    else: broker.stage(bf)
    seed_position(conn)
    eng.apply_broker_fill(bf,ACCOUNT,conn,broker=broker)
    intent = replace(_make_intent(quantity=1,limit_price=50),account_id=ACCOUNT)
    _insert_intent(conn,intent)
    account = TradingAccount.from_db_row(conn.execute('SELECT * FROM trading_accounts').fetchone())
    decision = risk_engine.evaluate(intent,_make_policy({'account_id':ACCOUNT}),account,conn,strict_all=True)
    assert next(c for c in decision.checks if c.rule == 'MAX_DAILY_LOSS').result == RuleResult.FAIL
    assert conn.execute('SELECT realized_pnl FROM fills').fetchone()[0] == -401


@pytest.mark.parametrize('authoritative', [False, True])
def test_event_fill_observed_when_ledger_lags(setup,authoritative):
    conn,broker = setup
    bf = fill()
    oid,cid = local_order(conn,bf)
    broker.stage(bf,cid)
    broker.ledger_lag = True
    broker.events = [BrokerOrderEvent('FILLED',bf.broker_order_id,oid,1,100,bf.filled_at,0,
                                     None if authoritative else bf.broker_fill_id)]
    fills,duplicates,stats = eng.sync_broker_state(ACCOUNT,conn,broker)
    assert len(fills) == 1
    assert duplicates == 0
    assert (stats['broker_fills_observed'],stats['broker_fills_new'],stats['broker_fills_duplicate']) == (1,1,0)
    # Same event + ledger later: one observed identity, no new economic fill.
    broker.ledger_lag = False
    broker.events = [BrokerOrderEvent('FILLED',bf.broker_order_id,oid,1,100,bf.filled_at,0,bf.broker_fill_id)]
    fills,_,stats = eng.sync_broker_state(ACCOUNT,conn,broker)
    assert fills == []
    assert (stats['broker_fills_observed'],stats['broker_fills_new'],stats['broker_fills_duplicate']) == (1,0,1)


def test_event_plus_ledger_new_fill_counted_once(setup):
    conn,broker = setup
    bf=fill(); oid,cid=local_order(conn,bf); broker.stage(bf,cid)
    broker.events=[BrokerOrderEvent('FILLED',bf.broker_order_id,oid,1,100,bf.filled_at,0,bf.broker_fill_id)]
    fills,_,stats=eng.sync_broker_state(ACCOUNT,conn,broker)
    assert len(fills)==1
    assert (stats['broker_fills_observed'],stats['broker_fills_new'],stats['broker_fills_duplicate'])==(1,1,0)


@pytest.mark.parametrize('failure', ['reconciliation','second_fill'])
def test_halted_initialization_retains_observations(setup,failure):
    conn,broker=setup
    first=fill(); broker.stage(first)
    if failure=='second_fill':
        second=fill(); broker.stage(second,ACCOUNT+':missing')
    # Broker cash/positions deliberately not updated, ensuring reconciliation failure.
    session=eng.ExecutionSession(ACCOUNT,conn,broker)
    with pytest.raises(eng.SessionNotReadyError): session.initialize()
    stats=session.merge_broker_stats({'execution_state':'HALTED','total_fills':0})
    assert stats['broker_fills_observed']==(2 if failure=='second_fill' else 1)
    assert stats['broker_fills_new']==1
    assert stats['external_fills_observed']==1
    assert stats['total_fills']==0


def test_runner_persists_initialization_stats_on_halt(setup,tmp_path,monkeypatch):
    conn,broker=setup
    bf=fill(); broker.stage(bf)
    dbpath=tmp_path/'runner.db'
    import sqlite3
    dest=sqlite3.connect(dbpath); conn.backup(dest)
    from test_runner import _SCHEMA
    dest.executescript(_SCHEMA)
    dest.close()
    monkeypatch.setattr(runner,'_DB_PATH',dbpath)
    monkeypatch.setenv('ALPACA_API_KEY','test')
    monkeypatch.setenv('ALPACA_API_SECRET','test')
    with patch('trade_engine.alpaca_adapter.AlpacaAdapter',return_value=broker), \
         patch('agent_db.acquire_execution_lease',return_value=True), \
         patch('agent_db.release_execution_lease'):
        assert runner.run()==1
    db=sqlite3.connect(dbpath)
    row=db.execute('SELECT execution_state,broker_fills_observed,broker_fills_new,external_fills_observed,fills_applied FROM cycle_runs').fetchone()
    assert row==('HALTED',1,1,1,0)
    db.close()


def test_paper_canary_exact_reconciliation(setup):
    """Normal engine BUY/loss SELL, external BUY/loss SELL, replay, pending recovery."""
    conn,broker=setup
    # Expected broker cash and holdings are explicit and independent of production math.
    cases=[('BUY',10,100,1,True,False,8999,10,100),
           ('SELL',4,80,1,True,False,9318,6,100),
           ('BUY',4,90,1,False,False,8957,10,96),
           ('SELL',5,70,1,False,False,9306,5,96),
           ('BUY',1,96,0,True,True,9210,6,96)]
    for side,qty,price,fee,engine,pending,cash,held,avg in cases:
        bf=fill(side,qty,price,fee)
        oid,cid=local_order(conn,bf,pending) if engine else (None,'manual-canary')
        broker.stage(bf,cid)
        broker.cash=cash
        broker.positions={'AAPL':BrokerPosition('AAPL',held,avg)}
        session=eng.ExecutionSession(ACCOUNT,conn,broker)
        assert session.initialize()==eng.TradingReadyState.TRADING_READY
        if oid:
            assert conn.execute('SELECT state FROM orders WHERE order_id=?',(oid,)).fetchone()[0]=='FILLED'
        local_cash=conn.execute('SELECT current_cash FROM trading_accounts').fetchone()[0]
        pos=conn.execute('SELECT qty,avg_cost FROM position_snapshots').fetchone()
        assert local_cash==cash
        assert tuple(pos)==(held,avg)
        assert reconcile(ACCOUNT,conn,broker,cash_tolerance=0,qty_tolerance=0).ok
        assert eng.apply_broker_fill(bf,ACCOUNT,conn,broker)==eng.FillResult.ALREADY_APPLIED
        assert conn.execute('SELECT current_cash FROM trading_accounts').fetchone()[0]==cash
    rows=conn.execute("SELECT origin,realized_pnl FROM fills WHERE side='SELL' ORDER BY filled_at").fetchall()
    assert [tuple(r) for r in rows]==[('ENGINE',-81),('BROKER_EXTERNAL',-131)]
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0]==5


def test_cycle_halt_retains_event_fill_observation(setup):
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn, bf)
    broker.stage(bf, cid)
    broker.events = [BrokerOrderEvent('FILLED', bf.broker_order_id, oid, 1, 100,
                                     bf.filled_at, 0, bf.broker_fill_id)]
    def ledger_unavailable(*args, **kwargs):
        raise TimeoutError('ledger unavailable after event applied')
    broker.get_fills = ledger_unavailable
    result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                    trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert (result['broker_fills_observed'], result['broker_fills_new']) == (1, 1)
    assert result['broker_fills_duplicate'] == 0
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 1


class _FakeResult:
    """Minimal ExecutionResult stand-in for CycleProgress tests."""
    def __init__(self, order_id=None, fill=None, decision='APPROVED'):
        self.order_id = order_id
        self.fill = fill
        self.decision = decision
    def to_dict(self): return {'order_id': self.order_id, 'decision': self.decision}


def test_submitted_order_preserved_when_open_orders_halts(setup):
    # 0577: process_new_intents succeeds (order created) → process_open_orders raises → order visible
    conn, broker = setup
    fake = _FakeResult(order_id=str(uuid.uuid4()))
    def _fake_pni(account_id, conn, broker=None, *, _progress=None):
        if _progress is not None:
            _progress.orders_created += 1
        return [fake]
    with patch.object(eng, 'process_new_intents', side_effect=_fake_pni), \
         patch.object(eng, 'process_open_orders', side_effect=eng.BrokerStateIntegrityError('halt')):
        result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                        trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['new_orders_created'] == 1
    assert result['new_intents_processed'] == 1


def test_submission_fill_preserved_when_open_orders_halts(setup):
    # 0577: immediate fill during intent submission → process_open_orders raises → fill counted
    conn, broker = setup
    fake = _FakeResult(order_id=str(uuid.uuid4()), fill=object())
    def _fake_pni(account_id, conn, broker=None, *, _progress=None):
        if _progress is not None:
            _progress.submission_fills.append(object())
        return [fake]
    with patch.object(eng, 'process_new_intents', side_effect=_fake_pni), \
         patch.object(eng, 'process_open_orders', side_effect=eng.BrokerStateIntegrityError('halt')):
        result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                        trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['fills_on_submission'] == 1
    assert result['total_fills'] == 1


def test_retry_fill_preserved_when_integrity_halt_on_later_event(setup):
    # 0577: order A fills (event 1) → INVALID event 2 on same order raises BSI → fill visible
    # sync_broker_state polls first (call 1 → empty); process_open_orders polls second (call 2 → events)
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn, bf)
    # broker.orders needed for apply_broker_fill ownership check; no ledger fill so sync sees nothing
    broker.orders[bf.broker_order_id] = BrokerOrder(
        bf.broker_order_id, bf.symbol, bf.side, bf.qty, bf.qty, 'FILLED', client_order_id=cid)
    _calls = [0]
    _orig = broker.poll_order_events
    def _two_phase(account_id, quote=None):
        _calls[0] += 1
        if _calls[0] == 1:
            return []  # sync phase: nothing to ingest
        return [
            BrokerOrderEvent('FILLED', bf.broker_order_id, oid, bf.qty, bf.price,
                             bf.filled_at, bf.fee, bf.broker_fill_id),
            BrokerOrderEvent('INVALID_TYPE', bf.broker_order_id, oid),
        ]
    broker.poll_order_events = _two_phase
    result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                    trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['fills_on_retry'] == 1
    assert result['total_fills'] == 1
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 1


def test_open_order_rejection_preserved_when_later_halt(setup):
    # 0577: partial process_open_orders records a pre-fill rejection before raising → visible in summary
    conn, broker = setup

    def _partial_then_raise(account_id, conn, broker=None, *, _progress=None):
        if _progress is not None:
            _progress.pre_fill_rejections += 1
        raise eng.BrokerStateIntegrityError('order B integrity halt')

    with patch.object(eng, 'process_open_orders', side_effect=_partial_then_raise):
        result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                        trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['risk_rejections'] == 1


def test_all_success_cycle_metrics_via_progress(setup):
    # 0577: idle OK cycle through CycleProgress.to_summary has all expected keys and sane values
    conn, broker = setup
    result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                    trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'OK'
    for key in ('new_intents_processed', 'new_intents_blocked', 'stale_symbols', 'market_state',
                'new_orders_created', 'fills_on_sync', 'fills_on_submission', 'risk_rejections',
                'working_orders_checked', 'fills_on_retry', 'total_fills', 'orders_expired',
                'duplicate_fills_skipped', 'broker_fills_observed', 'broker_fills_new',
                'broker_fills_duplicate', 'external_fills_observed', 'results'):
        assert key in result, f'missing key: {key}'
    assert result['total_fills'] == 0
    assert result['market_state'] == 'fresh'
    assert result['new_intents_blocked'] is False


@pytest.mark.parametrize('exc_type', [eng.BrokerSubmissionIndeterminate, eng.BrokerStateIntegrityError])
def test_sync_fill_preserved_when_process_new_intents_halts(setup, exc_type):
    # 0576: sync applies fill, then process_new_intents halts — fill must still appear in result
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn, bf)
    broker.stage(bf, cid)
    with patch.object(eng, 'process_new_intents', side_effect=exc_type('test halt')):
        result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                        trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['fills_on_sync'] == 1
    assert result['broker_fills_new'] == 1
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 1


@pytest.mark.parametrize('exc_type', [eng.PolicyUnavailable, eng.BrokerStateIntegrityError])
def test_sync_fill_preserved_when_process_open_orders_halts(setup, exc_type):
    # 0576: sync applies fill, then process_open_orders halts — fill must still appear in result
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn, bf)
    broker.stage(bf, cid)
    with patch.object(eng, 'process_open_orders', side_effect=exc_type('test halt')):
        result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                        trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['fills_on_sync'] == 1
    assert result['broker_fills_new'] == 1
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 1


@pytest.mark.parametrize('cid', [None, '', 'manual-order'])
def test_external_ownership_requires_positive_broker_response(setup, cid):
    conn, broker = setup
    bf = fill()
    broker.stage(bf, cid)
    assert eng.apply_broker_fill(bf, ACCOUNT, conn, broker) == eng.FillResult.APPLIED_EXTERNAL
    assert tuple(conn.execute('SELECT origin,order_id,engine_managed FROM fills').fetchone()) == (
        'BROKER_EXTERNAL', None, 0)


# ── 0578 tests ────────────────────────────────────────────────────────────────

def test_pending_submit_timeout_creates_row_and_reports_order(setup):
    # 0579: real process_intent() path — INSERT OR IGNORE committed → submit_order()
    # raises TimeoutError → BrokerSubmissionIndeterminate → HALTED summary reports
    # new_orders_created==1 and the DB row exists with state==PENDING_SUBMIT.
    from trade_engine.shadow_broker import Quote
    from test_trade_engine import _make_intent, _insert_intent
    from dataclasses import replace as dc_replace

    conn, broker = setup
    intent = dc_replace(_make_intent(quantity=1, limit_price=50), account_id=ACCOUNT)
    _insert_intent(conn, intent)

    broker.get_quote = lambda symbol: Quote(
        bid=49.0, ask=50.0, timestamp='t',
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )

    def _timeout_submit(intent, client_order_id=None):
        raise TimeoutError('broker unreachable')
    broker.submit_order = _timeout_submit

    result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                    trading_state=eng.TradingReadyState.TRADING_READY)

    assert result['execution_state'] == 'HALTED'
    assert result['halt_reason'] == 'SUBMISSION_INDETERMINATE'
    assert result['new_orders_created'] == 1

    order_row = conn.execute(
        "SELECT state FROM orders WHERE intent_id=?", (intent.intent_id,)
    ).fetchone()
    assert order_row is not None
    assert order_row['state'] == 'PENDING_SUBMIT'


def test_already_applied_retry_not_counted(setup):
    # 0578 criterion 6: replayed FILLED event (ALREADY_APPLIED) must not inflate fills_on_retry.
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn, bf)
    broker.orders[bf.broker_order_id] = BrokerOrder(
        bf.broker_order_id, bf.symbol, bf.side, bf.qty, 0.0, 'WORKING', client_order_id=cid)
    # Sync phase sees nothing; process_open_orders phase sees the FILLED event.
    _calls = [0]
    def _two_phase(account_id, quote=None):
        _calls[0] += 1
        if _calls[0] == 1:
            return []
        return [BrokerOrderEvent('FILLED', bf.broker_order_id, oid, bf.qty, bf.price,
                                 bf.filled_at, bf.fee, bf.broker_fill_id)]
    broker.poll_order_events = _two_phase
    with patch.object(eng, 'apply_broker_fill', return_value=eng.FillResult.ALREADY_APPLIED):
        result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                        trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'OK'
    assert result['fills_on_retry'] == 0
    assert result['total_fills'] == 0


def test_fills_on_sync_preserved_when_sync_raises_after_first_fill(setup):
    # 0578 criterion 7: fill applied in event loop → second event is invalid → fills_on_sync == 1
    conn, broker = setup
    bf = fill()
    oid, cid = local_order(conn, bf)
    broker.orders[bf.broker_order_id] = BrokerOrder(
        bf.broker_order_id, bf.symbol, bf.side, bf.qty, bf.qty, 'FILLED', client_order_id=cid)
    broker.events = [
        BrokerOrderEvent('FILLED', bf.broker_order_id, oid, bf.qty, bf.price,
                         bf.filled_at, bf.fee, bf.broker_fill_id),
        BrokerOrderEvent('INVALID_TYPE', bf.broker_order_id, oid),
    ]
    # Prevent ledger pull from running (raise would mask the event-loop error ordering)
    broker.get_fills = lambda account_id, since=None: []
    result = eng.run_execution_cycle(ACCOUNT, conn, broker,
                                    trading_state=eng.TradingReadyState.TRADING_READY)
    assert result['execution_state'] == 'HALTED'
    assert result['fills_on_sync'] == 1
    assert conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0] == 1
