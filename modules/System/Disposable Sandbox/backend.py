"""
Disposable VMware session.

We never boot the base VM. A linked clone is created from a snapshot,
the drop folder is shared read-only, and the clone is deleted when that
VM powers off. The base disk is not written.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import json
from pathlib import Path

from core import paths

SNAPSHOT_DEFAULT = "zs-clean"
CLONE_NAME = "Zs Disposable"
_INVENTORY = Path(os.environ.get("APPDATA", "")) / "VMware" / "inventory.vmls"
_VMRUN_CANDIDATES = [
    Path(r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe"),
    Path(r"C:\Program Files\VMware\VMware Workstation\vmrun.exe"),
    Path(r"C:\Program Files (x86)\VMware\VMware Player\vmrun.exe"),
    Path(r"C:\Program Files\VMware\VMware Player\vmrun.exe"),
]
_GUI_CANDIDATES = [
    Path(r"C:\Program Files (x86)\VMware\VMware Workstation\vmware.exe"),
    Path(r"C:\Program Files\VMware\VMware Workstation\vmware.exe"),
    Path(r"C:\Program Files (x86)\VMware\VMware Workstation\vmplayer.exe"),
    Path(r"C:\Program Files\VMware\VMware Player\vmplayer.exe"),
]


class VmError(Exception):
    pass


def drop_dir() -> Path:
    path = Path(paths.data_path("sandbox", "drop"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir() -> Path:
    path = Path(paths.data_path("sandbox", "session"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_vmx() -> Path:
    return session_dir() / f"{CLONE_NAME}.vmx"


def _config_path() -> Path:
    return Path(paths.data_path("sandbox", "config.json"))


def load_config() -> dict:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("base_vmx", "")
            data.setdefault("snapshot", SNAPSHOT_DEFAULT)
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"base_vmx": "", "snapshot": SNAPSHOT_DEFAULT}


def save_config(base_vmx: str, snapshot: str) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"base_vmx": base_vmx.strip(), "snapshot": (snapshot or SNAPSHOT_DEFAULT).strip()},
            indent=2,
        ),
        encoding="utf-8",
    )


def find_vmrun() -> Path | None:
    which = shutil.which("vmrun")
    if which:
        return Path(which)
    for path in _VMRUN_CANDIDATES:
        if path.is_file():
            return path
    return None


def find_gui() -> Path | None:
    for path in _GUI_CANDIDATES:
        if path.is_file():
            return path
    return None


def host_type() -> str:
    gui = find_gui()
    if gui and gui.name.lower() == "vmplayer.exe":
        return "player"
    return "ws"


def inventory_vms() -> list[dict]:
    """VMs from Workstation's inventory, plus any saved base path."""
    found: dict[str, dict] = {}
    if _INVENTORY.is_file():
        groups: dict[str, dict] = {}
        try:
            text = _INVENTORY.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for raw in text.splitlines():
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"')
            m = re.match(r"(vmlist\d+)\.(config|DisplayName)$", key, re.I)
            if not m:
                continue
            prefix, field = m.group(1), m.group(2).lower()
            groups.setdefault(prefix, {})
            if field == "config":
                groups[prefix]["vmx"] = value
            else:
                groups[prefix]["name"] = value
        for item in groups.values():
            vmx = (item.get("vmx") or "").strip()
            if vmx and Path(vmx).is_file():
                found[str(Path(vmx))] = {
                    "name": item.get("name") or Path(vmx).stem,
                    "vmx": vmx,
                }
    cfg = load_config().get("base_vmx") or ""
    if cfg and Path(cfg).is_file() and cfg not in found:
        found[cfg] = {"name": Path(cfg).stem, "vmx": cfg}
    return sorted(found.values(), key=lambda v: v["name"].lower())


def is_encrypted(vmx: str | Path) -> bool:
    try:
        text = Path(vmx).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(re.search(r"vmx\.encryptionType\s*=\s*\"(partial|full)\"", text, re.I))


def running_vmx_paths() -> list[str]:
    try:
        out = _vmrun(["list"], password="")
    except VmError:
        return []
    paths_out = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line:
            paths_out.append(line)
    return paths_out


def session_running() -> bool:
    target = str(session_vmx())
    for item in running_vmx_paths():
        if Path(item).resolve() == Path(target).resolve():
            return True
    return False


def status() -> dict:
    vmrun = find_vmrun()
    cfg = load_config()
    base = cfg.get("base_vmx") or ""
    if not vmrun:
        return {
            "available": False,
            "detail": (
                "VMware Workstation / Player was not found. Install Workstation "
                "(vmrun.exe) and pick a base VM."
            ),
            "vmrun": "",
            "base_vmx": base,
            "encrypted": False,
            "session": False,
        }
    detail = f"VMware ready · {vmrun}"
    if base:
        detail += f" · base: {Path(base).stem}"
        if not Path(base).is_file():
            detail += " (missing)"
        elif is_encrypted(base):
            detail += " (encrypted — password needed to snapshot / clone)"
    if session_running():
        detail += " · disposable VM is running"
    elif session_vmx().is_file():
        detail += " · leftover session on disk (will be removed on next launch or Discard)"
    return {
        "available": True,
        "detail": detail,
        "vmrun": str(vmrun),
        "base_vmx": base,
        "encrypted": bool(base and Path(base).is_file() and is_encrypted(base)),
        "session": session_running(),
    }


def copy_into_drop(source: str) -> Path:
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(source)
    dest = drop_dir() / src.name
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return dest


