# modules/AI/local_model_runner/backend.py
#
# GUI-agnostic client for talking to a locally-running model server.
# Deliberately separate from AI Chat's client.py (modules/AI/AI Chat/
# client.py) — that one always requires an API key and points at a
# hosted OpenAI-compatible provider. This one assumes no key, no
# internet, and supports two backends:
#
#   - "ollama"         Ollama's own REST API (GET /api/tags,
#                       POST /api/chat, NDJSON streaming).
#   - "openai_compat"  Anything that speaks the OpenAI chat-completions
#                       shape locally — llama.cpp's llama-server,
#                       LM Studio, text-generation-webui, etc.
#                       (GET /v1/models, POST /v1/chat/completions,
#                       SSE streaming.)

import json
from dataclasses import dataclass
from typing import Callable, List

import requests

OLLAMA_DEFAULT_URL = "http://localhost:11434"
OPENAI_COMPAT_DEFAULT_URL = "http://localhost:8080"

BACKEND_OLLAMA = "ollama"
BACKEND_OPENAI_COMPAT = "openai_compat"

BACKEND_LABELS = {
    BACKEND_OLLAMA: "Ollama",
    BACKEND_OPENAI_COMPAT: "llama.cpp / OpenAI-compatible",
}

DEFAULT_URLS = {
    BACKEND_OLLAMA: OLLAMA_DEFAULT_URL,
    BACKEND_OPENAI_COMPAT: OPENAI_COMPAT_DEFAULT_URL,
}


class LocalModelError(Exception):
    """Wraps any connection/parsing/server error into one user-facing type."""


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


# =====================================================
# MODEL DISCOVERY
# =====================================================

def list_models(base_url: str, backend: str, timeout: float = 5.0) -> List[str]:
    base_url = (base_url or DEFAULT_URLS[backend]).rstrip("/")
    try:
        if backend == BACKEND_OLLAMA:
            resp = requests.get(f"{base_url}/api/tags", timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["name"] for m in data.get("models", []) if "name" in m)
        else:
            resp = requests.get(f"{base_url}/v1/models", timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["id"] for m in data.get("data", []) if "id" in m)
    except requests.RequestException as e:
        raise LocalModelError(
            f"Couldn't reach {base_url} — is the server running? ({e})"
        ) from e
    except (KeyError, ValueError, TypeError) as e:
        raise LocalModelError(f"Unexpected response listing models: {e}") from e


def test_connection(base_url: str, backend: str, timeout: float = 5.0) -> str:
    models = list_models(base_url, backend, timeout=timeout)
    if models:
        return f"Connected — {len(models)} model{'s' if len(models) != 1 else ''} available."
    return "Connected, but no models are loaded yet."


# =====================================================
# CHAT
# =====================================================

def stream_chat(
    base_url: str,
    backend: str,
    model: str,
    messages: List[ChatMessage],
    on_delta: Callable[[str], None],
    stop_event,
    timeout: float = 300.0,
) -> str:
    """Streams a chat reply, calling on_delta(chunk) as text arrives.
    Checks stop_event so the caller can cancel mid-stream. Returns the
    full accumulated text. Safe to call from a background thread —
    on_delta runs on that same thread."""
    if backend == BACKEND_OLLAMA:
        return _stream_chat_ollama(base_url, model, messages, on_delta, stop_event, timeout)
    return _stream_chat_openai_compat(base_url, model, messages, on_delta, stop_event, timeout)


def _stream_chat_ollama(base_url, model, messages, on_delta, stop_event, timeout):
    base_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": True,
    }
    full_parts = []
    try:
        resp = requests.post(f"{base_url}/api/chat", json=payload, stream=True, timeout=timeout)
        resp.raise_for_status()
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if stop_event.is_set():
                    break
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    raise LocalModelError(str(obj["error"]))
                chunk = (obj.get("message") or {}).get("content", "")
                if chunk:
                    full_parts.append(chunk)
                    on_delta(chunk)
                if obj.get("done"):
                    break
        finally:
            resp.close()
    except requests.RequestException as e:
        raise LocalModelError(f"Ollama request failed: {e}") from e
    return "".join(full_parts)


def _stream_chat_openai_compat(base_url, model, messages, on_delta, stop_event, timeout):
    base_url = (base_url or OPENAI_COMPAT_DEFAULT_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": True,
    }
    full_parts = []
    try:
        resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, stream=True, timeout=timeout)
        resp.raise_for_status()
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if stop_event.is_set():
                    break
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                chunk = (choices[0].get("delta") or {}).get("content")
                if chunk:
                    full_parts.append(chunk)
                    on_delta(chunk)
        finally:
            resp.close()
    except requests.RequestException as e:
        raise LocalModelError(f"Request failed: {e}") from e
    return "".join(full_parts)
