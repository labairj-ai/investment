import hashlib
import json
import os
import re
import time
import urllib.request

DEFAULT_MODEL = "mlx-community/Qwen3.6-35B-A3B-4bit"


class StructuredOutputError(RuntimeError):
    """Raised when generate_structured() exhausts all retries without valid output."""
    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


def _validate_schema(obj: dict, schema: dict, path: str = "") -> list[str]:
    """Return a list of missing-key error strings. Schema values are ignored — only keys matter."""
    errors = []
    for key, val in schema.items():
        if key not in obj:
            errors.append(f"missing key '{path}{key}'")
        elif isinstance(val, dict) and isinstance(obj.get(key), dict):
            errors.extend(_validate_schema(obj[key], val, path=f"{path}{key}."))
    return errors


def _get_llm_url() -> str:
    """Resolve at call time so that env vars set after import (e.g. from .env) take effect."""
    return os.environ.get("LLM_URL") or os.environ.get("OLLAMA_URL", "http://127.0.0.1:8080")

# mlx_lm may not strip model special tokens from output
_SPECIAL_TOKENS = re.compile(r'<\|[^|>]+\|>')


def generate(prompt, model=DEFAULT_MODEL, temperature=0.3, num_predict=700, enable_thinking=False):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }).encode()
    req = urllib.request.Request(
        f"{_get_llm_url()}/v1/chat/completions",
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


def generate_structured(
    prompt: str,
    schema: dict,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    num_predict: int = 1000,
    thinking: bool = False,
    retries: int = 2,
) -> dict:
    """Call the LLM in JSON mode, validate against schema, retry on failure.

    schema: dict whose keys (recursively) must appear in the response.
            Values are ignored — they document expected shape but are not type-checked.

    Returns the parsed dict. Raises StructuredOutputError if all attempts fail.
    Metadata (model, prompt_hash, latency_s, attempt) is printed on retry/failure
    so it's visible in service logs without callers needing to handle it.
    """
    prompt_hash = hashlib.sha1(prompt.encode()).hexdigest()[:8]
    payload_base = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": False,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    last_raw = ""
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            payload = json.dumps(payload_base).encode()
            req = urllib.request.Request(
                f"{_get_llm_url()}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                msg = json.loads(r.read())["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning", "") or ""
                last_raw = _SPECIAL_TOKENS.sub('', content).strip()
        except Exception as e:
            latency = time.monotonic() - t0
            print(f"[generate_structured] prompt={prompt_hash} attempt={attempt+1} "
                  f"network error after {latency:.1f}s: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        latency = time.monotonic() - t0
        try:
            result = json.loads(last_raw)
        except json.JSONDecodeError:
            print(f"[generate_structured] prompt={prompt_hash} attempt={attempt+1} "
                  f"latency={latency:.1f}s — JSON parse failed. "
                  f"Raw (first 200): {last_raw[:200]!r}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        errors = _validate_schema(result, schema)
        if errors:
            print(f"[generate_structured] prompt={prompt_hash} attempt={attempt+1} "
                  f"latency={latency:.1f}s — schema mismatch: {errors}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        if attempt > 0:
            print(f"[generate_structured] prompt={prompt_hash} succeeded on attempt {attempt+1} "
                  f"latency={latency:.1f}s")
        return result

    raise StructuredOutputError(
        f"generate_structured failed after {retries+1} attempts "
        f"(prompt={prompt_hash}). Raw tail: {last_raw[-300:]!r}",
        raw=last_raw,
    )


def stream_generate(prompt, model=DEFAULT_MODEL, temperature=0.3, num_predict=700,
                    enable_thinking=False, content_only=False):
    """Yield text tokens one at a time as they arrive.

    content_only=True: skip delta.reasoning tokens and yield only delta.content.
    Use this when accumulating output for JSON parsing — reasoning tokens contain
    prose and JSON-like sketches that break _extract_json.
    """
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }).encode()
    req = urllib.request.Request(
        f"{_get_llm_url()}/v1/chat/completions",
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
                if content_only:
                    token = delta.get("content", "")
                else:
                    # Yield both reasoning and content so callers see thinking + answer.
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
        f"{_get_llm_url()}/v1/chat/completions",
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


def get_model_id() -> str:
    """Return the configured model identifier for audit logging."""
    return DEFAULT_MODEL


def available(model=DEFAULT_MODEL):
    try:
        with urllib.request.urlopen(f"{_get_llm_url()}/v1/models", timeout=10) as r:
            return r.status == 200
    except Exception:
        return False
