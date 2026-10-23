"""Owner promotion contract only. No ingestion/issuer; runtime remains fail-closed.

A structurally matching payload is not an authenticated owner decision. A future
reviewed owner-side issuer/verifier must establish that proof before this adapter
can ever return PASS. Neither configuration nor ledger JSON is an authority source.
"""
import re
import time

PROTOCOL='autonomy-promotion-1'
FIELDS={'protocol','repository','harness_hash','activation_pr','head','stage','maximum_risk','daily_cap','owner_login','owner_id','created','nonce','rationale'}
BOUND={'repository','harness_hash','activation_pr','head','stage','maximum_risk','daily_cap','owner_login','owner_id'}


def validate_binding(record,context,now=None):
    """Validate future protocol binding only; explicitly grants no authority."""
    now=time.time() if now is None else now
    if not isinstance(record,dict) or set(record)!=FIELDS or record['protocol']!=PROTOCOL:raise ValueError('exact owner promotion protocol required')
    if not isinstance(context,dict) or not BOUND<=context.keys() or any(record[k]!=context[k] for k in BOUND):raise ValueError('stale or mismatched owner promotion binding')
    if not isinstance(record['repository'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',record['repository']) or not isinstance(record['owner_login'],str) or not re.fullmatch(r'[A-Za-z0-9-]+',record['owner_login']):raise ValueError('canonical repository and verified owner login required')
    if not re.fullmatch(r'[a-f0-9]{40}',str(record['head'])) or not re.fullmatch(r'[a-f0-9]{64}',str(record['harness_hash'])):raise ValueError('exact activation head/harness required')
    if type(record['activation_pr']) is not int or record['activation_pr']<=0 or type(record['owner_id']) is not int or record['owner_id']<=0:raise ValueError('verified PR/owner identity required')
    if record['stage'] not in {'SHADOW','BUILD_ONLY','PR'} or record['maximum_risk']!='L2' or type(record['daily_cap']) is not int or not 1<=record['daily_cap']<=3:raise ValueError('bounded promotion policy required')
    if type(record['created']) not in (int,float) or not 0<=now-record['created']<=86400:raise ValueError('fresh owner promotion required')
    if not re.fullmatch(r'[A-Za-z0-9-]{16,128}',str(record['nonce'])) or not isinstance(record['rationale'],str) or not record['rationale'].strip():raise ValueError('deliberate single-use owner decision required')
    return dict(binding_valid=True,authenticated=False,grants_authority=False)


def authorization(root,store,*,now=None):
    # Deliberately do not accept request JSON, env vars or OWNER_REVIEW as proof.
    return dict(status='UNAVAILABLE',authenticated=False,protocol=PROTOCOL,reason='authenticated owner autonomy-promotion verifier not implemented; runtime activation unavailable',grants_authority=False)
