#!/usr/bin/env python3
"""Independent alert-only watchdog. Never invokes investment jobs or repairs."""
import argparse
import fcntl
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import operational_watchdog as wd


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--initialize-baseline',action='store_true',help='Explicit deployment-only baseline; refuses overwrite')
    p.add_argument('--notify',action='store_true',help='Deliver actual operational alerts to configured operator')
    args=p.parse_args()
    with (ROOT/'out/watchdog.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        now=time.time()
        if args.initialize_baseline:
            c=sqlite3.connect(f'file:{ROOT}/out/investment.db?mode=ro',uri=True);c.row_factory=sqlite3.Row
            identity=wd.identity(c,now)
            epoch=c.execute('SELECT epoch_id FROM macro_experiment_epochs ORDER BY registered_at DESC LIMIT 1').fetchone()
            if not identity['acceptance'] or identity['stage']!=0 or not epoch:
                raise RuntimeError('Current acceptance, stage zero and existing epoch required')
            baseline=dict(activated_at=now,identity=identity,epoch_id=epoch[0],schedules=wd.SCHEDULES)
            with wd.BASELINE.open('x') as f: json.dump(baseline,f,indent=2)
            c.close();print('Pinned explicit watchdog deployment baseline');return
        checks=[]
        try:
            baseline=json.loads(wd.BASELINE.read_text())
            if baseline['schedules']!=json.loads(json.dumps(wd.SCHEDULES)):
                checks.append(wd.result('watchdog_schedule','RED','Operational schedules differ from deployment baseline'))
            else:
                checks.append(wd.result('watchdog_schedule',reason='Operational schedules match deployment baseline'))
            checks.append(wd.result('watchdog_baseline',reason='Explicit deployment baseline loaded'))
        except Exception:
            baseline=None
            checks.append(wd.result('watchdog_baseline','RED','Deployment baseline missing or unreadable'))
        state=wd.connect()
        try:
            conn=sqlite3.connect(f'file:{ROOT}/out/investment.db?mode=ro',uri=True,timeout=5);conn.row_factory=sqlite3.Row
            conn.execute('SELECT 1 FROM agent_runs LIMIT 1').fetchone()
            checks.append(wd.result('database',reason='Business database reachable read-only'))
            if baseline: checks.extend(wd.collect(conn,state,baseline,now))
            conn.close()
        except Exception as exc:
            checks.append(wd.result('database','RED','Business database unavailable',error=type(exc).__name__))
        try:
            with urllib.request.urlopen('http://127.0.0.1:5001/api/watchdog/heartbeat',timeout=10) as response:
                heartbeat=json.load(response)
            if not heartbeat.get('ok'): raise RuntimeError('Heartbeat failed')
            checks.append(wd.result('serve',reason='HTTP service and database heartbeat succeeded',last_success_at=now))
        except Exception as exc:
            checks.append(wd.result('serve','RED','HTTP service heartbeat unavailable',error=type(exc).__name__))
        # Check independent timers themselves too; a disabled timer must not look
        # healthy just because its previous output has not aged out yet.
        import subprocess
        for unit in ('macro-health-watchdog.timer','macro-candidate-preparation.timer','outcome-labeler.timer','book-mtm.timer'):
            try:
                status=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True,timeout=5)
                checks.append(wd.result(unit,'INFO' if status.returncode==0 else 'YELLOW',
                                        'Timer active' if status.returncode==0 else 'Required timer is inactive'))
            except Exception:
                checks.append(wd.result(unit,'YELLOW','Timer status unavailable'))
        for unit in ('macro-candidate-preparation.service','outcome-labeler.service','book-mtm.service'):
            status=subprocess.run(['systemctl','show',unit,'--property=Result','--value'],capture_output=True,text=True,timeout=5)
            value=status.stdout.strip()
            severity='INFO' if status.returncode==0 and value=='success' else ('RED' if value else 'YELLOW')
            checks.append(wd.result(unit,severity,'Last service execution succeeded' if severity=='INFO' else 'Service execution failed or unavailable',result=value))
        wd.persist(state,checks,now)
        wd.deliver(state,now,wd.email_transport,enabled=args.notify)
        failures=wd.delivery_failures(state,now)
        checks.append(wd.result('notification_delivery','YELLOW' if failures else 'INFO',
                               'Notification delivery failed; retry pending' if failures else ('Configured alert transport armed' if args.notify else 'Dry run; no messages sent'),failed_n=failures))
        wd.persist(state,checks,now)
        snapshot=wd.report();snapshot['notification_failures']=failures
        # Fallback last-result file can be inspected even if watchdog DB fails later.
        tmp=ROOT/'out/watchdog_latest.json.tmp';tmp.write_text(json.dumps(snapshot,indent=2));tmp.replace(ROOT/'out/watchdog_latest.json')
        print(json.dumps(snapshot,indent=2));state.close()
        if any(c['status']=='RED' for c in checks) or failures: raise SystemExit(1)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        # Independent fallback when even watchdog storage/check execution fails.
        # JSON throttling survives restart without either SQLite database.
        fallback=ROOT/'out/watchdog_failure.json'
        try:
            prior=json.loads(fallback.read_text()) if fallback.exists() else {}
            now=time.time()
            data=dict(overall='RED',checked_at=now,error=type(exc).__name__,last_sent=prior.get('last_sent',0))
            if '--notify' in sys.argv and now-data['last_sent']>=21600:
                data['last_sent']=now
                fallback.write_text(json.dumps(data))
                wd.email_transport('RED: operational watchdog itself failed', 'Inspect macro-health-watchdog.service journal on Optiplex. Error: '+type(exc).__name__)
            fallback.write_text(json.dumps(data))
        finally:
            raise
