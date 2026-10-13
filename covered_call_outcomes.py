"""Versioned outcome provenance. USD_PER_SHARE economics never mix source arms."""
from __future__ import annotations
import hashlib
import json
import math
from enum import Enum
from time_utils import now_utc_iso, parse_timestamp

PROVENANCE_VERSION = 'cc-outcome-provenance-1'


class OutcomeSource(str, Enum):
    ACTUAL_EXECUTION = 'ACTUAL_EXECUTION'
    PROSPECTIVE_VIRTUAL = 'PROSPECTIVE_VIRTUAL'
    MARKET_PATH_ONLY = 'MARKET_PATH_ONLY'
    ESTIMATED_COUNTERFACTUAL = 'ESTIMATED_COUNTERFACTUAL'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate(outcome):
    source = OutcomeSource(outcome['outcome_source'])
    required = ('origin_episode', 'source_timestamp_start', 'source_timestamp_end',
                'units', 'source_evidence_hash', 'provenance_version', 'market_snapshot_lineage')
    if outcome.get('provenance_version')!=PROVENANCE_VERSION:raise ValueError('unknown provenance contract version')
    if any(not outcome.get(key) for key in required):
        raise ValueError('incomplete outcome provenance')
    start, end = (parse_timestamp(outcome[key]) for key in ('source_timestamp_start', 'source_timestamp_end'))
    if end < start or outcome['units'] != 'USD_PER_SHARE':
        raise ValueError('invalid outcome range or units')
    if source != OutcomeSource.ACTUAL_EXECUTION and outcome.get('broker_reconciled'):
        raise ValueError('only actual execution can be broker reconciled')
    if source == OutcomeSource.ACTUAL_EXECUTION:
        if not outcome.get('execution_ids') or not outcome.get('execution_reconciled') or not outcome.get('chain_identifier'):
            raise ValueError('actual outcome requires reconciled execution IDs and chain')
    if source == OutcomeSource.PROSPECTIVE_VIRTUAL:
        if not outcome.get('prospective') or not outcome.get('simulator_version') or not outcome.get('config_hash'):
            raise ValueError('virtual outcome requires prospective, versioned origin')
        if outcome.get('execution_source') != 'VIRTUAL_MODEL':
            raise ValueError('virtual execution source required')
    if source == OutcomeSource.ESTIMATED_COUNTERFACTUAL and outcome.get('prospective'):
        raise ValueError('counterfactual cannot be prospective')
    if source in (OutcomeSource.MARKET_PATH_ONLY, OutcomeSource.ESTIMATED_COUNTERFACTUAL):
        if any(outcome.get(k) is not None for k in ('total_option_pnl', 'realized_execution_cost',
                'realized_management_cost', 'cc_incremental_alpha', 'roll_hops', 'assignment_policy_violation')):
            raise ValueError('path/estimated evidence cannot contain realized chain economics')
    for key in ('cc_incremental_alpha', 'realized_execution_cost', 'realized_management_cost'):
        if outcome.get(key) is not None and not math.isfinite(float(outcome[key])):
            raise ValueError('nonfinite economic outcome')
    return outcome


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS cc_outcomes (
      id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES cc_decisions(id),
      candidate_id TEXT, arm TEXT NOT NULL CHECK(arm IN ('champion','challenger','path','estimate')),
      outcome_source TEXT NOT NULL, recorded_at TEXT NOT NULL, evidence_hash TEXT NOT NULL,
      outcome_json TEXT NOT NULL, UNIQUE(episode_id,arm,evidence_hash));
    CREATE INDEX IF NOT EXISTS cc_outcomes_episode ON cc_outcomes(episode_id,arm,recorded_at);
    CREATE TABLE IF NOT EXISTS cc_decision_contracts (
      episode_id TEXT PRIMARY KEY REFERENCES cc_decisions(id), contract_json TEXT NOT NULL);
    ''')
    for table in ('cc_outcomes', 'cc_decision_contracts'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable CC provenance'); END")


def persist(db, episode, candidate, arm, outcome):
    outcome=dict(outcome,candidate_id=candidate)
    validate(outcome)
    if outcome['origin_episode'] != episode:
        raise ValueError('outcome episode mismatch')
    # Corrections retain source; a different source belongs to a separate arm.
    previous = db.execute('SELECT outcome_source FROM cc_outcomes WHERE episode_id=? AND arm=? AND candidate_id IS ? ORDER BY recorded_at DESC LIMIT 1', (episode, arm,candidate)).fetchone()
    if previous and previous[0] != outcome['outcome_source']:
        raise ValueError('outcome revision cannot change provenance source')
    if outcome['outcome_source']=='ACTUAL_EXECUTION':
        identifiers=outcome['execution_ids']
        try:
            proofs=db.execute('SELECT e.id FROM executed_actions e JOIN recommendations r ON r.id=e.recommendation_id WHERE r.trade_chain_id=? AND e.id IN ('+','.join('?' for _ in identifiers)+')',
                              (outcome['chain_identifier'],*identifiers)).fetchall()
        except Exception as exc:
            raise ValueError('actual execution identifiers cannot be reconciled') from exc
        if {r[0] for r in proofs}!=set(identifiers):
            raise ValueError('actual execution identifiers do not match chain')

    payload = json.dumps(outcome, sort_keys=True, allow_nan=False)
    h = digest(outcome)
    identifier = digest([episode, arm, h])
    db.execute('INSERT OR IGNORE INTO cc_outcomes VALUES(?,?,?,?,?,?,?,?)',
               (identifier, episode, candidate, arm, outcome['outcome_source'], now_utc_iso(), h, payload))
    return identifier


def latest(db, episode, arm, candidate=None):
    if candidate is not None:
        row=db.execute('SELECT outcome_json FROM cc_outcomes WHERE episode_id=? AND arm=? AND candidate_id=? ORDER BY recorded_at DESC,rowid DESC LIMIT 1',(episode,arm,candidate)).fetchone()
        return json.loads(row[0]) if row else None
    row = db.execute('SELECT outcome_json FROM cc_outcomes WHERE episode_id=? AND arm=? ORDER BY recorded_at DESC,rowid DESC LIMIT 1', (episode, arm)).fetchone()
    return json.loads(row[0]) if row else None


def contract(db, episode):
    row = db.execute('SELECT contract_json FROM cc_decision_contracts WHERE episode_id=?', (episode,)).fetchone()
    return json.loads(row[0]) if row else None


def base(episode, source, start, end, lineage, evidence, **extra):
    outcome = dict(provenance_version=PROVENANCE_VERSION, origin_episode=episode,
                outcome_source=OutcomeSource(source).value, source_timestamp_start=start,
                source_timestamp_end=end, market_snapshot_lineage=lineage,
                source_evidence_hash=digest(evidence), units='USD_PER_SHARE',
                broker_reconciled=False, execution_reconciled=False, complete=False,
                censored=True, prospective=False)
    outcome.update(extra)
    return outcome
