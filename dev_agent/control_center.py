"""Bounded Investment-only presentation reads. Never an authority or execution API."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import csv
import hashlib
import io
import json
import math
import os
import posixpath
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import parse_qs, unquote, urlsplit

from .store import Store, STATES, SOURCES, CATEGORIES
from .policy import VERSION as POLICY_VERSION
from .structured_json import loads

VERSION = 'investment-engineering-1'
REPOSITORY = 'labairj-ai/investment'
API = '/api/engineering/v1/projects/investment/'
PAGE = '/engineering/projects/investment'
MAX_PAGE = 50
MAX_BYTES = 512_000
MAX_RECORD = 32768
SAFE_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
SHA = re.compile(r'[a-f0-9]{40}')
SENSITIVE = re.compile(r'(?i)bearer\s|gh[pousr]_|sk-[A-Za-z0-9]|(?:token|password|secret|api[_-]?key|authorization|cookie)\s*[:=]')
ALLOWED_DETAIL = {'problem', 'outcome', 'files', 'evidence', 'dependencies', 'acceptance', 'criteria', 'todo', 'head', 'base', 'risk', 'reasons', 'scope_hash', 'acceptance_hash', 'mode', 'iteration', 'disposition', 'findings', 'status', 'role', 'provider', 'model', 'context', 'review', 'source', 'observed_at', 'recurrence', 'confidence', 'evidence_location', 'stage', 'created', 'result', 'number', 'url', 'merge_sha', 'receipt', 'run_id', 'time_budget', 'action_budget', 'max_iterations', 'version', 'score', 'quality', 'component'}
ALLOWED_DETAIL |= {'run', 'branch', 'source_hash', 'trusted_test_tree_hash', 'time_budget_seconds', 'max_actions', 'risk_reasons', 'frozen_scope', 'allowed_files', 'protected_files', 'worker', 'acceptance_criteria', 'decision', 'policy_hash'}


class NotFound(ValueError):
    pass


def text(value, limit=1000):
    if not isinstance(value, str):
        return None
    if SENSITIVE.search(value):
        return '[redacted]'
    value = ''.join(c for c in value if c >= ' ' or c in '\n\t')
    return value[:limit]+('… [truncated]' if len(value)>limit else '')


def safe_detail(value, depth=0):
    """Export explicit presentation fields only; never dump event payloads or logs."""
    if depth > 5:
        return None
    if isinstance(value, dict):
        return {k: safe_detail(v, depth+1) for k, v in value.items() if k in ALLOWED_DETAIL}
    if isinstance(value, list):
        items = [safe_detail(v, depth+1) for v in value[:40]]
        return items if len(value)<=40 else dict(items=items, total=len(value), complete=False)
    if isinstance(value, str):
        return text(value)
    if value is None or type(value) is bool or type(value) in (int, float) and math.isfinite(value):
        return value
    return None


def stamp(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value > 0 else None


def identifier(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError('invalid identifier')
    return value


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode()) > MAX_RECORD:
        raise ValueError('bounded ledger record required')
    obj = loads(raw)
    if not isinstance(obj, dict):
        raise ValueError('object record required')
    return obj


class ReadStore(Store):
    @contextmanager
    def connect(self, write=False):
        if write:
            raise ValueError('presentation is read only')
        with super().connect() as db:
            db.execute('PRAGMA query_only=ON')
            steps = 0
            def budget():
                nonlocal steps
                steps += 1
                return int(steps > 2000)
            db.set_progress_handler(budget, 1000)
            yield db


class ControlCenter:
    def __init__(self, root, store, *, now=None):
        self.root = Path(root)
        self.store = ReadStore(store.path)
        self.now = time.time() if now is None else now
        from .discovery import git
        self.source_clean = False
        try:
            self.head = git(self.root, 'rev-parse', 'HEAD')
            self.source_clean = not git(self.root, 'status', '--porcelain', '--untracked-files=no').strip()
            if not SHA.fullmatch(self.head):
                self.head = None
        except Exception:
            self.head = None

    def judgment(self, status, code, reason, *, source='development-ledger', observed=None, ttl=None, head=None, receipt=None, verifier='UNAVAILABLE'):
        if status not in {'PASS', 'FAIL', 'PARTIAL', 'NOT_RUN', 'UNAVAILABLE', 'STALE', 'READY', 'NOT READY', 'BLOCKED'}:
            status = 'UNAVAILABLE'
        observed = stamp(observed)
        expires = observed+ttl if observed is not None and ttl is not None else None
        if status in {'PASS', 'READY'} and (not self.source_clean or observed is None or verifier in {'UNAVAILABLE', 'UNVERIFIED'} or not isinstance(head or self.head, str) or not SHA.fullmatch(head or self.head)):
            status, code, reason, verifier = 'UNAVAILABLE', 'PROVENANCE_INCOMPLETE', 'Current verified source and observation identity are required.', 'UNAVAILABLE'
        if observed is not None and (observed > self.now or expires is not None and expires < self.now):
            status, code, reason, verifier = 'STALE', 'EVIDENCE_STALE', 'Evidence is future-dated or expired.', 'UNAVAILABLE'
        return dict(status=status, reason_code=code, reason_summary=text(reason), observed_at=observed, expires_at=expires,
                    source=source, policy_version=POLICY_VERSION, repository=REPOSITORY, head_sha=head or self.head,
                    receipt_id=text(receipt, 128), verifier_status=verifier)

    @contextmanager
    def db(self):
        with self.store.connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != {'dev_candidates', 'dev_events'}:
                raise ValueError('dedicated ledger schema required')
            db.execute('BEGIN')  # stable read snapshot; query_only prevents writes
            yield db

    def options(self, query, allowed):
        if not isinstance(query, str) or len(query) > 2048:
            raise ValueError('bounded query required')
        q = parse_qs(query, keep_blank_values=True, max_num_fields=16, strict_parsing=True) if query else {}
        if set(q)-set(allowed)-{'limit', 'cursor'} or any(len(v) != 1 or len(v[0]) > 1024 for v in q.values()):
            raise ValueError('invalid query')
        q = {k: v[0] for k, v in q.items()}
        raw = q.pop('limit', '20')
        if not re.fullmatch(r'[0-9]{1,2}', raw) or not 1 <= int(raw) <= MAX_PAGE:
            raise ValueError('invalid page size')
        return q, int(raw)

    def cursor(self, db, q, resource):
        raw = q.pop('cursor', '')
        binding = hashlib.sha256(json.dumps([resource, q], sort_keys=True).encode()).hexdigest()
        maximum = db.execute('SELECT coalesce(max(seq),0) FROM dev_events').fetchone()[0]
        if not raw:
            return maximum, None, binding
        try:
            value = loads(base64.b64decode(raw, altchars=b'-_', validate=True))
            if set(value) != {'seq', 'key', 'binding'} or type(value['seq']) is not int or not 0 <= value['seq'] <= maximum or value['binding'] != binding:
                raise ValueError()
            return value['seq'], value['key'], binding
        except Exception:
            raise ValueError('invalid cursor') from None

    @staticmethod
    def next_cursor(seq, key, binding):
        return base64.urlsafe_b64encode(json.dumps(dict(seq=seq, key=key, binding=binding), separators=(',', ':')).encode()).decode()

    def envelope(self, **values):
        return dict(dict(version=VERSION, repository=REPOSITORY, head_sha=self.head, source_clean=self.source_clean, read_at=self.now), **values)

    def candidates(self, query=''):
        q, limit = self.options(query, {'search', 'state', 'risk', 'category', 'source', 'sort', 'active'})
        if 'active' in q and q['active'] not in {'true', 'false'}:
            raise ValueError('invalid active filter')
        for field, allowed in [('state', STATES), ('risk', {f'L{i}' for i in range(6)} | {'UNKNOWN'}), ('category', CATEGORIES), ('source', SOURCES)]:
            if field in q and q[field] not in allowed:
                raise ValueError('unknown filter')
        sort = q.get('sort', 'newest')
        if sort not in {'newest', 'oldest', 'risk', 'value'} or len(q.get('search', '')) > 120:
            raise ValueError('invalid sort/search')
        with self.db() as db:
            seq, key, binding = self.cursor(db, q, 'candidates')
            # Correlated reads are bound to the snapshot sequence, so appends cannot
            # move a candidate between pages. Unknown risk/value sort last.
            def event(kind, path):
                return f"(SELECT json_extract(e.payload,'{path}') FROM dev_events e WHERE e.candidate=c.id AND e.kind='{kind}' AND e.seq<=? ORDER BY e.seq DESC LIMIT 1)"
            cte = f"""WITH rows AS (SELECT c.id,c.created,c.payload,
                {event('STATE', '$.state')} AS state,
                coalesce({event('PLAN', '$.context.risk')},'UNKNOWN') AS risk,
                {event('SCORE', '$.score')} AS value,
                {event('SCORE', '$.version')} AS score_version,
                {event('SCORE', '$.confidence')} AS evidence_quality,
                (SELECT max(e.created) FROM dev_events e WHERE e.candidate=c.id AND e.seq<=?) AS updated,
                json_extract(c.payload,'$.title') AS title,
                json_extract(c.payload,'$.category') AS category,
                json_extract(c.payload,'$.source') AS source FROM dev_candidates c),
                ranked AS (SELECT *, CASE WHEN risk GLOB 'L[0-5]' THEN cast(substr(risk,2) AS INTEGER) ELSE -1 END AS risk_order,
                    CASE WHEN typeof(value) IN ('real','integer') THEN value ELSE -1 END AS value_order FROM rows WHERE state IS NOT NULL) """
            conditions = ['1=1']; args = [seq]*6
            if q.get('active')=='true':
                conditions.append("state NOT IN ('CLOSED','REJECTED','ROLLED_BACK')")
            for field in ('state', 'risk', 'category', 'source'):
                if field in q:
                    conditions.append(field+'=?'); args.append(q[field])
            if q.get('search'):
                conditions.append("(instr(lower(title),lower(?))>0 OR instr(id,?)>0 OR instr(lower(json_extract(payload,'$.files')),lower(?))>0 OR instr(lower(json_extract(payload,'$.component')),lower(?))>0)")
                args.extend([q['search']]*4)
            order = {'newest': '-created', 'oldest': 'created', 'risk': '-risk_order', 'value': '-value_order'}[sort]
            total = db.execute(cte+'SELECT count(*) FROM ranked WHERE '+' AND '.join(conditions), args).fetchone()[0]
            if key is not None:
                if not isinstance(key, list) or len(key) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in key[:2]):
                    raise ValueError('invalid candidate cursor')
                identifier(key[2]); conditions.append(f'({order},created,id)>(?,?,?)'); args.extend(key)
            rows = db.execute(cte+f'SELECT *,{order} AS ordering FROM ranked WHERE '+' AND '.join(conditions)+' ORDER BY ordering,created,id LIMIT ?', [*args, limit+1]).fetchall()
            items = [self.candidate_row(row) for row in rows[:limit]]
            next_page = self.next_cursor(seq, [rows[limit-1]['ordering'], rows[limit-1]['created'], rows[limit-1]['id']], binding) if len(rows)>limit else None
        return self.envelope(items=items, total=total, next_cursor=next_page, snapshot_seq=seq)

    def candidate_row(self, row):
        p = decode(row['payload']); identifier(row['id'])
        if row['state'] not in STATES or row['category'] not in CATEGORIES or row['source'] not in SOURCES or row['risk'] not in {f'L{i}' for i in range(6)} | {'UNKNOWN'}:
            raise ValueError('unknown candidate schema')
        value = row['value'] if type(row['value']) in (int, float) and math.isfinite(row['value']) else None
        return dict(id=row['id'], title=text(p.get('title')), created_at=stamp(row['created']), updated_at=stamp(row['updated']), state=row['state'], risk=row['risk'],
                    category=row['category'], source=row['source'], value_score=value, score_version=text(row['score_version'], 80) if value is not None else None,
                    evidence_quality=text(row['evidence_quality'], 80),
                    component=text(p.get('component')), files=safe_detail(p.get('files', [])),
                    blocker='Review financial, execution and governance consequences.' if row['risk'] in {'L4', 'L5'} else 'Inspect frozen scope and current evidence before any action.',
                    evidence=self.judgment('UNAVAILABLE', 'CLAIM_ONLY', 'Candidate content is a proposal, not independent verification.', observed=row['updated'], verifier='UNVERIFIED'))

    def candidate(self, cid, query=''):
        identifier(cid)
        q, _ = self.options(query, set())
        if q:
            raise ValueError('candidate detail takes no query')
        with self.db() as db:
            row = db.execute('SELECT payload,created FROM dev_candidates WHERE id=?', (cid,)).fetchone()
            if row is None:
                raise NotFound('candidate missing')
            p = decode(row['payload'])
            events = db.execute('SELECT seq,event_id,candidate,kind,created,payload FROM dev_events WHERE candidate=? ORDER BY seq DESC LIMIT 101', (cid,)).fetchall()
            latest = {}
            for kind in ('PLAN', 'ITERATION', 'RUN', 'PR', 'DEPLOYMENT', 'WORKTREE', 'SIGNAL_OBSERVATION', 'RECEIPT'):
                row = db.execute('SELECT payload FROM dev_events WHERE candidate=? AND kind=? ORDER BY seq DESC LIMIT 1', (cid, kind)).fetchone()
                if row is not None:
                    latest[kind] = safe_detail(decode(row['payload']))
        return self.envelope(id=cid, title=text(p.get('title')), proposal=safe_detail(p), latest=latest,
                             timeline=[self.event_row(e) for e in reversed(events[:100])], timeline_complete=len(events)<=100,
                             timeline_query='candidate='+cid,
                             actions=dict(build=False, approve=False, reason='Read-only inspection; existing authenticated workflow retains all authority.'))

    def event_row(self, row):
        p = decode(row['payload'])
        # An actor string in a payload is a historical claim, never owner proof.
        observed = stamp(row['created'])
        context = p.get('context') if isinstance(p.get('context'), dict) else {}
        result = p.get('result') if isinstance(p.get('result'), dict) else {}
        pr = p.get('pr', context.get('pr', result.get('number')))
        risk = p.get('risk', context.get('risk'))
        head = p.get('head', context.get('head'))
        origin = p.get('origin') if isinstance(p.get('origin'), dict) else {}
        return dict(seq=row['seq'], event_id=text(row['event_id'], 160), candidate=text(row['candidate'], 128), kind=text(row['kind'], 80),
                    created_at=observed, actor=text(p.get('actor'), 200), actor_identity_source='UNVERIFIED_LEDGER_CLAIM',
                    claimed_identity_source=text(p.get('authentication_source'), 128),
                    recorded_disposition=text(p.get('status', p.get('decision', p.get('disposition'))), 80),
                    receipt_id=str(origin['id']) if type(origin.get('id')) is int and origin['id']>0 else None,
                    pr=pr if type(pr) is int else None,
                    risk=risk if isinstance(risk, str) and risk in {f'L{i}' for i in range(6)} else None,
                    head_sha=head if isinstance(head, str) and SHA.fullmatch(head) else None,
                    status=self.judgment('UNAVAILABLE', 'HISTORICAL_EVENT', 'Historical ledger observation; not a current authorization.', observed=observed, verifier='UNVERIFIED'),
                    details=safe_detail(p))

    def audit(self, query=''):
        q, limit = self.options(query, {'kind', 'candidate', 'actor', 'pr', 'status', 'since', 'until', 'format'})
        output = q.pop('format', 'json')
        if output not in {'json', 'csv'}:
            raise ValueError('invalid format')
        for k in ('kind', 'candidate', 'status'):
            if k in q:
                identifier(q[k])
        if 'actor' in q and (not q['actor'] or len(q['actor']) > 200):
            raise ValueError('invalid actor')
        if 'pr' in q and not re.fullmatch(r'[1-9][0-9]{0,8}', q['pr']):
            raise ValueError('invalid PR')
        with self.db() as db:
            seq, key, binding = self.cursor(db, q, 'audit')
            conditions = ['seq<=?']; args = [seq]
            if key is not None:
                if type(key) is not int or not 0 < key <= seq:
                    raise ValueError('invalid audit cursor')
                conditions.append('seq<?'); args.append(key)
            for field in ('kind', 'candidate'):
                if field in q:
                    conditions.append(field+'=?'); args.append(q[field])
            for field in ('actor', 'pr', 'status'):
                if field in q:
                    expr = "json_extract(payload,'$."+field+"')"
                    if field=='pr':
                        expr = "coalesce(json_extract(payload,'$.pr'),json_extract(payload,'$.context.pr'),json_extract(payload,'$.result.number'))"
                    if field=='status':
                        expr = "coalesce(json_extract(payload,'$.status'),json_extract(payload,'$.decision'),json_extract(payload,'$.disposition'))"
                    conditions.append(expr+'=?'); args.append(int(q[field]) if field=='pr' else q[field])
            for field, operator in [('since', '>='), ('until', '<=')]:
                if field in q:
                    v = float(q[field])
                    if not stamp(v) or v > self.now:
                        raise ValueError('invalid date filter')
                    conditions.append('created'+operator+'?'); args.append(v)
            rows = db.execute('SELECT seq,event_id,candidate,kind,created,payload FROM dev_events WHERE '+' AND '.join(conditions)+' ORDER BY seq DESC LIMIT ?', [*args, limit+1]).fetchall()
            next_page = self.next_cursor(seq, rows[limit-1]['seq'], binding) if len(rows)>limit else None
        return self.envelope(items=[self.event_row(r) for r in rows[:limit]], next_cursor=next_page, page_cursor=self.next_cursor(seq, key, binding), snapshot_seq=seq)

    def projections(self):
        # Existing admission/qualification code assumes complete inventories. Refuse
        # excess data rather than feed it a truncated view and invent readiness.
        with self.db() as db:
            n = db.execute('SELECT count(*),coalesce(sum(length(payload)),0),coalesce(max(length(payload)),0) FROM dev_events').fetchone()
            c = db.execute('SELECT count(*),coalesce(sum(length(payload)),0),coalesce(max(length(payload)),0) FROM dev_candidates').fetchone()
            if n[0]>10000 or n[1]>4_000_000 or n[2]>MAX_RECORD or c[0]>500 or c[1]>4_000_000 or c[2]>MAX_RECORD:
                raise ValueError('projection inventory exceeds bounded complete read')
        from .readiness import readiness
        return readiness(self.root, self.store, self.now)

    def overview(self):
        counts = None
        try:
            candidates = self.candidates('limit=5&sort=risk&active=true')
            counts = candidates['total']
            state = self.projections()
            owner = state.get('owner', {})
            ready = self.judgment(owner.get('status'), 'SUPERVISED_ADMISSION', owner.get('reason', 'Admission unavailable.'), source='readiness.owner_status', observed=self.now, ttl=60, verifier='EXISTING_ADMISSION_GATE')
            ready['expires_at'] = self.projection_deadline(state)
            reasons = list(dict.fromkeys([owner.get('reason')]+state.get('blockers', [])))
            blockers = [dict(reason=text(s), destination='certification') for s in reasons if isinstance(s, str)][:3]
        except Exception:
            candidates = dict(items=[])
            state = {}
            ready = self.judgment('UNAVAILABLE', 'SOURCE_UNAVAILABLE', 'Complete current source evidence is unavailable.')
            blockers = [dict(reason='Current admission evidence unavailable.', destination='certification')]
        return self.envelope(readiness=ready, blockers=blockers, metrics=dict(candidate_backlog=counts, owner_decisions=None,
                             validation=self.judgment('UNAVAILABLE', 'NO_AGGREGATE_AUTHORITY', 'Inspect exact-source validation receipts.')),
                             priority_queue=candidates['items'], autonomy_configuration=self.configuration(),
                             scheduler=self.judgment('PASS' if state.get('scheduled_discovery', {}).get('status')=='SCHEDULED' else 'UNAVAILABLE', 'SCHEDULER_OBSERVATION', state.get('scheduled_discovery', {}).get('reason', 'Scheduled discovery observation; qualification remains separate.'), source='scheduler_health.health', observed=state.get('scheduled_discovery', {}).get('created'), ttl=1800, verifier='EXISTING_SCHEDULER_GATE'))

    def projection_deadline(self, state):
        """A view cannot outlive the earliest underlying proof it presents."""
        deadlines = [self.now+60]
        for item, key, ttl in ((state.get('github_protection', {}), 'created', 300), (state.get('production_snapshot', {}), 'backup_timestamp', 86400), (state.get('scheduled_discovery', {}), 'created', 1800)):
            if stamp(item.get(key)):
                deadlines.append(item[key]+ttl)
        from .operations import certificates, policy
        certs = certificates(self.store)
        if certs:
            latest = certs[-1]
            hours = policy(self.root).get('technical_certificate_max_age_hours', 24)
            if stamp(latest.get('created')):
                deadlines.append(latest['created']+min(24, max(1, hours))*3600)
            for item in latest.get('evidence', {}).values():
                if isinstance(item, dict) and stamp(item.get('expires_at')):
                    deadlines.append(item['expires_at'])
        return min(deadlines)

    def configuration(self):
        from .discovery import git
        try:
            cfg = loads(git(self.root, 'show', self.head+':config/development_agent.json'))
            allowed = ('autonomous_implementation', 'auto_merge', 'required_human_merge', 'supervised_loop_enabled', 'supervised_publish_pr', 'autonomy_stage', 'autonomous_max_risk', 'daily_implementation_cap', 'emergency_stop')
            values = {k:cfg.get(k) for k in allowed}
            if any(type(v) not in (bool, int, str) and v is not None for v in values.values()):
                raise ValueError('scalar configuration required')
            return dict(source='committed-configuration-not-host-observation', values=values, head_sha=self.head)
        except Exception:
            return dict(source='committed-configuration-not-host-observation', values=None, head_sha=self.head)

    def certification(self):
        try:
            s = self.projections()
            from .operations import certificates
            certs = certificates(self.store)
            latest = certs[-1] if certs else {}
            evidence = latest.get('evidence', {})
            technical = self.judgment(s.get('technical_certification'), 'TECHNICAL_CERTIFICATE', 'Existing technical certificate verification; separate from operational credit.', source='readiness.technical_certification', observed=self.now, ttl=60, verifier='EXISTING_CERTIFICATE_CHECK')
            technical['expires_at'] = self.projection_deadline(s)
            supervised = s.get('supervised', {})
            from .scheduler_health import acceptance
            scout = acceptance(self.store, self.head, self.now) if self.head else {}
            details = dict(harness_hash=s.get('harness_hash'), certificate_id=text(latest.get('id'), 128), issued_at=stamp(latest.get('created')),
                github_protection=self.judgment(s.get('github_protection', {}).get('status'), 'GITHUB_PROTECTION', 'Effective GitHub protection evidence.', source='readiness.github_protection', observed=s.get('github_protection', {}).get('created'), ttl=300, verifier='EXISTING_READINESS_GATE'),
                backup=self.judgment(s.get('production_snapshot', {}).get('status'), 'BACKUP_PROVENANCE', 'Authenticated protected-state backup evidence.', source='readiness.production_snapshot', observed=s.get('production_snapshot', {}).get('backup_timestamp'), ttl=86400, verifier='EXISTING_READINESS_GATE'),
                sandbox=self.judgment(s.get('sandbox_runtime'), 'SANDBOX_RUNTIME', 'Existing sandbox readiness check.', source='readiness.sandbox_runtime', observed=self.now, ttl=60, verifier='EXISTING_READINESS_GATE'))
            oracle = evidence.get('oracle', {})
            details['oracle'] = self.judgment('PASS' if technical['status']=='PASS' and oracle.get('fixture_only') is False and oracle.get('harness_hash')==s.get('harness_hash') and stamp(oracle.get('expires_at')) and self.now<oracle['expires_at']<=self.now+86400 else 'UNAVAILABLE', 'ORACLE_CERTIFICATE', 'Real source-bound Oracle certificate required.', source='technical-certificate.oracle', observed=oracle.get('created'), ttl=86400, verifier='EXISTING_CERTIFICATE_CHECK')
            return self.envelope(technical=technical, technical_details=details,
                supervised=dict(completed=supervised.get('completed'), required=supervised.get('required'), observation_days=supervised.get('observation_days'), required_days=supervised.get('required_days'),
                    evidence=self.judgment('PASS' if supervised.get('eligible') else 'NOT READY', 'SUPERVISED_QUALIFICATION', 'Qualified runs and the prospective calendar window are evaluated by existing policy.', source='operations.eligibility', observed=self.now, ttl=60, verifier='EXISTING_QUALIFICATION_GATE')),
                scout=dict(successful_runs=scout.get('successful_runs'), required_runs=scout.get('required_runs'), runs=safe_detail(scout.get('runs', [])),
                    evidence=self.judgment(scout.get('status'), 'SCOUT_ACCEPTANCE', scout.get('reason', 'Current acceptance unavailable.'), source='scheduler_health.acceptance', observed=self.now, ttl=60, verifier='EXISTING_ACCEPTANCE_GATE')),
                autonomy=dict(configuration=self.configuration(), eligible=s.get('autonomous_starts_allowed') is True, enabled=s.get('autonomous_implementation') is True, blockers=[text(v) for v in s.get('blockers', [])[:30]]))
        except Exception:
            unavailable = self.judgment('UNAVAILABLE', 'CERTIFICATION_UNAVAILABLE', 'Complete current certification evidence unavailable.')
            return self.envelope(technical=unavailable, supervised=dict(completed=None, required=3, evidence=unavailable), scout=dict(successful_runs=None, required_runs=3, evidence=unavailable), autonomy=dict(configuration=self.configuration(), eligible=False, enabled=None, blockers=['Certification unavailable.']))

    def validation(self, cid):
        identifier(cid)
        from .validation import GATES, VERSION as manifest_version
        from .evidence import trusted_receipt
        # Boundedness is required before calling legacy reconstruct/get paths.
        with self.db() as db:
            count = db.execute('SELECT count(*),coalesce(max(length(payload)),0) FROM dev_events WHERE candidate=?', (cid,)).fetchone()
            if count[0]>200 or count[1]>MAX_RECORD:
                raise ValueError('validation inventory too large')
            rows = db.execute("SELECT payload FROM dev_events WHERE candidate=? AND kind='RECEIPT' ORDER BY seq DESC LIMIT 1", (cid,)).fetchall()
        receipt = decode(rows[0][0]).get('receipt', {}) if rows else {}
        if not isinstance(receipt, dict):
            raise ValueError('receipt schema')
        try:
            trusted = trusted_receipt(self.root, self.store, cid, receipt)
        except Exception:
            trusted = False
        records = receipt.get('validations', []) if trusted else []
        items = []
        for name in GATES:
            row = next((r for r in records if r.get('name')==name), {})
            status = row.get('status', 'UNAVAILABLE')
            if not trusted and receipt.get('head') and receipt.get('head')!=self.head:
                status = 'STALE'
            evidence = self.judgment(status, 'TRUSTED_VALIDATION' if trusted else 'NO_TRUSTED_RECEIPT', 'Existing receipt reconstruction verified.' if trusted else 'Candidate PASS claims and CI-only results cannot establish trusted validation.', source='evidence.trusted_receipt', observed=row.get('ended_at'), ttl=86400, head=receipt.get('head'), receipt=receipt.get('id'), verifier='EXISTING_RECEIPT_VERIFIER' if trusted else 'UNAVAILABLE')
            inventory = row.get('inventory', {})
            inventory_view = {k: inventory.get(k) for k in ('total', 'passed')} if trusted else None
            if inventory_view is not None:
                inventory_view.update(failures=[text(v) for v in inventory.get('failures', [])[:40]], skipped=[text(v) for v in inventory.get('skipped', [])[:40]], skip_count=len(inventory.get('skipped', [])), inventory_complete=len(inventory.get('failures', []))<=40 and len(inventory.get('skipped', []))<=40)
            items.append(dict(name=name, evidence=evidence, base_sha=row.get('base'), source_hash=row.get('source_hash'), trusted_test_tree_hash=row.get('trusted_test_tree_hash'), image_digest=row.get('sandbox_image_digest'), manifest_id=row.get('manifest_hash'), exit_code=row.get('exit_code'), started_at=row.get('started_at'), ended_at=row.get('ended_at'), inventory=inventory_view))
        from scripts.aggregate_release_validation import GATES as repository_gates
        return self.envelope(candidate=cid, manifest_version=manifest_version, repository_ci_manifest=dict(version='repository-validation-1', gates=list(repository_gates), authority='diagnostics-only'), items=items, all_required_pass=all(r['evidence']['status']=='PASS' for r in items))

    def prs(self, query=''):
        q, limit = self.options(query, set())
        # PR list is historical and is explicitly not an owner-decision count.
        suffix = '&limit='+str(limit)
        if q.get('cursor'):
            suffix += '&cursor='+q['cursor']
        data = self.audit('kind=PR'+suffix)
        items = []
        for event in data['items']:
            result = event['details'].get('result', {})
            number = result.get('number') if isinstance(result, dict) else None
            if type(number) is int and 0<number<1_000_000_000:
                items.append(dict(number=number, candidate=event['candidate'], recorded_head=event['head_sha'], url=f'https://github.com/{REPOSITORY}/pull/{number}', evidence=event['status']))
        return self.envelope(items=items, next_cursor=data['next_cursor'], snapshot_seq=data['snapshot_seq'])

    def pr(self, number):
        if not re.fullmatch(r'[1-9][0-9]{0,8}', number):
            raise ValueError('invalid PR')
        number = int(number)
        from .github import GitHub
        from .owner_review import context, state
        client = GitHub(REPOSITORY)  # only read methods; never owner_gateway
        ctx = context(client, number, risk='L5')
        remote = client.read(f'repos/{REPOSITORY}/pulls/{number}')
        if remote['head']['sha']!=ctx['head']:
            raise ValueError('head changed')
        files = client.read_all(f'repos/{REPOSITORY}/pulls/{number}/files')
        if not files or len(files)>=3000:
            raise ValueError('complete files required')
        owner = state(self.store, client, number)
        ci = self.judgment('UNAVAILABLE', 'CI_UNAVAILABLE', 'Complete current-head CI evidence unavailable.', source='GitHub.check-runs', head=ctx['head'])
        try:
            runs = client.read(f'repos/{REPOSITORY}/commits/{ctx["head"]}/check-runs?per_page=100')
            checks = runs.get('check_runs', [])
            if type(runs.get('total_count')) is not int or runs['total_count']!=len(checks) or len(checks)>100:
                raise ValueError('complete check inventory required')
            tests = [r for r in checks if r.get('name')=='test' and r.get('head_sha')==ctx['head'] and type(r.get('id')) is int]
            if tests:
                latest = max(tests, key=lambda r:r['id'])
                outcome = 'PASS' if latest.get('status')=='completed' and latest.get('conclusion')=='success' else 'FAIL' if latest.get('status')=='completed' else 'NOT_RUN'
                ci = self.judgment(outcome, 'REPOSITORY_CI_ONLY', 'Latest exact-head test check; diagnostics only, not independent Oracle or release authority.', source='GitHub.check-runs', observed=self.now, ttl=60, head=ctx['head'], receipt=str(latest['id']), verifier='GITHUB_API')
        except Exception:
            pass
        protection = self.judgment('UNAVAILABLE', 'PROTECTION_UNAVAILABLE', 'Effective protection and bypass visibility unavailable.', source='GitHub.protections', head=ctx['head'])
        try:
            from .protection import observation_valid
            observed = client.protections()
            valid = observation_valid(observed, REPOSITORY, 300, self.now)
            protection = self.judgment('PASS' if valid else 'UNAVAILABLE', 'EFFECTIVE_PROTECTION', 'Existing effective-protection verifier result.', source='protection.observation_valid', observed=observed.get('created'), ttl=300, head=ctx['head'], verifier='EXISTING_PROTECTION_VERIFIER')
        except Exception:
            pass
        if client.pr_identity(number)['headRefOid']!=ctx['head']:
            raise ValueError('head changed')
        return self.envelope(number=number, base_branch=text(remote['base']['ref']), base_sha=remote['base']['sha'], head_sha=ctx['head'], head_branch=text(remote['head']['ref']), risk=ctx['risk'],
            files=[text(f['filename']) for f in files[:200]], file_count=len(files), files_complete=len(files)<=200,
            url=f'https://github.com/{REPOSITORY}/pull/{number}', diff_url=f'https://github.com/{REPOSITORY}/pull/{number}/files', ci=ci, protection=protection,
            owner_disposition=owner['status'], owner_evidence=self.judgment('PASS' if owner['status']=='APPROVE' else 'UNAVAILABLE', 'OWNER_DISPOSITION', 'Current owner disposition verified through existing governance.', source='owner_review.state', observed=self.now, ttl=60, head=ctx['head'], verifier='EXISTING_OWNER_VERIFIER'),
            oracle=self.judgment('UNAVAILABLE', 'EXACT_RECEIPT_REQUIRED', 'Inspect the linked candidate receipt; CI is not independent Oracle proof.', head=ctx['head']),
            actions=dict(go=False, no_go=False, reason='Live owner-connector UI handoff has not been accepted. Use the existing isolated owner Go/No-Go workflow; no action is sent by this page.'),
            deployment=self.judgment('UNAVAILABLE', 'NO_DEPLOYMENT_ATTESTATION', 'Approval and merge are separate from actual deployed health.', head=ctx['head']))

    def dispatch(self, endpoint, query=''):
        if endpoint in {'overview', 'certification'}:
            if query:
                raise ValueError('query not allowed')
            return getattr(self, endpoint)()
        if endpoint in {'candidates', 'audit', 'prs'}:
            return getattr(self, endpoint)(query)
        match = re.fullmatch(r'(candidates|validations|prs)/([^/]+)', endpoint)
        if not match:
            raise NotFound('route missing')
        name, value = match.groups()
        if name == 'candidates':
            return self.candidate(value, query)
        if query:
            raise ValueError('query not allowed')
        return self.validation(value) if name == 'validations' else self.pr(value)


def csv_export(data):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['repository', 'exported_at_utc', 'snapshot_seq', 'seq', 'event_id', 'candidate', 'kind', 'created_at_utc', 'actor', 'identity_source', 'head_sha', 'verifier_status'])
    from datetime import datetime, timezone
    def utc(v):
        return datetime.fromtimestamp(v, timezone.utc).isoformat() if stamp(v) else ''
    def cell(v):
        v = '' if v is None else str(v)
        return "'"+v if v.lstrip().startswith(('=', '+', '-', '@')) else v
    for e in data['items']:
        writer.writerow([cell(v) for v in (REPOSITORY, utc(data['read_at']), data['snapshot_seq'], e['seq'], e['event_id'], e['candidate'], e['kind'], utc(e['created_at']), e['actor'], e['actor_identity_source'], e['head_sha'], e['status']['verifier_status'])])
    return out.getvalue().encode()


def reader_authorized(handler):
    """Reuse existing reader token or authenticated loopback Serve identity.

    The page receives neither service tokens nor owner credentials. Programmatic
    readers may supply the pre-existing token, which grants no owner action.
    """
    from .dashboard import authorized
    try:
        for name in ('Origin', 'Host', 'X-Development-Agent-Token'):
            if hasattr(handler.headers, 'get_all') and len(handler.headers.get_all(name, []))>1:
                return False
        origin = handler.headers.get('Origin')
        if origin:
            u = urlsplit(origin)
            if u.scheme not in {'https', 'http'} or u.netloc != handler.headers.get('Host') or u.path not in {'', '/'} or u.query or u.fragment:
                return False
    except ValueError:
        return False
    if handler.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
        return False
    if authorized(handler.headers, os.environ.get('DEV_AGENT_API_TOKEN', '')):
        return True
    try:
        from .identity import dashboard_identity
        dashboard_identity(handler)
        return True
    except ValueError:
        return False


def source_asset_request(path):
    """Do not let SimpleHTTPRequestHandler's fallback bypass the opt-in route."""
    canonical = posixpath.normpath('/'+unquote(path).lstrip('/'))
    return canonical=='/dev_agent/control_center_assets' or canonical.startswith('/dev_agent/control_center_assets/')


