import json
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1:8b"


def generate(prompt, model=DEFAULT_MODEL, temperature=0.3):
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature, "num_predict": 800},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["response"].strip()


def stream_generate(prompt, model=DEFAULT_MODEL, temperature=0.3):
    """Yield text tokens one at a time as they arrive from Ollama."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": True,
        "format": "json",
        "options": {"temperature": temperature, "num_predict": 800},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        for line in r:
            if not line:
                continue
            chunk = json.loads(line)
            token = chunk.get("response", "")
            if token:
                yield token
            if chunk.get("done"):
                break


def available(model=DEFAULT_MODEL):
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            data = json.loads(r.read())
            return any(
                m["name"].startswith(model.split(":")[0])
                for m in data.get("models", [])
            )
    except Exception:
        return False
