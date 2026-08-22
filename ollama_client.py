import json
import os
import urllib.request

# Supports both LLM_URL (MLX / any OpenAI-compatible server) and legacy OLLAMA_URL
LLM_URL = os.environ.get("LLM_URL") or os.environ.get("OLLAMA_URL", "http://127.0.0.1:8080")
DEFAULT_MODEL = "mlx-community/phi-4-4bit"


def generate(prompt, model=DEFAULT_MODEL, temperature=0.3, num_predict=700):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def stream_generate(prompt, model=DEFAULT_MODEL, temperature=0.3, num_predict=700):
    """Yield text tokens one at a time as they arrive."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": True,
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
                token = chunk["choices"][0]["delta"].get("content", "")
                if token:
                    yield token


def stream_chat(messages, model=DEFAULT_MODEL, temperature=0.4, num_predict=1000):
    """Multi-turn conversational chat — yields text tokens. messages = [{role, content}, ...]"""
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
    with urllib.request.urlopen(req, timeout=180) as r:
        for line in r:
            line = line.strip()
            if not line or line == b"data: [DONE]":
                continue
            if line.startswith(b"data: "):
                chunk = json.loads(line[6:])
                token = chunk["choices"][0]["delta"].get("content", "")
                if token:
                    yield token


def available(model=DEFAULT_MODEL):
    try:
        with urllib.request.urlopen(f"{LLM_URL}/v1/models", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False
