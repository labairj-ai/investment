#!/bin/bash
set -euo pipefail

LOG="/Users/ai_lab/Desktop/investment/out/newsletter.log"
TZNAME="America/New_York"
TODAY="$(TZ=$TZNAME /bin/date +%F)"
FLAG="/Users/ai_lab/Desktop/investment/out/last_run_date.txt"

{
  echo "=== INVESTMENT AUTO $(TZ=$TZNAME /bin/date) ==="
} >> "$LOG" 2>&1

# Check flag file instead of database
if [ -f "$FLAG" ] && [ "$(cat $FLAG)" = "$TODAY" ]; then
  echo "Already sent for $TODAY — exiting." >> "$LOG" 2>&1
  exit 0
fi

echo "Sending newsletter for $TODAY..." >> "$LOG" 2>&1

cd /Users/ai_lab/Desktop/investment
/Users/ai_lab/Desktop/investment/venv/bin/python3 /Users/ai_lab/Desktop/investment/send_newsletter_main.py >> "$LOG" 2>&1

# Mark as sent
echo "$TODAY" > "$FLAG"
echo "SENT OK for $TODAY" >> "$LOG" 2>&1

/Users/ai_lab/Desktop/investment/venv/bin/python3 /Users/ai_lab/Desktop/investment/generate_dashboard.py >> "$LOG" 2>&1
echo "DASHBOARD OK for $TODAY" >> "$LOG" 2>&1
