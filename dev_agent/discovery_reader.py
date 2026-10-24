"""Discovery-only GitHub GETs. Public mode has no credential or CLI path."""
import os
import re
import urllib.request
from .structured_json import loads

PUBLIC_HEADERS={'Accept':'application/vnd.github+json','User-Agent':'investment-read-only-discovery'}
MODES={'public','token'}


def verify_repository(data,repository,mode):
    if not isinstance(data,dict) or data.get('full_name')!=repository:raise ValueError('canonical discovery repository required')
    if mode=='public':
        if data.get('private') is not False or data.get('visibility')!='public':raise ValueError('public discovery requires a currently public repository')
    elif mode=='token':
        p=data.get('permissions',{})
        if not isinstance(p,dict) or p.get('pull') is not True or any(p.get(k) is not False for k in ('push','admin','maintain')):raise ValueError('independently verified read-only GitHub identity required')
    else:raise ValueError('explicit reviewed discovery reader mode required')
    return data


class _PublicRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,urls):self.urls=frozenset(urls)
    def redirect_request(self,request,fp,code,message,headers,newurl):
        if newurl not in self.urls or request.get_method()!='GET' or any(k.lower() in {'authorization','proxy-authorization'} for k,v in request.header_items()):
            raise ValueError('public discovery redirect outside reviewed HTTPS GET endpoints')
        return urllib.request.Request(newurl,headers=PUBLIC_HEADERS,method='GET')


class DiscoveryReader:
    """No write methods, owner API, arbitrary URL or authentication fallback."""
    def __init__(self,repository,mode=None):
        if not isinstance(repository,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or any(p in {'.','..'} for p in repository.split('/')):raise ValueError('canonical repository required')
        self.repository=repository
        self.mode=os.environ.get('DEV_AGENT_DISCOVERY_READER_MODE','token') if mode is None else mode
        if self.mode not in MODES:raise ValueError('explicit reviewed discovery reader mode required')
        self.metadata='repos/'+repository
        self.runs=self.metadata+'/actions/runs?per_page=10'
        self.endpoints=frozenset((self.metadata,self.runs))

    def _get(self,endpoint):
        if endpoint not in self.endpoints:raise ValueError('unreviewed discovery endpoint')
        if self.mode=='token':
            from .github import GitHub
            # Mandatory before entering GitHub.read: its general owner-side CLI
            # fallback is intentionally unreachable from this discovery reader.
            return GitHub(self.repository).read(endpoint,require_token=True)
        urls={'https://api.github.com/'+p for p in self.endpoints}
        request=urllib.request.Request('https://api.github.com/'+endpoint,headers=PUBLIC_HEADERS,method='GET')
        # Fresh opener: no global owner opener, cookies, auth handler, .netrc,
        # credential file, environment proxy or CLI is consulted.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_PublicRedirect(urls))
        with opener.open(request,timeout=30) as response:
            if response.status!=200:raise ValueError('public GitHub GET did not succeed')
            raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('bounded discovery response required')
        return loads(raw)

    def read(self,endpoint):
        if not isinstance(endpoint,str) or endpoint not in self.endpoints:raise ValueError('unreviewed discovery endpoint')
        before=verify_repository(self._get(self.metadata),self.repository,self.mode)
        if endpoint==self.metadata:return before
        result=self._get(endpoint)
        verify_repository(self._get(self.metadata),self.repository,self.mode)
        if not isinstance(result,dict) or not isinstance(result.get('workflow_runs'),list) or len(result['workflow_runs'])>10:raise ValueError('bounded workflow inventory required')
        return result
