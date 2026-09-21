#!/usr/bin/env python3
"""Create an integrity-checked consistent SQLite backup, including WAL commits."""
import os
import sqlite3
import sys
from pathlib import Path


def snapshot(source, destination):
    destination=Path(destination)
    temporary=destination.with_name(destination.name+'.snapshot.tmp')
    try:
        with sqlite3.connect(f'file:{Path(source)}?mode=ro',uri=True,timeout=10) as src:
            with sqlite3.connect(temporary) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise RuntimeError('Backup integrity check failed')
            dst.close()
        src.close()
        with temporary.open('rb') as f: os.fsync(f.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__=='__main__':
    snapshot(sys.argv[1],sys.argv[2])
