#!/bin/bash
# Wrapper that keeps serve.py running. launchd manages this script;
# the loop here handles restarts so we don't rely on KeepAlive.
cd /Users/ai_lab/Desktop/investment
source venv/bin/activate

while true; do
  python3 serve.py
  echo "[run_server] serve.py exited ($(date)), restarting in 5s..." \
    >> /Users/ai_lab/Desktop/investment/out/dashboard-server.log 2>&1
  sleep 5
done
