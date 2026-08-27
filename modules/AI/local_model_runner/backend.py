# modules/AI/local_model_runner/backend.py
#
# GUI-agnostic client for talking to a locally-running model server.
# Deliberately separate from AI Chat's client.py (modules/AI/AI Chat/
# client.py) — that one always requires an API key and points at a
# hosted OpenAI-compatible provider. This one assumes no key, no
# internet, and supports two backends:
#
#   - "ollama"         Ollama's own REST API (GET /api/tags,
#                       POST /api/chat, POST /api/show, NDJSON streaming).
#   - "openai_compat"  Anything that speaks the OpenAI chat-completions
#                       shape locally — llama.cpp's llama-server,
#                       LM Studio, text-generation-webui, etc.
#                       (GET /v1/models, POST /v1/chat/completions,
#                       SSE streaming.)

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

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


@dataclass
class GenOptions:
    """Generation params. None fields are left at server defaults."""
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    num_predict: Optional[int] = None   # max tokens to generate
    num_ctx: Optional[int] = None       # context window (ollama only)
    keep_alive: Optional[str] = None    # e.g. "5m", "0" to unload immediately, "-1" to keep forever


@dataclass
class ChatStats:
    tokens: int = 0
    seconds: float = 0.0

    @property
    def tokens_per_sec(self) -> float:
        return self.tokens / self.seconds if self.seconds > 0 else 0.0


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


def list_models_with_retry(
    base_url: str, backend: str, attempts: int = 3, delay: float = 1.5, timeout: float = 5.0
) -> List[str]:
    """Retries list_models with a short backoff before giving up — covers the
    case where a server (esp. Ollama, see try_start_ollama) is still spinning
    up when the first check runs."""
    last_err = None
    for i in range(attempts):
        try:
            return list_models(base_url, backend, timeout=timeout)
        except LocalModelError as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(delay)
    raise last_err


def test_connection(base_url: str, backend: str, timeout: float = 5.0) -> str:
    models = list_models(base_url, backend, timeout=timeout)
    if models:
        return f"Connected — {len(models)} model{'s' if len(models) != 1 else ''} available."
    return "Connected, but no models are loaded yet."


def unload_model(base_url: str, backend: str, model: str, timeout: float = 10.0) -> None:
    """Forces Ollama to unload the model from memory immediately, freeing
    VRAM/RAM without stopping the server. Unsupported for openai_compat
    backends — those servers (llama.cpp, LM Studio, etc.) typically hold
    one model for their whole process lifetime with no unload endpoint."""
    if backend != BACKEND_OLLAMA:
        raise LocalModelError("Unload is only supported for the Ollama backend.")
    base_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": "", "keep_alive": "0"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise LocalModelError(f"Couldn't unload model: {e}") from e


def get_model_info(base_url: str, backend: str, model: str, timeout: float = 5.0) -> dict:
    """Returns model metadata (size, quantization, context length, family).
    Only supported for Ollama — returns {} for openai_compat servers, since
    that API has no standard equivalent."""
    if backend != BACKEND_OLLAMA:
        return {}
    base_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    try:
        resp = requests.post(f"{base_url}/api/show", json={"name": model}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        details = data.get("details", {}) or {}
        info = {
            "family": details.get("family", "?"),
            "parameter_size": details.get("parameter_size", "?"),
            "quantization": details.get("quantization_level", "?"),
            "format": details.get("format", "?"),
        }
        model_info = data.get("model_info", {}) or {}
        for key, val in model_info.items():
            if key.endswith("context_length"):
                info["context_length"] = val
                break
        return info
    except requests.RequestException as e:
        raise LocalModelError(f"Couldn't fetch model info: {e}") from e
    except (KeyError, ValueError, TypeError) as e:
        raise LocalModelError(f"Unexpected response reading model info: {e}") from e


# =====================================================
# AUTO-LAUNCH (Ollama only, localhost only)
# =====================================================

def is_localhost(base_url: str) -> bool:
    return "localhost" in base_url or "127.0.0.1" in base_url


def try_start_ollama() -> bool:
    """Attempts to launch `ollama serve` in the background if the `ollama`
    binary is on PATH. Returns True if a process was spawned (not a
    guarantee it's healthy yet — caller should retry the connection after
    a short delay). Never raises; failures just return False."""
    exe = shutil.which("ollama")
    if not exe:
        return False
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return True
    except OSError:
        return False


def ensure_ollama_running(base_url: str, backend: str, boot_wait: float = 2.0) -> bool:
    """If backend is Ollama pointed at localhost and nothing answers, tries
    to launch it and waits briefly. Returns True if a launch was attempted."""
    if backend != BACKEND_OLLAMA or not is_localhost(base_url):
        return False
    try:
        list_models(base_url, backend, timeout=2.0)
        return False  # already running, nothing to do
    except LocalModelError:
        pass
    launched = try_start_ollama()
    if launched:
        time.sleep(boot_wait)
    return launched


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
    options: Optional[GenOptions] = None,
    timeout: float = 300.0,
) -> "tuple[str, ChatStats]":
    """Streams a chat reply, calling on_delta(chunk) as text arrives.
    Checks stop_event so the caller can cancel mid-stream. Returns
    (full_text, ChatStats). Safe to call from a background thread —
    on_delta runs on that same thread."""
    options = options or GenOptions()
    if backend == BACKEND_OLLAMA:
        return _stream_chat_ollama(base_url, model, messages, on_delta, stop_event, options, timeout)
    return _stream_chat_openai_compat(base_url, model, messages, on_delta, stop_event, options, timeout)


def _ollama_options_payload(options: GenOptions) -> dict:
    opts = {}
    if options.temperature is not None:
        opts["temperature"] = options.temperature
    if options.top_p is not None:
        opts["top_p"] = options.top_p
    if options.num_predict is not None:
        opts["num_predict"] = options.num_predict
    if options.num_ctx is not None:
        opts["num_ctx"] = options.num_ctx
    return opts


def _stream_chat_ollama(base_url, model, messages, on_delta, stop_event, options, timeout):
    base_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": True,
    }
    gen_opts = _ollama_options_payload(options)
    if gen_opts:
        payload["options"] = gen_opts
    if options.keep_alive:
        payload["keep_alive"] = options.keep_alive

    full_parts = []
    stats = ChatStats()
    start = time.monotonic()
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
                    eval_count = obj.get("eval_count")
                    eval_duration = obj.get("eval_duration")  # nanoseconds
                    if eval_count and eval_duration:
                        stats.tokens = eval_count
                        stats.seconds = eval_duration / 1e9
                    break
        finally:
            resp.close()
    except requests.RequestException as e:
        raise LocalModelError(f"Ollama request failed: {e}") from e
    if stats.seconds == 0.0 and full_parts:
        stats.seconds = time.monotonic() - start
    return "".join(full_parts), stats


def _stream_chat_openai_compat(base_url, model, messages, on_delta, stop_event, options, timeout):
    base_url = (base_url or OPENAI_COMPAT_DEFAULT_URL).rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": True,
    }
    if options.temperature is not None:
        payload["temperature"] = options.temperature
    if options.top_p is not None:
        payload["top_p"] = options.top_p
    if options.num_predict is not None:
        payload["max_tokens"] = options.num_predict

    full_parts = []
    stats = ChatStats()
    start = time.monotonic()
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
    stats.seconds = time.monotonic() - start
    stats.tokens = len(full_parts)  # rough — no per-token accounting from this API shape
    return "".join(full_parts), stats
