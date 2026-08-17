# modules/AI/local_model_runner/storage.py
#
# Remembers backend/base URL/model/system prompt across restarts —
# same paths.data_path() convention as every other module.

import json
import os

from core import paths
from . import backend

SETTINGS_FILE = paths.data_path("local_model_runner", "settings.json")

_DEFAULTS = {
    "backend": backend.BACKEND_OLLAMA,
    "base_url": backend.OLLAMA_DEFAULT_URL,
    "model": "",
    "system_prompt": "",
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
