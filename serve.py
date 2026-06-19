#!/usr/bin/env python3
"""Serve the investment dashboard at http://localhost:5001/out/dashboard.html"""

import http.server
import os
import sys
import threading
import webbrowser
from pathlib import Path

PORT = 5001
PROJECT_DIR = Path(__file__).parent

os.chdir(PROJECT_DIR)

handler = http.server.SimpleHTTPRequestHandler
handler.log_message = lambda *a: None  # suppress per-request noise

server = http.server.HTTPServer(("localhost", PORT), handler)

url = f"http://localhost:{PORT}/out/dashboard.html"

# Only open browser when run interactively (not as a launchd daemon)
if sys.stdout.isatty():
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(f"Investment Dashboard → {url}")
    print("Press Ctrl+C to stop.\n")

try:
    server.serve_forever()
except KeyboardInterrupt:
    server.shutdown()
