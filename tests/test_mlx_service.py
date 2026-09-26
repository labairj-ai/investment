"""An inference-thread crash must not leave an apparently healthy HTTP process."""
from pathlib import Path
import subprocess
import sys


def test_fatal_background_thread_terminates_process():
    root=Path(__file__).resolve().parents[1]
    code='''import threading,time
from ops.mlx_service import fatal_thread_error
threading.excepthook=fatal_thread_error
def fail(): raise RuntimeError('simulated inference failure')
t=threading.Thread(target=fail)
t.start()
t.join()
time.sleep(5)
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True,timeout=3)
    assert result.returncode==1
    assert 'simulated inference failure' in result.stderr
