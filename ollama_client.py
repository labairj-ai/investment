import json
import os
import re
import urllib.request

# Supports both LLM_URL (MLX / any OpenAI-compatible server) and legacy OLLAMA_URL
LLM_URL = os.environ.get("LLM_URL") or os.environ.get("OLLAMA_URL", "http://127.0.0.1:8080")
DEFAULT_MODEL = "mlx-community/Qwen3.6-35B-A3B-4bit"

# mlx_lm may not strip model special tokens from output
_SPECIAL_TOKENS = re.compile(r'<\|[^|>]+\|>')


def generate(prompt, model=DEFAULT_MODEL, temperature=0.3, num_predict=700):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
        # Qwen3 thinking models put chain-of-thought in "reasoning" and the answer
        # in "content"; if the token budget ran out during reasoning, content is
        # absent — fall back to reasoning so callers get something to parse.
        content = msg.get("content") or msg.get("reasoning", "") or ""
        return _SPECIAL_TOKENS.sub('', content).strip()


def stream_generate(prompt, model=DEFAULT_MODEL, temperature=0.3, num_predict=700):
    """Yield text tokens one at a time as they arrive."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        for line in r:
            line = line.strip()
            if not line or line == b"data: [DONE]":
                continue
            if line.startswith(b"data: "):
                chunk = json.loads(line[6:])
                delta = chunk["choices"][0]["delta"]
                # Qwen3 thinking models emit reasoning tokens before content tokens;
                # yield both so callers receive output even during the thinking phase.
                token = delta.get("content") or delta.get("reasoning", "")
                token = _SPECIAL_TOKENS.sub('', token)
                if token:
                    yield token


def stream_chat(messages, model=DEFAULT_MODEL, temperature=0.4, num_predict=1000):
    """Multi-turn conversational chat — yields text tokens. messages = [{role, content}, ...]"""
    import time as _time
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    # Retry on transient connection errors (mlx_lm.server briefly refuses during inference)
    last_exc = None
    conn = None
    for attempt in range(3):
        try:
            conn = urllib.request.urlopen(req, timeout=180)
            break
        except urllib.error.URLError as e:
            last_exc = e
            if "Connection refused" in str(e) and attempt < 2:
                _time.sleep(2 ** attempt)
            else:
                raise
    if conn is None:
        raise last_exc
    with conn as r:
        for line in r:
            line = line.strip()
            if not line or line == b"data: [DONE]":
                continue
            if line.startswith(b"data: "):
                chunk = json.loads(line[6:])
                delta = chunk["choices"][0]["delta"]
                # Qwen3 thinking models emit reasoning tokens before content tokens;
                # yield both so chat shows the thinking process then the answer.
                token = delta.get("content") or delta.get("reasoning", "")
                token = _SPECIAL_TOKENS.sub('', token)
                if token:
                    yield token


def available(model=DEFAULT_MODEL):
    try:
        with urllib.request.urlopen(f"{LLM_URL}/v1/models", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False
