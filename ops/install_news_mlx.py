"""Install resilient dedicated news MLX; optionally bound the shared service too.
Run with the model host's MLX Python. No model download or model change.
"""
import argparse
from pathlib import Path
import os
import plistlib
import shutil
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--bound-shared', action='store_true')
args=parser.parse_args()
home=Path.home()
wrapper=home/'.local/lib/investment/mlx_service.py'
wrapper.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(Path(__file__).with_name('mlx_service.py'),wrapper)
domain='gui/'+str(os.getuid())
limits={'--prompt-cache-size':'2','--prompt-cache-bytes':'512MB',
        '--decode-concurrency':'1','--prompt-concurrency':'1','--prefill-step-size':'512'}
labels=['com.mlx.news']+(['com.mlx.serve'] if args.bound_shared else [])
for label in labels:
    path=home/'Library/LaunchAgents'/(label+'.plist')
    log=home/'.local/var/log/mlx-news.log'
    log.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        config=plistlib.loads(path.read_bytes())
        argv=config['ProgramArguments']
        # Preserve model and other service arguments; replace only runtime and limits.
        start=argv.index('--model')
        model_args=argv[start:]
    elif label=='com.mlx.news':
        config={'Label':label,'StandardOutPath':str(log),'StandardErrorPath':str(log)}
        model_args=['--model','mlx-community/Qwen3.6-35B-A3B-4bit','--port','8081','--host','0.0.0.0']
    else:
        raise SystemExit('Shared service configuration missing; refusing to invent it')
    cleaned=[]; i=0
    while i<len(model_args):
        if model_args[i] in limits:
            i+=2
        else:
            cleaned.append(model_args[i]); i+=1
    config['ProgramArguments']=[sys.executable,str(wrapper)]+cleaned+[x for pair in limits.items() for x in pair]
    config.update(KeepAlive=True,RunAtLoad=True,ThrottleInterval=10)
    config.setdefault('EnvironmentVariables',{}).update(
        PATH=str(Path(sys.executable).parent)+':/usr/bin:/bin', HF_HUB_OFFLINE='1')
    if path.exists():
        backup=path.with_suffix('.plist.before-news-recovery')
        if not backup.exists(): shutil.copyfile(path,backup)
    path.write_bytes(plistlib.dumps(config))
    loaded=subprocess.run(['launchctl','print',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if loaded:
        subprocess.run(['launchctl','bootout',domain+'/'+label],check=True)
        time.sleep(2)  # launchd releases a booted-out job asynchronously.
    for attempt in range(5):
        result=subprocess.run(['launchctl','bootstrap',domain,str(path)],capture_output=True,text=True)
        if result.returncode==0:
            break
        if attempt==4:
            raise RuntimeError(result.stderr.strip())
        time.sleep(2)
    print('Installed/restarted '+label+' with bounded cache/concurrency and fatal-thread recovery')
