"""Validate dated broker bid/ask evidence. Default dry run; writes only display JSON."""
import argparse
import fcntl
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cc_broker_quotes import prepare, load, append, atomic_write
from portfolio_valuation import verified_mark, value_portfolio
from covered_call_daily_pnl import reporting_session
from time_utils import now_utc


def run(db, supplied, quotes_path, snapshot_path, *, apply=False, now=None):
    now = now or now_utc()
    if quotes_path.name != 'cc-broker-quotes.json' or snapshot_path.name != 'portfolio-valuation.json':
        raise ValueError('DISPLAY_ARTIFACT_PATH_REQUIRED')
    # Sidecar writes cannot target investment.db, any SQLite file or position rows.
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        position = conn.execute('SELECT * FROM cc_positions WHERE id=?', (supplied['position_id'],)).fetchone()
        if position is None:
            raise ValueError('POSITION_NOT_FOUND')
        record = prepare(dict(position), supplied, now)
        verified_mark(dict(position), record, reporting_session(now), now)
        snapshot = json.loads(snapshot_path.read_text())
        records = load(quotes_path)
        report = value_portfolio(conn, snapshot['gross_stock_value'], snapshot.get('stock_snapshot_day', snapshot['stock_session']),
                                 now, broker_quotes=[*records, record])
        inserted = append(quotes_path, record) if apply else False
        if apply:
            atomic_write(snapshot_path, json.dumps(report, allow_nan=False))
    return dict(mode='APPLIED' if apply else 'DRY_RUN', inserted=inserted,
                position_id=supplied['position_id'], quote=json.loads(record['quote_json']), valuation=report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    supplied = json.loads(args.input.read_text())
    supplied['evidence_sha256'] = hashlib.sha256(args.evidence.read_bytes()).hexdigest()
    quotes = args.db.parent / 'cc-broker-quotes.json'
    snapshot = args.db.parent / 'portfolio-valuation.json'
    # Serialize concurrent imports without touching the authoritative database.
    if args.apply:
        with (args.db.parent / '.cc-broker-quotes.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = run(args.db, supplied, quotes, snapshot, apply=True)
    else:
        result = run(args.db, supplied, quotes, snapshot)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
