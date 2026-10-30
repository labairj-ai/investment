"""Validate native availability, never authenticate or award a Scout run."""
import json,sys
from pathlib import Path

def validate(rows):
 assert len(rows)>=6,'three complete fixture activations required'
 rows=rows[:6];invocations=[];jobs=[];fires=[];unit_first=None
 for index in range(0,6,2):
  pair=rows[index:index+2];assert [p['phase'] for p in pair]==['pre','main']
  first=pair[0]
  for p in pair:
   assert p['fixture_only'] is True and p['accepted_scout_run'] is False and p['uid']==1000
   assert p['boot']==first['boot'] and p['job']==p['job_again']==first['job']
   j=p['job'];assert j['type']=='(uo)' and type(j['data'][0]) is int and j['data'][0]>0
   assert j['data'][1]=='/org/freedesktop/systemd1/job/'+str(j['data'][0])
   props=p['job_properties']
   assert props['Id']=={'type':'u','data':j['data'][0]}
   assert props['Unit']=={'type':'(so)','data':['provenance-proof.service','/org/freedesktop/systemd1/unit/provenance_2dproof_2eservice']}
   assert props['JobType']=={'type':'s','data':'start'} and props['State']=={'type':'s','data':'running'}
   detail=props['ActivationDetails'];assert detail['type']=='a(ss)'
   d=dict(detail['data']);assert len(d)==len(detail['data']) and d['trigger_unit']=='provenance-proof.timer'
   assert d['trigger_timer_monotonic_usec']==str(p['timer_monotonic']['data'])
   assert d['trigger_timer_realtime_usec']==str(p['timer_realtime']['data'])
   assert 0<=p['now_monotonic_us']-p['timer_monotonic']['data']<5_000_000
   inv=p['invocation'];assert inv['type']=='ay' and len(inv['data'])==16
   assert bytes(inv['data']).hex()==p['invocation_hint']==first['invocation_hint']
   cmd=p['command'];assert cmd['type']=='a(sasbttttuii)' and len(cmd['data'])==1
   r=cmd['data'][0];assert r[7]==p['pid'] and r[1][-1]==p['phase'] and not any(r[i] for i in (5,6,8,9))
   assert r[0]=='/usr/bin/python3' and r[1][:3]==['/usr/bin/python3','-I','-S']
   assert p['substate']=={'type':'s','data':'start-pre' if p['phase']=='pre' else 'start'}
  invocations.append(first['invocation_hint']);jobs.append(first['job']['data'][0]);fires.append(first['timer_monotonic']['data'])
  details=dict(first['unit_details']['data'])
  if unit_first is None:unit_first=details['trigger_timer_monotonic_usec']
  assert details['trigger_timer_monotonic_usec']==unit_first,'fixture must reproduce retained Unit metadata'
 assert len(set(invocations))==len(set(jobs))==len(set(fires))==3
 assert fires==sorted(fires) and str(fires[1])!=unit_first and str(fires[2])!=unit_first
 return dict(status='PASS',fixture_only=True,accepted_scout_run=False,activation_count=3,pre_and_main_job_available=True,retained_unit_metadata_reproduced=True,invocations=invocations,jobs=jobs,timer_fires=fires)

if __name__=='__main__':
 rows=[json.loads(s) for s in Path(sys.argv[1]).read_text().splitlines()]
 result=validate(rows);result['systemd_package']=Path(sys.argv[2]).read_text().strip()
 assert result['systemd_package']=='255.4-1ubuntu8.18'
 print(json.dumps(result,indent=2))
