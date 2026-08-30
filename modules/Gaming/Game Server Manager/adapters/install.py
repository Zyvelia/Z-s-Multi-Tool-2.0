"""Install/download helpers for game server adapters."""

from __future__ import annotations

import platform
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import requests

from .. import backend as mc
from ..core.events import DownloadEvent

TERRARIA_SERVER_ZIP_URL = (
    "https://terraria.org/api/download/pc-dedicated-server/terraria-server-1456.zip"
)
TMOD_STEAM_APP_ID = "1281930"
TMOD_GITHUB_RELEASES_API = (
    "https://api.github.com/repos/tModLoader/tModLoader/releases/latest"
)

_LOG_TS_RE = re.compile(r"^\[\d{4}-[^\]]+\]\s*")
_UPDATE_PROGRESS_RE = re.compile(
    r"Update state\s+\(0x[0-9a-fA-F]+\)\s+([^,]+),\s*progress:\s*([\d.]+)\s*\((\d+)\s*/\s*(\d+)\)",
    re.I,
)
_PROGRESS_BYTES_RE = re.compile(r"progress:\s*[\d.]+\s*\((\d+)\s*/\s*(\d+)\)", re.I)
_PROGRESS_PCT_RE = re.compile(r"progress:\s*([\d.]+)", re.I)
_BRACKET_PCT_RE = re.compile(r"^\[\s*(\d+)%\]\s*(.+)", re.I)
_BRACKET_PHASE_RE = re.compile(r"^\[----\]\s*(.+)", re.I)
_VALIDATE_PCT_RE = re.compile(r"Validating[^\d]*(\d+)%", re.I)

# SteamCMD self-update / small-app output often uses [----] phases instead of byte counts.
_PHASE_FRACTIONS: tuple[tuple[str, float], ...] = (
    ("checking for available updates", 0.04),
    ("verifying installation", 0.10),
    ("downloading update", 0.18),
    ("download complete", 0.55),
    ("extracting package", 0.68),
    ("installing update", 0.82),
    ("cleaning up", 0.94),
    ("update complete", 0.98),
)
_BOOTSTRAP_FRACTIONS: tuple[tuple[str, float], ...] = (
    ("loading steam api", 0.02),
    ("connecting anonymously", 0.05),
    ("waiting for client config", 0.07),
    ("waiting for user info", 0.09),
    ("installing steam app", 0.11),
)

_PROGRESS_SCALE = 10_000


def _normalize_steamcmd_line(line: str) -> str:
    line = line.strip()
    if not line or line == ".":
        return ""
    return _LOG_TS_RE.sub("", line).strip()


def _fraction_event(fraction: float, message: str) -> DownloadEvent:
    fraction = min(0.99, max(0.0, fraction))
    return DownloadEvent(
        kind="progress",
        downloaded=int(round(fraction * _PROGRESS_SCALE)),
        total=_PROGRESS_SCALE,
        message=message,
    )


def _phase_fraction(text: str, table: tuple[tuple[str, float], ...]) -> float | None:
    lower = text.lower().strip().rstrip(".")
    for key, frac in table:
        if key in lower:
            return frac
    return None


