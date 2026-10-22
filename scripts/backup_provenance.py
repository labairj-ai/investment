#!/usr/bin/env python3
"""Operator-only receipt after the established consistent SQLite backup workflow.

No backup is created here. Signing is restricted to the authoritative OptiPlex
workflow and its canonical runtime source; development certification only verifies.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dev_agent.snapshot import sign_backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup',type=Path)
    args=parser.parse_args()
    if socket.gethostname().split('.')[0].lower()!='optiplex':
        raise ValueError('only authoritative OptiPlex backup workflow may sign')
    key=os.environ.get('DEV_AGENT_BACKUP_SIGNING_KEY','').encode()
    # Verify the closed backup has the same schema as the canonical source.
    # Source is accessed only by this separately invoked operator backup workflow.
    import sqlite3
    from dev_agent.snapshot import schema_identity
    source=ROOT/'out/investment.db'
    with sqlite3.connect(source.resolve(strict=True).as_uri()+'?mode=ro',uri=True) as db:
        identity=schema_identity(db)
    sha=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    receipt=sign_backup(args.backup,key=key,source_sha=sha)
    if any(receipt[k]!=identity[k] for k in identity): raise ValueError('source and backup schema differ')
    output=args.backup.with_suffix('.provenance.json')
    temporary=output.with_suffix('.tmp')
    with temporary.open('w') as stream:
        os.chmod(temporary,0o600);json.dump(receipt,stream,sort_keys=True);stream.write('\n')
        stream.flush();os.fsync(stream.fileno())
    temporary.replace(output)


if __name__=='__main__': main()
