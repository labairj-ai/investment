#!/usr/bin/env python3
"""Daily macro health watchdog — runs independently of the weekly scorer (0499).

Reads from the DB without triggering a scoring run. Exits 1 if scorer hasn't
run in >8 days so systemd/launchd can alert on failure.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Run from project root so relative paths (out/, holdings.csv, etc.) resolve correctly
os.chdir(Path(__file__).resolve().parent.parent)

from portfolio_ai import compute_macro_health  # noqa: E402 (after chdir)

health = compute_macro_health()

out_dir = Path("out")
out_dir.mkdir(exist_ok=True)
out_file = out_dir / "macro_health_latest.json"
out_file.write_text(json.dumps(health, indent=2))

print(json.dumps(health, indent=2))

if health.get("scorer_status") == "WARNING":
    print("[Watchdog] WARNING: macro scorer has not produced a successful run in >8 days",
          file=sys.stderr)
    sys.exit(1)

if health.get("status") in ("NO_DB", "ERROR"):
    print(f"[Watchdog] ERROR: {health.get('error', health.get('status'))}", file=sys.stderr)
    sys.exit(1)
