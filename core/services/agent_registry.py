"""
Named actions the in-app AI agent can call.

Modules register tools once (name, JSON-schema params, handler). The
AI Chat tab turns this list into OpenAI `tools` and runs handlers when
the model requests them. Handlers must be GUI-agnostic and thread-safe
enough to run on a worker thread — hop to Tk yourself if you need widgets.

No shell execution. No vault reads. Destructive work is marked so the
chat UI can label it; the model still needs the user to ask for it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional


MAX_RESULT_CHARS = 8000


class AgentActionError(Exception):
    """User-facing failure from a single tool call."""


@dataclass
class AgentAction:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], Any]
    risk: str = "read"  # "read" | "write" | "destructive"


class AgentRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._actions: dict[str, AgentAction] = {}
        self.plugin_manager = None

    def register(self, action: AgentAction) -> None:
        name = (action.name or "").strip()
        if not name:
            raise ValueError("Agent action needs a name.")
        with self._lock:
            self._actions[name] = action

    def get(self, name: str) -> Optional[AgentAction]:
        with self._lock:
            return self._actions.get(name)

    def list_actions(self) -> list[AgentAction]:
        with self._lock:
            return list(self._actions.values())

    def openai_tools(self) -> list[dict]:
        tools = []
        for action in self.list_actions():
            params = action.parameters or {"type": "object", "properties": {}}
            if "type" not in params:
                params = {"type": "object", "properties": params}
            tools.append({
                "type": "function",
                "function": {
                    "name": action.name,
                    "description": action.description,
                    "parameters": params,
                },
            })
        return tools

    def call(self, name: str, arguments: dict | str | None = None) -> dict:
        action = self.get(name)
        if action is None:
            return {"ok": False, "error": f"Unknown action: {name}"}
        args = _parse_arguments(arguments)
        if action.risk in ("write", "destructive"):
            confirm = getattr(self, "confirm_write", None)
            if callable(confirm) and not confirm(name, args):
                result = {"ok": False, "error": "Cancelled."}
                self._log_call(name, args, result, action.risk)
                return result
        try:
            result = action.handler(args)
        except AgentActionError as e:
            result = {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        else:
            result = _normalize_result(result)
        self._log_call(name, args, result, action.risk)
        return result

    def _log_call(self, name: str, args: dict, result: dict, risk: str) -> None:
        try:
            from core.services import activity_log
            ok = bool(result.get("ok", False))
            hint = result.get("error") or result.get("name") or result.get("backup") or ""
            activity_log.add(
                "agent",
                name,
                str(hint)[:160],
                "ok" if ok else "error",
            )
        except Exception:
            pass


_REGISTRY = AgentRegistry()


def get_registry() -> AgentRegistry:
    return _REGISTRY


def register_action(
    name: str,
    description: str,
    handler: Callable[[dict], Any],
    parameters: dict | None = None,
    risk: str = "read",
) -> None:
    _REGISTRY.register(AgentAction(
        name=name,
        description=description,
        parameters=parameters or {"type": "object", "properties": {}},
        handler=handler,
        risk=risk,
    ))


def _parse_arguments(arguments: dict | str | None) -> dict:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    text = str(arguments).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise AgentActionError(f"Invalid tool arguments JSON: {text[:200]}")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise AgentActionError("Tool arguments must be a JSON object.")
    return parsed


def _normalize_result(result: Any) -> dict:
    if isinstance(result, dict):
        payload = dict(result)
        payload.setdefault("ok", True)
    else:
        payload = {"ok": True, "result": result}
    text = json.dumps(payload, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        payload = {
            "ok": payload.get("ok", True),
            "truncated": True,
            "result": text[:MAX_RESULT_CHARS] + "…",
        }
    return payload
