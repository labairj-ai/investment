"""Pure observe/classify projection. No I/O, callbacks or remediation interface."""
from __future__ import annotations
import math
import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

VERSION='development-watchdog-1'
ET=ZoneInfo('America/New_York')
REQUIRED={'ci','telemetry','performance'}
HEX40=re.compile('[a-f0-9]{40}');HEX32=re.compile('[a-f0-9]{32}');HEX64=re.compile('[a-f0-9]{64}')
RANK={'INFO':0,'YELLOW':1,'RED':2}
COMPONENTS=('source','authority','schedule','signals','scheduler','execution','host_safety','coverage')
DEFAULTS=dict(version=VERSION,execution_grace_seconds=900,missed_run_red_seconds=7200,collector_delayed_seconds=4500,spool_warning_seconds=108000,scheduler_warning_seconds=1800)
REASONS={
 'source_ok':'Reviewed discovery source and observer pin match', 'source_bad':'Discovery source, observer service or trusted boundary differs',
 'authority_ok':'Reviewed development authority controls match', 'authority_bad':'Unexpected development implementation authority or activity',
 'schedule_ok':'Reviewed Scout timer is active with a valid next trigger', 'schedule_bad':'Scout timer is missing, disabled, inactive or drifted',
 'signals_ok':'Required discovery signals are fresh and available', 'signals_warn':'Collector is delayed or signal freshness is approaching its limit', 'signals_bad':'Required discovery signals or collector are unavailable, invalid or stale',
 'scheduler_ok':'Independent scheduler observation is current', 'scheduler_warn':'Scheduler observation or service is delayed', 'scheduler_bad':'Independent scheduler observation is unavailable or stale',
 'execution_ok':'Genuine required Scout execution is accounted for', 'execution_future':'First genuine Scout slot is not due yet', 'execution_pending':'Required Scout slot is inside its permitted completion window', 'execution_late':'Expected genuine Scout run is late', 'execution_bad':'Expected genuine Scout run failed, is invalid or never completed',
 'safety_ok':'Genuine Scout runs have matching protected host-safety evidence', 'safety_pending':'Host safety is pending the first completed genuine Scout run', 'safety_bad':'Scout host-safety evidence is missing, mismatched or unsafe',
 'coverage_ok':'Independent watchdog component and timer are verified', 'coverage_bad':'Independent watchdog coverage is unavailable',
 'unavailable':'Development discovery evidence could not be inspected'}


def finite(value):return type(value) in (int,float) and math.isfinite(value)
def valid_hex(value,pattern):return isinstance(value,str) and pattern.fullmatch(value) is not None


def policy(data):
    if not isinstance(data,dict) or set(data)!=set(DEFAULTS) or data['version']!=VERSION:raise ValueError('reviewed watchdog policy required')
    for k in DEFAULTS.keys()-{'version'}:
        if type(data[k]) is not int:raise ValueError('integer watchdog threshold required')
    if not 0<=data['execution_grace_seconds']<=3600 or not max(data['execution_grace_seconds'],900)<data['missed_run_red_seconds']<=21600:raise ValueError('bounded execution escalation required')
    if not 3600<=data['collector_delayed_seconds']<=7200 or not 3600<=data['spool_warning_seconds']<129600 or not 900<=data['scheduler_warning_seconds']<3600:raise ValueError('existing freshness limits cannot expand')
    return data


def reviewed_phase(config):
    if not isinstance(config,dict) or any(config.get(k) is not False for k in ('autonomous_implementation','auto_merge')) or config.get('required_human_merge') is not True or config.get('autonomy_stage')!='SHADOW' or config.get('autonomous_max_risk')!='L2':return None
    pair=(config.get('supervised_loop_enabled'),config.get('supervised_publish_pr'))
    if all(v is False for v in pair):return 'discovery'
    if all(v is True for v in pair):return 'supervised'
    return None


def required_slot(now,installed):
    """Latest due Eastern calendar slot since real installation observation."""
    if not finite(installed) or not 0<installed<=now:raise ValueError('real scheduler installation observation required')
    day=datetime.fromtimestamp(now,ET).date()
    scheduled=datetime(day.year,day.month,day.day,8,15,tzinfo=ET)
    if scheduled.timestamp()>now:scheduled-=timedelta(days=1)
    return scheduled if scheduled.timestamp()>=installed else None


def timer_valid(unit):
    return isinstance(unit,dict) and unit.get('LoadState')=='loaded' and unit.get('UnitFileState') in {'enabled','enabled-runtime'} and unit.get('ActiveState')=='active' and unit.get('pinned') is True



