"""Quarter-hour display-quote refresh. No models, mail, broker or account actions."""
import fcntl
import subprocess
import time
from datetime import time as day_time
from pathlib import Path

from time_utils import now_utc, TZ_EASTERN
from trade_engine.market_calendar import is_trading_day, session_close_time


def slot(now):
    local = now.astimezone(TZ_EASTERN)
    if not is_trading_day(local.date()):
        return None
    clock = local.time().replace(tzinfo=None)
    close = session_close_time(local.date())
    # Include one post-close refresh at the next quarter-hour.
    close_minutes = close.hour*60+close.minute+15
    if clock < day_time(9,30) or local.hour*60+local.minute > close_minutes:
        return None
    return local.strftime('%Y-%m-%dT%H:')+str(local.minute//15)


def refresh(root, invoke=subprocess.run):
    root = Path(root)
    with (root/'out'/'display-quote-refresh.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(status='BUSY')
        py = str(root/'venv/bin/python')
        # The isolated child executes only the existing display-mark refresh.
        process = invoke([py,'-c',"from send_newsletter_main import fetch_cc_mtm; fetch_cc_mtm()"],
                         cwd=root,capture_output=True,text=True,timeout=180)
        if process.returncode:
            raise RuntimeError('DISPLAY_QUOTE_REFRESH_FAILED')
        process = invoke([py,str(root/'generate_dashboard.py')],cwd=root,
                         capture_output=True,text=True,timeout=180)
        if process.returncode:
            raise RuntimeError('DISPLAY_DASHBOARD_REFRESH_FAILED')
        return dict(status='REFRESHED')


def run(root, clock=now_utc, sleep=time.sleep):
    # Wait for the next scheduled slot on startup, avoiding duplicate jobs on restart.
    previous = slot(clock())
    while True:
        sleep(15)
        current = slot(clock())
        if current is None or current==previous:
            continue
        previous = current
        try:
            refresh(root)
        except Exception as error:
            print('[Display quotes] '+type(error).__name__+': '+str(error),flush=True)
