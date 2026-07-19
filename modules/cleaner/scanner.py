"""
scanner.py
----------
Pure scanning logic for the Cleaner module — no UI, no tkinter. Mirrors the
separation used in folder_gen (game_database.py / generator.py stay UI-free
and get driven by ui.py).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    total += dir_size(Path(entry.path))
                else:
                    total += entry.stat().st_size
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return total


@dataclass
class Category:
    key: str
    label: str
    description: str
    path: Path
    size: int = 0
    exists: bool = False
    risk: str = "safe"  # "safe" | "caution"


def default_categories() -> List[Category]:
    user = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", user / "AppData" / "Local"))
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    sysdrive = os.environ.get("SystemDrive", "C:")

    cats = [
        Category("win_temp", "Windows Temp", "System-wide temp files (Windows\\Temp)",
                  windir / "Temp", risk="safe"),
        Category("user_temp", "User Temp", "Your account's temp folder (%TEMP%)",
                  Path(tempfile.gettempdir()), risk="safe"),
        Category("prefetch", "Prefetch cache", "Windows app-launch prefetch data",
                  windir / "Prefetch", risk="caution"),
        Category("wu_download", "Windows Update leftovers", "Downloaded update files no longer needed",
                  windir / "SoftwareDistribution" / "Download", risk="safe"),
        Category("chrome_cache", "Chrome cache", "Chrome's cached site data",
                  local / "Google" / "Chrome" / "User Data" / "Default" / "Cache", risk="safe"),
        Category("edge_cache", "Edge cache", "Edge's cached site data",
                  local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache", risk="safe"),
        Category("firefox_cache", "Firefox cache", "Firefox profile cache folders",
                  local / "Mozilla" / "Firefox" / "Profiles", risk="safe"),
        Category("pip_cache", "pip cache", "Cached wheel/sdist downloads",
                  local / "pip" / "Cache", risk="safe"),
        Category("npm_cache", "npm cache", "Cached npm packages",
                  local / "npm-cache", risk="safe"),
        Category("recycle_bin", "Recycle Bin", "Files you've already deleted",
                  Path(sysdrive + "/$Recycle.Bin"), risk="caution"),
    ]
    for c in cats:
        c.exists = c.path.exists()
    return cats


def scan_sizes(categories: List[Category]) -> None:
    """Fills in .size for each existing category, in place."""
    for c in categories:
        if c.exists:
            c.size = dir_size(c.path)


def find_pycache_dirs(root: Path, max_depth: int = 6) -> List[Path]:
    """Recursively find __pycache__ dirs under root (bounded depth)."""
    found: List[Path] = []
    root_depth = len(root.parts)
    for dirpath, dirnames, _ in os.walk(root):
        depth = len(Path(dirpath).parts) - root_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        if "__pycache__" in dirnames:
            found.append(Path(dirpath) / "__pycache__")
    return found
