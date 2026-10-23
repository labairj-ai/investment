"""Reproduce the already-deployed lineage change without changing its contract."""
import ast
import hashlib
from datetime import datetime,timezone
import json
import sqlite3
import subprocess
from pathlib import Path
import pytest
import covered_call_evidence as evidence

ROOT=Path(__file__).resolve().parents[1]
PRIOR='0c775008ad9ec0fa8ed32cc61a1d9c3215ce80ce'
PRIOR_FUNCTION_SHA256='e5181a144698d9f86c8652915b141f5d5aeefc682d866ffff5f51de4b194ff64'

def prior_source():
    raw=(ROOT/'tests/fixtures/cc_lineage_prior_0c77500.txt').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==PRIOR_FUNCTION_SHA256
    return raw.decode()


def function(source):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='create_decision_contract')
    namespace=dict(evidence.__dict__,committed_policy=lambda *a:True)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<immutable lineage function>','exec'),namespace)
    return namespace['create_decision_contract']


def run(fn,spot):
    recorded=datetime(2026,10,23,tzinfo=timezone.utc)
    with sqlite3.connect(':memory:') as db:
        db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE cc_decisions(id INTEGER,timestamp TEXT,git_sha TEXT)')
        db.execute('CREATE TABLE cc_decision_contracts(episode INTEGER,payload TEXT)')
        db.execute('INSERT INTO cc_decisions VALUES(1,?,?)',(recorded.isoformat(),'a'*40))
        return fn(db,1,[dict(spot=spot,strike=110,bid=2,ask=3,impliedVolatility=.2)],dict(promotion=dict(version='fixture'),virtual={}),True,recorded_at=recorded)


def test_finite_snapshot_contract_unchanged_from_acknowledged_deployment():
    old=prior_source()
    assert run(function(old),100.0)==run(function((ROOT/"covered_call_evidence.py").read_text()),100.0)


@pytest.mark.parametrize('invalid',[float('nan'),float('inf'),float('-inf')])
def test_existing_main_nonfinite_lineage_change_is_explicit(invalid):
    old=prior_source()
    with pytest.raises(ValueError):run(function(old),invalid)
    payload=run(evidence.create_decision_contract,invalid)
    assert payload['market_snapshot_lineage']
    json.dumps(payload,allow_nan=False)
