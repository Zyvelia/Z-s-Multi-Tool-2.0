from __future__ import annotations

import os
from pathlib import Path


def list_drives() -> list[str]:
    drives = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.isdir(root):
            drives.append(root)
    return drives or [str(Path.home())]


def folder_children(root: str, *, max_entries: int = 40) -> list[dict]:
    path = Path(root)
    rows = []
    try:
        children = list(path.iterdir())
    except OSError as e:
        return [{"name": str(e), "path": root, "bytes": 0, "is_dir": False}]
    for child in children:
        try:
            if child.is_symlink():
                continue
            if child.is_file():
                size = child.stat().st_size
            elif child.is_dir():
                size = _dir_size(child)
            else:
                continue
        except OSError:
            continue
        rows.append({"name": child.name, "path": str(child), "bytes": size, "is_dir": child.is_dir()})
    rows.sort(key=lambda r: r["bytes"], reverse=True)
    return rows[:max_entries]


def _dir_size(folder: Path, *, cap_files: int = 80_000) -> int:
    total = 0
    n = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "$Recycle.Bin", "System Volume Information"}]
            for name in filenames:
                n += 1
                if n > cap_files:
                    return total
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
