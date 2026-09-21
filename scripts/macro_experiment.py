#!/usr/bin/env python3
"""Read-only macro experiment report; explicit prospective registration/label sync."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.learning.macro_experiment import evaluate, register_epoch, sync_labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--epoch")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--sync-labels", action="store_true")
    args = parser.parse_args()
    mode = "rw" if args.register or args.sync_labels else "ro"
    with sqlite3.connect(args.db.resolve().as_uri() + "?mode=" + mode, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if args.register:
            register_epoch(conn)
        if args.sync_labels:
            sync_labels(conn)
        print(json.dumps(evaluate(conn, epoch_id=args.epoch), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
