"""
deleter.py
----------
Deletion logic for the Cleaner module — no UI. Given categories/paths to
remove, does the work and returns errors instead of raising, so the UI
layer can report skipped/locked files without crashing the worker thread.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import List

from .scanner import Category


def _rm_readonly(func, path, exc_info):
    """shutil.rmtree onerror hook: clear the read-only bit and retry once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def clear_dir_contents(path: Path) -> List[str]:
    """Delete the *contents* of a folder without removing the folder itself.

    Safer for things like %TEMP% or Windows\\Temp that need to keep existing
    as a folder even after being emptied.
    """
    errors: List[str] = []
    if not path.exists():
        return errors

    try:
        entries = list(os.scandir(path))
    except PermissionError:
        errors.append(f"{path}: access denied — click 'Restart as Administrator' and try again")
        return errors
    except OSError as e:
        errors.append(f"{path}: {e}")
        return errors

    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, onerror=_rm_readonly)
            else:
                os.chmod(entry.path, stat.S_IWRITE)
                os.remove(entry.path)
        except Exception as e:
            errors.append(f"{entry.path}: {e}")
    return errors


def delete_categories(categories: List[Category]) -> List[str]:
    errors: List[str] = []
    for c in categories:
        errors.extend(clear_dir_contents(c.path))
    return errors


def delete_pycache_dirs(dirs: List[Path]) -> List[str]:
    errors: List[str] = []
    for d in dirs:
        try:
            shutil.rmtree(d, onerror=_rm_readonly)
        except Exception as e:
            errors.append(f"{d}: {e}")
    return errors
