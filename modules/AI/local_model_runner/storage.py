# modules/AI/local_model_runner/storage.py
#
# Remembers backend/base URL/model/system prompt/generation params across
# restarts, and persists chat history so a session survives a restart —
# same paths.data_path() convention as every other module.

import json
import os

from core import paths
from . import backend

SETTINGS_FILE = paths.data_path("local_model_runner", "settings.json")
HISTORY_FILE = paths.data_path("local_model_runner", "history.json")
PRESETS_FILE = paths.data_path("local_model_runner", "presets.json")

_DEFAULTS = {
    "backend": backend.BACKEND_OLLAMA,
    "base_url": backend.OLLAMA_DEFAULT_URL,
    "model": "",
    "system_prompt": "",
    "temperature": 0.7,
    "top_p": 0.9,
    "num_predict": -1,     # -1 = no limit (ollama default)
    "num_ctx": 4096,
    "keep_alive": "5m",
    "active_preset": "Balanced",
}

DEFAULT_PRESETS = {
    "Fast / Short": {"temperature": 0.4, "top_p": 0.9, "num_predict": 256, "num_ctx": 2048, "keep_alive": "5m"},
    "Balanced": {"temperature": 0.7, "top_p": 0.9, "num_predict": -1, "num_ctx": 4096, "keep_alive": "5m"},
    "Creative / Long": {"temperature": 1.0, "top_p": 0.95, "num_predict": -1, "num_ctx": 8192, "keep_alive": "30m"},
}


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return dict(_DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(_DEFAULTS)
        merged.update({k: v for k, v in data.items() if k in _DEFAULTS})
        return merged
    except Exception:
        return dict(_DEFAULTS)


def save_settings(settings: dict):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({k: settings.get(k, _DEFAULTS[k]) for k in _DEFAULTS}, f, indent=2)
    except Exception as e:
        print(f"[local_model_runner] Failed saving settings: {e}")


def load_history() -> list:
    """Returns a list of {"role": ..., "content": ...} dicts, oldest first."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict) and "role" in m and "content" in m]
        return []
    except Exception:
        return []


def save_history(messages: list):
    """messages: list of ChatMessage or {"role", "content"} dicts."""
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        serializable = [
            {"role": m.role, "content": m.content} if hasattr(m, "role") else m
            for m in messages
        ]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
    except Exception as e:
        print(f"[local_model_runner] Failed saving history: {e}")


def load_presets() -> dict:
    """Returns {preset_name: {temperature, top_p, num_predict, num_ctx,
    keep_alive}}. Seeds with built-in defaults on first run."""
    if not os.path.exists(PRESETS_FILE):
        return dict(DEFAULT_PRESETS)
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
        return dict(DEFAULT_PRESETS)
    except Exception:
        return dict(DEFAULT_PRESETS)


def save_presets(presets: dict):
    try:
        os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)
    except Exception as e:
        print(f"[local_model_runner] Failed saving presets: {e}")


def clear_history():
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
    except Exception as e:
        print(f"[local_model_runner] Failed clearing history: {e}")