def list_snapshots(vmx: str, password: str = "") -> list[str]:
    out = _vmrun(["listSnapshots", vmx], password=password)
    names = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("total snapshot"):
            continue
        names.append(line)
    return names


def create_snapshot(vmx: str, name: str, password: str = "") -> None:
    name = (name or SNAPSHOT_DEFAULT).strip()
    if not Path(vmx).is_file():
        raise VmError("Pick a base .vmx first.")
    _vmrun(["snapshot", vmx, name], password=password)


def launch(
    *,
    base_vmx: str,
    snapshot: str,
    password: str = "",
    networking: bool = False,
    clipboard: bool = True,
) -> Path:
    if not find_vmrun():
        raise VmError("vmrun.exe was not found.")
    if not base_vmx or not Path(base_vmx).is_file():
        raise VmError("Pick a base VMware VM (.vmx).")
    if Path(base_vmx).resolve().is_relative_to(session_dir().resolve()):
        raise VmError("The base VM cannot be the disposable session itself.")
    snapshot = (snapshot or SNAPSHOT_DEFAULT).strip()
    save_config(base_vmx, snapshot)

    if session_running():
        raise VmError("A disposable session is already running. Close that VM first.")
    discard_session(password=password, missing_ok=True)

    dest = session_vmx()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _vmrun(
        [
            "clone",
            base_vmx,
            str(dest),
            "linked",
            f"-snapshot={snapshot}",
            f"-cloneName={CLONE_NAME}",
        ],
        password=password,
    )
    if not dest.is_file():
        raise VmError("Clone finished but the session .vmx was not created.")

    _patch_clone_vmx(dest, networking=networking, clipboard=clipboard)
    _vmrun(["start", str(dest), "gui"], password=password)
    _try_share_drop(dest, password=password)
    return dest


def discard_session(*, password: str = "", missing_ok: bool = False) -> None:
    vmx = session_vmx()
    if session_running():
        try:
            _vmrun(["stop", str(vmx), "hard"], password=password)
        except VmError:
            pass
    if vmx.is_file():
        _assert_session_vmx(vmx)
        try:
            _vmrun(["deleteVM", str(vmx)], password=password)
        except VmError:
            pass
    folder = session_dir()
    if folder.is_dir():
        _assert_under_sandbox(folder)
        try:
            shutil.rmtree(folder)
        except OSError:
            if not missing_ok:
                raise
    session_dir()


def _try_share_drop(vmx: Path, password: str = "") -> None:
    host = str(drop_dir())
    try:
        _vmrun(["enableSharedFolders", str(vmx)], password=password)
        _vmrun(["addSharedFolder", str(vmx), "drop", host], password=password)
        _vmrun(["setSharedFolderState", str(vmx), "drop", host, "readonly"], password=password)
    except VmError:
        pass


def _patch_clone_vmx(vmx: Path, *, networking: bool, clipboard: bool) -> None:
    try:
        text = vmx.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    updates = {
        "displayName": CLONE_NAME,
        "isolation.tools.copy.disable": "FALSE" if clipboard else "TRUE",
        "isolation.tools.paste.disable": "FALSE" if clipboard else "TRUE",
        "isolation.tools.dnd.disable": "FALSE" if clipboard else "TRUE",
        "isolation.tools.hgfs.disable": "FALSE",
        "sharedFolder.maxNum": "1",
        "sharedFolder0.present": "TRUE",
        "sharedFolder0.enabled": "TRUE",
        "sharedFolder0.readAccess": "TRUE",
        "sharedFolder0.writeAccess": "FALSE",
        "sharedFolder0.hostPath": str(drop_dir()),
        "sharedFolder0.guestName": "drop",
        "sharedFolder0.expiration": "never",
    }
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip().strip('"')
        if re.match(r"ethernet\d+\.startConnected$", key, re.I):
            out.append(f'{key} = "{"TRUE" if networking else "FALSE"}"')
            seen.add(key.lower())
            continue
        if key in updates:
            out.append(f'{key} = "{_vmx_escape(updates[key])}"')
            seen.add(key.lower())
            continue
        out.append(line)
    for key, value in updates.items():
        if key.lower() not in seen:
            out.append(f'{key} = "{_vmx_escape(value)}"')
    if not networking and "ethernet0.startConnected".lower() not in seen:
        out.append('ethernet0.startConnected = "FALSE"')
    try:
        vmx.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        pass


def _vmx_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _assert_session_vmx(vmx: Path) -> None:
    resolved = vmx.resolve()
    if resolved != session_vmx().resolve() and session_dir().resolve() not in resolved.parents:
        raise VmError("Refusing to delete a VM outside the sandbox session folder.")


def _assert_under_sandbox(folder: Path) -> None:
    root = Path(paths.data_path("sandbox")).resolve()
    resolved = folder.resolve()
    if resolved != root and root not in resolved.parents and resolved != session_dir().resolve():
        raise VmError("Refusing to delete files outside the sandbox data folder.")


def _vmrun(args: list[str], *, password: str = "") -> str:
    exe = find_vmrun()
    if exe is None:
        raise VmError("vmrun.exe was not found.")
    cmd = [str(exe), "-T", host_type()]
    if password:
        cmd.extend(["-vp", password])
    cmd.extend(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired as e:
        raise VmError("VMware timed out. Snapshot / clone of a large VM can take several minutes.") from e
    except OSError as e:
        raise VmError(str(e)) from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "vmrun failed").strip()
        if password:
            err = err.replace(password, "••••")
        if "password is required" in err.lower():
            raise VmError("This VM is encrypted. Enter the VMware encryption password (it is not saved).")
        raise VmError(err)
    return proc.stdout or ""