def handle(handler, path, query='', *, mutation=False):
    def send(data, code=200, content_type='application/json; charset=utf-8', cursor=None):
        raw = data if isinstance(data, bytes) else json.dumps(data, allow_nan=False).encode()
        if len(raw)>MAX_BYTES:
            raw = b'{"ok":false,"error":"response exceeds bounded view"}'; code = 503; content_type='application/json'
        handler.send_response(code)
        for k, v in [('Content-Type', content_type), ('Cache-Control', 'no-store'), ('Vary', 'Origin, X-Development-Agent-Token'), ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'), ('X-Frame-Options', 'DENY'), ('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"), ('Content-Length', str(len(raw)))]:
            handler.send_header(k, v)
        if cursor:
            handler.send_header('X-Next-Cursor', cursor)
        handler.end_headers()
        if getattr(handler, 'command', 'GET')!='HEAD':
            handler.wfile.write(raw)
    if os.environ.get('DEV_AGENT_ECC_ENABLED')!='1':
        return send(dict(ok=False, error='route unavailable'), 404)
    if mutation:
        return send(dict(ok=False, error='read-only interface'), 405)
    if not reader_authorized(handler):
        return send(dict(ok=False, error='authenticated same-origin reader required'), 403)
    assets = {PAGE: ('index.html', 'text/html; charset=utf-8'),
              '/engineering/assets/control-center.css': ('control-center.css', 'text/css; charset=utf-8'),
              '/engineering/assets/control-center.js': ('control-center.js', 'text/javascript; charset=utf-8')}
    if path in assets:
        if query:
            return send(dict(ok=False, error='query not allowed'), 400)
        name, content_type = assets[path]
        return send((Path(__file__).parent/'control_center_assets'/name).read_bytes(), content_type=content_type)
    if not path.startswith(API):
        return send(dict(ok=False, error='route unavailable'), 404)
    try:
        from .dashboard import configured_store
        center = ControlCenter(Path(__file__).resolve().parents[1], configured_store())
        result = center.dispatch(path[len(API):], query)
        if path == API+'audit' and parse_qs(query).get('format')==['csv']:
            return send(csv_export(result), content_type='text/csv; charset=utf-8', cursor=result.get('next_cursor'))
        return send(result)
    except NotFound:
        return send(dict(ok=False, error='record or route unavailable'), 404)
    except (ValueError, TypeError, KeyError):
        return send(dict(ok=False, error='invalid or unavailable read request'), 400)
    except Exception:
        return send(dict(ok=False, error='current evidence unavailable'), 503)
