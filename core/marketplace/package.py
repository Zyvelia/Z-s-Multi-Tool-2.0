from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core.marketplace import dirs, versions

MANIFEST_NAME = "manifest.json"
PAYLOAD_DIR = "payload"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(module_id: str, meta: dict, payload_root: Path, rel_under_modules: str, dest_zmod: Path, build: int) -> dict:
    now = datetime.now(timezone.utc)
    manifest = {
        "id": dirs.slug(module_id),
        "name": meta.get("name") or module_id,
        "category": meta.get("category") or "Utilities",
        "desc": meta.get("desc") or "",
        "icon": meta.get("icon") or "📦",
        "qt_page": meta.get("qt_page") or "",
        "publisher": meta.get("publisher") or "official",
        "build": int(build),
        "label": versions.label_for(build, now),
        "published_at": now.isoformat(),
        "min_app_version": meta.get("min_app_version") or "4.0.5",
        "relpath": rel_under_modules.replace("\\", "/"),
        "signature": None,
    }
    dest_zmod.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zmod, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        payload_root = Path(payload_root)
        for file in payload_root.rglob("*"):
            if not file.is_file():
                continue
            if file.suffix == ".pyc" or "__pycache__" in file.parts:
                continue
            rel = file.relative_to(payload_root).as_posix()
            zf.write(file, f"{PAYLOAD_DIR}/{rel}")
    manifest["sha256"] = sha256_file(dest_zmod)
    return manifest


def unpack(zmod: Path, overlay_root: Path, expected_sha: str | None = None) -> dict:
    if expected_sha:
        got = sha256_file(zmod)
        if got.lower() != expected_sha.lower():
            raise ValueError("Package hash does not match the marketplace listing.")
    with zipfile.ZipFile(zmod, "r") as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        rel = (manifest.get("relpath") or "").strip("/").replace("\\", "/")
        if not rel or ".." in rel.split("/"):
            raise ValueError("Package path is invalid.")
        target = overlay_root.joinpath(*rel.split("/"))
        if target.exists():
            shutil.rmtree(target)
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or not name.startswith(PAYLOAD_DIR + "/"):
                continue
            inner = name[len(PAYLOAD_DIR) + 1 :]
            parts = Path(inner).parts
            if not parts or ".." in parts:
                continue
            dest = target.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
    return manifest