def _parse_steamcmd_line(raw_line: str) -> DownloadEvent | None:
    line = _normalize_steamcmd_line(raw_line)
    if not line:
        return None

    update_match = _UPDATE_PROGRESS_RE.search(line)
    if update_match:
        phase = update_match.group(1).strip()
        pct = float(update_match.group(2))
        downloaded = int(update_match.group(3))
        total = int(update_match.group(4))
        if total > 0:
            pct = downloaded * 100.0 / total
            return DownloadEvent(
                kind="progress",
                downloaded=downloaded,
                total=total,
                message=f"{phase}… {pct:.0f}%",
            )
        if pct > 0:
            return _fraction_event(pct / 100.0, f"{phase}… {pct:.0f}%")
        phase_frac = _phase_fraction(phase, _PHASE_FRACTIONS)
        if phase_frac is not None:
            return _fraction_event(phase_frac, phase)
        return DownloadEvent(kind="progress", message=phase)

    byte_match = _PROGRESS_BYTES_RE.search(line)
    if byte_match:
        downloaded = int(byte_match.group(1))
        total = int(byte_match.group(2))
        if total > 0:
            pct = downloaded * 100.0 / total
            return DownloadEvent(
                kind="progress",
                downloaded=downloaded,
                total=total,
                message=f"Downloading… {pct:.0f}%",
            )

    bracket_pct = _BRACKET_PCT_RE.match(line)
    if bracket_pct:
        pct = int(bracket_pct.group(1))
        detail = bracket_pct.group(2).strip()
        return _fraction_event(pct / 100.0, f"{detail} ({pct}%)")

    bracket_phase = _BRACKET_PHASE_RE.match(line)
    if bracket_phase:
        detail = bracket_phase.group(1).strip()
        phase_frac = _phase_fraction(detail, _PHASE_FRACTIONS)
        if phase_frac is not None:
            return _fraction_event(phase_frac, detail.rstrip("."))
        return DownloadEvent(kind="progress", message=detail.rstrip("."))

    validate_match = _VALIDATE_PCT_RE.search(line)
    if validate_match:
        pct = int(validate_match.group(1))
        return _fraction_event(max(0.10, pct / 100.0), f"Validating… {pct}%")

    pct_match = _PROGRESS_PCT_RE.search(line)
    if pct_match:
        pct = float(pct_match.group(1))
        if pct > 0:
            return _fraction_event(pct / 100.0, f"Updating… {pct:.0f}%")

    bootstrap_frac = _phase_fraction(line, _BOOTSTRAP_FRACTIONS)
    if bootstrap_frac is not None:
        return _fraction_event(bootstrap_frac, line)

    phase_frac = _phase_fraction(line, _PHASE_FRACTIONS)
    if phase_frac is not None:
        return _fraction_event(phase_frac, line.rstrip("."))

    if line.lower().startswith("success!"):
        return _fraction_event(0.99, line)

    return DownloadEvent(kind="progress", message=line)


def _should_emit_progress(last_pct: float, pct: float, *, finished: bool = False) -> bool:
    if finished:
        return True
    if last_pct < 0:
        return True
    return pct - last_pct >= 0.15 or pct >= 99.0


def _event_progress_pct(event: DownloadEvent) -> float:
    if event.total > _PROGRESS_SCALE:
        return event.downloaded * 100.0 / event.total
    if event.total == _PROGRESS_SCALE:
        return event.downloaded / (_PROGRESS_SCALE / 100.0)
    if event.total == 100:
        return float(event.downloaded)
    return -1.0


def _emit_steamcmd_progress(
    queue_out: queue.Queue[DownloadEvent],
    event: DownloadEvent,
    *,
    last_pct: float,
) -> float:
    pct = _event_progress_pct(event)
    finished = bool(event.message and event.message.lower().startswith("success!"))
    if pct >= 0 and not _should_emit_progress(last_pct, pct, finished=finished):
        return last_pct
    queue_out.put(event)
    return pct if pct >= 0 else last_pct


def _tail_steamcmd_log(log_path: Path, offset: int, handle_line: Callable[[str], None]) -> int:
    if not log_path.exists():
        return offset
    size = log_path.stat().st_size
    if size <= offset:
        return offset
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        for line in handle:
            handle_line(line.rstrip("\r\n"))
        return handle.tell()


def _monitor_steamcmd_output(
    proc: subprocess.Popen[str],
    log_path: Path,
    queue_out: queue.Queue[DownloadEvent],
) -> None:
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    last_pct = -1.0

    def consume(raw_line: str) -> None:
        nonlocal last_pct
        event = _parse_steamcmd_line(raw_line)
        if event is None:
            return
        last_pct = _emit_steamcmd_progress(queue_out, event, last_pct=last_pct)

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            consume(line)

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stdout_thread.start()

    while proc.poll() is None:
        log_offset = _tail_steamcmd_log(log_path, log_offset, consume)
        time.sleep(0.12)

    stdout_thread.join(timeout=3)
    log_offset = _tail_steamcmd_log(log_path, log_offset, consume)
    if proc.stdout is not None:
        for line in proc.stdout:
            consume(line)


