"""Refresh current snapshot, then advance only the isolated CC virtual book."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from datetime import timedelta,datetime
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from time_utils import now_utc,parse_timestamp,TZ_EASTERN
from covered_call_ledger import connect,migrate
from covered_call_virtual import state,store_snapshot,advance,record_interval,metrics


def capture_snapshot(ticker,current):
    import yfinance as yf
    import covered_call_rec as cc
    stock=yf.Ticker(ticker)
    begun=now_utc();today=begun.astimezone(TZ_EASTERN).date()
    spot=cc._market_price(stock)
    if spot is None:raise ValueError('underlying quote unavailable')
    options=[]
    for expiration in stock.options:
        days=(datetime.strptime(expiration,'%Y-%m-%d').date()-today).days
        if not 0<=days<=180:continue
        chain=stock.option_chain(expiration).calls
        observed=now_utc().isoformat()
        for _,row in chain.iterrows():
            values={k:float(row.get(k,0) or 0) for k in ('strike','bid','ask','impliedVolatility')}
            if all(__import__('math').isfinite(v) for v in values.values()):
                options.append(dict(values,expiration=expiration,observed_at=observed,available_at=observed))
    events=cc.get_risk_events(stock,spot,today,today+timedelta(days=180))
    known=now_utc().isoformat()
    events=[dict(e,known_at=known) for e in events]
    settlement=None
    expiry=datetime.strptime(current['expiration'],'%Y-%m-%d').date()
    if today>=expiry:
        frame=stock.history(start=(expiry-timedelta(days=7)).isoformat(),end=(expiry+timedelta(days=1)).isoformat(),auto_adjust=False)
        if not frame.empty:
            index=frame.index[-1];session=index.date()
            settle_time=datetime(session.year,session.month,session.day,16,tzinfo=TZ_EASTERN)
            if parse_timestamp(settle_time)<=now_utc():
                settlement=dict(expiration=current['expiration'],price=float(frame.iloc[-1]['Close']),
                    timestamp=settle_time.isoformat(),available_at=now_utc().isoformat(),coverage_verified=session==expiry)
    hist=stock.history(period='1y')
    vm=cc.compute_vol_model(hist) if not hist.empty else {}
    available=now_utc().isoformat()
    return dict(ticker=ticker,spot=spot,underlying_timestamp=begun.isoformat(),captured_at=begun.isoformat(),available_at=available,
                options=options,events=events,settlement=settlement,hv_forecast=vm.get('hv_forecast'),mu_center=vm.get('mu_center'),forecast_available_at=available,coverage_verified=bool(options or settlement),
                quote_timing_verified=True,provider_quote_timestamp_verified=False,quote_time_source='CAPTURE_TIME_NOT_EXCHANGE',maximum_quote_age_seconds=900)


def run(path=None,capture=None,clock=None):
    capture=capture or capture_snapshot;clock=clock or now_utc
    db=connect(path);migrate(db);results=[]
    for chain in db.execute('SELECT * FROM cc_virtual_chains WHERE simulation_kind="PROSPECTIVE"').fetchall():
        current=state(db,chain['id'])
        if current['status'] not in ('OPEN','AWAIT_ASSIGNMENT'):continue
        origin=json.loads(chain['origin_json']);at=clock();et=at.astimezone(TZ_EASTERN)
        cadence=origin['config']['virtual']['cadence_minutes']
        cycle=f'{et.date().isoformat()}:{et.hour:02d}:{et.minute//cadence}'
        duplicate=db.execute("SELECT 1 FROM cc_virtual_actions WHERE chain_id=? AND json_extract(action_json,'$.cycle_key')=?",(chain['id'],cycle)).fetchone()
        if duplicate:results.append(dict(chain_id=chain['id'],duplicate=True));continue
        try:
            snapshot=capture(origin['ticker'],current)
            with db:snapshot_id=store_snapshot(db,snapshot)
            evaluation=snapshot['available_at']
            # If this service misses an earlier scheduled market interval, later
            # quotes cannot fill that gap. Preserve the unavailable interval.
            last=parse_timestamp(current['last_evaluation']).astimezone(TZ_EASTERN)
            if et.date()==last.date() and 9<=et.hour<=16 and (et-last).total_seconds()>cadence*60*2:
                with db:record_interval(db,chain['id'],(last+timedelta(minutes=cadence)).isoformat(),None,'MISSED_SCHEDULED_INTERVAL',{'censored':True})
            result=advance(db,chain['id'],snapshot_id,evaluation,cycle_key=cycle)
            results.append(result)
            print('[VIRTUAL_CC]',json.dumps(result),flush=True)
        except Exception as exc:
            with db:record_interval(db,chain['id'],at.isoformat(),None,'CAPTURE_OR_CYCLE_ERROR',{'error':str(exc),'censored':True})
            results.append(dict(chain_id=chain['id'],error=str(exc)))
            print('[VIRTUAL_CC] ERROR',str(exc),flush=True)
    summary=metrics(db);db.close()
    return dict(results=results,open_chains=summary['open_chains'],completed_chains=summary['completed_chains'],
                censored_intervals=summary['censored_intervals'],errors=sum('error' in r for r in results))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db')
    args=parser.parse_args()
    print(json.dumps(run(args.db),indent=2))
