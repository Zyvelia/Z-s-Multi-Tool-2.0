"""Collect Tcl/Tk script data for PyInstaller.

Python 3.14+ ships Tcl/Tk 9.0 inside libtcl*.zip / libtk*.zip and exposes
virtual //zipfs:/ paths. PyInstaller's stock hook cannot copy those, so we
extract the archives at build time into _tcl_data / _tk_data (the names its
runtime hook expects).
"""
from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path

TCL_ROOTNAME = "_tcl_data"
TK_ROOTNAME = "_tk_data"


def _staging_root() -> Path:
    return Path(__file__).resolve().parent.parent / "build" / "_tcl_tk_staging"


def _extract_zip_prefix(zippath: Path, prefix: str, dest_root: Path) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zippath) as zf:
        for name in zf.namelist():
            if not name.startswith(prefix):
                continue
            rel = name[len(prefix) :]
            if not rel or rel.endswith("/"):
                continue
            out = dest_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(name))


def _walk_data_files(staging: Path) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for dirpath, _, filenames in os.walk(staging):
        for filename in filenames:
            src = Path(dirpath) / filename
            rel = src.relative_to(staging).as_posix()
            out.append((rel, str(src), "DATA"))
    return out


def collect_tcl_tk_datas(*, clean: bool = True) -> list[tuple[str, str, str]]:
    """Return PyInstaller DATA tuples for Tcl/Tk script directories."""
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info

    if tcltk_info.data_files:
        return list(tcltk_info.data_files)

    tcl_dir = Path(sys.base_prefix) / "tcl"
    tcl_zip = next(iter(sorted(tcl_dir.glob("libtcl*.zip"))), None)
    tk_zip = next(iter(sorted(tcl_dir.glob("libtk*.zip"))), None)
    if not tcl_zip or not tk_zip:
        return []

    staging = _staging_root()
    if clean and staging.exists():
        shutil.rmtree(staging)

    tcl_dest = staging / TCL_ROOTNAME
    tk_dest = staging / TK_ROOTNAME
    _extract_zip_prefix(tcl_zip, "tcl_library/", tcl_dest)
    _extract_zip_prefix(tk_zip, "tk_library/", tk_dest)

    # Non-zipped extras (pkgIndex.tcl, etc.) — skip demos to save size.
    tk_extra = tcl_dir / f"tk{tcltk_info.tk_version[0]}.{tcltk_info.tk_version[1]}"
    if tk_extra.is_dir():
        for item in tk_extra.iterdir():
            if item.name == "demos":
                continue
            target = tk_dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)

    if not tcl_dest.is_dir() or not (tcl_dest / "init.tcl").is_file():
        return []
    if not tk_dest.is_dir():
        return []

    return _walk_data_files(staging)
