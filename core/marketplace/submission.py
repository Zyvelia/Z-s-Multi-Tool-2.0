from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core.marketplace import dirs


def load_author() -> str:
    path = dirs.author_profile_path()
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("author") or "").strip()
    except Exception:
        return ""


def save_author(author: str) -> str:
    author = (author or "").strip()
    if not author:
        raise ValueError("Author name cannot be empty.")
    dirs.author_profile_path().write_text(
        json.dumps({"author": author}, indent=2), encoding="utf-8"
    )
    return author


def _safe_name(value: str) -> str:
    return dirs.slug(value) or "module"


def create_submission(
    module_root: str | Path,
    *,
    name: str,
    author: str,
    description: str = "",
    category: str = "Utilities",
    icon: str = "📦",
    website: str = "",
    min_app_version: str = "4.0.5",
) -> Path:
    """Create a portable .zmod submission without any publishing credentials."""
    root = Path(module_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Module folder does not exist.")
    init = root / "__init__.py"
    if not init.exists():
        raise ValueError("The selected module folder must contain __init__.py.")

    author = (author or "").strip()
    name = (name or root.name).strip()
    if not author:
        raise ValueError("Author name is required.")
    if not name:
        raise ValueError("Module name is required.")

    module_id = _safe_name(name)
    out_dir = dirs.submissions_dir()
    timestamp = datetime.now(timezone.utc)
    stamp = timestamp.strftime("%Y%m%d-%H%M%S")
    dest = out_dir / f"{module_id}-{stamp}-submission.zmod"

    manifest = {
        "submission": True,
        "id": module_id,
        "name": name,
        "author": author,
        "description": description.strip(),
        "category": category.strip() or "Utilities",
        "icon": icon.strip() or "📦",
        "website": website.strip(),
        "min_app_version": min_app_version.strip() or "4.0.5",
        "submitted_at": timestamp.isoformat(),
        "relpath": module_id,
    }

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("submission.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for file in root.rglob("*"):
            if not file.is_file() or file.suffix == ".pyc" or "__pycache__" in file.parts:
                continue
            zf.write(file, f"payload/{file.relative_to(root).as_posix()}")

    return dest
