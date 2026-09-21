"""Compatibility entry point for the in-app agent.

The implementation now lives in modules.AI.agent_engine. This module keeps
the previous run_agent_turn API so older callers do not need to change.
"""
from __future__ import annotations
import threading
from typing import Callable
from modules.AI.agent_engine import AgentEngine, MAX_ROUNDS
from modules.AI.agent_registry import AgentRegistry

def run_agent_turn(
    client,
    history: list,
    registry: AgentRegistry,
    *,
    chat_message_cls,
    on_delta: Callable[[str], None],
    on_tool: Callable[[str, dict, dict], None],
    stop_event: threading.Event,
    max_rounds: int = MAX_ROUNDS,
) -> str:
    text, _stats = AgentEngine(registry).run(
        client, history,
        chat_message_cls=chat_message_cls,
        mode="agent",
        on_delta=on_delta,
        on_tool=on_tool,
        stop_event=stop_event,
        max_rounds=max_rounds,
    )
    return text
