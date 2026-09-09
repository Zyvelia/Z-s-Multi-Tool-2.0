"""
ADB phone mirror helpers. GUI-free.

Primary path is `adb exec-out screencap` plus `input tap/swipe/keyevent`
so the screen lives inside this app and mouse clicks are real touches.
scrcpy is optional HD if it is on PATH.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

ADB_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
    Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe",
    Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb.exe",
    Path(r"C:\Android\platform-tools\adb.exe"),
    Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"),
    Path(r"C:\Program Files\BlueStacks_nxt\Bluestacks_ext\HD-Adb.exe"),
    Path(r"C:\Program Files\BlueStacks_msi5\HD-Adb.exe"),
    Path(r"C:\Program Files\BlueStacks\HD-Adb.exe"),
    Path(r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe"),
    Path(r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\adb.exe"),
    Path(r"C:\Program Files\Netease\MuMuPlayer\shell\adb.exe"),
    Path(r"C:\Program Files\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe"),
]
_BS_PROCESS_NAMES = {
    "hd-player.exe",
    "bluestacks.exe",
}
_BS_FALLBACK_PORTS = (5555, 5556, 5565, 5575, 5585, 5595, 5605, 5615, 5625)

# MuMu Player (NetEase): classic single-instance build uses a fixed ADB port,
# the MuMu Player 12 multi-instance manager assigns 127.0.0.1:16384 to instance
# 0 and steps by 32 for each further instance (16384, 16416, 16448, ...).
_MUMU_PROCESS_NAMES = {
    "mumuplayer.exe",
    "mumumultiplayer.exe",
    "mumuvmmheadless.exe",
    "mumunxdevice.exe",
    "nemuheadless.exe",
    "nemulauncher.exe",
}
_MUMU_LEGACY_PORT = 7555
_MUMU_BASE_PORT = 16384
_MUMU_PORT_STEP = 32
_MUMU_MAX_INSTANCES = 8
_MUMU_FALLBACK_PORTS = (_MUMU_LEGACY_PORT,) + tuple(
    _MUMU_BASE_PORT + _MUMU_PORT_STEP * i for i in range(_MUMU_MAX_INSTANCES)
)
_MUMU_INSTALL_MARKERS = (
    r"C:\Program Files\Netease\MuMuPlayer-12.0",
    r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0",
    r"C:\Program Files\Netease\MuMuPlayer",
    r"C:\Program Files\MuMuVMMVbox",
    r"C:\Program Files\MuMu",
)
SCRCPY_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "scrcpy.exe",
    Path(r"C:\Program Files\scrcpy\scrcpy.exe"),
    Path(os.environ.get("USERPROFILE", "")) / "scoop" / "shims" / "scrcpy.exe",
]


class AdbError(Exception):
    pass


# Serializes every adb call and the whole device-scan sequence. With several
# Phone Screen docks open at once, each does its own background refresh —
# without this, concurrent `adb` subprocess spawns and concurrent writes to
# _SCAN_LOG below could race each other and destabilize things.
_ADB_LOCK = threading.RLock()

_SCAN_LOG: list[str] = []


def _log(msg: str) -> None:
    _SCAN_LOG.append(msg)


def get_scan_log() -> str:
    """Human-readable trace of the most recent device scan, for the Diagnostics button."""
    return "\n".join(_SCAN_LOG) if _SCAN_LOG else "(no scan run yet)"


@dataclass
class Device:
    serial: str
    state: str
    model: str = ""
    product: str = ""

    @property
    def label(self) -> str:
        name = self.model or self.product or self.serial
        extra = f" · {self.serial}" if name != self.serial else ""
        return f"{name}{extra} [{self.state}]"


def find_adb() -> Path | None:
    which = shutil.which("adb")
    if which:
        _log(f"adb: found on PATH -> {which}")
        return Path(which)
    for path in ADB_CANDIDATES:
        if path and path.is_file():
            _log(f"adb: found candidate -> {path}")
            return path
    _log(f"adb: NOT found on PATH or in any of {len(ADB_CANDIDATES)} candidate paths")
    return None


def _programdata() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))


def _bluestacks_conf_paths() -> list[Path]:
    root = _programdata()
    return [
        root / "BlueStacks_nxt" / "bluestacks.conf",
        root / "BlueStacks_msi5" / "bluestacks.conf",
        root / "BlueStacks_msi2" / "bluestacks.conf",
        root / "BlueStacks" / "bluestacks.conf",
    ]


def bluestacks_running() -> bool:
    try:
        import psutil

        names = []
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            names.append(name)
            if name in _BS_PROCESS_NAMES:
                _log(f"BlueStacks: process match -> {name}")
                return True
        _log(f"BlueStacks: no process match among {len(names)} running processes")
    except Exception as e:
        _log(f"BlueStacks: process scan failed ({e.__class__.__name__}: {e}) — "
             "is psutil installed? (pip install psutil)")
    return False


def bluestacks_installed() -> bool:
    if any(path.is_file() for path in _bluestacks_conf_paths()):
        return True
    return any(
        Path(p).is_file()
        for p in (
            r"C:\Program Files\BlueStacks_nxt\HD-Player.exe",
            r"C:\Program Files\BlueStacks_msi5\HD-Player.exe",
            r"C:\Program Files\BlueStacks\Bluestacks.exe",
        )
    )


def mumu_running() -> bool:
    try:
        import psutil

        names = []
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            names.append(name)
            if name in _MUMU_PROCESS_NAMES:
                _log(f"MuMu: process match -> {name}")
                return True
        _log(f"MuMu: no process match among {len(names)} running processes")
    except Exception as e:
        _log(f"MuMu: process scan failed ({e.__class__.__name__}: {e}) — "
             "is psutil installed? (pip install psutil)")
    return False


def mumu_installed() -> bool:
    hit = next((p for p in _MUMU_INSTALL_MARKERS if Path(p).is_dir()), None)
    if hit:
        _log(f"MuMu: install marker found -> {hit}")
        return True
    _log("MuMu: no install marker directory found")
    return False


def emulator_running() -> bool:
    return bluestacks_running() or mumu_running()


def emulator_installed() -> bool:
    return bluestacks_installed() or mumu_installed()


@dataclass
class _EmulatorPort:
    port: int
    label: str


def _parse_bluestacks_ports() -> list[_EmulatorPort]:
    """Live ADB ports from BlueStacks conf (status.adb_port wins — it changes every launch)."""
    by_instance: dict[str, dict[str, int | None]] = {}
    for conf in _bluestacks_conf_paths():
        if not conf.is_file():
            continue
        try:
            text = conf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(
            r'bst\.instance\.([A-Za-z0-9_]+)\.(status\.)?adb_port=["\']?(\d+)',
            text,
        ):
            inst, is_status, port = match.group(1), bool(match.group(2)), int(match.group(3))
            rec = by_instance.setdefault(inst, {"port": None, "status": None})
            if is_status:
                rec["status"] = port
            else:
                rec["port"] = port
    found: list[_EmulatorPort] = []
    seen: set[int] = set()
    for inst, rec in by_instance.items():
        port = rec["status"] or rec["port"]
        if not port or port in seen:
            continue
        seen.add(port)
        found.append(_EmulatorPort(port, f"BlueStacks {inst}"))
    return found


def _port_open(port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def emulator_status_note(*, device_count: int = 0) -> str:
    bs_running = bluestacks_running()
    mm_running = mumu_running()
    if (bs_running or mm_running) and device_count == 0:
        which = "BlueStacks and MuMu Player" if bs_running and mm_running else (
            "BlueStacks" if bs_running else "MuMu Player"
        )
        return (
            f"{which} is running but not on ADB. Enable Android Debug Bridge in "
            f"{which} settings (BlueStacks: Settings → Advanced · MuMu: Settings → Other), "
            "then Refresh."
        )
    if emulator_installed() and not (bs_running or mm_running) and device_count == 0:
        return "Start a BlueStacks or MuMu Player instance, then Refresh — it will connect to the emulator ADB port."
    if bs_running or mm_running:
        which = "BlueStacks and MuMu Player" if bs_running and mm_running else (
            "BlueStacks" if bs_running else "MuMu Player"
        )
        return f"{which} instance(s) included below."
    return ""


def discover_local_emulators() -> list[str]:
    """adb connect to BlueStacks/MuMu localhost ports so they appear in `adb devices`."""
    mapped = _parse_bluestacks_ports()
    if mapped:
        _log(f"BlueStacks conf: found {len(mapped)} instance port(s) -> "
             + ", ".join(f"{m.label}:{m.port}" for m in mapped))
    else:
        _log("BlueStacks conf: no bluestacks.conf found/parsed under ProgramData")

    ports = {item.port: item.label for item in mapped}
    bs_run, bs_inst = bluestacks_running(), bluestacks_installed()
    if bs_run or mapped or bs_inst:
        for extra in _BS_FALLBACK_PORTS:
            ports.setdefault(extra, "BlueStacks")
    mm_run, mm_inst = mumu_running(), mumu_installed()
    if mm_run or mm_inst:
        for extra in _MUMU_FALLBACK_PORTS:
            ports.setdefault(extra, "MuMu Player")

    if not ports:
        _log("Port scan: skipped — no BlueStacks/MuMu process running and no install found, "
             "so no ports were even attempted. Start the emulator first, or check the install "
             "path markers in the code match your setup.")
        return []

    _log(f"Port scan: probing {len(ports)} candidate port(s) on 127.0.0.1 -> "
         + ", ".join(f"{label}:{port}" for port, label in ports.items()))
    notes = []
    for port, label in ports.items():
        if not _port_open(port):
            _log(f"  {label}:{port} -> closed/unreachable")
            continue
        _log(f"  {label}:{port} -> open, running `adb connect`")
        try:
            out = connect_tcp(f"127.0.0.1:{port}", timeout=6)
            _log(f"    adb connect result: {out!r}")
            if out:
                notes.append(f"{label}: {out}")
        except AdbError as e:
            _log(f"    adb connect FAILED: {e}")
            continue
    return notes


def find_scrcpy() -> Path | None:
    which = shutil.which("scrcpy")
    if which:
        return Path(which)
    for path in SCRCPY_CANDIDATES:
        if path and path.is_file():
            return path
    return None


def _adb(*args: str, timeout: float = 20.0) -> bytes:
    exe = find_adb()
    if exe is None:
        raise AdbError(
            "adb.exe was not found. Install Android platform-tools "
            "(or the Android SDK) and try again."
        )
    try:
        with _ADB_LOCK:
            proc = subprocess.run(
                [str(exe), *args],
                capture_output=True,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as e:
        raise AdbError("adb timed out.") from e
    except OSError as e:
        raise AdbError(str(e)) from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise AdbError(err or f"adb {' '.join(args)} failed")
    return proc.stdout


def start_server() -> None:
    exe = find_adb()
    if exe is None:
        raise AdbError("adb.exe was not found.")
    subprocess.run([str(exe), "start-server"], capture_output=True, timeout=20)


def list_devices() -> list[Device]:
  with _ADB_LOCK:
    _SCAN_LOG.clear()
    _log(f"--- scan started ---")
    start_server()
    discovered = discover_local_emulators()
    if discovered:
        _log(f"Auto-connected: {'; '.join(discovered)}")
    else:
        _log("Auto-connected: nothing")
    raw = _adb("devices", "-l").decode("utf-8", errors="replace")
    _log(f"`adb devices -l` raw output:\n{raw.strip() or '(empty)'}")
    labels = {item.port: item.label for item in _parse_bluestacks_ports()}
    devices = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        model = ""
        product = ""
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token.split(":", 1)[1].replace("_", " ")
            elif token.startswith("product:"):
                product = token.split(":", 1)[1]
        if serial.startswith("127.0.0.1:") or serial.startswith("localhost:"):
            try:
                port = int(serial.rsplit(":", 1)[1])
            except ValueError:
                port = 0
            pretty = labels.get(port)
            if pretty:
                model = pretty
            elif port == _MUMU_LEGACY_PORT or port in _MUMU_FALLBACK_PORTS:
                model = "MuMu Player"
            elif not model or model.lower() in ("sdk_gphone64_x86_64", "google sdk", "unknown"):
                model = "BlueStacks"
        devices.append(Device(serial=serial, state=state, model=model, product=product))
    _log(f"--- scan finished: {len(devices)} device(s) parsed ---")
    return devices


def connect_tcp(address: str, timeout: float = 15.0) -> str:
    address = address.strip()
    if ":" not in address:
        address = address + ":5555"
    out = _adb("connect", address, timeout=timeout).decode("utf-8", errors="replace")
    return out.strip()


def disconnect_tcp(address: str) -> str:
    out = _adb("disconnect", address.strip(), timeout=10).decode("utf-8", errors="replace")
    return out.strip()


def wm_size(serial: str) -> tuple[int, int]:
    raw = _adb("-s", serial, "shell", "wm", "size").decode("utf-8", errors="replace")
    match = re.search(r"(\d+)\s*x\s*(\d+)", raw)
    if not match:
        raise AdbError(f"Could not read screen size: {raw.strip()}")
    return int(match.group(1)), int(match.group(2))


def screencap(serial: str) -> bytes:
    data = _adb("-s", serial, "exec-out", "screencap", "-p", timeout=12)
    if data[:4] == b"\x89PNG":
        return data
    repaired = data.replace(b"\r\n", b"\n")
    if repaired[:4] == b"\x89PNG":
        return repaired
    raise AdbError("screencap did not return a PNG. Unlock the phone and allow USB debugging.")


def tap(serial: str, x: int, y: int) -> None:
    _adb("-s", serial, "shell", "input", "tap", str(int(x)), str(int(y)))


def swipe(serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 250) -> None:
    _adb(
        "-s", serial, "shell", "input", "swipe",
        str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)),
    )


def keyevent(serial: str, key: str | int) -> None:
    _adb("-s", serial, "shell", "input", "keyevent", str(key))


def type_text(serial: str, text: str) -> None:
    safe = (
        text.replace("\\", "\\\\")
        .replace(" ", "%s")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("&", "\\&")
        .replace("<", "\\<")
        .replace(">", "\\>")
        .replace("|", "\\|")
        .replace(";", "\\;")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    if not safe:
        return
    _adb("-s", serial, "shell", "input", "text", safe)


def stay_awake(serial: str, on: bool) -> None:
    _adb("-s", serial, "shell", "svc", "power", "stayon", "usb" if on else "false")


def start_scrcpy(serial: str, title: str, *, stay: bool = True, screen_off: bool = False) -> subprocess.Popen:
    exe = find_scrcpy()
    if exe is None:
        raise AdbError(
            "scrcpy is not installed. The in-app mirror still works. "
            "For HD, winget install Genymobile.scrcpy"
        )
    args = [str(exe), "-s", serial, "--window-title", title, "--mouse=sdk"]
    if stay:
        args.append("--stay-awake")
    if screen_off:
        args.append("--turn-screen-off")
    try:
        return subprocess.Popen(args)
    except OSError as e:
        raise AdbError(str(e)) from e


# --------------------------------------------------------------------------
# Native window embedding (BlueStacks / MuMu) — Windows only.
#
# Instead of polling `adb exec-out screencap`, this grabs the emulator's own
# top-level window and reparents it directly inside a Qt container widget
# (Win32 SetParent + style rewrite). The result is the emulator's real,
# live render at full speed, and clicks land on it natively — no ADB tap
# synthesis needed. Only works for local emulator windows, since a physical
# phone has no window to grab.
# --------------------------------------------------------------------------


class EmbedError(Exception):
    pass


@dataclass
class EmulatorWindow:
    hwnd: int
    pid: int
    title: str
    process_name: str
    width: int
    height: int

    @property
    def kind(self) -> str:
        name = self.process_name.lower()
        if name in _BS_PROCESS_NAMES:
            return "BlueStacks"
        if name in _MUMU_PROCESS_NAMES:
            return "MuMu Player"
        return self.process_name

    @property
    def label(self) -> str:
        title = self.title or self.process_name
        return f"{self.kind} — {title} ({self.width}x{self.height}) [pid {self.pid}]"


def _require_win32():
    try:
        import win32con  # noqa: F401
        import win32gui  # noqa: F401
        import win32process  # noqa: F401
    except ImportError as e:
        raise EmbedError(
            "pywin32 is required for window embedding (pip install pywin32)."
        ) from e


def list_emulator_windows() -> list[EmulatorWindow]:
    """Enumerate visible top-level windows belonging to a BlueStacks/MuMu process."""
    _require_win32()
    import win32gui
    import win32process

    try:
        import psutil
    except ImportError as e:
        raise EmbedError("psutil is required for window embedding (pip install psutil).") from e

    names = _BS_PROCESS_NAMES | _MUMU_PROCESS_NAMES
    found: list[EmulatorWindow] = []
    proc_name_cache: dict[int, str] = {}

    def _proc_name(pid: int) -> str:
        if pid not in proc_name_cache:
            try:
                proc_name_cache[pid] = psutil.Process(pid).name().lower()
            except Exception:
                proc_name_cache[pid] = ""
        return proc_name_cache[pid]

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetParent(hwnd) != 0:
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        pname = _proc_name(pid)
        if pname not in names:
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w < 200 or h < 200:
            return  # skip tray/helper windows too small to be the actual player
        found.append(
            EmulatorWindow(
                hwnd=hwnd, pid=pid,
                title=win32gui.GetWindowText(hwnd),
                process_name=pname, width=w, height=h,
            )
        )

    win32gui.EnumWindows(_cb, None)
    found.sort(key=lambda w: w.width * w.height, reverse=True)
    return found


@dataclass
class EmbedState:
    hwnd: int
    original_parent: int
    original_style: int
    original_exstyle: int
    original_rect: tuple[int, int, int, int]


def embed_window(hwnd: int, container_hwnd: int) -> EmbedState:
    """Reparent a native emulator window into `container_hwnd` (a Qt widget's winId)."""
    _require_win32()
    import win32con
    import win32gui

    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    state = EmbedState(
        hwnd=hwnd,
        original_parent=win32gui.GetParent(hwnd),
        original_style=style,
        original_exstyle=exstyle,
        original_rect=win32gui.GetWindowRect(hwnd),
    )
    strip = (
        win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_THICKFRAME
        | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX | win32con.WS_SYSMENU
        | win32con.WS_BORDER | win32con.WS_DLGFRAME
    )
    new_style = (style & ~strip) | win32con.WS_CHILD
    try:
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)
        win32gui.SetParent(hwnd, container_hwnd)
        # NOTE: SWP_NOMOVE | SWP_NOSIZE are required here. Without them this
        # call collapses the window to x=0,y=0,w=0,h=0 (its cx/cy args)
        # instead of leaving position/size alone — which is what made the
        # emulator's render surface go blank right after reparenting. The
        # real size is applied a moment later by resize_embedded().
        win32gui.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED
            | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
        )
    except Exception as e:
        detail = str(e)
        try:
            import pywintypes
            if isinstance(e, pywintypes.error) and e.winerror == 5:
                detail += (
                    " — Access denied. If the emulator is running as Administrator, "
                    "this app needs to run as Administrator too (Windows blocks "
                    "cross-privilege window reparenting otherwise)."
                )
        except ImportError:
            pass
        raise EmbedError(f"Failed to embed window: {detail}") from e
    return state


def resize_embedded(hwnd: int, width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        return
    try:
        import win32gui
        win32gui.MoveWindow(hwnd, 0, 0, int(width), int(height), True)
    except Exception:
        pass


def unembed_window(state: EmbedState) -> None:
    """Restore a previously embedded window to a normal top-level window."""
    try:
        import win32con
        import win32gui
        win32gui.SetWindowLong(state.hwnd, win32con.GWL_STYLE, state.original_style)
        win32gui.SetWindowLong(state.hwnd, win32con.GWL_EXSTYLE, state.original_exstyle)
        left, top, right, bottom = state.original_rect
        win32gui.SetParent(state.hwnd, state.original_parent or win32gui.GetDesktopWindow())
        win32gui.SetWindowPos(
            state.hwnd, 0, left, top, right - left, bottom - top,
            win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW,
        )
    except Exception:
        pass
