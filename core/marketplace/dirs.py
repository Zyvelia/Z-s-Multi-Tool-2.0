from __future__ import annotations

from pathlib import Path

from core import paths


def root() -> Path:
    p = Path(paths.data_path("marketplace"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def overlay_modules() -> Path:
    p = root() / "modules"
    p.mkdir(parents=True, exist_ok=True)
    return p


def history_dir(module_id: str) -> Path:
    p = root() / "history" / slug(module_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def publisher_root() -> Path:
    p = root() / "publisher"
    (p / "packages").mkdir(parents=True, exist_ok=True)
    return p


def publisher_index_path() -> Path:
    return publisher_root() / "index.json"


def publisher_state_path() -> Path:
    return publisher_root() / "state.json"


def installed_db_path() -> Path:
    return root() / "installed.json"


def slug(value: str) -> str:
    out = []
    prev_dash = False
    for ch in (value or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-") or "module"
