"""Exercise the real backup shell script against a disposable local Git remote."""
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


def run(args, **kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kw)


def test_backup_delivers_restorable_gzip_without_raw_database_blob(tmp_path):
    root=Path(__file__).resolve().parents[1]
    project=tmp_path/'project';project.mkdir();(project/'out').mkdir();(project/'scripts').mkdir();(project/'venv/bin').mkdir(parents=True)
    shutil.copy(root/'backup_data.sh',project/'backup_data.sh')
    shutil.copy(root/'scripts/watchdog_backup_snapshot.py',project/'scripts/watchdog_backup_snapshot.py')
    (project/'venv/bin/python3').symlink_to(sys.executable)
    with sqlite3.connect(project/'out/investment.db') as c:
        c.executescript("CREATE TABLE investment_theses(ticker,version); CREATE TABLE thesis_claims(thesis_id,id); CREATE TABLE proof(value); INSERT INTO proof VALUES ('retained');")
    (project/'holdings.csv').write_text('ticker,shares\nAAA,1\n')
    remote=tmp_path/'remote.git';run(['git','init','--bare','--initial-branch=main',str(remote)])
    backup=tmp_path/'backup';run(['git','clone',str(remote),str(backup)])
    run(['git','-C',str(backup),'config','user.name','Fixture'])
    run(['git','-C',str(backup),'config','user.email','fixture@example.invalid'])
    # Isolated shims provide Linux's flock/timeout on the macOS development host.
    # Linux CI uses the real installed utilities.
    tools=tmp_path/'tools';tools.mkdir()
    if not shutil.which('flock'):
        p=tools/'flock';p.write_text(f'#!{sys.executable}\nimport fcntl,sys\nfcntl.flock(int(sys.argv[-1]),fcntl.LOCK_EX|fcntl.LOCK_NB)\n');p.chmod(0o755)
    if not shutil.which('timeout'):
        p=tools/'timeout';p.write_text(f'#!{sys.executable}\nimport subprocess,sys\nraise SystemExit(subprocess.run(sys.argv[2:],timeout=float(sys.argv[1].rstrip("s"))).returncode)\n');p.chmod(0o755)
    env=dict(os.environ,INVESTMENT_BACKUP_DIR=str(backup),PATH=str(tools)+os.pathsep+os.environ['PATH'])
    # The script exports thesis JSON to its configured backup directory as well.
    result=run(['bash',str(project/'backup_data.sh')],env=env)
    assert 'Destination verified' in result.stdout
    head=run(['git','-C',str(backup),'rev-parse','HEAD']).stdout.strip()
    assert run(['git','--git-dir',str(remote),'rev-parse','refs/heads/main']).stdout.strip()==head
    names=run(['git','--git-dir',str(remote),'ls-tree','--name-only','main']).stdout.splitlines()
    assert 'investment.db.gz' in names and 'investment.db' not in names
    restored=tmp_path/'restored.db';restored.write_bytes(gzip.decompress((backup/'investment.db.gz').read_bytes()))
    with sqlite3.connect(restored) as c:
        assert c.execute('SELECT value FROM proof').fetchone()[0]=='retained'
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    # Even when bytes haven't changed, retry delivery and verify remote identity.
    assert 'Destination verified' in run(['bash',str(project/'backup_data.sh')],env=env).stdout
