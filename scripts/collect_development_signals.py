"""Trusted read-only collector, separate from the private-network scout timer.

Only bounded metadata is persisted; no raw log, broker endpoint or financial DB.
"""
from __future__ import annotations
import argparse,json,os,subprocess,sys,time,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dev_agent.github import GitHub
from dev_agent.signals import redact


def collect(repository,*,invoke=subprocess.run,open_url=urllib.request.urlopen):
    observations=[];enabled=[];unavailable=[];now=time.time()
    try:
        payload=GitHub(repository).read(f'repos/{repository}/actions/runs?per_page=10')
        enabled.append('ci')
        for run in payload.get('workflow_runs',[])[:10]:
            if run.get('conclusion') in {'failure','timed_out'}:observations.append(dict(kind='flaky_test',component='repository-ci',problem='Repository workflow failed: '+redact(run.get('name','Tests')),files=['.github/workflows/test.yml'],evidence_location=run['html_url'],observed_at=now,recurrence=1,outcome='Restore green exact-head validation',validation='complete regression and release gates',synthetic=False))
    except Exception:unavailable.append('ci')
    try:
        raw=invoke(['systemctl','show','investment.service','--no-pager','--property=ActiveState,NRestarts'],capture_output=True,text=True,check=True,timeout=10).stdout
        state=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        enabled.append('telemetry')
        count=min(100000,max(int(state.get('NRestarts','0')),1))
        if state.get('ActiveState')!='active' or int(state.get('NRestarts','0'))>=3:observations.append(dict(kind='service_restart',component='investment.service',problem='Service inactive or repeated restarts',files=['serve.py'],evidence_location='systemd:investment.service',observed_at=now,recurrence=count,outcome='Restore stable read-only service health',validation='service health and restart observation',synthetic=False))
    except Exception:unavailable.append('telemetry')
    try:
        started=time.monotonic()
        try:
            with open_url('http://127.0.0.1:5001/development-agent',timeout=5) as response:status=response.status;response.read(1024)
        except urllib.error.HTTPError as error:status=error.code
        elapsed=time.monotonic()-started;enabled.append('performance')
        if status>=500:observations.append(dict(kind='http_failure',component='development-dashboard',problem='Dashboard HTTP health failed',files=['serve.py'],evidence_location='loopback GET /development-agent',observed_at=now,recurrence=1,outcome='Restore dashboard health',validation='read-only HTTP health check',synthetic=False))
        # Persist duration as bounded observation only; a single slow event is not
        # an actionable regression without a trusted rolling baseline.
        health=dict(dashboard_seconds=round(elapsed,3),http_status=status)
    except Exception:unavailable.append('performance');health=dict(http_status='UNAVAILABLE')
    return dict(version='development-signals-1',created=now,enabled_sources=enabled,unavailable=unavailable,health=health,observations=observations[:50])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--repository',default='labairj-ai/investment');a=p.parse_args()
    if a.out.is_symlink():raise ValueError('symlink spool denied')
    a.out.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temp=a.out.with_name(a.out.name+'.new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:json.dump(collect(a.repository),f);f.flush();os.fsync(f.fileno())
    os.replace(temp,a.out)
