"""Install dedicated MLX news service on the existing Apple Silicon model host.
Run using that host's MLX Python. Reuses the downloaded model, port 8081.
"""
from pathlib import Path
import os
import plistlib
import subprocess
import sys

home = Path.home()
label = 'com.mlx.news'
path = home / 'Library/LaunchAgents' / (label + '.plist')
log = home / '.local/var/log/mlx-news.log'
log.parent.mkdir(parents=True, exist_ok=True)
config = {
    'Label': label,
    'ProgramArguments': [str(Path(sys.executable).parent / 'mlx_lm.server'),
        '--model', 'mlx-community/Qwen3.6-35B-A3B-4bit', '--port', '8081',
        '--host', '0.0.0.0', '--prompt-cache-size', '2', '--prompt-cache-bytes', '512MB'],
    'KeepAlive': True, 'RunAtLoad': True,
    'StandardOutPath': str(log), 'StandardErrorPath': str(log),
    'EnvironmentVariables': {'PATH': str(Path(sys.executable).parent)+':/usr/bin:/bin'},
}
path.write_bytes(plistlib.dumps(config))
domain = 'gui/'+str(os.getuid())
loaded = subprocess.run(['launchctl', 'print', domain+'/'+label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
if not loaded:
    subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
print('Installed '+label+' on port 8081')
