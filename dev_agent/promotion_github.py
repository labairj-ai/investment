"""Read-only verification of deliberate owner promotion objects on current GitHub.

No issuer writes GitHub objects. The owner submits the documented protocol through
an allowlisted connector; ingestion records provenance, never grants activation.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import time

from . import owner_promotion
from .github import GitHub
from .owner_review import policy
from .result_collector import canonical
from .structured_json import loads

HEADER = 'OWNER-AUTONOMY-PROMOTION autonomy-promotion-1\n'


def context(root, number, client=None):
    from .certification import harness_hash
    from .operations import policy as runtime_policy
    from .git_exec import output
    p = policy()
    client = client or GitHub(p['repository'])
    if type(number) is not int or number <= 0 or client.repository != p['repository']:
        raise ValueError('operator-selected activation PR required')
    repo = client.read('repos/' + client.repository)
    owner = repo.get('owner') or {}
    if (repo.get('full_name') != p['repository'] or owner.get('type') != 'User'
            or owner.get('login') != p['owner_login'] or owner.get('id') != p['owner_id']):
        raise ValueError('current personal repository owner required')
    pr = client.pr_identity(number)
    if (pr.get('number') != number or pr.get('baseRefName') != 'main'
            or pr.get('state') not in {'OPEN', 'MERGED'}
            or (pr.get('headRepository') or {}).get('nameWithOwner') != client.repository):
        raise ValueError('current same-repository activation PR required')
    # Local execution must run the exact reviewed source or its owner merge.
    local = output(root, 'rev-parse', 'HEAD').strip()
    allowed = {pr.get('headRefOid')}
    if pr.get('state') == 'MERGED':
        from .owner_review import verify_merge_actor
        merge = (pr.get('mergeCommit') or {}).get('oid')
        verify_merge_actor(client, number, pr.get('headRefOid'), merge)
        allowed.add(merge)
    if local not in allowed:
        raise ValueError('runtime is not the exact activation source')
    cfg = runtime_policy(root)
    return dict(repository=p['repository'], harness_hash=harness_hash(root), activation_pr=number,
                head=pr.get('headRefOid'), stage=cfg.get('autonomy_stage'),
                maximum_risk=cfg.get('autonomous_max_risk'), daily_cap=cfg.get('daily_implementation_cap'),
                owner_login=p['owner_login'], owner_id=p['owner_id'])


def verified(client, obj, expected, now):
    p = policy()
    actor = obj.get('user') or {}
    app = obj.get('performed_via_github_app') or {}
    oid = obj.get('id')
    if (type(oid) is not int or oid <= 0 or actor.get('type') != 'User'
            or actor.get('id') != p['owner_id'] or actor.get('login') != p['owner_login']
            or app.get('id') != 1144995 or type(app.get('id')) is not int
            or app.get('slug') != 'chatgpt-codex-connector'
            or not any(app.get('id') == a['id'] and app.get('slug') == a['slug'] for a in p.get('allowed_github_apps', []))):
        raise ValueError('allowlisted connector and human repository owner required')
    if obj.get('updated_at') != obj.get('created_at'):
        raise ValueError('edited promotion object rejected')
    stamp = datetime.fromisoformat(obj['created_at'].replace('Z', '+00:00')).timestamp()
    if not 0 <= now - stamp <= 86400:
        raise ValueError('fresh GitHub promotion object required')
    number = expected['activation_pr']
    if (obj.get('issue_url') != f'https://api.github.com/repos/{client.repository}/issues/{number}'
            or obj.get('html_url') != f'https://github.com/{client.repository}/pull/{number}#issuecomment-{oid}'):
        raise ValueError('promotion PR/object mismatch')
    body = obj.get('body')
    if not isinstance(body, str) or len(body.encode()) > 16000 or not body.startswith(HEADER):
        raise ValueError('versioned promotion object required')
    data = loads(body[len(HEADER):])
    if not isinstance(data, dict) or set(data) != owner_promotion.FIELDS | {'decision'}:
        raise ValueError('exact promotion decision schema required')
    if data['decision'] not in {'APPROVE', 'REVOKE'}:
        raise ValueError('explicit promotion decision required')
    binding = {k: v for k, v in data.items() if k != 'decision'}
    owner_promotion.validate_binding(binding, expected, now)
    if abs(binding['created'] - stamp) > 60:
        raise ValueError('payload/GitHub timestamp mismatch')
    selected = {k: obj[k] for k in ('id', 'body', 'created_at', 'updated_at', 'issue_url', 'html_url')}
    selected['user'] = {k: actor[k] for k in ('id', 'login', 'type')}
    selected['app'] = dict(id=app['id'], slug=app['slug'])
    origin = dict(id=oid, url=obj['html_url'], sha256=hashlib.sha256(canonical(selected)).hexdigest())
    return dict(binding=binding, decision=data['decision'], origin=origin)


def latest(client, expected, now):
    """Re-read complete current comment inventory; a newer revoke/invalid act blocks."""
    rows = client.read_all(f'repos/{client.repository}/issues/{expected["activation_pr"]}/comments')
    if not isinstance(rows, list) or len(rows) > 3000:
        raise ValueError('bounded complete promotion inventory required')
    p = policy()
    own = [o for o in rows if (o.get('user') or {}).get('id') == p['owner_id']
           and isinstance(o.get('body'), str) and o['body'].startswith(HEADER)]
    if not own:
        raise ValueError('owner promotion object missing')
    for obj in own:
        if type(obj.get('id')) is not int:
            raise ValueError('canonical promotion object identity required')
    obj = max(own, key=lambda o: (o['created_at'], o['id']))
    # Fetch individually as well: list/edit races cannot silently authorize.
    current = client.read(f'repos/{client.repository}/issues/comments/{obj["id"]}')
    one = verified(client, obj, expected, now)
    if verified(client, current, expected, now) != one:
        raise ValueError('promotion changed during verification')
    return one


def ingest(root, store, number, *, client=None, now=None):
    now = time.time() if now is None else now
    p = policy(); client = client or GitHub(p['repository'])
    expected = context(root, number, client)
    item = latest(client, expected, now)
    nonce = item['binding']['nonce']
    event_id = 'owner-promotion:' + nonce
    with store.connect(True) as db:
        row = db.execute('SELECT payload FROM dev_events WHERE event_id=?', (event_id,)).fetchone()
        if row:
            if json.loads(row[0]) != item:
                raise ValueError('promotion nonce replay')
        else:
            store._append(db, None, 'OWNER_AUTONOMY_PROMOTION', item, event_id)
    return dict(status='INGESTED', decision=item['decision'], origin=item['origin'], enables_autonomy=False)


def verify_current(root, store, number, *, client=None, now=None):
    now = time.time() if now is None else now
    p = policy(); client = client or GitHub(p['repository'])
    expected = context(root, number, client)
    item = latest(client, expected, now)
    if item['decision'] != 'APPROVE':
        raise ValueError('owner promotion revoked')
    # Ledger JSON is never authentication; it must match a newly verified object.
    with store.connect() as db:
        row = db.execute('SELECT payload FROM dev_events WHERE event_id=? AND kind=?',
                         ('owner-promotion:' + item['binding']['nonce'], 'OWNER_AUTONOMY_PROMOTION')).fetchone()
    if not row or json.loads(row[0]) != item:
        raise ValueError('verified promotion ingestion missing or changed')
    if context(root, number, client) != expected:
        raise ValueError('runtime context changed during owner verification')
    return dict(status='PASS', authenticated=True, fixture_only=False, protocol=owner_promotion.PROTOCOL,
                binding=item['binding'], origin=item['origin'], grants_authority=False,
                revocation_checked=True, replay_checked=True)
