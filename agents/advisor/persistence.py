"""Immutable advisor snapshots with explicit monotonic invalidation."""
import json
from pathlib import Path
from .contracts import canonical, digest, ADVISOR_CONTRACT_VERSION, ADVISOR_POLICY_VERSION
from time_utils import now_utc, parse_timestamp


def migrate(conn):
    conn.executescript((Path(__file__).resolve().parents[2]/'schema.sql').read_text())


def persist(conn, decision):
    if conn.in_transaction: raise ValueError('CALLER_TRANSACTION_ACTIVE')
    payload=canonical(decision)
    with conn:
        old=conn.execute('SELECT structured_json FROM advisor_decisions WHERE advisor_decision_id=?',(decision['advisor_decision_id'],)).fetchone()
        if old:
            if old[0]!=payload: raise ValueError('DECISION_ID_CONFLICT')
            return decision
        conn.execute('''INSERT INTO advisor_decisions
          (advisor_decision_id,request_hash,context_hash,authorization_hash,contract_version,policy_version,
           structured_json,rendered_answer,created_at,valid_until) VALUES (?,?,?,?,?,?,?,?,?,?)''',
          (decision['advisor_decision_id'],digest(decision['request']),decision['context']['context_hash'],
           decision['context']['authorization_hash'],ADVISOR_CONTRACT_VERSION,ADVISOR_POLICY_VERSION,
           payload,decision['explanation'],decision['created_at'],decision['valid_until']))
    return decision


def load(conn, decision_id, *, context=None, now=None, update=False):
    row=conn.execute('SELECT * FROM advisor_decisions WHERE advisor_decision_id=?',(decision_id,)).fetchone()
    if not row: return None
    columns=[c[0] for c in conn.execute('SELECT * FROM advisor_decisions LIMIT 0').description]
    row=dict(zip(columns,tuple(row)))
    status=row['lifecycle_status'];reason=row['status_reason']
    if status=='VALID':
        if parse_timestamp(row['valid_until'])<=(now or now_utc()): status,reason='EXPIRED','TTL_EXPIRED'
        elif row['policy_version']!=ADVISOR_POLICY_VERSION: status,reason='STALE','POLICY_VERSION_CHANGED'
        elif context is not None and row['authorization_hash']!=context['authorization_hash']: status,reason='STALE','SOURCE_CONTEXT_CHANGED'
    if update and status!=row['lifecycle_status']:
        with conn:
            conn.execute('UPDATE advisor_decisions SET lifecycle_status=?,status_reason=? WHERE advisor_decision_id=?',
                         (status,reason,decision_id))
    result=json.loads(row['structured_json'])
    result['lifecycle_status']=status;result['status_reason']=reason
    if status!='VALID':
        result['policy']=dict(result['policy'],decision_state='REVIEW_REQUIRED',execution_ready=False,
                              reasons=result['policy']['reasons']+[reason or status])
    return result


def health(conn, *, context=None, now=None, context_for_account=None):
    counts={state:0 for state in ('ACTIONABLE','REVIEW_REQUIRED','RESEARCH_ONLY','BLOCKED')}
    lifecycle={};failures={}
    try:
        rows=conn.execute('SELECT lifecycle_status,structured_json,valid_until,authorization_hash,policy_version FROM advisor_decisions').fetchall()
    except Exception:
        return dict(status='UNAVAILABLE',decision_counts=counts,lifecycle_counts={},failure_reasons={})
    contexts={}
    for status,payload,valid_until,authority,policy_version in rows:
        d=json.loads(payload)
        current_context=context
        if context_for_account is not None:
            account=d.get('account_id')
            if account not in contexts: contexts[account]=context_for_account(account)
            current_context=contexts[account]
        if status=='VALID':
            if parse_timestamp(valid_until)<=(now or now_utc()): status='EXPIRED'
            elif policy_version!=ADVISOR_POLICY_VERSION or (current_context is not None and authority!=current_context['authorization_hash']): status='STALE'
        d=json.loads(payload);state=d['policy']['decision_state'] if status=='VALID' else 'REVIEW_REQUIRED'
        counts[state]+=1;lifecycle[status]=lifecycle.get(status,0)+1
        for reason in d['policy']['reasons']:
            failures[reason]=failures.get(reason,0)+1
        for reason in d.get('rendering_errors',[]): failures[reason]=failures.get(reason,0)+1
    return dict(status='AVAILABLE',decision_counts=counts,lifecycle_counts=lifecycle,failure_reasons=failures)
