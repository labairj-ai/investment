"""Canonical equity-preview inputs for one explicitly selected risk account."""
from time_utils import now_utc


def _rows(conn, table, where, order, parameters, columns='*'):
    import sqlite3
    try:
        return [dict(r) for r in conn.execute(
            'SELECT '+columns+' FROM '+table+' WHERE '+where+' ORDER BY '+order, parameters)]
    except sqlite3.OperationalError:
        return None


def build_risk_snapshot(conn, account_id, *, now=None):
    day=(now or now_utc()).date().isoformat()
    account=_rows(conn,'trading_accounts','account_id=?','account_id',(account_id,))
    positions=_rows(conn,'position_snapshots','account_id=?','account_id,symbol',(account_id,))
    if positions is not None:
        # Surrogate insertion IDs are not position identity (account, symbol is).
        positions=[{k:v for k,v in r.items() if k!='id'} for r in positions]
    return dict(snapshot_version='advisor-risk-snapshot-v2',account_id=account_id,
        risk_day_utc=day, trading_accounts=account, position_snapshots=positions,
        orders=_rows(conn,'orders',"account_id=? AND (DATE(submitted_at)=? OR state IN ('WORKING','PARTIALLY_FILLED'))",
                     'account_id,order_id',(account_id,day)),
        fills=_rows(conn,'fills','account_id=? AND DATE(filled_at)=?',
                    'account_id,filled_at,fill_id',(account_id,day),
                    columns='fill_id,account_id,qty,price,filled_at,realized_pnl'),
        trade_intents=_rows(conn,'trade_intents',"account_id=? AND status NOT IN ('FILLED','CANCELLED','EXPIRED','REJECTED')",
                            'account_id,intent_id',(account_id,)),
        global_inputs={'policy_identity':'Captured separately in context.risk_policy; includes resolved global defaults.'})
