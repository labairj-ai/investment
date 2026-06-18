#!/usr/bin/env python3
import sys
import traceback
from pathlib import Path
from datetime import date

PROJECT_DIR = Path("/Users/ai_lab/Desktop/investment")
FLAG_FILE = PROJECT_DIR / "out" / "last_run_date.txt"
LOG_FILE = PROJECT_DIR / "out" / "wrapper.log"

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{date.today()} {msg}\n")

def already_ran_today():
    if not FLAG_FILE.exists():
        return False
    try:
        last_run = FLAG_FILE.read_text().strip()
        return last_run == date.today().isoformat()
    except:
        return False

def mark_as_run():
    FLAG_FILE.parent.mkdir(exist_ok=True)
    FLAG_FILE.write_text(date.today().isoformat())

if __name__ == "__main__":
    try:
        log("Starting wrapper")
        
        if already_ran_today():
            log("Already sent today, skipping")
            sys.exit(0)
        
        log("Running main script")
        sys.path.insert(0, str(PROJECT_DIR))
        exec(open(PROJECT_DIR / "send_newsletter_main.py").read())
        
        mark_as_run()
        log("Success")
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        sys.exit(1)
