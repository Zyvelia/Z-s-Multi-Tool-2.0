"""Java runtime discovery and Minecraft-version compatibility helpers."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

@dataclass(frozen=True)
class JavaRuntime:
    major: int
    version: str
    path: str
    source: str = ""


def parse_java_major(version: str) -> int | None:
    s = str(version).strip()
    m = re.search(r"(?:^|[^0-9])(?:1\.)?(\d+)(?:[._+-]|$)", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def java_version(java_path: str) -> tuple[bool, str, int | None]:
    try:
        p = subprocess.run([java_path, "-version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False, "", None
    out = (p.stderr or "") + "\n" + (p.stdout or "")
    m = re.search(r'version\s+"([^"]+)"', out)
    version = m.group(1) if m else (out.strip().splitlines()[0] if out.strip() else "")
    return bool(version), version, parse_java_major(version)


_bitness_cache: dict[str, bool] = {}
_max_heap_cache: dict[str, int] = {}


def is_32bit_jvm(java_path: str) -> bool:
    """Best-effort early signal for whether a JVM is 32-bit, used only to
    pick a sane starting point (see max_settable_heap_mb below, which is
    the actual authority and cannot be fooled by this being wrong).

    Uses `sun.arch.data.model`, a standard JVM system property. Not fully
    trusted on its own: some real-world Java 8 builds have been observed
    to report in ways that don't match how they actually behave when asked
    for a large heap, which is why max_settable_heap_mb() verifies by
    actually test-booting the JVM rather than relying on this alone.
    """
    key = str(java_path)
    if key in _bitness_cache:
        return _bitness_cache[key]
    result = True  # unknown -> assume 32-bit; only affects the starting
                   # guess, the real answer comes from the boot test below
    try:
        p = subprocess.run([java_path, "-XshowSettings:properties", "-version"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=8, creationflags=_CREATE_NO_WINDOW)
        out = (p.stderr or "") + "\n" + (p.stdout or "")
        m = re.search(r"sun\.arch\.data\.model\s*=\s*(\d+)", out)
        if m:
            result = (m.group(1) == "32")
        else:
            low = out.lower()
            if "64-bit" in low:
                result = False
    except (OSError, subprocess.SubprocessError):
        pass
    _bitness_cache[key] = result
    return result


def max_settable_heap_mb(java_path: str, requested_mb: int, timeout: int = 8) -> tuple[int, list[str]]:
    """Find the largest heap at or below `requested_mb` that this exact JVM
    will actually accept at boot, by test-launching it — not by predicting
    from bitness or path heuristics.

    This exists because bitness-guessing (property text, version banner,
    install path) can all be wrong for a given real-world Java build, and
    the failure it's protecting against is not cosmetic: a 32-bit JVM
    given an -Xmx it can't represent or reserve fails immediately with
    "Invalid maximum heap size ... exceeds the maximum representable
    size" or "Could not reserve enough space for object heap", and the
    game/server never starts. Only a real boot test can't be fooled by
    that, since it reproduces the exact failure (or success) the real
    launch would hit.

    Only probes when requested_mb is large enough to plausibly be a
    problem (>= 2048); smaller requests are trusted without a boot test to
    avoid adding launch latency for the common case where nothing is wrong.
    Successful results are cached per (path, requested_mb) so repeat
    launches at the same setting don't re-probe.
    """
    if requested_mb < 2048:
        return requested_mb, []

    cache_key = f"{java_path}::{requested_mb}"
    if cache_key in _max_heap_cache:
        return _max_heap_cache[cache_key], []

    ladder = [mb for mb in (requested_mb, 3584, 3072, 2560, 2048, 1536, 1024, 768, 512)
              if mb <= requested_mb]
    seen: set[int] = set()
    ladder = [mb for mb in ladder if not (mb in seen or seen.add(mb))]

    notes: list[str] = []
    for mb in ladder:
        try:
            p = subprocess.run([java_path, f"-Xmx{mb}M", "-version"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout,
                               creationflags=_CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            notes.append(f"-Xmx{mb}M: couldn't run Java ({e})")
            continue
        if p.returncode == 0:
            notes.append(f"-Xmx{mb}M: accepted")
            _max_heap_cache[cache_key] = mb
            return mb, notes
        detail_lines = (p.stderr or p.stdout or "").strip().splitlines()
        detail = detail_lines[-1] if detail_lines else "unknown error"
        notes.append(f"-Xmx{mb}M: rejected — {detail}")

    _max_heap_cache[cache_key] = 512
    return 512, notes


def _candidate_paths() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    def add(p: Path, source: str):
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key not in seen and p.exists() and p.is_file():
            seen.add(key); out.append((str(p), source))

    # Current PATH/JAVA_HOME first.
    for exe in ("java.exe", "java"):
        found = shutil.which(exe)
        if found:
            add(Path(found), "PATH")
    home = os.environ.get("JAVA_HOME", "").strip()
    if home:
        add(Path(home) / "bin" / ("java.exe" if platform.system() == "Windows" else "java"), "JAVA_HOME")

    if platform.system() == "Windows":
        roots = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Java",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Eclipse Adoptium",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Eclipse Foundation",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Zulu",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "BellSoft",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Java",
        ]
        patterns = [
            "jdk*/bin/java.exe", "jre*/bin/java.exe", "*/bin/java.exe",
            "Microsoft/jdk*/bin/java.exe", "Eclipse Adoptium/*/bin/java.exe",
        ]
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                try:
                    for p in root.glob(pattern): add(p, "Installed")
                except OSError:
                    pass
        # Windows registry: catches JDKs installed by MSI/WinGet even when
        # their installation directory is not on PATH or in our common roots.
        try:
            import winreg
            registry_locations = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JDK"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\Java Runtime Environment"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\JavaSoft\JDK"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\JavaSoft\Java Runtime Environment"),
            ]
            for hive, base in registry_locations:
                try:
                    with winreg.OpenKey(hive, base) as key:
                        current, _ = winreg.QueryValueEx(key, "CurrentVersion")
                        versions = [str(current)] if current else []
                        try:
                            versions.extend(winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0]))
                        except OSError:
                            pass
                    for ver in dict.fromkeys(versions):
                        try:
                            with winreg.OpenKey(hive, base + "\\" + ver) as vk:
                                java_home, _ = winreg.QueryValueEx(vk, "JavaHome")
                                add(Path(str(java_home)) / "bin" / "java.exe", "Registry")
                        except OSError:
                            pass
                except OSError:
                    pass
        except ImportError:
            pass
    else:
        for root in (Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt/java")):
            if root.exists():
                for p in root.glob("*/bin/java"): add(p, "Installed")
    return out


def discover_java_runtimes() -> list[JavaRuntime]:
    found: list[JavaRuntime] = []
    seen: set[str] = set()
    for path, source in _candidate_paths():
        ok, version, major = java_version(path)
        if not ok or major is None:
            continue
        try: key = str(Path(path).resolve()).lower()
        except OSError: key = path.lower()
        if key in seen: continue
        seen.add(key)
        found.append(JavaRuntime(major, version, path, source))
    found.sort(key=lambda x: (x.major, x.path), reverse=True)
    return found


def required_java_major(minecraft_version: str) -> int:
    """Minecraft/Forge-supported Java baseline used by the manager."""
    v = str(minecraft_version or "").strip().lower()
    if v.startswith("26."):
        return 25
    # Minecraft 1.20.6 through 1.21.x require Java 21; 1.18.2-1.20.4 use 17.
    if v.startswith("1."):
        parts = v.split(".")
        try: minor = int(parts[1]); patch = int(parts[2]) if len(parts) > 2 else 0
        except ValueError: return 21
        if minor >= 21 or (minor == 20 and patch >= 6): return 21
        if minor >= 18: return 17
        if minor == 17: return 16
        return 8
    return 25


def recommended_runtime(minecraft_version: str, runtimes: list[JavaRuntime] | None = None) -> JavaRuntime | None:
    required = required_java_major(minecraft_version)
    runtimes = runtimes if runtimes is not None else discover_java_runtimes()
    exact = [r for r in runtimes if r.major == required]
    return exact[0] if exact else None


def compatibility_text(minecraft_version: str, runtimes: list[JavaRuntime]) -> tuple[int, str]:
    required = required_java_major(minecraft_version)
    match = recommended_runtime(minecraft_version, runtimes)
    if match:
        return required, f"✓ Java {required} installed — {match.version}"
    return required, f"✗ Java {required} not installed"
