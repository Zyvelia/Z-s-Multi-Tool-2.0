"""
Tool-calling loop for the in-app agent.

Uses one non-streaming completion per round so tool_calls stay easy to
parse. Streams are not used here — the chat UI prints the final text
and a line per tool call.
"""

from __future__ import annotations

import threading
from typing import Callable

from core.services.agent_registry import AgentRegistry


MAX_TOOL_ROUNDS = 8

AGENT_SYSTEM_PROMPT = """You are the in-app agent for Z's Multi Tool, a local Windows desktop app.
You can call tools to actually do things on this PC — game servers, Remote Hub, YouTube downloads, notes, messages, clipboard, system stats, /build-style projects, soundboard, and a limited server console.
Prefer tools over guessing. If a name is ambiguous, list first, then act.
For "start X and tell me when it's up": start_game_server, then wait_until_game_server_ready, then summarize (and send_message if they asked to be pinged).
For downloads: queue_youtube_download, then wait_for_youtube_download if they want to know when it finishes.
For "build me a …" or /build: call build_project with the full prompt. Files are written under AI_Projects on this PC. Do not claim a build finished if the tool failed.
After tools run, summarize what happened in plain language.
Never claim you started, stopped, or saved something if the tool reported a failure.
Do not invent servers, notes, or modules that the tools did not return.
Do not ask the user to run a command you can run yourself.
You cannot read the password vault, shred files, or run arbitrary shell commands.
"""


def run_agent_turn(
    client,
    history: list,
    registry: AgentRegistry,
    *,
    chat_message_cls,
    on_delta: Callable[[str], None],
    on_tool: Callable[[str, dict, dict], None],
    stop_event: threading.Event,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> str:
    """
    history is a list of ChatMessage (same class as modules.AI.client.ChatMessage).
    Returns the final assistant text (possibly empty if cancelled).
    Mutates history in place, including tool-call / tool-result messages.
    """
    tools = registry.openai_tools()
    working = _with_system_prompt(history, chat_message_cls)

    final_text = ""
    for _ in range(max_rounds):
        if stop_event.is_set():
            break

        assistant = client.complete_with_tools(
            working,
            tools=tools,
            stop_event=stop_event,
        )
        history.append(assistant)
        working.append(assistant)

        if not assistant.tool_calls:
            final_text = assistant.content or ""
            if final_text:
                on_delta(final_text)
            break

        for call in assistant.tool_calls:
            if stop_event.is_set():
                break
            fn = (call.get("function") or {}) if isinstance(call, dict) else {}
            name = fn.get("name") or "unknown"
            raw_args = fn.get("arguments") or "{}"
            result = registry.call(name, raw_args)
            on_tool(name, _safe_args(raw_args), result)
            tool_msg = chat_message_cls(
                role="tool",
                content=_json(result),
                tool_call_id=call.get("id") if isinstance(call, dict) else None,
                name=name,
            )
            history.append(tool_msg)
            working.append(tool_msg)
        else:
            continue
        break
    else:
        final_text = "Stopped after too many tool rounds. Ask me to continue if you still need something."
        on_delta(final_text)
        history.append(chat_message_cls(role="assistant", content=final_text))

    return final_text


def _with_system_prompt(history: list, chat_message_cls) -> list:
    out = [chat_message_cls(role="system", content=AGENT_SYSTEM_PROMPT)]
    for msg in history:
        if getattr(msg, "role", None) == "system":
            continue
        out.append(msg)
    return out


def _safe_args(raw_args) -> dict:
    if isinstance(raw_args, dict):
        return raw_args
    try:
        import json
        parsed = json.loads(raw_args or "{}")
        return parsed if isinstance(parsed, dict) else {"_": parsed}
    except Exception:
        return {"_raw": str(raw_args)[:200]}


def _json(payload: dict) -> str:
    import json
    return json.dumps(payload, default=str, ensure_ascii=False)
