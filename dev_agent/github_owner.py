"""Read-only GitHub owner attestation ingestion. Never writes comments or merges."""
from __future__ import annotations
import hashlib
import json
import re
import time
from datetime import datetime
from .owner_review import policy,context,allowed_owner_app
from .result_collector import canonical

HEADER='OWNER-REVIEW solo-owner-2\n'
ACTION_HEADER='OWNER-AUTHORIZATION solo-owner-3\n'
ACTIONS=frozenset({'MERGE_ONLY','MERGE_AND_DEPLOY'})
FIELDS={'repository','pr','head','risk','decision','nonce','rationale','financial_ack','execution_ack'}

ACTION_FIELDS=FIELDS|{'action','issued_at','owner_login','owner_id','source_head','policy_hash'}


def action_binding(current,action,nonce,rationale,*,financial_ack,execution_ack,issued_at=None):
    """Construct shape only; only authenticated owner connector may issue it."""
    p=policy()
    data=dict(repository=current['repository'],pr=current['pr'],head=current['head'],risk=current['risk'],
              decision='APPROVE',nonce=nonce,rationale=rationale,financial_ack=financial_ack,execution_ack=execution_ack,
              action=action,issued_at=time.time() if issued_at is None else issued_at,
              owner_login=current['owner_login'],owner_id=current['owner_id'],
              source_head=p.get('issuer_source_head'),policy_hash=current['policy_hash'])
    validate_action(data,'MERGE')
    return data


def validate_action(data,operation):
    # Rationale never grants authority. No legacy/default/missing-scope fallback.
    from .store import digest
    p=policy()
    if not isinstance(data,dict) or set(data)!=ACTION_FIELDS or type(data.get('action')) is not str or data.get('action') not in ACTIONS:
        raise ValueError('exact versioned action scope required')
    if (type(data.get('decision')) is not str or data.get('decision') not in {'APPROVE','REQUEST_CHANGES','DEFER'} or type(data.get('pr')) is not int or data['pr']<=0
            or not re.fullmatch('[a-f0-9]{40}',str(data.get('head'))) or not re.fullmatch('[A-Za-z0-9-]{16,128}',str(data.get('nonce')))
            or not isinstance(data.get('rationale'),str) or not data['rationale'].strip()):raise ValueError('canonical deliberate action binding required')
    if data['action'] not in p.get('authorized_actions',[]):raise ValueError('action not explicitly supported by owner policy')
    if data['source_head']!=p.get('issuer_source_head') or not re.fullmatch('[a-f0-9]{40}',str(data['source_head'])) or data['policy_hash']!=digest(p):
        raise ValueError('reviewed controller source and policy identity required')
    if data['repository']!=p['repository'] or data['owner_login']!=p['owner_login'] or type(data['owner_id']) is not int or data['owner_id']!=p['owner_id']:
        raise ValueError('authenticated action owner binding mismatch')
    if data['risk']!='L5' or data['financial_ack'] is not True or data['execution_ack'] is not True:
        raise ValueError('explicit L5 acknowledgments required for action authority')
    if type(data['issued_at']) not in (int,float) or not 0<data['issued_at']<=time.time():raise ValueError('valid action timestamp required')
    if operation not in {'MERGE','DEPLOY'} or operation=='DEPLOY' and data['action']!='MERGE_AND_DEPLOY':
        raise ValueError('MERGE_ONLY cannot authorize deployment')
    return data['action']


def nonce_inventory(client,nonce,object_id=None):
    """Check complete remote history, not only one controller's local ledger."""
    from .structured_json import loads
    rows=client.read_all('repos/'+client.repository+'/issues/comments')
    if not isinstance(rows,list) or len(rows)>=10000:raise ValueError('complete bounded owner nonce inventory required')
    p=policy();matches=[]
    for row in rows:
        actor=row.get('user') or {};body=row.get('body','')
        if (actor.get('id')!=p['owner_id'] or actor.get('login')!=p['owner_login'] or actor.get('type')!='User'
                or not isinstance(body,str) or not body.startswith((HEADER,ACTION_HEADER))):continue
        if len(body.encode())>16000:raise ValueError('bounded owner object required')
        data=loads(body[len(ACTION_HEADER if body.startswith(ACTION_HEADER) else HEADER):])
        if not isinstance(data,dict):raise ValueError('typed owner nonce inventory required')
        if data.get('nonce')==nonce:matches.append(row.get('id'))
    if matches!=([object_id] if object_id is not None else []):raise ValueError('owner nonce replay or incomplete remote inventory')


