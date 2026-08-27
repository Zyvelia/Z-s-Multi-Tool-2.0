"""Detect Microsoft Edge WebView2 Runtime via registry (no tkwebview2 import)."""

from __future__ import annotations

import sys


_WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _edge_build(key_type, key) -> str:
    import winreg

    if sys.maxsize <= 2**32:
        path = rf"Microsoft\EdgeUpdate\Clients\{key}"
    elif key_type == winreg.HKEY_CURRENT_USER:
        path = rf"Microsoft\EdgeUpdate\Clients\{key}"
    else:
        path = rf"WOW6432Node\Microsoft\EdgeUpdate\Clients\{key}"

    try:
        with winreg.OpenKey(key_type, rf"SOFTWARE\{path}") as handle:
            build, _ = winreg.QueryValueEx(handle, "pv")
            return str(build)
    except OSError:
        return "0"


def _is_new_version(min_build: str, build: str) -> bool:
    try:
        return tuple(int(x) for x in build.split(".")) >= tuple(int(x) for x in min_build.split("."))
    except ValueError:
        return False


def runtime_installed() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg

        for key_type in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            build = _edge_build(key_type, _WEBVIEW2_CLIENT_ID)
            if _is_new_version("86.0.622.0", build):
                return True
    except Exception:
        pass
    return False
