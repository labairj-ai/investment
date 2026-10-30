"""Read actual v255 properties during fixture Pre/Main; cannot emit Scout credit."""
import json,os,subprocess,sys,time
from pathlib import Path
SERVICE='/org/freedesktop/systemd1/unit/provenance_2dproof_2eservice'
TIMER='/org/freedesktop/systemd1/unit/provenance_2dproof_2etimer'
ENV={'PATH':'/usr/bin:/bin','HOME':'/nonexistent'}
def prop(path,interface,name):
 return json.loads(subprocess.check_output(['/usr/bin/busctl','--system','--json=short','get-property','org.freedesktop.systemd1',path,'org.freedesktop.systemd1.'+interface,name],env=ENV,timeout=5))
assert Path('/run/systemd/container').read_text().strip()=='docker'
phase=sys.argv[1];assert phase in {'pre','main'}
job=prop(SERVICE,'Unit','Job');path=job['data'][1]
row=dict(fixture_only=True,accepted_scout_run=False,phase=phase,pid=os.getpid(),uid=os.getuid(),boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),now_monotonic_us=int(time.monotonic()*1e6),job=job,job_properties={k:prop(path,'Job',k) for k in ('Id','Unit','JobType','State','ActivationDetails')},unit_details=prop(SERVICE,'Unit','ActivationDetails'),invocation=prop(SERVICE,'Unit','InvocationID'),invocation_hint=os.environ.get('INVOCATION_ID'),command=prop(SERVICE,'Service','ExecStartPre' if phase=='pre' else 'ExecStart'),substate=prop(SERVICE,'Unit','SubState'),timer_monotonic=prop(TIMER,'Timer','LastTriggerUSecMonotonic'),timer_realtime=prop(TIMER,'Timer','LastTriggerUSec'),job_again=prop(SERVICE,'Unit','Job'))
with Path('/var/lib/provenance-proof/records.jsonl').open('a') as stream:
 stream.write(json.dumps(row,separators=(',',':'))+'\n');stream.flush();os.fsync(stream.fileno())
