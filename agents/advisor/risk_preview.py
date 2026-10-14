"""Read-only risk preview over the engine's shared rule core."""
from datetime import timedelta
from .context import ReadView, rows
from .contracts import digest
from time_utils import parse_timestamp
from trade_engine.models import TradingAccount, TradeIntent, InstrumentType, Side, OrderType, TimeInForce
from trade_engine.policy import load_policy
from trade_engine import risk_engine


def preview(impact, context, conn, *, policy=None):
    if not impact['valid'] or not context.get('account'):
        return dict(decision='UNKNOWN',preview_only=True,reasons=['ACCOUNT_OR_VALID_IMPACT_UNAVAILABLE'],execution_ready=False)
    view=ReadView(conn)
    snapshot={name:rows(view,name) for name in ('trading_accounts','position_snapshots','orders','fills','trade_intents')}
    snapshot_hash=digest(snapshot)
    if snapshot_hash!=context['risk_state_hash']:
        return dict(decision='UNKNOWN',preview_only=True,reasons=['RISK_SNAPSHOT_CHANGED'],account_snapshot_hash=snapshot_hash,execution_ready=False)
    account=TradingAccount.from_db_row(context['account'])
    try:
        policy=policy or load_policy(account.account_id)
        results=[]
        for leg in impact['legs']:
            if leg['side']=='NO_CHANGE': continue
            # Captured holdings must describe the same account state, not another
            # paper/live book with a coincidentally matching ticker.
            position=next((p for p in context.get('account_positions') or [] if p['symbol']==leg['ticker']),None)
            qty=float(position['qty']) if position else 0
            if abs(qty-leg['before_shares'])>1e-8:
                raise ValueError('ACCOUNT_POSITION_MISMATCH')
            intent=TradeIntent(intent_id='advisor-preview-'+digest(leg)[:20],account_id=account.account_id,
                recommendation_id=None,agent_run_id=None,instrument_type=InstrumentType.EQUITY,
                symbol=leg['ticker'],side=Side(leg['side']),quantity=abs(leg['delta_shares']),contracts=None,
                option_type=None,strike=None,expiration=None,order_type=OrderType.LIMIT,
                limit_price=leg['reference_price'],time_in_force=TimeInForce.DAY,strategy='ADVISOR_PREVIEW',
                thesis_version=None,strategy_config_hash=None,policy_hash=policy.policy_hash(),
                valid_until=(parse_timestamp(context['captured_at'])+timedelta(minutes=15)).isoformat(),created_at=context['captured_at'])
            result=risk_engine.preview(intent,policy,account,view)
            result['ticker']=leg['ticker'];results.append(result)
        rejected=any(r['decision']=='REJECTED' for r in results)
        unknown=any(c['rule']=='DATA_FRESHNESS' and c['result']=='SKIP' for r in results for c in r['checks'])
        # Per-leg checks are not a proof of aggregate reservations for a linked
        # reallocation. Keep that distinction explicit, never silently pass it.
        multi=len(results)>1
        return dict(decision='REJECTED' if rejected else 'UNKNOWN' if unknown or multi or not results else 'PREVIEW_PASS',
            preview_only=True,legs=results,policy_version=policy.policy_version,policy_hash=policy.policy_hash(),
            account_snapshot_hash=snapshot_hash,execution_ready=False,
            reasons=(['MULTI_LEG_RESERVATION_REVIEW'] if multi else [])+(['UNKNOWN_PRICE_FRESHNESS'] if unknown else []))
    except Exception as error:
        return dict(decision='UNKNOWN',preview_only=True,reasons=[str(error) if isinstance(error,ValueError) else 'RISK_PREVIEW_UNAVAILABLE'],
                    account_snapshot_hash=snapshot_hash,execution_ready=False)
