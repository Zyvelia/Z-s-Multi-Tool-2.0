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


def installed_db_path() -> Path:
    return root() / "installed.json"


def author_profile_path() -> Path:
    """Saved marketplace author profile for creating submissions."""
    return root() / "author.json"


def submissions_dir() -> Path:
    """Local outbox for module submissions created by the client."""
    p = root() / "submissions"
    p.mkdir(parents=True, exist_ok=True)
    return p


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
