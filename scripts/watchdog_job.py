#!/usr/bin/env python3
"""Completion receipts for existing scheduled commands; never retries jobs."""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operational_watchdog import receipt

if __name__=='__main__':
    component=sys.argv[1]
    if sys.argv[2]!='--': raise SystemExit('Usage: watchdog_job.py component -- command ...')
    record=receipt(component)
    try:
        completed=subprocess.run(sys.argv[3:],check=False)
        receipt(component,record,'COMPLETE' if completed.returncode==0 else 'FAILED',{'exit_code':completed.returncode})
        raise SystemExit(completed.returncode)
    except Exception as exc:
        receipt(component,record,'FAILED',{'error':type(exc).__name__})
        raise
