# core/paths.py
#
# Central place that decides WHERE user data lives, so it survives:
#   - running as a onefile exe (no writable folder next to the exe)
#   - reinstalling / rebuilding the exe
#   - moving the project folder around during development
#
# User data -> %APPDATA%\ZsMultiTool\...  (a "real Windows app" location)
# Bundled read-only defaults (e.g. template JSON shipped with a module) are
# read via resource_path(), which understands PyInstaller's sys._MEIPASS.

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "ZsMultiTool"


def get_app_data_dir() -> Path:
    """
    Per-user writable root folder for this app.
    Windows -> %APPDATA%\\ZsMultiTool
    macOS/Linux -> ~/.local/share/ZsMultiTool (fallback, in case this ever
    runs somewhere other than Windows)
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")

    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_path(*parts) -> str:
    """
    Build a path inside the per-user AppData folder, e.g.
        data_path("gaming_hub", "save_paths.json")
    -> %APPDATA%\\ZsMultiTool\\gaming_hub\\save_paths.json
    Creates any missing parent folders.
    """
    full = get_app_data_dir().joinpath(*parts)
    full.parent.mkdir(parents=True, exist_ok=True)
    return str(full)


def resource_path(*parts) -> str:
    """
    Path to a bundled, read-only resource — works both running from source
    and running as a frozen PyInstaller exe (where bundled files live under
    sys._MEIPASS instead of next to the exe).
    """
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent  # project root

    return str(base.joinpath(*parts))


def migrate_legacy_path(new_path: str, legacy_absolute_path: str) -> str:
    """
    Same as migrate_legacy_file, but for a legacy location given as a full
    absolute path (e.g. an old ~/.some_folder/data.json) rather than a path
    relative to the project/exe root.
    """
    if os.path.exists(new_path):
        return new_path

    if os.path.exists(legacy_absolute_path):
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(legacy_absolute_path, new_path)
            print(f"[paths] Migrated {legacy_absolute_path} -> {new_path}")
        except Exception as e:
            print(f"[paths] Migration failed for {legacy_absolute_path}: {e}")

    return new_path


def migrate_legacy_file(new_path: str, *legacy_relparts) -> str:
    """
    One-time migration: if the new AppData path doesn't have a file yet,
    but an old file exists at a path relative to the project/exe root
    (i.e. wherever this app used to store it), move it into AppData so
    existing user data (vaults, settings, hunt data, etc.) isn't lost.

    Safe to call every startup — it only acts once, the first time the new
    path is missing and an old file is found.
    """
    if os.path.exists(new_path):
        return new_path

    legacy_path = resource_path(*legacy_relparts) if getattr(sys, "frozen", False) else \
        os.path.join(os.getcwd(), *legacy_relparts)

    if os.path.exists(legacy_path):
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copy2(legacy_path, new_path)
            print(f"[paths] Migrated {legacy_path} -> {new_path}")
        except Exception as e:
            print(f"[paths] Migration failed for {legacy_path}: {e}")

    return new_path


def seed_from_resource(new_path: str, *resource_relparts) -> str:
    """
    If the AppData file doesn't exist yet, seed it from a bundled default
    (e.g. a template games.json shipped with the app), so first-run users
    still get the app's built-in defaults instead of an empty file.
    """
    if not os.path.exists(new_path):
        src = resource_path(*resource_relparts)
        if os.path.exists(src):
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.copy2(src, new_path)
                print(f"[paths] Seeded {new_path} from {src}")
            except Exception as e:
                print(f"[paths] Seed failed for {new_path}: {e}")

    return new_path
