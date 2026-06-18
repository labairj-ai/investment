#!/usr/bin/env python3
"""Serve the investment dashboard at http://localhost:5001/out/dashboard.html"""

import http.server
import os
import threading
import webbrowser
from pathlib import Path

PORT = 5001
PROJECT_DIR = Path(__file__).parent

os.chdir(PROJECT_DIR)

url = f"http://localhost:{PORT}/out/dashboard.html"

threading.Timer(0.5, lambda: webbrowser.open(url)).start()

print(f"Investment Dashboard → {url}")
print("Press Ctrl+C to stop.\n")

http.server.test(
    HandlerClass=http.server.SimpleHTTPRequestHandler,
    port=PORT,
    bind="localhost",
)