def _find_steam_terraria_dir() -> Path | None:
    """Return a local Steam Terraria folder if TerrariaServer.exe is present."""
    candidates: list[Path] = []
    if platform.system() == "Windows":
        try:
            import winreg

            for hive, key_path in (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        steam_root = Path(str(winreg.QueryValueEx(key, "SteamPath")[0]))
                        candidates.append(steam_root / "steamapps" / "common" / "Terraria")
                except OSError:
                    continue
        except ImportError:
            pass
        candidates.extend([
            Path(r"C:\Program Files (x86)\Steam\steamapps\common\Terraria"),
            Path(r"C:\Program Files\Steam\steamapps\common\Terraria"),
        ])
    else:
        home = Path.home()
        candidates.extend([
            home / ".steam" / "steam" / "steamapps" / "common" / "Terraria",
            home / ".local" / "share" / "Steam" / "steamapps" / "common" / "Terraria",
        ])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if (candidate / "TerrariaServer.exe").is_file() or (
            candidate / "TerrariaServer.bin.x86_64"
        ).is_file():
            return candidate
    return None


def _cleanup_partial_terraria_steamcmd(server_dir: Path) -> None:
    """Remove leftover SteamCMD metadata when no server binary was installed."""
    exe_names = ("TerrariaServer.exe", "TerrariaServer.bin.x86_64")
    if any((server_dir / name).is_file() for name in exe_names):
        return
    for rel in ("steamapps", "installscript.vdf"):
        path = server_dir / rel
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)


def _copy_terraria_from_steam(
    server_dir: Path,
    source: Path,
    events: queue.Queue[DownloadEvent],
) -> bool:
    files = sorted(f for f in source.iterdir() if f.is_file())
    if not files:
        return False
    server_dir.mkdir(parents=True, exist_ok=True)
    events.put(_fraction_event(0.05, f"Copying Terraria server files from {source}…"))
    total = len(files)
    for index, src in enumerate(files, start=1):
        shutil.copy2(src, server_dir / src.name)
        events.put(DownloadEvent(
            kind="progress",
            downloaded=index,
            total=total,
            message=f"Copying from Steam… {index}/{total}",
        ))
    return any((server_dir / name).is_file() for name in ("TerrariaServer.exe", "TerrariaServer.bin.x86_64"))


def _terraria_payload_prefix(zip_names: list[str]) -> str | None:
    if platform.system() == "Windows":
        marker = "Windows/TerrariaServer.exe"
    else:
        marker = "Linux/TerrariaServer.bin.x86_64"
    for name in zip_names:
        if name.endswith(marker):
            return name[: -len(marker)] + ("Windows/" if platform.system() == "Windows" else "Linux/")
    return None


def _extract_terraria_zip(
    zip_path: Path,
    server_dir: Path,
    events: queue.Queue[DownloadEvent],
) -> None:
    events.put(_fraction_event(0.90, "Extracting Terraria server files…"))
    server_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        prefix = _terraria_payload_prefix(names)
        if not prefix:
            raise RuntimeError("Downloaded Terraria package did not contain server binaries.")

        members = [name for name in names if name.startswith(prefix) and not name.endswith("/")]
        total = max(len(members), 1)
        for index, member in enumerate(members, start=1):
            rel = member[len(prefix):]
            if not rel:
                continue
            dest = server_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if index == 1 or index == total or index % 8 == 0:
                frac = 0.90 + 0.09 * index / total
                events.put(_fraction_event(frac, f"Extracting… {index}/{total}"))