def verified_object(client,object_id):
    if type(object_id) is not int or object_id<=0:raise ValueError('GitHub comment ID required')
    p=policy();obj=client.read(f'repos/{client.repository}/issues/comments/{object_id}')
    user=obj.get('user') or {}
    if (client.repository!=p['repository'] or obj.get('id')!=object_id or user.get('id')!=p['owner_id']
        or user.get('login')!=p['owner_login'] or user.get('type')!='User' or not allowed_owner_app(obj,p)):raise ValueError('owner-authored human object required')
    try:created=datetime.fromisoformat(obj['created_at'].replace('Z','+00:00')).timestamp()
    except (ValueError,KeyError,TypeError):raise ValueError('GitHub decision timestamp required') from None
    # Authority expires on changed context or revocation, not a daily owner ceremony.
    # Technical evidence retains its independent TTL and is rechecked downstream.
    if not 0<created<=time.time():raise ValueError('valid GitHub owner decision timestamp required')
    body=obj.get('body','')
    if not isinstance(body,str) or len(body.encode())>16000 or not body.startswith((HEADER,ACTION_HEADER)):raise ValueError('versioned structured owner review required')
    scoped=body.startswith(ACTION_HEADER)
    raw=body[len(ACTION_HEADER if scoped else HEADER):]
    from dev_agent.structured_json import loads
    data=loads(raw)
    if not isinstance(data,dict) or set(data)!=(ACTION_FIELDS if scoped else FIELDS):raise ValueError('exact owner payload schema required')
    if data['repository']!=client.repository or type(data['pr']) is not int or data['pr']<=0:raise ValueError('repository/PR mismatch')
    if obj.get('issue_url')!=f'https://api.github.com/repos/{client.repository}/issues/{data["pr"]}':raise ValueError('comment belongs to another PR')
    if obj.get('html_url')!=f'https://github.com/{client.repository}/pull/{data["pr"]}#issuecomment-{object_id}':raise ValueError('canonical owner object URL required')
    if obj.get('created_at')!=obj.get('updated_at'):raise ValueError('edited owner objects require a new nonce/object')
    if data['decision'] not in {'APPROVE','REQUEST_CHANGES','DEFER'} or not re.fullmatch(r'[A-Za-z0-9-]{16,128}',str(data['nonce'])):raise ValueError('explicit decision and nonce required')
    if type(data['financial_ack']) is not bool or type(data['execution_ack']) is not bool or not isinstance(data['rationale'],str):raise ValueError('typed domain acknowledgments required')
    current=context(client,data['pr'],risk=data['risk'])
    if current['head']!=data['head']:raise ValueError('stale owner-approved head')
    level=int(data['risk'][1:])
    if data['decision']=='APPROVE' and (level>=3 and not data['rationale'].strip() or level>=4 and not data['financial_ack'] or level>=5 and not data['execution_ack']):raise ValueError('risk acknowledgments missing')
    if scoped:
        nonce_inventory(client,data['nonce'],object_id)
        validate_action(data,'MERGE')
        if abs(data['issued_at']-created)>60:raise ValueError('fresh issuance bound to GitHub timestamp required')
    # No conversation, OAuth token or private credential enters the ledger.
    selected={k:obj.get(k) for k in ('id','html_url','issue_url','body','created_at','updated_at')};selected['user']={k:user[k] for k in ('id','login','type')};selected['performed_via_github_app']=obj.get('performed_via_github_app')
    if scoped and client.read(f'repos/{client.repository}/issues/comments/{object_id}')!=obj:raise ValueError('owner object changed during validation')
    return data,current,dict(id=object_id,url=obj['html_url'],created_at=obj['created_at'],sha256=hashlib.sha256(canonical(selected)).hexdigest())


