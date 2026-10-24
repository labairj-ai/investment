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
FIELDS={'repository','pr','head','risk','decision','nonce','rationale','financial_ack','execution_ack'}


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
    if not isinstance(body,str) or len(body.encode())>16000 or not body.startswith(HEADER):raise ValueError('versioned structured owner review required')
    raw=body[len(HEADER):]
    from dev_agent.structured_json import loads
    data=loads(raw)
    if not isinstance(data,dict) or set(data)!=FIELDS:raise ValueError('exact owner payload schema required')
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
    # No conversation, OAuth token or private credential enters the ledger.
    selected={k:obj.get(k) for k in ('id','html_url','issue_url','body','created_at','updated_at')};selected['user']={k:user[k] for k in ('id','login','type')};selected['performed_via_github_app']=obj.get('performed_via_github_app')
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
        if user.get('id')!=p['owner_id'] or user.get('login')!=p['owner_login'] or user.get('type')!='User' or not isinstance(body,str) or not body.startswith(HEADER):continue
        if len(body.encode())>16000:raise ValueError('oversized owner decision')
        data=loads(body[len(HEADER):])
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
        return latest_object(client,data['pr'],current['head'],origin['created_at'])==origin['id'] and current==item['context'] and origin==item['origin'] and data['decision']==item['decision'] and data['nonce']==item['decision_nonce']
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