def _find_steam_tmodloader_dir() -> Path | None:
    """Locate the local Steam tModLoader install (client + dedicated server files)."""
    candidates: list[Path] = []
    if platform.system() == "Windows":
        try:
            import winreg

            for hive, key_path in (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        steam_root = Path(str(winreg.QueryValueEx(key, "SteamPath")[0]))
                        candidates.append(steam_root / "steamapps" / "common" / "tModLoader")
                except OSError:
                    continue
        except ImportError:
            pass
        candidates.extend([
            Path(r"C:\Program Files (x86)\Steam\steamapps\common\tModLoader"),
            Path(r"C:\Program Files\Steam\steamapps\common\tModLoader"),
        ])
    else:
        home = Path.home()
        candidates.extend([
            home / ".steam" / "steam" / "steamapps" / "common" / "tModLoader",
            home / ".local" / "share" / "Steam" / "steamapps" / "common" / "tModLoader",
        ])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_dir() and (
            (candidate / "start-tModLoaderServer.bat").is_file()
            or (candidate / "start-tModLoaderServer.sh").is_file()
            or (candidate / "tModLoaderServer.exe").is_file()
            or (candidate / "tModLoaderServer.bin.x86_64").is_file()
            or (candidate / "tModLoaderServer").is_file()
        ):
            return candidate
    return None


def _fetch_tmodloader_github_url() -> tuple[str, str]:
    """Return (release_tag, download_url) for the latest tModLoader.zip."""
    resp = requests.get(
        TMOD_GITHUB_RELEASES_API,
        timeout=30,
        headers={"Accept": "application/vnd.github+json"},
    )
    resp.raise_for_status()
    data = resp.json()
    tag = str(data.get("tag_name", "")).strip()
    if not tag:
        raise RuntimeError("Could not determine the latest tModLoader release tag.")
    for asset in data.get("assets", []):
        if asset.get("name") == "tModLoader.zip":
            url = str(asset.get("browser_download_url", "")).strip()
            if url:
                return tag, url
    raise RuntimeError("tModLoader.zip was not found in the latest GitHub release.")


def _cleanup_partial_tmod_steamcmd(server_dir: Path) -> None:
    """Remove empty SteamCMD metadata when no tModLoader server files exist."""
    from .games import find_tmodloader_executable

    if find_tmodloader_executable(server_dir):
        return
    common = server_dir / "steamapps" / "common" / "tModLoader"
    if common.is_dir() and find_tmodloader_executable(common):
        return
    manifest = server_dir / "steamapps" / f"appmanifest_{TMOD_STEAM_APP_ID}.acf"
    if not manifest.is_file():
        return
    try:
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if '"SizeOnDisk"\t\t"0"' in text or '"InstalledDepots"\n\t{\n\t}' in text:
        steamapps = server_dir / "steamapps"
        if steamapps.is_dir():
            shutil.rmtree(steamapps, ignore_errors=True)


def _extract_tmodloader_zip(
    zip_path: Path,
    server_dir: Path,
    events: queue.Queue[DownloadEvent],
    *,
    version_tag: str,
) -> None:
    events.put(_fraction_event(0.90, "Extracting tModLoader server files…"))
    server_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        total = max(len(members), 1)
        for index, member in enumerate(members, start=1):
            dest = server_dir / member
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            if index == 1 or index == total or index % 40 == 0:
                frac = 0.90 + 0.09 * index / total
                events.put(_fraction_event(frac, f"Extracting… {index}/{total}"))
    (server_dir / ".tml-version").write_text(f"{version_tag}\n", encoding="utf-8")
    _write_tmod_steam_appid(server_dir)
    _ensure_tmod_mods_folder(server_dir)


def _download_tmodloader_github(
    server_dir: Path,
    events: queue.Queue[DownloadEvent],
) -> None:
    """Download and extract the official tModLoader release from GitHub."""
    tag, url = _fetch_tmodloader_github_url()
    events.put(_fraction_event(0.08, f"Downloading tModLoader {tag} from GitHub…"))
    tmp_zip: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
            tmp_zip = Path(handle.name)
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            last_pct = -1.0
            with open(tmp_zip, "wb") as out:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100.0 / total
                        if pct - last_pct >= 0.5 or downloaded == total:
                            last_pct = pct
                            events.put(DownloadEvent(
                                kind="progress",
                                downloaded=downloaded,
                                total=total,
                                message=f"Downloading… {pct:.0f}%",
                            ))
                    else:
                        events.put(DownloadEvent(
                            kind="progress",
                            downloaded=downloaded,
                            total=0,
                            message=f"Downloading… {_human_size(downloaded)}",
                        ))
        _extract_tmodloader_zip(tmp_zip, server_dir, events, version_tag=tag)
    finally:
        if tmp_zip and tmp_zip.exists():
            tmp_zip.unlink(missing_ok=True)


def _write_tmod_steam_appid(server_dir: Path) -> None:
    (server_dir / "steam_appid.txt").write_text(f"{TMOD_STEAM_APP_ID}\n", encoding="utf-8")


def _ensure_tmod_mods_folder(server_dir: Path) -> None:
    (server_dir / "Mods").mkdir(parents=True, exist_ok=True)


def _copy_tmodloader_from_steam(
    server_dir: Path,
    source: Path,
    events: queue.Queue[DownloadEvent],
) -> bool:
    if not source.is_dir():
        return False
    server_dir.mkdir(parents=True, exist_ok=True)
    events.put(_fraction_event(0.05, f"Copying tModLoader from {source}…"))
    shutil.copytree(source, server_dir, dirs_exist_ok=True)
    _write_tmod_steam_appid(server_dir)
    _ensure_tmod_mods_folder(server_dir)
    from .games import find_tmodloader_executable

    return find_tmodloader_executable(server_dir) is not None


def create_terraria_install_worker(
    server_dir: Path,
    *,
    mode: str = "vanilla",
    verify: Callable[[Path], bool] | None = None,
) -> threading.Thread:
    """Install Terraria (vanilla) or tModLoader using Steam library copy or download."""

    class _Starter(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue[DownloadEvent] = queue.Queue()

        def run(self) -> None:
            try:
                self._run()
            except Exception as exc:  # noqa: BLE001 — surface install failures to the UI
                self.events.put(DownloadEvent(kind="error", message=str(exc)))

        def _run_tmodloader(self) -> None:
            server_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_partial_tmod_steamcmd(server_dir)

            if verify and verify(server_dir):
                self.events.put(DownloadEvent(
                    kind="done",
                    message=f"tModLoader server is already installed in {server_dir}.",
                ))
                return

            self.events.put(_fraction_event(0.01, "Preparing tModLoader server install…"))
            steam_dir = _find_steam_tmodloader_dir()
            if steam_dir and _copy_tmodloader_from_steam(server_dir, steam_dir, self.events):
                if not verify or verify(server_dir):
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=f"tModLoader copied from Steam to {server_dir}.",
                    ))
                    return

            try:
                _download_tmodloader_github(server_dir, self.events)
            except Exception as exc:  # noqa: BLE001 — report download/extract failures
                self.events.put(DownloadEvent(
                    kind="error",
                    message=f"Couldn't download tModLoader from GitHub: {exc}",
                ))
                return

            if verify and not verify(server_dir):
                self.events.put(DownloadEvent(
                    kind="error",
                    message=(
                        "Install finished but start-tModLoaderServer was not found. "
                        "Try again or copy your Steam tModLoader folder into the server directory."
                    ),
                ))
                return

            self.events.put(DownloadEvent(
                kind="done",
                message=f"tModLoader server installed to {server_dir}.",
            ))

        def _run_vanilla(self) -> None:
            server_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_partial_terraria_steamcmd(server_dir)

            if verify and verify(server_dir):
                self.events.put(DownloadEvent(
                    kind="done",
                    message=f"Terraria server is already installed in {server_dir}.",
                ))
                return

            self.events.put(_fraction_event(0.01, "Preparing Terraria server install…"))
            steam_dir = _find_steam_terraria_dir()
            if steam_dir and _copy_terraria_from_steam(server_dir, steam_dir, self.events):
                if not verify or verify(server_dir):
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=f"Terraria server copied from Steam to {server_dir}.",
                    ))
                    return

            self.events.put(_fraction_event(0.08, "Downloading official Terraria server package…"))
            tmp_zip: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
                    tmp_zip = Path(handle.name)
                with requests.get(TERRARIA_SERVER_ZIP_URL, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    last_pct = -1.0
                    with open(tmp_zip, "wb") as out:
                        for chunk in resp.iter_content(chunk_size=256 * 1024):
                            if not chunk:
                                continue
                            out.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = downloaded * 100.0 / total
                                if pct - last_pct >= 0.5 or downloaded == total:
                                    last_pct = pct
                                    self.events.put(DownloadEvent(
                                        kind="progress",
                                        downloaded=downloaded,
                                        total=total,
                                        message=f"Downloading… {pct:.0f}%",
                                    ))
                            else:
                                self.events.put(DownloadEvent(
                                    kind="progress",
                                    downloaded=downloaded,
                                    total=0,
                                    message=f"Downloading… {_human_size(downloaded)}",
                                ))

                _extract_terraria_zip(tmp_zip, server_dir, self.events)
            finally:
                if tmp_zip and tmp_zip.exists():
                    tmp_zip.unlink(missing_ok=True)

            if verify and not verify(server_dir):
                self.events.put(DownloadEvent(
                    kind="error",
                    message=(
                        "Install finished but TerrariaServer was not found. "
                        "Try again or copy TerrariaServer.exe from your Steam Terraria folder."
                    ),
                ))
                return

            self.events.put(DownloadEvent(
                kind="done",
                message=f"Terraria server installed to {server_dir}.",
            ))

        def _run(self) -> None:
            if mode == "tmodloader":
                self._run_tmodloader()
            else:
                self._run_vanilla()

    return _Starter()


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{num} B"


def find_steamcmd() -> tuple[Path | None, str]:
    """Locate a SteamCMD executable on this machine."""
    system = platform.system()
    names = ["steamcmd.exe", "steamcmd"] if system == "Windows" else ["steamcmd.sh", "steamcmd"]
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found), ""

    candidates: list[Path] = []
    if system == "Windows":
        candidates.extend([
            Path(r"C:\steamcmd\steamcmd.exe"),
            Path(r"C:\Program Files (x86)\Steam\steamcmd\steamcmd.exe"),
            Path.home() / "steamcmd" / "steamcmd.exe",
        ])
    else:
        candidates.extend([
            Path.home() / "steamcmd" / "steamcmd.sh",
            Path("/usr/games/steamcmd"),
        ])

    for path in candidates:
        if path.exists():
            return path, ""

    return None, (
        "SteamCMD not found. Download it from "
        "https://developer.valvesoftware.com/wiki/SteamCMD and add it to PATH."
    )