def latest_object(client,number,head,created_at,*,required=True):
    """Observe newer owner decisions even before a scout ingests them locally."""
    from datetime import timedelta
    from urllib.parse import urlencode
    since=(datetime.fromisoformat(created_at.replace('Z','+00:00'))-timedelta(seconds=1)).isoformat()
    p=policy();rows=[]
    for page in range(1,5):
        batch=client.read(f'repos/{client.repository}/issues/{number}/comments?'+urlencode(dict(since=since,per_page=30,page=page)))
        if not isinstance(batch,list):raise ValueError('complete owner-decision inventory unavailable')
        rows.extend(batch)
        if len(batch)<30:break
    else:raise ValueError('owner-decision inventory exceeds bounded visibility')
    matches=[]
    from .structured_json import loads
    for row in rows:
        user=row.get('user') or {};body=row.get('body','')
        if user.get('id')!=p['owner_id'] or user.get('login')!=p['owner_login'] or user.get('type')!='User' or not isinstance(body,str) or not body.startswith((HEADER,ACTION_HEADER)):continue
        if len(body.encode())>16000:raise ValueError('oversized owner decision')
        data=loads(body[len(ACTION_HEADER if body.startswith(ACTION_HEADER) else HEADER):])
        if data.get('head')==head and data.get('repository')==client.repository and data.get('pr')==number:
            stamp=datetime.fromisoformat(row['created_at'].replace('Z','+00:00')).timestamp()
            if type(row.get('id')) is not int:raise ValueError('canonical owner object ID required')
            matches.append((stamp,row['id']))
    if not matches:
        if required:raise ValueError('owner decision absent from current PR inventory')
        return None
    return max(matches)[1]


def ingest(store,client,object_id):
    data,current,origin=verified_object(client,object_id)
    if latest_object(client,data['pr'],current['head'],origin['created_at'])!=object_id:raise ValueError('newer owner decision exists')
    payload=dict(context=current,decision=data['decision'],rationale=data['rationale'],financial_ack=data['financial_ack'],execution_ack=data['execution_ack'],created=time.time(),decision_nonce=data['nonce'],actor=current['owner_login'],authentication_source='github-owner-object',authenticated_at=time.time(),origin=origin)
    if 'action' in data:payload['action_binding']=data
    with store.connect(True) as db:
        row=db.execute('SELECT payload FROM dev_events WHERE event_id=?',('owner-review:'+data['nonce'],)).fetchone()
        if row:
            old=json.loads(row[0])
            if old.get('origin')==origin and old.get('context')==current and old.get('decision')==data['decision']:return old
            raise ValueError('owner nonce replay or different origin')
        store._append(db,None,'OWNER_REVIEW',payload,'owner-review:'+data['nonce'])
    return payload


def still_valid(item,client):
    try:
        data,current,origin=verified_object(client,item['origin']['id'])
        return latest_object(client,data['pr'],current['head'],origin['created_at'])==origin['id'] and current==item['context'] and origin==item['origin'] and data['decision']==item['decision'] and data['nonce']==item['decision_nonce'] and (data==item.get('action_binding') if 'action' in data else 'action_binding' not in item)
    except Exception:return False


def newest_review(client,number,head):
    from datetime import timezone,timedelta
    since='1970-01-01T00:00:01+00:00'
    return latest_object(client,number,head,since)


def authenticated_identity(client,object_id):
    """Trusted API boundary, analogous to the verified proxy identity factory.

    Never accepts actor names or credentials from model/request JSON.
    """
    data,current,origin=verified_object(client,object_id)
    if data['decision']!='APPROVE':raise ValueError('owner approval is required for success attribution')
    if latest_object(client,data['pr'],current['head'],origin['created_at'])!=object_id:raise ValueError('owner decision superseded')
    from .identity import HumanIdentity,_PROOF
    return HumanIdentity(current['owner_login'],'github-owner-object',_PROOF)
