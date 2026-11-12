"""Dated user-supplied broker evidence for display valuation only.

Stored outside investment.db. No network, position mutation or trading consumer.
"""
import json
import re
import os
import tempfile
from datetime import datetime
from pathlib import Path

from covered_call_daily_pnl import number, position_identity, reporting_session
from time_utils import parse_timestamp

SOURCE = 'USER_SUPPLIED_BROKER_QUOTE'


def prepare(position, supplied, now):
    if position['status'] != 'open':
        raise ValueError('POSITION_NOT_OPEN')
    identity = {k: supplied[k] for k in ('ticker', 'strike', 'expiry', 'contracts', 'opened_date')}
    if position_identity(identity) != position_identity(position):
        raise ValueError('POSITION_CHANGED')
    bid, ask = number(supplied.get('bid')), number(supplied.get('ask'))
    if bid is None or ask is None or ask <= 0 or ask < bid:
        raise ValueError('INVALID_BROKER_SPREAD')
    stamp = datetime.fromisoformat(supplied['quoted_at'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('BROKER_QUOTE_TIMEZONE_REQUIRED')
    quoted = parse_timestamp(stamp)
    if quoted > now:
        raise ValueError('FUTURE_BROKER_QUOTE')
    if not isinstance(supplied.get('evidence_sha256'), str) or not re.fullmatch('[a-f0-9]{64}', supplied['evidence_sha256']):
        raise ValueError('BROKER_EVIDENCE_REQUIRED')
    quote = dict(source=SOURCE, mark_basis='BID_ASK_MIDPOINT', mark=(bid + ask) / 2,
                 bid=bid, ask=ask, quoted_at=quoted.isoformat(), received_at=now.isoformat(),
                 evidence_sha256=supplied['evidence_sha256'])
    return dict(position_id=position['id'], position_identity=position_identity(position),
                session=reporting_session(quoted), observed_at=quoted.isoformat(),
                quote_json=json.dumps(quote, allow_nan=False))


def load(path):
    path = Path(path)
    if not path.exists():
        return []
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError('INVALID_BROKER_QUOTE_FILE')
    records = json.loads(path.read_text())
    if not isinstance(records, list) or len(records) > 1000 or any(not isinstance(r, dict) for r in records):
        raise ValueError('INVALID_BROKER_QUOTE_FILE')
    for record in records:
        if not {'position_id', 'position_identity', 'session', 'observed_at', 'quote_json'} <= record.keys():
            raise ValueError('INVALID_BROKER_QUOTE_FILE')
    return records


def append(path, record):
    """Atomic display artifact update; retain every prior observation verbatim."""
    path = Path(path)
    records = load(path)
    def identity(r):
        quote = json.loads(r['quote_json'])
        quote.pop('received_at', None)
        return (r['position_id'], r['position_identity'], r['observed_at'], json.dumps(quote, sort_keys=True))
    if any(identity(r) == identity(record) for r in records):
        return False
    if len(records) >= 1000:
        raise ValueError('BROKER_QUOTE_ARCHIVE_FULL')
    atomic_write(path, json.dumps(records + [record], allow_nan=False))
    return True


def atomic_write(path, text):
    path = Path(path)
    if path.is_symlink() or path.name not in {'cc-broker-quotes.json', 'portfolio-valuation.json'}:
        raise ValueError('DISPLAY_ARTIFACT_PATH_REQUIRED')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