def create_minecraft_java_install_worker(
    server_dir: Path,
    version: mc.MCVersion,
) -> threading.Thread:
    class _Starter(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue[DownloadEvent] = queue.Queue()

        def run(self) -> None:
            info, error = mc.get_server_download_info(version)
            if error or info is None:
                self.events.put(DownloadEvent(kind="error", message=error or "No download info."))
                return
            worker = mc.ServerDownloadWorker(info, server_dir)
            worker.events = self.events
            worker.run()

    return _Starter()


def create_minecraft_bedrock_install_worker(
    server_dir: Path,
    preview: bool = False,
) -> threading.Thread:
    class _Starter(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue[DownloadEvent] = queue.Queue()
            self.version = ""

        def run(self) -> None:
            info, error = mc.get_bedrock_download_info(preview=preview)
            if error or info is None:
                self.events.put(DownloadEvent(kind="error", message=error or "No download info."))
                return
            self.version = info.version
            worker = mc.BedrockDownloadWorker(info, server_dir)
            worker.events = self.events
            worker.run()

    return _Starter()


def create_steamcmd_install_worker(
    server_dir: Path,
    app_id: str,
    *,
    verify: Callable[[Path], bool] | None = None,
) -> threading.Thread:
    """Install/update a Steam dedicated server via SteamCMD."""

    class _Starter(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue[DownloadEvent] = queue.Queue()

        def run(self) -> None:
            steamcmd, err = find_steamcmd()
            if not steamcmd:
                self.events.put(DownloadEvent(kind="error", message=err))
                return

            steam_app_id = str(app_id or "").strip()
            if not steam_app_id.isdigit():
                self.events.put(DownloadEvent(kind="error", message="Set a valid Steam App ID first."))
                return

            server_dir.mkdir(parents=True, exist_ok=True)
            self.events.put(_fraction_event(0.01, f"Installing Steam app {steam_app_id}…"))

            cmd = [
                str(steamcmd),
                "+force_install_dir", str(server_dir.resolve()),
                "+login", "anonymous",
                "+app_update", steam_app_id, "validate",
                "+quit",
            ]
            log_path = steamcmd.parent / "logs" / "console_log.txt"

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(steamcmd.parent),
                    bufsize=1,
                )
            except OSError as e:
                self.events.put(DownloadEvent(kind="error", message=f"Couldn't run SteamCMD: {e}"))
                return

            _monitor_steamcmd_output(proc, log_path, self.events)
            code = proc.wait()
            if code != 0:
                self.events.put(DownloadEvent(
                    kind="error",
                    message=f"SteamCMD exited with code {code}. Check console output above.",
                ))
                return

            if verify and not verify(server_dir):
                self.events.put(DownloadEvent(
                    kind="error",
                    message=(
                        f"SteamCMD finished but the server executable was not found in {server_dir}. "
                        "See Console output above for details."
                    ),
                ))
                return

            self.events.put(DownloadEvent(
                kind="done",
                message=f"Steam app {steam_app_id} installed to {server_dir}.",
            ))

    return _Starter()
