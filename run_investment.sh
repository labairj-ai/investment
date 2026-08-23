#!/bin/bash
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOG="$BASE/out/newsletter.log"
TZNAME="America/New_York"
TODAY="$(TZ=$TZNAME /bin/date +%F)"
FLAG="$BASE/out/last_run_date.txt"

{
  echo "=== INVESTMENT AUTO $(TZ=$TZNAME /bin/date) ==="
} >> "$LOG" 2>&1

# Check flag file instead of database
if [ -f "$FLAG" ] && [ "$(cat $FLAG)" = "$TODAY" ]; then
  echo "Already sent for $TODAY — exiting." >> "$LOG" 2>&1
  exit 0
fi

echo "Sending newsletter for $TODAY..." >> "$LOG" 2>&1
cd "$BASE"
"$BASE/venv/bin/python3" "$BASE/send_newsletter_main.py" >> "$LOG" 2>&1

# Mark as sent
echo "$TODAY" > "$FLAG"
echo "SENT OK for $TODAY" >> "$LOG" 2>&1

"$BASE/venv/bin/python3" "$BASE/generate_dashboard.py" >> "$LOG" 2>&1
echo "DASHBOARD OK for $TODAY" >> "$LOG" 2>&1
