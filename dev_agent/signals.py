"""Bounded read-only operational signals; no broker/DB/network model calls."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import time
from .policy import safe_relative
from .store import SECRET,digest

SOURCES={'ci','telemetry','performance','accessibility','user'}


def redact(text):
    text=SECRET.sub('[REDACTED]',str(text))
    text=re.sub(r'(?i)(?:authorization|cookie|x-api-key)\s*[:=][^\r\n]*','[REDACTED]',text)
    text=re.sub(r'https?://[^\s/@:]+:[^\s/@]+@','https://[REDACTED]@',text)
    return text[:1000]


def signal(source,component,problem,files,evidence,*,outcome,validation,impact=3,confidence=.8,recurrence=1,observed=None,synthetic=False,category='FIX'):
    if source not in SOURCES or not files or len(files)>20:raise ValueError('bounded signal source/files required')
    for name in files:safe_relative(name)
    if type(recurrence) is not int or not 1<=recurrence<=100000 or not math.isfinite(confidence) or not 0<=confidence<=1 or not 0<=impact<=5:raise ValueError('signal metric bounds')
    observed=time.time() if observed is None else observed
    if not isinstance(observed,(int,float)) or not math.isfinite(observed) or not 0<=time.time()-observed<=7*86400:raise ValueError('fresh observed timestamp required')
    if not problem.strip() or not outcome.strip() or not validation.strip() or not evidence:raise ValueError('concrete problem/outcome/provenance required')
    stable=digest(dict(source=source,component=component,problem=redact(problem),files=sorted(files)))
    return dict(signal_id=stable,source=source,component=redact(component),observed_at=observed,evidence_location=redact(evidence),problem=redact(problem),files=files,impact=impact,recurrence=recurrence,confidence=confidence,category=category,outcome=redact(outcome),validation=redact(validation),synthetic=bool(synthetic),title=redact(problem)[:120],evidence=['signal:'+stable],dimensions=dict(impact=impact,reliability=impact))


def ci(client):
    payload=client.read(f'repos/{client.repository}/actions/runs?per_page=10')
    runs=payload.get('workflow_runs',[])
    if not isinstance(runs,list):raise ValueError('CI inventory unavailable')
    failures={};result=[]
    for run in runs[:10]:
        if run.get('conclusion') in {'failure','timed_out'}:failures.setdefault(run.get('name','Repository CI'),[]).append(run)
    for name,items in failures.items():
        result.append(signal('ci',name,'Repeated CI failure: '+name,['.github/workflows/test.yml'],items[0].get('html_url','GitHub workflow run'),outcome='Restore exact-head green CI without weakening gates',validation='reproduce failing gates and complete regression',recurrence=len(items),impact=4))
    return result


def runtime(observations):
    result=[]
    for item in observations[:50]:
        if item.get('kind') not in {'http_failure','service_restart','exception','stale_job','slow_endpoint','slow_dashboard','asset_growth','viewport_overflow','accessibility','skipped_test_growth','flaky_test','ci_duration'}:raise ValueError('unsupported bounded observation')
        count=item.get('recurrence',1)
        if item.get('recovered') and count==1:continue
        kind=item['kind'];source='performance' if kind.startswith(('slow_','asset_','ci_duration')) else 'accessibility' if kind in {'viewport_overflow','accessibility'} else 'ci' if kind in {'skipped_test_growth','flaky_test'} else 'telemetry'
        result.append(signal(source,item['component'],item['problem'],item['files'],item['evidence_location'],outcome=item['outcome'],validation=item['validation'],observed=item['observed_at'],synthetic=item.get('synthetic',False),recurrence=count,impact=min(5,2+count),category='FIX'))
    return result


def ingest(store,signals,*,suppressions=None):
    """Stable recurring identity updates evidence, never unlimited candidates."""
    if len(signals)>50:raise ValueError('signal batch too large')
    suppressions=suppressions or {};ids=[];deduplicated=0;suppressed=0
    for item in signals:
        if item['signal_id'] in suppressions and time.time()<suppressions[item['signal_id']]:suppressed+=1;continue
        with store.connect() as db:
            row=db.execute("SELECT payload FROM dev_events WHERE kind='SIGNAL_OBSERVATION' AND json_extract(payload,'$.signal_id')=? ORDER BY seq DESC LIMIT 1",(item['signal_id'],)).fetchone()
        previous=json.loads(row[0]) if row else None
        if previous:
            candidate=store.get(previous['candidate'])
            if candidate['state'] not in {'CLOSED','REJECTED'}:
                cid=candidate['id'];deduplicated+=1
            else:
                closed=max(e['created'] for e in candidate['events'] if e['kind']=='STATE')
                if item['observed_at']<=closed:suppressed+=1;continue
                item=dict(item,evidence=item['evidence']+['recurrence-after:'+str(closed)]);cid=store.discover(item)
        else:cid=store.discover(item)
        store.event(cid,'SIGNAL_OBSERVATION',dict(signal_id=item['signal_id'],candidate=cid,source=item['source'],observed_at=item['observed_at'],evidence_location=item['evidence_location'],recurrence=(previous.get('recurrence',0) if previous else 0)+item['recurrence'],confidence=item['confidence'],synthetic=item['synthetic']))
        ids.append(cid)
    return dict(candidates=ids,deduplicated=deduplicated,suppressed=suppressed)


def spool(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>64000:raise ValueError('bounded regular operator signal spool required')
    data=json.loads(path.read_text())
    if not isinstance(data,list) or len(data)>50:raise ValueError('bounded signal inventory required')
    return runtime(data)


def load_spool(path):
    import os,stat
    path=Path(path);info=path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or info.st_size>64000:raise ValueError('private operator spool required')
    data=json.loads(path.read_text())
    if data.get('version')!='development-signals-1' or not 0<=time.time()-data.get('created',0)<=36*3600:raise ValueError('stale or unrecognized signal spool')
    enabled=data.get('enabled_sources',[])
    if not isinstance(enabled,list) or not set(enabled)<=SOURCES:raise ValueError('signal source inventory invalid')
    if not {'ci','telemetry','performance'}<=set(enabled) or not isinstance(data.get('unavailable'),list) or set(data['unavailable'])&{'ci','CI','telemetry','performance'}:raise ValueError('required discovery signal sources unavailable')
    return runtime(data['observations']),enabled
