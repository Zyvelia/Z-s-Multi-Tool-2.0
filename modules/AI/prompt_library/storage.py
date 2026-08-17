# modules/AI/prompt_library/storage.py
#
# Persistence for saved prompts. Follows the same paths.data_path()
# convention every other module uses (see core/paths.py) — lives at
# %APPDATA%\ZsMultiTool\prompt_library\prompts.json.

import json
import os
import re
import time
import uuid

from core import paths

STORE_FILE = paths.data_path("prompt_library", "prompts.json")

DEFAULT_CATEGORY = "General"

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[prompt_library] Failed saving {path}: {e}")


def extract_variables(body: str):
    """Returns the unique {{variable}} names in a prompt body, in the
    order they first appear."""
    seen = []
    for match in _VAR_PATTERN.finditer(body or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def fill_variables(body: str, values: dict) -> str:
    def _sub(match):
        name = match.group(1)
        return values.get(name, match.group(0))
    return _VAR_PATTERN.sub(_sub, body or "")


def load_all():
    prompts = _load_json(STORE_FILE, [])
    # newest-first by default (falls back gracefully if a field is missing
    # on prompts saved before some future field is added)
    prompts.sort(key=lambda p: p.get("updated_at", 0), reverse=True)
    return prompts


def get_categories(prompts=None):
    prompts = prompts if prompts is not None else load_all()
    cats = {p.get("category") or DEFAULT_CATEGORY for p in prompts}
    cats.add(DEFAULT_CATEGORY)
    return sorted(cats)


def save_prompt(prompt: dict) -> dict:
    """Upsert by id. If prompt has no id (or an id not already in the
    store), it's created as new. Returns the saved record."""
    prompts = _load_json(STORE_FILE, [])
    now = time.time()

    prompt_id = prompt.get("id")
    existing = next((p for p in prompts if p.get("id") == prompt_id), None) if prompt_id else None

    record = {
        "id": prompt_id or uuid.uuid4().hex,
        "title": (prompt.get("title") or "Untitled Prompt").strip(),
        "category": (prompt.get("category") or DEFAULT_CATEGORY).strip() or DEFAULT_CATEGORY,
        "tags": [t.strip() for t in prompt.get("tags", []) if t.strip()],
        "body": prompt.get("body", ""),
        "favorite": bool(prompt.get("favorite", False)),
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "use_count": existing.get("use_count", 0) if existing else 0,
        "last_used_at": existing.get("last_used_at") if existing else None,
    }

    if existing:
        prompts = [record if p.get("id") == record["id"] else p for p in prompts]
    else:
        prompts.append(record)

    _save_json(STORE_FILE, prompts)
    return record


def delete_prompt(prompt_id: str):
    prompts = _load_json(STORE_FILE, [])
    prompts = [p for p in prompts if p.get("id") != prompt_id]
    _save_json(STORE_FILE, prompts)


def toggle_favorite(prompt_id: str):
    prompts = _load_json(STORE_FILE, [])
    for p in prompts:
        if p.get("id") == prompt_id:
            p["favorite"] = not p.get("favorite", False)
            break
    _save_json(STORE_FILE, prompts)


def mark_used(prompt_id: str):
    prompts = _load_json(STORE_FILE, [])
    for p in prompts:
        if p.get("id") == prompt_id:
            p["use_count"] = p.get("use_count", 0) + 1
            p["last_used_at"] = time.time()
            break
    _save_json(STORE_FILE, prompts)
