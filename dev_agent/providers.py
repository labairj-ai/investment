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