def next_trigger_valid(timer,now):
    value=timer.get('next_at');last=timer.get('last_at')
    if not finite(value) or not now<value<=now+27*3600 or last is not None and (not finite(last) or not 0<=last<=now):return False
    try:
        today=datetime.fromtimestamp(now,ET).replace(hour=8,minute=15,second=0,microsecond=0)
        target=datetime.fromtimestamp(value,ET);base=target.replace(hour=8,minute=15,second=0,microsecond=0)
        days={today.date()} if now<today.timestamp() else {today.date(),(today+timedelta(days=1)).date()} if now<=today.timestamp()+180 else {(today+timedelta(days=1)).date()}
        if target.date() in days and 0<=value-base.timestamp()<=180:return True
        # A genuine Persistent catch-up may be queued outside calendar time.
        # This validates metadata only: only root-bookended execution clears late work.
        return timer.get('Persistent')=='yes' and now>=today.timestamp() and (last is None or last<today.timestamp()) and value-now<=180
    except (ValueError,OverflowError,OSError):return False


def good_run(p,head,now):
    from .scheduler_health import successful_execution,timer_invocation
    if not isinstance(p,dict) or not successful_execution(dict(kind='SCHEDULE',payload=p),set(),now):return False
    return (p.get('head')==head and p.get('fixture_only') is not True and p.get('synthetic') is not True and p.get('status')=='COLLECTED' and p.get('unavailable')==[]
            and isinstance(p.get('enabled_sources'),list) and REQUIRED<=set(p['enabled_sources']) and p['duration_seconds']<=240
            and isinstance(p.get('candidates'),list) and all(isinstance(c,str) and c for c in p['candidates'])
            and all(type(p.get(k)) is int and p[k]>=0 for k in ('created','deduplicated','suppressed','signal_count','proposal_count'))
            and timer_invocation(p) is not None)


def safe_record(run,proof,head,now):
    from .scheduler_health import timer_invocation
    if not isinstance(proof,dict) or proof.get('source_head')!=head or proof.get('fixture_only') is not False or proof.get('os_boundary_verified') is not True:return False
    stamp=proof.get('observed_at')
    if not finite(stamp) or not run['ended_at']<=stamp<=now:return False
    rows=proof.get('runs')
    if not isinstance(rows,list) or len(rows)>30:return False
    matches=[r for r in rows if isinstance(r,dict) and r.get('invocation')==timer_invocation(run)]
    if len(matches)!=1:return False
    r=matches[0]
    return (r.get('slot')==run['slot'] and all(r.get(k) is True for k in ('no_builder','no_worktree','no_source_mutation','no_pr','no_deploy','no_financial_execution'))
            and all(valid_hex(r.get(k+'_before'),HEX64) and r[k+'_before']==r.get(k+'_after') for k in ('holdings','investment')))


def failures(service,previous):
    """Distinct observed failed invocations in watchdog's own projection only."""
    if service.get('Result')=='success':return []
    rows=[v for v in previous if valid_hex(v,HEX32)] if isinstance(previous,list) else []
    key=service.get('InvocationID')
    if valid_hex(key,HEX32) and key not in rows:rows.append(key)
    return rows[-4:]


