#!/bin/bash
echo "$(date) starting" >> /Users/ai_lab/Desktop/investment/out/daemon-debug.log
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH __PYVENV_LAUNCHER__
/opt/homebrew/opt/python@3.14/bin/python3.14 -m http.server 5001 \
  --bind localhost \
  --directory /Users/ai_lab/Desktop/investment >> /Users/ai_lab/Desktop/investment/out/daemon-debug.log 2>&1
echo "$(date) exited $?" >> /Users/ai_lab/Desktop/investment/out/daemon-debug.log
