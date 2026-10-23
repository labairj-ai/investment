"""Sanitized immutable deployment history. Hashes detect edits, not human authority."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
import re
import time
from pathlib import Path
from .result_collector import canonical
from .structured_json import loads

SCHEMA='deployment-evidence-1'
FIELDS={'repository','pr','head','merge_sha','deployed_sha','prior_sha','main_sha','deployed_at','actor','fixture_only','head_ci','merge_ci','health','backup','activation','state_safety'}
HEALTH={'service_active','dashboard_http','development_dashboard_http','authenticated_api_http','unauthorized_api_http','advisor_functional','advisor_mutation_safety'}
FLAGS={'autonomous_implementation','supervised_loop_enabled','supervised_publish_pr','auto_merge'}
SAFETY={'holdings_unchanged','investment_state_unchanged','development_ledger_unchanged'}


def require_keys(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError('exact deployment evidence fields required')


def validate(envelope,*,expected_sha256=None):
    require_keys(envelope,{'schema','receipt','sha256'})
    if envelope['schema']!=SCHEMA:raise ValueError('deployment evidence schema required')
    digest=hashlib.sha256(canonical(dict(schema=SCHEMA,receipt=envelope['receipt']))).hexdigest()
    if envelope['sha256']!=digest or expected_sha256 is not None and expected_sha256!=digest:raise ValueError('deployment evidence digest mismatch')
    r=envelope['receipt'];require_keys(r,FIELDS)
    if not isinstance(r['repository'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',r['repository']) or type(r['pr']) is not int or r['pr']<=0:raise ValueError('repository/PR identity required')
    for key in ('head','merge_sha','deployed_sha','prior_sha','main_sha'):
        if not isinstance(r[key],str) or not re.fullmatch(r'[a-f0-9]{40}',r[key]):raise ValueError('exact deployment SHA required')
    if not r['deployed_sha']==r['merge_sha']==r['main_sha']:raise ValueError('merged main/deployed SHA mismatch')
    try:
        stamp=datetime.fromisoformat(r['deployed_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp.timestamp()>time.time()+60:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ValueError('timezone-bound deployment timestamp required') from None
    if r['actor'] not in {'manual-owner-authorized','deployment-agent'} or type(r['fixture_only']) is not bool:raise ValueError('deployment actor/provenance required')
    for field,sha in [('head_ci',r['head']),('merge_ci',r['merge_sha'])]:
        ci=r[field];require_keys(ci,{'run_id','head','status','url'})
        if type(ci['run_id']) is not int or ci['run_id']<=0 or ci['head']!=sha or ci['status']!='PASS' or ci['url']!=f'https://github.com/{r["repository"]}/actions/runs/{ci["run_id"]}':raise ValueError('exact-SHA passing CI evidence required')
    require_keys(r['health'],HEALTH);h=r['health']
    if h['service_active'] is not True or any(type(h[k]) is not int or h[k]!=v for k,v in [('dashboard_http',200),('development_dashboard_http',200),('authenticated_api_http',200),('unauthorized_api_http',403)]) or h['advisor_functional']!='PASS' or h['advisor_mutation_safety']!='PASS':raise ValueError('complete passing runtime health evidence required')
    require_keys(r['backup'],{'exists','integrity','sha256'})
    if r['backup']['exists'] is not True or r['backup']['integrity']!='ok' or not isinstance(r['backup']['sha256'],str) or not re.fullmatch(r'[a-f0-9]{64}',r['backup']['sha256']):raise ValueError('verified rollback backup required')
    require_keys(r['activation'],FLAGS)
    if any(type(v) is not bool for v in r['activation'].values()) or r['activation']['auto_merge']:raise ValueError('typed activation and disabled auto-merge required')
    require_keys(r['state_safety'],SAFETY)
    if any(v is not True for v in r['state_safety'].values()):raise ValueError('complete protected-state safety required')
    return r


def seal(receipt):
    value=dict(schema=SCHEMA,receipt=receipt)
    value['sha256']=hashlib.sha256(canonical(value)).hexdigest();validate(value);return value


def load(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16000:raise ValueError('bounded regular deployment evidence required')
    value=loads(path.read_text());validate(value);return value


def qualifying(envelope,*,repository,pr,head,merge_sha,expected_sha256=None):
    r=validate(envelope,expected_sha256=expected_sha256)
    if r['fixture_only'] or r['actor']!='deployment-agent':raise ValueError('real deployment-agent release required for supervised success')
    if (r['repository'],r['pr'],r['head'],r['merge_sha'])!=(repository,pr,head,merge_sha):raise ValueError('deployment evidence candidate identity mismatch')
    return r