def evaluate(snapshot,now):
    """Returns sanitized existing-watchdog checks; never awards acceptance."""
    checks=[];detail={};head=snapshot.get('head');head=head if valid_hex(head,HEX40) else None
    def add(component,code,severity='INFO',**evidence):
        checks.append(dict(component='development_discovery_'+component,status=severity,reason=REASONS[code],evidence=dict(code=code,source_head=head,**evidence)))
    try:cfg=policy(snapshot.get('policy'))
    except (ValueError,TypeError):cfg=DEFAULTS;add('source','source_bad','RED')
    observer=snapshot.get('units',{}).get('investment-discovery-observer.service',{})
    source_ok=(head is not None and snapshot.get('source_ok') is True and snapshot.get('observer_head')==head and snapshot.get('observer_socket_ok') is True and observer.get('pinned') is True and observer.get('ActiveState')=='active' and observer.get('SubState')=='running')
    add('source','source_ok' if source_ok else 'source_bad','INFO' if source_ok else 'RED')
    phase=reviewed_phase(snapshot.get('reviewed_config'))
    authority_ok=(source_ok and phase is not None and snapshot.get('config')==snapshot.get('reviewed_config') and not snapshot.get('worktree_present') and snapshot.get('supervised_units_absent') is True)
    if phase=='supervised':authority_ok=(source_ok and snapshot.get('config')==snapshot.get('reviewed_config'))
    if phase=='discovery' and (snapshot.get('implementation_events') or snapshot.get('builder_processes',-1)!=0):authority_ok=False
    add('authority','authority_ok' if authority_ok else 'authority_bad','INFO' if authority_ok else 'RED')
    units=snapshot.get('units',{});scout=units.get('development-scout.timer',{});next_run=scout.get('next_at')
    schedule_ok=(timer_valid(scout) and scout.get('calendar_valid') is True and next_trigger_valid(scout,now))
    add('schedule','schedule_ok' if schedule_ok else 'schedule_bad','INFO' if schedule_ok else 'RED')
    previous=snapshot.get('previous_failures',{});history={}
    for name in ('development-signal-collector','development-scheduler-observer'):
        history[name]=failures(units.get(name+'.service',{}),previous.get(name,[]))
    spool=snapshot.get('spool',{});stamp=spool.get('created');age=now-stamp if finite(stamp) else None
    signals_ok=(timer_valid(units.get('development-signal-collector.timer',{})) and snapshot.get('spool_valid') is True and finite(age) and 0<=age<=129600
                and spool.get('unavailable')==[] and isinstance(spool.get('enabled_sources'),list) and REQUIRED<=set(spool['enabled_sources']))
    signal_fail=units.get('development-signal-collector.service',{}).get('Result') not in {'success'}
    if not signals_ok or len(history['development-signal-collector'])>=2:add('signals','signals_bad','RED')
    elif age>=min(cfg['spool_warning_seconds'],cfg['collector_delayed_seconds']) or signal_fail:add('signals','signals_warn','YELLOW')
    else:add('signals','signals_ok')
    observed=snapshot.get('scheduler',{});stamp=observed.get('created');scheduler_age=now-stamp if finite(stamp) else None
    scheduler_ok=(timer_valid(units.get('development-scheduler-observer.timer',{})) and observed.get('status')=='SCHEDULED' and observed.get('enabled') is True
                  and observed.get('active')=='active' and finite(scheduler_age) and 0<=scheduler_age<=3600)
    if not scheduler_ok or len(history['development-scheduler-observer'])>=2:add('scheduler','scheduler_bad','RED')
    elif scheduler_age>=cfg['scheduler_warning_seconds'] or units.get('development-scheduler-observer.service',{}).get('Result')!='success':add('scheduler','scheduler_warn','YELLOW')
    else:add('scheduler','scheduler_ok')
    try:slot=required_slot(now,snapshot.get('installed_at'))
    except (ValueError,OverflowError,OSError):slot=None;add('execution','execution_bad','RED')
    expected='scout:'+slot.date().isoformat() if slot else None
    runs=snapshot.get('runs',[]);runs=runs if isinstance(runs,list) and len(runs)<=1000 else []
    successful=[p for p in runs if good_run(p,head,now)]
    proof=snapshot.get('host_proof') if snapshot.get('host_proof_protected') is True else None
    proof_header_ok=(isinstance(proof,dict) and proof.get('source_head')==head and proof.get('fixture_only') is False and proof.get('os_boundary_verified') is True and finite(proof.get('observed_at')) and 0<=now-proof['observed_at'] and isinstance(proof.get('runs'),list) and len(proof['runs'])<=30)
    if runs:
        latest=max((p for p in runs if isinstance(p,dict)),key=lambda p:p.get('ended_at') if finite(p.get('ended_at')) else 0,default={})
        if latest.get('head')!=head:add('source','source_bad','RED')
        if not good_run(latest,head,now):add('execution','execution_bad','RED')
    proven=[p for p in successful if safe_record(p,proof,head,now)]
    selected=[p for p in runs if isinstance(p,dict) and p.get('slot')==expected] if expected else []
    failed=[p for p in snapshot.get('failed_runs',[]) if isinstance(p,dict) and p.get('slot')==expected]
    current=[p for p in proven if p.get('slot')==expected]
    last=max(proven,key=lambda p:p['ended_at'],default=None)
    latest_service=units.get('development-scout.service',{})
    pending=[p for p in successful if p not in proven and latest_service.get('InvocationID')==p['trigger']['invocation'] and latest_service.get('ActiveState') in {'activating','active','deactivating'} and 0<=now-p['started_at']<=240]
    mature=[p for p in successful if p not in pending]
    last_current=max((p['ended_at'] for p in current),default=None)
    unresolved_failures=[p for p in failed if last_current is None or not finite(p.get('ended_at')) or p['ended_at']>=last_current]
    selected_pending=[p for p in selected if p in pending]
    if unresolved_failures or (selected and (len(selected)!=1 or not current and not selected_pending)) or (expected and latest_service.get('Result') not in {'success'}):add('execution','execution_bad','RED',expected_slot=expected)
    elif current:
        if not scout.get('last_at'):add('execution','execution_bad','RED',expected_slot=expected)
        else:add('execution','execution_ok',expected_slot=expected,last_success_at=current[-1]['ended_at'])
    elif not expected:add('execution','execution_future')
    else:
        # Reviewed delay120 + timer accuracy60 + full observer completion240.
        late=now-(slot.timestamp()+120+60+240)
        if late>cfg['missed_run_red_seconds']:add('execution','execution_bad','RED',expected_slot=expected)
        elif late>cfg['execution_grace_seconds']:add('execution','execution_late','YELLOW',expected_slot=expected)
        else:add('execution','execution_pending',expected_slot=expected)
    if proof_header_ok:
        for record in proof['runs']:
            if not isinstance(record,dict) or not valid_hex(record.get('invocation'),HEX32) or not re.fullmatch(r'scout:\d{4}-\d{2}-\d{2}',str(record.get('slot',''))) or any(record.get(k) is not True for k in ('no_builder','no_worktree','no_source_mutation','no_pr','no_deploy','no_financial_execution')) or any(not valid_hex(record.get(k+'_before'),HEX64) or record[k+'_before']!=record.get(k+'_after') for k in ('holdings','investment')):proof_header_ok=False;break
    unsafe=(snapshot.get('host_proof_invalid') is True or (snapshot.get('host_proof') is not None and not proof_header_ok) or bool(mature and len(proven)!=len(mature)))
    add('host_safety','safety_bad' if unsafe else 'safety_ok' if proven else 'safety_pending','RED' if unsafe else 'INFO')
    producer_ok=snapshot.get('producer_verified') is True and timer_valid(units.get('macro-health-watchdog.timer',{}))
    add('coverage','coverage_ok' if producer_ok else 'coverage_bad','INFO' if producer_ok else 'RED')
    if snapshot.get('errors'):add('source','unavailable','RED')
    worst=max(checks,key=lambda c:RANK[c['status']]);severity=worst['status']
    acceptance=snapshot.get('acceptance',{});count=acceptance.get('successful_runs');count=count if type(count) is int and 0<=count<=30 else 0
    acceptance_valid=(acceptance.get('source_head')==head and acceptance.get('required_runs')==3 and isinstance(acceptance.get('runs'),list))
    ready=acceptance_valid and acceptance.get('status')=='READY' and count>=3 and acceptance.get('host_safety_accepted') is True
    if not acceptance_valid:
        add('source','source_bad','RED');severity='RED';worst=checks[-1]
    display='BLOCKED' if severity=='RED' else 'READY 3/3' if ready else 'ACCEPTING '+str(min(count,3))+'/3'
    detail=dict(version=VERSION,observed_at=now,producer_invocation=snapshot.get('producer_invocation') if valid_hex(snapshot.get('producer_invocation'),HEX32) else None,producer_pid=snapshot.get('producer_pid') if type(snapshot.get('producer_pid')) is int and snapshot['producer_pid']>0 else None,code=worst['evidence']['code'],source_head=head,observer_head=snapshot.get('observer_head') if valid_hex(snapshot.get('observer_head'),HEX40) else None,
                cached_main=snapshot.get('cached_main') if valid_hex(snapshot.get('cached_main'),HEX40) else None,status='HEALTHY' if severity=='INFO' else severity,phase=phase,acceptance=display,accepted_runs=count,required_runs=3,accepted_slots=[p['slot'] for p in acceptance.get('runs',[]) if isinstance(p,dict) and re.fullmatch(r'scout:\d{4}-\d{2}-\d{2}',str(p.get('slot','')))],
                host_safety='FAIL' if unsafe else 'PASS' if proven else 'PENDING',host_safety_accepted=acceptance.get('host_safety_accepted') is True,
                signals='HEALTHY' if signals_ok and not signal_fail else 'DEGRADED',expected_slot=expected,last_success_at=last['ended_at'] if last else None,
                candidate_count=len(last['candidates']) if last else 0,last_invocation=last['trigger']['invocation'] if last else None,next_scout=next_run if finite(next_run) else None,spool_age_seconds=age if finite(age) else None,
                scheduler_age_seconds=scheduler_age if finite(scheduler_age) else None,unavailable=sorted(s for s in REQUIRED if isinstance(spool.get('unavailable'),list) and s in spool['unavailable']),
                builder='DISABLED' if authority_ok and phase=='discovery' else 'SUPERVISED' if authority_ok else 'UNEXPECTED',producer_verified=producer_ok,
                code_identity=snapshot.get('code_identity'),failure_invocations=history,inspected=True,grants_implementation=False)
    for check in checks:
        check['evidence'].setdefault('expected_slot',expected)
        check['evidence'].setdefault('last_success_at',last['ended_at'] if last else None)
    checks.append(dict(component='development_discovery',status=severity,reason=REASONS[detail['code']],evidence=detail))
    return checks
