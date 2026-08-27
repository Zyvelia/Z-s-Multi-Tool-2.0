"""
Checks whether tools and runtimes this app depends on are installed and working.

Each check returns: name, ok (bool), detail (str), optional fix (str).
"""

from __future__ import annotations

import os
import shutil
import sys

from core.paths import get_app_data_dir


def _check_python() -> dict:
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 10)
    return {
        "name": "Python",
        "ok": ok,
        "detail": f"{sys.version.split()[0]} ({major}.{minor})",
        "fix": "Use Python 3.10 or newer." if not ok else "",
    }


def _check_import(module: str, label: str, fix: str = "") -> dict:
    try:
        __import__(module)
        return {"name": label, "ok": True, "detail": "Installed", "fix": ""}
    except ImportError as exc:
        return {"name": label, "ok": False, "detail": str(exc), "fix": fix or f"pip install {module}"}


def _find_vlc() -> str | None:
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "VideoLAN", "VLC"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "VideoLAN", "VLC"),
    ]
    for folder in candidates:
        if folder and os.path.isfile(os.path.join(folder, "libvlc.dll")):
            return folder
    if os.path.isfile("libvlc.dll"):
        return os.getcwd()
    return None


def _check_vlc() -> dict:
    loc = _find_vlc()
    if loc:
        return {"name": "VLC (Media Player)", "ok": True, "detail": loc, "fix": ""}
    return {
        "name": "VLC (Media Player)",
        "ok": False,
        "detail": "libvlc.dll not found",
        "fix": "Install VLC from videolan.org, or place libvlc.dll + plugins/ next to the app.",
    }


def _check_tailscale() -> dict:
    path = shutil.which("tailscale")
    if path:
        return {"name": "Tailscale CLI", "ok": True, "detail": path, "fix": ""}
    return {
        "name": "Tailscale CLI",
        "ok": False,
        "detail": "tailscale not on PATH",
        "fix": "Install Tailscale for remote hub / phone access.",
    }


def _check_webview2_packages() -> dict:
    try:
        import clr  # noqa: F401
        from webview.platforms.edgechromium import EdgeChrome  # noqa: F401
        from System.Windows.Forms import Control  # noqa: F401
        return {"name": "WebView2 Python packages (pywebview)", "ok": True, "detail": "Installed", "fix": ""}
    except ImportError as exc:
        return {
            "name": "WebView2 Python packages (pywebview)",
            "ok": False,
            "detail": str(exc),
            "fix": "pip install pythonnet pywebview — included when built with build.bat",
        }


def _check_webview2_runtime() -> dict:
    if sys.platform != "win32":
        return {"name": "WebView2 Runtime (Windows)", "ok": True, "detail": "N/A on this OS", "fix": ""}
    try:
        from core.webview2_detect import runtime_installed
        ok = runtime_installed()
    except Exception as exc:
        return {"name": "WebView2 Runtime (Windows)", "ok": False, "detail": str(exc), "fix": ""}
    if ok:
        return {"name": "WebView2 Runtime (Windows)", "ok": True, "detail": "Microsoft Edge WebView2 detected", "fix": ""}
    return {
        "name": "WebView2 Runtime (Windows)",
        "ok": False,
        "detail": "Not found in registry",
        "fix": "Re-run the app installer and enable WebView2, or install from https://developer.microsoft.com/microsoft-edge/webview2/",
    }


def _check_npcap_nmap() -> dict:
    nmap = shutil.which("nmap")
    npcap = os.path.exists(os.path.join(os.environ.get("ProgramFiles", ""), "Npcap"))
    if nmap and npcap:
        return {"name": "Nmap + Npcap (Network Auditor)", "ok": True, "detail": "Both detected", "fix": ""}
    missing = []
    if not nmap:
        missing.append("nmap")
    if not npcap:
        missing.append("Npcap")
    return {
        "name": "Nmap + Npcap (Network Auditor)",
        "ok": False,
        "detail": f"Missing: {', '.join(missing)}",
        "fix": "Install Nmap and Npcap for packet capture / port scans.",
    }


def _check_app_data_disk() -> dict:
    root = str(get_app_data_dir())
    try:
        usage = shutil.disk_usage(root)
        free_gb = usage.free / (1024 ** 3)
        ok = free_gb >= 0.5
        return {
            "name": "App data disk space",
            "ok": ok,
            "detail": f"{free_gb:.1f} GB free · {root}",
            "fix": "Free disk space for vault, downloads, and logs." if not ok else "",
        }
    except Exception as exc:
        return {"name": "App data disk space", "ok": False, "detail": str(exc), "fix": ""}


def _check_fido2() -> dict:
    try:
        import fido2  # noqa: F401
        return {"name": "FIDO2 (optional security key)", "ok": True, "detail": "Installed", "fix": ""}
    except ImportError:
        return {
            "name": "FIDO2 (optional security key)",
            "ok": True,
            "detail": "Not installed — optional",
            "fix": "pip install fido2 if you use a USB security key with Secure Vault.",
        }


def run_all_checks() -> list[dict]:
    checks = [
        _check_python(),
        _check_import("customtkinter", "CustomTkinter"),
        _check_import("cryptography", "Cryptography (Vault)"),
        _check_vlc(),
        _check_tailscale(),
        _check_webview2_runtime(),
        _check_webview2_packages(),
        _check_npcap_nmap(),
        _check_fido2(),
        _check_app_data_disk(),
    ]
    return checks
