"""Alert-only operational checks. Business database is always opened read-only.

Watchdog projections, append-only events and producer receipts live in a separate
SQLite file so outages of the investment database can still be reported.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo('America/New_York')
STATE = ROOT / 'out/watchdog.db'
BASELINE = ROOT / 'out/watchdog_baseline.json'
RANK = {'INFO': 0, 'YELLOW': 1, 'RED': 2}


def connect(path=None):
    c = sqlite3.connect(str(path or STATE), timeout=5)
    c.row_factory = sqlite3.Row
    c.executescript('''
    CREATE TABLE IF NOT EXISTS system_watchdog_state (
      component TEXT PRIMARY KEY, last_expected_at REAL, last_started_at REAL,
      last_success_at REAL, last_record_id TEXT, expected_cadence TEXT,
      status TEXT NOT NULL, detail TEXT NOT NULL, checked_at REAL NOT NULL,
      incident_id TEXT);
    CREATE TABLE IF NOT EXISTS watchdog_events (
      event_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, component TEXT NOT NULL,
      severity TEXT NOT NULL, detected_at REAL NOT NULL, transition TEXT NOT NULL,
      reason TEXT NOT NULL, evidence_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS watchdog_receipts (
      record_id TEXT PRIMARY KEY, component TEXT NOT NULL, started_at REAL NOT NULL,
      completed_at REAL, status TEXT NOT NULL, detail TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS watchdog_sweeps (
      run_id TEXT PRIMARY KEY, captured_at REAL NOT NULL, candidate_n INTEGER NOT NULL,
      models_json TEXT NOT NULL, exclusion_reason TEXT);
    CREATE TABLE IF NOT EXISTS watchdog_delivery (
      delivery_key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, last_attempt REAL,
      delivered_at REAL, error TEXT);
    CREATE TRIGGER IF NOT EXISTS watchdog_events_no_update BEFORE UPDATE ON watchdog_events
      BEGIN SELECT RAISE(ABORT,'immutable watchdog event'); END;
    CREATE TRIGGER IF NOT EXISTS watchdog_events_no_delete BEFORE DELETE ON watchdog_events
      BEGIN SELECT RAISE(ABORT,'immutable watchdog event'); END;
    CREATE TRIGGER IF NOT EXISTS watchdog_sweeps_no_update BEFORE UPDATE ON watchdog_sweeps
      BEGIN SELECT RAISE(ABORT,'immutable sweep receipt'); END;
    CREATE TRIGGER IF NOT EXISTS watchdog_sweeps_no_delete BEFORE DELETE ON watchdog_sweeps
      BEGIN SELECT RAISE(ABORT,'immutable sweep receipt'); END;
    ''')
    return c


def receipt(component, record_id=None, status='STARTED', detail=None, path=None):
    """Best-effort instrumentation; failure never changes investment behavior."""
    record_id = record_id or str(uuid.uuid4())
    try:
        with connect(path or STATE) as c:
            if status == 'STARTED':
                c.execute('INSERT INTO watchdog_receipts VALUES (?,?,?,NULL,?,?)',
                          (record_id, component, time.time(), status, json.dumps(detail or {})))
            else:
                c.execute('UPDATE watchdog_receipts SET completed_at=?,status=?,detail=? WHERE record_id=? AND component=?',
                          (time.time(), status, json.dumps(detail or {}), record_id, component))
        c.close()
    except Exception as exc:
        print(f'[watchdog] receipt failure {component}: {type(exc).__name__}', flush=True)
    return record_id


def sweep_receipt(run_id, candidate_n, models, exclusion_reason=None):
    try:
        with connect() as c:
            c.execute('INSERT INTO watchdog_sweeps VALUES (?,?,?,?,?)',
                      (str(run_id), time.time(), candidate_n, json.dumps(models), exclusion_reason))
        c.close()
    except Exception as exc:
        print(f'[watchdog] sweep receipt failure: {type(exc).__name__}', flush=True)


def stamp(value, local=False):
    from agents.learning.macro_provenance import timestamp
    return timestamp(value, local=local)


def result(component, severity='INFO', reason='Completed successfully', **evidence):
    return dict(component=component, status=severity, reason=reason, evidence=evidence)


def due_slots(now, since, hours, weekdays=None, sessions=False, grace=3600):
    """All expected slots since activation; grace delays inspection, not deadline identity."""
    from trade_engine.market_calendar import is_trading_day
    day = datetime.fromtimestamp(since, ET).date()
    end = datetime.fromtimestamp(now, ET).date()
    while day <= end:
        if (weekdays is None or day.weekday() in weekdays) and (not sessions or is_trading_day(day)):
            for hour, minute in hours:
                at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).timestamp()
                if at >= since and at + grace <= now:
                    yield at
        day += timedelta(days=1)


def latest_due(now, since, schedule):
    return max(due_slots(now, since, **schedule), default=None)


SCHEDULES = {
    'macro_holding_refresh': dict(hours=[(1, 0)], weekdays=[5], grace=6*3600),
    'candidate_macro_refresh': dict(hours=[(4, 0)], weekdays=list(range(5)), grace=6*3600),
    'agent_pipeline': dict(hours=[(7, 0)], weekdays=[5], grace=6*3600),
    'outcome_labeler': dict(hours=[(18, 0)], weekdays=list(range(5)), grace=3600),
    'virtual_book_mtm': dict(hours=[(18, 30)], weekdays=list(range(5)), grace=3600),
    'backup': dict(hours=[(20, 0)], grace=3600),
}


def run_health(component, rows, now, since, schedule=None, timeout=6*3600):
    rows = sorted(rows, key=lambda r: r['started_at'] or 0)
    success = [r for r in rows if r['status'] == 'COMPLETE' and r.get('completed_at')]
    last = success[-1] if success else {}
    due = latest_due(now, since, schedule) if schedule else None
    evidence = dict(last_expected_at=due, last_started_at=rows[-1]['started_at'] if rows else None,
                    last_success_at=last.get('completed_at'), last_record_id=last.get('record_id'),
                    expected_cadence=json.dumps(schedule) if schedule else 'triggered', count=len(rows))
    # Historical resolved failures do not page forever; a later success resolves them.
    unresolved = [r for r in rows if r['started_at'] >= since and
                  (not last or r['started_at'] > last['started_at'])]
    failed = [r['record_id'] for r in unresolved if r['status'] in ('FAILED', 'STALE_FAILED', 'ERROR', 'error')]
    stuck = [r['record_id'] for r in unresolved if r['status'] in ('STARTED', 'IN_PROGRESS', 'running')
             and now - r['started_at'] > timeout]
    if failed or stuck:
        return result(component, 'RED', 'Failed or stale started work', failed=failed, stuck=stuck, **evidence)
    window_start = due
    if due and component == 'backup':
        # serve.py backs up after earlier successful refreshes too; its 20:00
        # backstop intentionally skips a day already backed up successfully.
        window_start = datetime.fromtimestamp(due, ET).replace(hour=0, minute=0).timestamp()
    if due and not any(r['started_at'] >= window_start and r['completed_at'] <= now for r in success):
        return result(component, 'YELLOW', 'Expected work has not completed', **evidence)
    return result(component, reason='Completed successfully' if last else 'No scheduled work due yet', **evidence)


def identity(conn, now):
    from agents.learning.macro_provenance import accepted_contract, digest
    from agents.learning.macro_experiment import load_protocol, base_contract
    acc = accepted_contract(conn, now)
    protocol = load_protocol()
    # Current code has no production macro weight setting/caller. Pin its entire
    # production routing source as well as the experimental stage-zero policy.
    files = ['agents/opportunity_agent.py', 'agents/orchestrator.py',
             'agents/learning/macro_experiment.py', 'agents/opportunity_config.py']
    return dict(acceptance=acc, validation_config_hash=hashlib.sha256((ROOT/'validation_config.json').read_bytes()).hexdigest(),
                protocol_hash=digest(protocol), base_contract_hash=base_contract(),
                influence_sources={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
                stage=0 if protocol['mode'] == 'observe_only' and protocol['stages']['0']['cap'] == 0 else None)


def check_identity(conn, baseline, now):
    current = identity(conn, now)
    expected = baseline['identity']
    checks = []
    for component, keys in [('macro_acceptance', ['acceptance', 'validation_config_hash']),
                            ('protocol', ['protocol_hash', 'base_contract_hash']),
                            ('influence_lock', ['influence_sources', 'stage'])]:
        okay = all(current[k] == expected[k] for k in keys)
        if component == 'macro_acceptance':
            okay = okay and current['acceptance'] is not None
        if component == 'influence_lock':
            okay = okay and current['stage'] == 0
        checks.append(result(component, 'INFO' if okay else 'RED',
                             'Pinned deployment contract matches' if okay else 'Unexpected contract or influence drift',
                             current={k: current[k] for k in keys}))
    epoch = conn.execute('SELECT * FROM macro_experiment_epochs ORDER BY registered_at DESC LIMIT 1').fetchone()
    if not epoch or epoch['epoch_id'] != baseline['epoch_id']:
        checks.append(result('protocol', 'RED', 'Unexpected experiment epoch', epoch_id=epoch['epoch_id'] if epoch else None))
    return checks


def continuity(conn, state, baseline, now):
    since = baseline['activated_at']
    runs = [dict(r) for r in conn.execute("SELECT * FROM agent_runs WHERE agent_type='opportunity_hunter' AND started_at>=?", (since,))]
    receipts = {r['run_id']: dict(r) for r in state.execute('SELECT * FROM watchdog_sweeps WHERE captured_at>=?', (since,))}
    cohorts = {str(r['agent_run_id']): dict(r) for r in conn.execute('SELECT * FROM macro_experiment_cohorts WHERE epoch_id=?', (baseline['epoch_id'],))}
    counts = dict(expected=0, observed=0, excluded=0, unexplained_missing=0)
    missing, learning_missing = [], []
    for run in runs:
        if run['status'] != 'done' or not run['finished_at'] or run['finished_at'] + 300 > now:
            continue
        counts['expected'] += 1
        key = str(run['id']); cohort = cohorts.get(key); rec = receipts.get(key)
        if cohort and cohort['status'] == 'OBSERVED':
            counts['observed'] += 1
        elif ((cohort and cohort['status'] == 'EXCLUDED' and cohort['exclusion_reason']) or
              (rec and rec['candidate_n'] == 0 and rec['exclusion_reason'] in ('no_candidates', 'all_candidates_held'))):
            counts['excluded'] += 1
        else:
            counts['unexplained_missing'] += 1; missing.append(key)
        # Independent receipt freezes applicable model set before shadow scoring.
        if not rec:
            learning_missing.append({'run_id': key, 'reason': 'missing sweep expectation receipt'})
        elif rec['candidate_n']:
            for model in json.loads(rec['models_json']):
                row = conn.execute('SELECT status,error FROM learning_sweep_runs WHERE agent_run_id=? AND model_version=? ORDER BY id DESC LIMIT 1', (key, model)).fetchone()
                if not row or row['status'] != 'COMPLETED':
                    learning_missing.append({'run_id': key, 'model': model, 'status': row['status'] if row else 'MISSING'})
    out = [result('macro_experiment', 'RED' if missing else 'INFO',
                  'Unexplained missing cohorts' if missing else 'Every completed sweep accounted for', **counts, missing_run_ids=missing),
           result('learning_continuity', 'RED' if learning_missing else 'INFO',
                  'Expected learning work missing or incomplete' if learning_missing else 'Expected learning sweeps accounted for', missing=learning_missing)]
    if counts['expected'] >= 5 and counts['excluded']/counts['expected'] > .5:
        out.append(result('experiment_exclusions', 'YELLOW', 'More than half of monitored sweeps excluded', **counts))
    else:
        out.append(result('experiment_exclusions', reason='Exclusion rate below investigation threshold', **counts))
    normalized = [dict(record_id=str(r['id']), started_at=r['started_at'], completed_at=r['finished_at'],
                       status='COMPLETE' if r['status']=='done' else r['status']) for r in runs]
    out.append(run_health('opportunity_hunter', normalized, now, since))
    return out


def outcomes_and_marks(conn, baseline, now):
    from trade_engine.market_calendar import maturity_date, is_trading_day
    from agents.learning.macro_experiment import _outcome
    from agents.learning.outcome_labeler import _entry_date
    missing, paired_missing, due_n = [], [], 0
    # Protect every captured candidate in this experiment, not just winners.
    for ep in conn.execute('SELECT episode_id,ticker,captured_at FROM decision_episodes WHERE macro_epoch=?', (baseline['epoch_id'],)):
        for horizon in ('1w','1m','3m'):
            day = maturity_date(_entry_date(ep['captured_at']), 'sessions_v2', horizon)
            deadline = datetime.fromisoformat(str(day)+'T19:00:00').replace(tzinfo=ET).timestamp()
            if deadline > now:
                continue
            due_n += 1
            if _outcome(conn, ep['episode_id'], horizon, now) is None:
                missing.append(dict(episode_id=ep['episode_id'], horizon=horizon, reason='missing_or_invalid_outcome'))
    for cohort in conn.execute("SELECT * FROM macro_experiment_cohorts WHERE epoch_id=? AND status='OBSERVED'", (baseline['epoch_id'],)):
        for horizon in ('1w','1m','3m'):
            day = maturity_date(cohort['decision_date'], 'sessions_v2', horizon)
            deadline = datetime.fromisoformat(str(day)+'T19:00:00').replace(tzinfo=ET).timestamp()
            if deadline <= now and not conn.execute("SELECT 1 FROM macro_experiment_labels WHERE cohort_id=? AND horizon=? AND horizon_version='sessions_v2'", (cohort['cohort_id'],horizon)).fetchone():
                paired_missing.append(dict(cohort_id=cohort['cohort_id'],horizon=horizon))
    marks = []
    for book in conn.execute('SELECT book_id,MIN(created_at) inception FROM virtual_fills GROUP BY book_id'):
        since = max(book['inception'], baseline['activated_at'])
        for due in due_slots(now, since, [(18,30)], sessions=True, grace=3600):
            day = datetime.fromtimestamp(due, ET).date().isoformat()
            row = conn.execute('SELECT is_complete,total_nav FROM virtual_book_nav WHERE book_id=? AND date=?', (book['book_id'],day)).fetchone()
            if not row or row['is_complete'] != 1 or row['total_nav'] is None:
                marks.append(dict(book_id=book['book_id'], date=day, reason='missing' if not row else 'incomplete'))
    return [result('outcome_completeness', 'YELLOW' if missing or paired_missing else 'INFO',
                   'Due outcomes missing or unevaluable' if missing or paired_missing else ('All due outcomes labeled' if due_n else 'Nothing due'),
                   due=due_n, overdue=len(missing), missing=missing[:50], paired_missing=paired_missing[:50]),
            result('mtm_completeness','YELLOW' if marks else 'INFO',
                   'Missing or incomplete daily marks' if marks else 'All due daily marks complete; pre-inception/not-due days excluded',
                   missing_n=len(marks), missing=marks[:50])]


def collect(conn, state, baseline, now):
    """No network, writes, scorer calls, state transitions or remediation here."""
    since = baseline['activated_at']; checks = []
    supported_calendar = 2026 <= datetime.fromtimestamp(now, ET).year <= 2028
    checks.append(result('market_calendar', 'INFO' if supported_calendar else 'RED',
                         'Session calendar within supported years' if supported_calendar else 'Session calendar requires an explicit update'))
    def guarded(component, fn):
        try:
            value = fn(); checks.extend(value if isinstance(value,list) else [value])
            if not any(r['component'] == component for r in (value if isinstance(value,list) else [value])):
                checks.append(result(component, reason='Authoritative checks completed'))
        except Exception as exc:
            checks.append(result(component,'RED','Check could not read authoritative evidence', error=type(exc).__name__))
    guarded('contracts', lambda: check_identity(conn,baseline,now))
    guarded('continuity', lambda: continuity(conn,state,baseline,now))
    guarded('outcomes', lambda: outcomes_and_marks(conn,baseline,now))
    def holding():
        rows=[]
        for r in conn.execute("SELECT * FROM macro_scoring_runs WHERE run_scope='full_refresh'"):
            end=conn.execute('SELECT MAX(completed_at) FROM macro_scoring_run_items WHERE run_id=?',(r['run_id'],)).fetchone()[0]
            status=r['status']
            if status=='COMPLETE' and (r['failed_n'] or r['scored_n']!=r['expected_n']): status='FAILED'
            rows.append(dict(record_id=r['run_id'],started_at=stamp(r['run_at'],True),completed_at=stamp(end,True),status=status))
        return run_health('macro_holding_refresh',rows,now,since,SCHEDULES['macro_holding_refresh'])
    guarded('macro_holding_refresh',holding)
    def candidates():
        rows=[dict(record_id=r['run_id'],started_at=r['started_at'],completed_at=r['completed_at'],
                   status='FAILED' if r['status']=='COMPLETE' and (r['failed_n'] or r['scored_n']!=r['expected_n']) else r['status'])
              for r in conn.execute('SELECT * FROM macro_candidate_scoring_runs')]
        return run_health('candidate_macro_refresh',rows,now,since,SCHEDULES['candidate_macro_refresh'])
    guarded('candidate_macro_refresh',candidates)
    def coverage():
        from agents.learning.macro_provenance import snapshot
        from agents.learning.macro_experiment import balanced_coverage, load_protocol
        cohort=conn.execute('SELECT cohort_id FROM macro_experiment_cohorts WHERE epoch_id=? ORDER BY captured_at DESC LIMIT 1',(baseline['epoch_id'],)).fetchone()
        if not cohort: return result('candidate_certification','YELLOW','No prospective universe available')
        rows=conn.execute('SELECT ticker,base_score,risk_eligible FROM macro_experiment_candidates WHERE cohort_id=?',(cohort[0],)).fetchall()
        if not rows: return result('candidate_certification','YELLOW','Latest cohort has no candidate evidence')
        best=max((r['base_score'] for r in rows if r['risk_eligible']),default=None)
        targets=[r for r in rows if r['risk_eligible'] and best is not None and r['base_score']>=best-2*load_protocol()['adjustment_cap']]
        snaps={r['ticker']:snapshot(r['ticker'],conn,now) for r in targets}
        common=set.intersection(*(set(s['usable_dimensions']) for s in snaps.values())) if snaps else set()
        incomplete=[t for t,s in snaps.items() if not s.get('coverage_certified')]
        return result('candidate_certification','YELLOW' if incomplete or not common else 'INFO',
                      'Coverage needs preparation' if incomplete or not common else 'Latest decision envelope has current certified evidence',
                      target_n=len(targets),common_dimensions=sorted(common),incomplete=incomplete)
    guarded('candidate_certification',coverage)
    def freshness():
        # The existing provenance gate applies actual runtime freshness/quality;
        # holdings receive its native five-day warning rather than invented expiry.
        from portfolio_ai import SCORE_STALE_DAYS
        rows=conn.execute('SELECT ticker,updated_at FROM holding_macro_scores').fetchall()
        stale=[r['ticker'] for r in rows if not stamp(r['updated_at'],True) or now-stamp(r['updated_at'],True)>SCORE_STALE_DAYS*86400]
        last_day=conn.execute('SELECT MAX(day) FROM holding_day WHERE price>0').fetchone()[0]
        from trade_engine.market_calendar import is_trading_day
        day=datetime.fromtimestamp(now,ET).date()
        if datetime.fromtimestamp(now,ET).hour<19: day-=timedelta(days=1)
        while not is_trading_day(day): day-=timedelta(days=1)
        prices_stale=not last_day or last_day<day.isoformat()
        return result('data_freshness','YELLOW' if stale or prices_stale else 'INFO',
                      'Stale prices or holding scores' if stale or prices_stale else 'Source freshness checks passed',
                      stale_holding_scores=stale,last_price_day=last_day,expected_price_day=day.isoformat())
    guarded('data_freshness',freshness)
    for component in ('agent_pipeline','outcome_labeler','virtual_book_mtm','backup','candidate_preparation'):
        rows=[dict(r) for r in state.execute('SELECT * FROM watchdog_receipts WHERE component=?',(component,))]
        schedule=SCHEDULES.get(component,SCHEDULES['candidate_macro_refresh'])
        timeout = 600 if component == 'backup' else (3600 if component in ('outcome_labeler','virtual_book_mtm') else 6*3600)
        checks.append(run_health(component,rows,now,since,schedule,timeout=timeout))
    # Pipeline receipt lists expected triggered OH and actual completed run IDs.
    for row in state.execute("SELECT * FROM watchdog_receipts WHERE component='agent_pipeline' AND status='COMPLETE' AND started_at>=?",(since,)):
        detail=json.loads(row['detail'])
        if detail.get('opportunity_expected') and not detail.get('opportunity_run_ids'):
            checks.append(result('opportunity_hunter','RED','Triggered Opportunity Hunter never started',last_record_id=row['record_id']))
    return checks


def persist(state, checks, now):
    # Merge duplicate component checks by highest severity.
    merged={}
    for check in checks:
        key=check['component']
        if key not in merged or RANK[check['status']]>=RANK[merged[key]['status']]: merged[key]=check
    for key, check in merged.items():
        old=state.execute('SELECT * FROM system_watchdog_state WHERE component=?',(key,)).fetchone()
        incident=old['incident_id'] if old else None
        severity=check['status']
        if severity=='INFO' and incident:
            state.execute('INSERT INTO watchdog_events VALUES (?,?,?,?,?,?,?,?)',
                          (str(uuid.uuid4()),incident,key,'INFO',now,'RESOLVED',check['reason'],json.dumps(check['evidence'])))
            incident=None
        elif severity!='INFO' and (not incident or old['status']!=severity):
            incident=incident or str(uuid.uuid4())
            state.execute('INSERT INTO watchdog_events VALUES (?,?,?,?,?,?,?,?)',
                          (str(uuid.uuid4()),incident,key,severity,now,'OPEN' if not old or not old['incident_id'] else 'SEVERITY_CHANGED',check['reason'],json.dumps(check['evidence'])))
        e=check['evidence']
        state.execute('INSERT OR REPLACE INTO system_watchdog_state VALUES (?,?,?,?,?,?,?,?,?,?)',
                      (key,e.get('last_expected_at'),e.get('last_started_at'),e.get('last_success_at'),e.get('last_record_id'),
                       e.get('expected_cadence'),severity,json.dumps(check),now,incident))
    # Uninspected components retain their previous evidence and age to STALE.
    # Missing evidence during a DB outage must never resolve an incident.
    state.commit()


def report(path=None, now=None):
    now=time.time() if now is None else now
    path=path or STATE
    try:
        c=sqlite3.connect(f'file:{path}?mode=ro',uri=True);c.row_factory=sqlite3.Row
        rows=[dict(r) for r in c.execute('SELECT * FROM system_watchdog_state ORDER BY component')];c.close()
        checked=min((r['checked_at'] for r in rows),default=0)
        stale=not checked or now-checked>35*60
        severity=max((r['status'] for r in rows),key=lambda s:RANK[s],default='INFO')
        output=dict(overall='RED' if severity=='RED' else ('STALE' if stale else ('HEALTHY' if severity=='INFO' else severity)),
                    stale=stale,checked_at=checked,components=rows)
        fallback=Path(path).parent/'watchdog_failure.json'
        if fallback.exists():
            failure=json.loads(fallback.read_text())
            if failure['checked_at']>max((r['checked_at'] for r in rows),default=0):
                output.update(overall='RED',watchdog_failure=failure)
        return output
    except (OSError,sqlite3.Error,ValueError,KeyError):
        return dict(overall='UNKNOWN',checked_at=None,components=[])


def delivery_failures(state, now):
    keys=[]
    for r in state.execute("SELECT incident_id FROM system_watchdog_state WHERE status='RED' AND incident_id IS NOT NULL"):
        event=state.execute("SELECT event_id FROM watchdog_events WHERE incident_id=? AND severity='RED' ORDER BY detected_at DESC LIMIT 1",(r[0],)).fetchone()
        if event: keys.append('red:'+event[0])
    if state.execute("SELECT 1 FROM system_watchdog_state WHERE status='YELLOW' AND component!='notification_delivery' LIMIT 1").fetchone():
        keys.append('yellow:'+datetime.fromtimestamp(now,ET).date().isoformat())
    return sum(bool(state.execute('SELECT 1 FROM watchdog_delivery WHERE delivery_key=? AND delivered_at IS NULL AND error IS NOT NULL',(key,)).fetchone()) for key in keys)


def deliver(state, now, transport, enabled=False):
    """Deduplicated notification attempts, never business-job retries.

    Immediate RED incident transitions, one unresolved-YELLOW digest after 20:00
    ET. Failed deliveries retry at 15m, 30m, 1h, 2h, then at most every 6h.
    """
    pending=[]
    for row in state.execute("SELECT * FROM system_watchdog_state WHERE status='RED' AND incident_id IS NOT NULL"):
        event=state.execute("SELECT event_id FROM watchdog_events WHERE incident_id=? AND severity='RED' ORDER BY detected_at DESC LIMIT 1",(row['incident_id'],)).fetchone()
        pending.append(('red:'+event[0], 'RED operational watchdog: '+row['component'],[dict(row)]))
    et=datetime.fromtimestamp(now,ET)
    yellow=[dict(r) for r in state.execute("SELECT * FROM system_watchdog_state WHERE status='YELLOW'")]
    if yellow and et.hour>=20:
        pending.append(('yellow:'+et.date().isoformat(),'Operational watchdog: unresolved YELLOW findings',yellow))
    sent=0
    for key,subject,rows in pending:
        previous=state.execute('SELECT * FROM watchdog_delivery WHERE delivery_key=?',(key,)).fetchone()
        if previous and (previous['delivered_at'] or now-previous['last_attempt']<min(21600,900*2**min(previous['attempts']-1,5))): continue
        # Only component summaries and timing go to email; evidence can contain
        # portfolio data and remains on the host for authenticated inspection.
        body='\n'.join(f"{r['component']}: {json.loads(r['detail'])['reason']}\nLast success: {r['last_success_at']}\nRecord: {r['last_record_id']}\nIncident: {r['incident_id']}" for r in rows)
        if not enabled:
            print(json.dumps(dict(delivery_key=key,subject=subject,body=body,dry_run=True)))
            continue
        attempts=(previous['attempts'] if previous else 0)+1
        # Reserve attempt before transport so crash/restart does not storm SMTP.
        state.execute('INSERT OR REPLACE INTO watchdog_delivery VALUES (?,?,?,NULL,NULL)',(key,attempts,now));state.commit()
        error=None
        try:
            transport(subject,body);sent+=1
        except Exception as exc:
            error=type(exc).__name__
            print(f'[watchdog] notification delivery failed: {error}',flush=True)
        state.execute('UPDATE watchdog_delivery SET delivered_at=?,error=? WHERE delivery_key=?',(None if error else now,error,key));state.commit()
    return sent


def email_transport(subject, body):
    # Same Gmail transport and credential names as serve.py; independent import
    # avoids booting the application just to report that it is unavailable.
    import os
    import smtplib
    from email.message import EmailMessage
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    sender,password,recipient=(os.getenv(k) for k in ('EMAIL_FROM','EMAIL_APP_PASSWORD','EMAIL_TO'))
    if not all((sender,password,recipient)): raise RuntimeError('Missing configured email credentials')
    msg=EmailMessage();msg['From']=sender;msg['To']=recipient;msg['Subject']=subject;msg.set_content(body)
    with smtplib.SMTP_SSL('smtp.gmail.com',465,timeout=20) as smtp:
        smtp.login(sender,password);smtp.send_message(msg)
