"""Provider adapters return bounded JSON actions; no shell/tool authority."""
from __future__ import annotations

import json
import urllib.request
import queue
import threading

from .store import bounded


def respond_bounded(provider, context, timeout=60):
    """Timeout discards late model responses; models have no host action handles."""
    if timeout <= 0: raise ValueError("wall-time budget exhausted")
    results = queue.Queue(maxsize=1)
    def request():
        try: results.put((True, provider.respond(context)))
        except Exception as error: results.put((False, type(error).__name__))
    worker = threading.Thread(target=request, daemon=True); worker.start()
    try: ok, result = results.get(timeout=min(60, timeout))
    except queue.Empty: raise ValueError("provider timeout") from None
    if not ok: raise ValueError("provider unavailable: " + result)
    bounded(result)
    return result


class ReplayProvider:
    identity = {"provider": "replay", "model": "fixture-1"}

    def __init__(self, replies):
        self.replies = iter(replies)

    def respond(self, context):
        return next(self.replies)


class OllamaProvider:
    def __init__(self, model, endpoint="http://127.0.0.1:11434/api/chat", timeout=60):
        if endpoint != "http://127.0.0.1:11434/api/chat":
            raise ValueError("only explicitly supported local model endpoint")
        self.model, self.endpoint, self.timeout = model, endpoint, min(timeout, 60)
        self.identity = dict(provider="ollama", model=model)

    def respond(self, context):
        request = urllib.request.Request(self.endpoint, json.dumps(dict(model=self.model, stream=False, format="json", messages=[
            {"role": "system", "content": "Return JSON only. Builder: {actions:[{type:write,path,content}],done:bool}. Reviewer: {disposition:PASS|REQUEST_CHANGES|NEEDS_HUMAN,findings:[{id,severity,file,requirement,evidence,principle}]}. You have no process, network or filesystem access. Follow supplied contract and principles."},
            {"role": "user", "content": bounded(context)},
        ])).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read(500_001)
        if len(raw) > 500_000: raise ValueError("provider output budget")
        result = json.loads(raw)
        content = json.loads(result["message"]["content"])
        bounded(content)
        return content


class MLXProvider:
    """Existing private Qwen endpoint, bounded JSON only; no native model tools.

    Endpoints come from installed operator configuration, never candidate JSON.
    The dedicated news server is deliberately excluded from coding workloads.
    """
    ENDPOINTS={'http://100.73.128.40:8080/v1/chat/completions','http://127.0.0.1:8080/v1/chat/completions'}
    MODEL='mlx-community/Qwen3.6-35B-A3B-4bit'

    def __init__(self,model,endpoint,timeout=60):
        if endpoint not in self.ENDPOINTS or model!=self.MODEL:raise ValueError('reviewed existing MLX coding endpoint/model required')
        self.model,self.endpoint,self.timeout=model,endpoint,min(60,max(1,timeout))
        self.identity=dict(provider='mlx',model=model)

    def respond(self,context):
        from .structured_json import loads
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise ValueError('model endpoint redirect denied')
        payload=dict(model=self.model,stream=False,temperature=0,max_tokens=2048,response_format={'type':'json_object'},
                     chat_template_kwargs={'enable_thinking':False},messages=[
                         {'role':'system','content':'Return JSON only. Builder: {actions:[{type:write,path,content}],done:bool}. Reviewer: {disposition:PASS|REQUEST_CHANGES|NEEDS_HUMAN,findings:[{id,severity,file,requirement,evidence,principle}]}. You have no process, network, filesystem, approval, merge or deployment authority. Follow the supplied contract.'},
                         {'role':'user','content':bounded(context)}])
        request=urllib.request.Request(self.endpoint,json.dumps(payload).encode(),{'Content-Type':'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=self.timeout) as response:raw=response.read(500_001)
        if len(raw)>500_000:raise ValueError('provider output budget')
        data=loads(raw)
        if not isinstance(data,dict) or not isinstance(data.get('choices'),list) or len(data['choices'])!=1:raise ValueError('one complete model response required')
        choice=data['choices'][0]
        if choice.get('finish_reason')!='stop':raise ValueError('truncated or tool-calling model response rejected')
        message=choice['message']
        if message.get('tool_calls') or not isinstance(message.get('content'),str):raise ValueError('JSON file actions required; native tools denied')
        result=loads(message['content'])
        if not isinstance(result,dict):raise ValueError('bounded JSON object required')
        bounded(result);return result


def configured_provider(model,role):
    """Operator service selection; defaults retain the existing local Ollama path."""
    import os
    if role not in {'builder','reviewer'}:raise ValueError('explicit provider role required')
    endpoint=os.environ.get('DEV_AGENT_'+role.upper()+'_ENDPOINT')
    return MLXProvider(model,endpoint) if endpoint else OllamaProvider(model)
