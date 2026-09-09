"""
client.py
AI/API logic for the AI Terminal module - fully decoupled from the GUI.

Uses the OpenAI Python SDK pointed at a configurable base URL, so it
works with any OpenAI-compatible provider (default: https://api.xkiro.com/v1).

The API key lives only in memory for the lifetime of the process (see
security.InMemorySecret) and is never written to disk/logs/config/DB.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

try:
    from openai import OpenAI
    from openai import (
        APIError,
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "The 'openai' package is required for the AI Terminal module. "
        "Install it with: pip install openai"
    ) from e

from .security import InMemorySecret

DEFAULT_BASE_URL = "https://api.xkiro.com/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


class AIClientError(Exception):
    """Wraps any client/network/API error into a single user-facing type."""


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class AIClientConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: InMemorySecret = field(default_factory=InMemorySecret)
    timeout: float = 60.0


class AIClient:
    """
    Thin, GUI-agnostic wrapper around the OpenAI SDK.

    Thread-safety note: call configure() from the main thread; individual
    request methods (test_connection, stream_chat, simple_chat, list_models)
    are safe to call from a background worker thread since they never touch
    any GUI state directly.
    """

    def __init__(self, config: Optional[AIClientConfig] = None):
        self.config = config or AIClientConfig()
        self._client_lock = threading.Lock()
        self._sdk_client: Optional[OpenAI] = None

    # -- configuration -------------------------------------------------------

    def configure(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        with self._client_lock:
            self.config.base_url = (base_url or DEFAULT_BASE_URL).strip()
            self.config.model = (model or DEFAULT_MODEL).strip()
            self.config.timeout = timeout
            self.config.api_key.set(api_key.strip() if api_key else "")
            self._sdk_client = None  # force rebuild with new settings

    def _get_sdk_client(self) -> OpenAI:
        with self._client_lock:
            if self._sdk_client is None:
                if not self.config.api_key.is_set():
                    raise AIClientError("No API key set. Enter your API key before connecting.")
                self._sdk_client = OpenAI(
                    api_key=self.config.api_key.get(),
                    base_url=self.config.base_url or DEFAULT_BASE_URL,
                    timeout=self.config.timeout,
                )
            return self._sdk_client

    def has_key(self) -> bool:
        return self.config.api_key.is_set()

    # -- requests --------------------------------------------------------------

    def test_connection(self) -> str:
        """
        Sends a minimal request to verify the provider/key/model work.
        Returns a short success message or raises AIClientError.
        """
        client = self._get_sdk_client()
        try:
            resp = client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": "Reply with just: OK"}],
                max_tokens=5,
            )
            text = (resp.choices[0].message.content or "").strip()
            return f"Connection OK. Model responded: {text!r}"
        except AuthenticationError as e:
            raise AIClientError(f"Authentication failed: invalid API key. ({e})") from e
        except (APIConnectionError, APITimeoutError) as e:
            raise AIClientError(f"Network error contacting provider: {e}") from e
        except RateLimitError as e:
            raise AIClientError(f"Rate limited by provider: {e}") from e
        except APIError as e:
            raise AIClientError(f"API error: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise AIClientError(f"Unexpected error: {e}") from e

    def list_models(self) -> List[str]:
        client = self._get_sdk_client()
        try:
            models = client.models.list()
            return sorted(m.id for m in models.data)
        except Exception as e:  # noqa: BLE001
            raise AIClientError(f"Could not list models: {e}") from e

    def stream_chat(
        self,
        messages: List[ChatMessage],
        on_delta: Callable[[str], None],
        stop_event: threading.Event,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Streams a chat completion, calling on_delta(text_chunk) for each
        piece of text as it arrives. Checks stop_event frequently so the
        caller can cancel generation early. Returns the full accumulated
        text. Raises AIClientError on failure.

        Safe to call from a background thread. on_delta runs on that same
        thread - the caller (GUI) is responsible for marshalling updates
        back to the main thread (e.g. via a queue + widget.after()).
        """
        client = self._get_sdk_client()
        full_text_parts: List[str] = []

        payload = [_message_payload(m) for m in messages]

        try:
            stream = client.chat.completions.create(
                model=self.config.model,
                messages=payload,
                stream=True,
                max_tokens=max_tokens,
            )
            for chunk in stream:
                if stop_event.is_set():
                    try:
                        stream.close()
                    except Exception:
                        pass
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    full_text_parts.append(text)
                    on_delta(text)
            return "".join(full_text_parts)

        except AuthenticationError as e:
            raise AIClientError(f"Authentication failed: invalid API key. ({e})") from e
        except (APIConnectionError, APITimeoutError) as e:
            raise AIClientError(f"Network error: {e}") from e
        except RateLimitError as e:
            raise AIClientError(f"Rate limited by provider: {e}") from e
        except APIError as e:
            raise AIClientError(f"API error: {e}") from e
        except Exception as e:  # noqa: BLE001
            if stop_event.is_set():
                # Cancellation-related exceptions are expected; return what we have.
                return "".join(full_text_parts)
            raise AIClientError(f"Unexpected error: {e}") from e

    def simple_chat(self, messages: List[ChatMessage], max_tokens: Optional[int] = None) -> str:
        """Non-streaming helper, used by the AI builder for structured requests."""
        client = self._get_sdk_client()
        payload = [_message_payload(m) for m in messages]
        try:
            resp = client.chat.completions.create(
                model=self.config.model,
                messages=payload,
                max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        except AuthenticationError as e:
            raise AIClientError(f"Authentication failed: invalid API key. ({e})") from e
        except (APIConnectionError, APITimeoutError) as e:
            raise AIClientError(f"Network error: {e}") from e
        except RateLimitError as e:
            raise AIClientError(f"Rate limited by provider: {e}") from e
        except APIError as e:
            raise AIClientError(f"API error: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise AIClientError(f"Unexpected error: {e}") from e

    def complete_with_tools(
        self,
        messages: List[ChatMessage],
        tools: list,
        stop_event: threading.Event,
    ) -> ChatMessage:
        """One non-streaming completion that may include tool_calls."""
        if stop_event.is_set():
            return ChatMessage(role="assistant", content="")

        client = self._get_sdk_client()
        payload = [_message_payload(m) for m in messages]
        kwargs = {
            "model": self.config.model,
            "messages": payload,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = client.chat.completions.create(**kwargs)
        except AuthenticationError as e:
            raise AIClientError(f"Authentication failed: invalid API key. ({e})") from e
        except (APIConnectionError, APITimeoutError) as e:
            raise AIClientError(f"Network error: {e}") from e
        except RateLimitError as e:
            raise AIClientError(f"Rate limited by provider: {e}") from e
        except APIError as e:
            raise AIClientError(f"API error: {e}") from e
        except Exception as e:  # noqa: BLE001
            if stop_event.is_set():
                return ChatMessage(role="assistant", content="")
            raise AIClientError(f"Unexpected error: {e}") from e

        choice = resp.choices[0].message
        raw_calls = getattr(choice, "tool_calls", None) or []
        tool_calls = []
        for call in raw_calls:
            fn = getattr(call, "function", None)
            tool_calls.append({
                "id": getattr(call, "id", "") or "",
                "type": "function",
                "function": {
                    "name": getattr(fn, "name", "") if fn is not None else "",
                    "arguments": (getattr(fn, "arguments", None) or "{}") if fn is not None else "{}",
                },
            })
        return ChatMessage(
            role="assistant",
            content=choice.content or "",
            tool_calls=tool_calls or None,
        )


def _message_payload(message: ChatMessage) -> dict:
    if message.role == "tool":
        payload = {"role": "tool", "content": message.content or ""}
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.name:
            payload["name"] = message.name
        return payload
    if message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": message.tool_calls,
        }
    return {"role": message.role, "content": message.content or ""}
