# core/services/tailscale_service.py
#
# Thin wrapper around the `tailscale` CLI. Lets the app join/leave the
# user's private Tailscale network (a "tailnet") and, via `tailscale
# serve`, reverse-proxy a local port onto that tailnet over HTTPS with
# a Tailscale-issued certificate — no port forwarding, no exposure to
# the public internet, reachable only from the user's own devices.
#
# Everything here shells out to the tailscale binary. If it isn't
# installed, every method fails soft (returns ok=False with a message)
# instead of raising, so the Settings tab can just show "not installed"
# with a download link rather than crashing.

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import socket
import time
import webbrowser

from core import paths

CONFIG_FILE = paths.data_path("tailscale", "settings.json")

DEFAULT_CONFIG = {
    "hostname": "",              # optional --hostname for `tailscale up`
    "auth_key": "",              # optional --authkey for unattended login
    "accept_routes": True,       # --accept-routes
    "web_port": 8765,            # local port the vault web server binds
    "auto_off_enabled": False,
    "auto_off_minutes": 30,
}

# Each app gets its own fixed HTTPS port on this device's tailnet address,
# instead of all three fighting over the single default (443) address via
# `tailscale serve --bg http://127.0.0.1:<port>`. This is what lets Music
# Player, Security Vault, and mediaDl all be reachable at the
# same time — see enable_app_serve() below. The default port 443 is left
# free for the Remote Hub's landing page (see hub_service.py), which is
# what your phone actually opens first and links out from.
APP_HTTPS_PORTS = {
    "vault": 8443,
    "music": 8444,
    "yt": 8445,
    "games": 8446,
    "soundboard": 8447,
    "notes": 8448,
    "send": 8449,
    "social": 8450,
    "arcade": 8451,
    "messages": 8452,
    "gsm": 8453,
    "chat": 8454,
    "trust": 8455,
}
HUB_HTTPS_PORT = 443

# tailscale up/down and serve calls can hang if the daemon is in a
# weird state (e.g. waiting on a login flow) — never block the UI
# thread forever.
CLI_TIMEOUT = 12
STATUS_CACHE_SECONDS = 2.0


class TailscaleService:

    def __init__(self):
        self._timer = None
        self._timer_started_at = None
        self._timer_minutes = None
        self._on_auto_off = None  # callback set by whoever starts the timer
        self._cli_lock = threading.RLock()
        self._status_cache = None
        self._status_cache_at = 0.0
        self._serve_cache = set()
        self._serve_cache_at = 0.0

    # =====================================================
    # CONFIG
    # =====================================================

    def load_config(self):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged

    def save_config(self, config):
        merged = self.load_config()
        merged.update(config)
        with open(CONFIG_FILE, "w") as f:
            json.dump(merged, f, indent=4)
        return merged

    # =====================================================
    # CLI PLUMBING
    # =====================================================

    def _binary(self):
        """Resolve Tailscale reliably on Windows and normal PATH installs."""
        found = shutil.which("tailscale") or shutil.which("tailscale.exe")
        if found:
            return found
        if os.name == "nt":
            candidates = [
                os.path.expandvars(r"%ProgramFiles%\Tailscale\tailscale.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Tailscale\tailscale.exe"),
                os.path.expandvars(r"%LocalAppData%\Tailscale\tailscale.exe"),
            ]
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    return candidate
        return None

    def is_installed(self):
        return self._binary() is not None

    def _no_window_kwargs(self):
        """
        Extra kwargs for subprocess calls so that, on Windows, the
        `tailscale` CLI never pops up its own console window and never
        hangs waiting on a console that doesn't exist.

        This app is a windowed (no-console) GUI app on Windows, so it
        has no valid inherited stdin/stdout/stderr console handles.
        When a console subprocess (tailscale.exe) is spawned from a
        process like that without explicitly redirecting stdin,
        Windows allocates a brand-new console for the child to attach
        to — that's the terminal window that flashes on screen. Worse,
        if the child ever tries to read from that console (e.g. while
        waiting on auth), it can sit there indefinitely since nothing
        is actually connected to it, which is what was causing
        "Connect" to silently hang until it timed out.

        Explicitly setting stdin=DEVNULL plus CREATE_NO_WINDOW/SW_HIDE
        fixes both: no console is created, and the child never blocks
        waiting on input that will never come.
        """
        kwargs = {"stdin": subprocess.DEVNULL}
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return kwargs

    def _run(self, args, timeout=CLI_TIMEOUT):
        binary = self._binary()
        if not binary:
            return False, "Tailscale isn't installed (or not on PATH)."
        try:
            # Tailscale is a single local daemon. Serializing CLI calls avoids
            # several Remote Hub/module pages spawning competing `tailscale`
            # processes at the same time.
            with self._cli_lock:
                result = subprocess.run(
                    [binary] + args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    **self._no_window_kwargs(),
                )
                if result.returncode != 0:
                    return False, (result.stderr or result.stdout or "Unknown error").strip()
                return True, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "tailscale command timed out."
        except Exception as e:
            return False, str(e)

    # =====================================================
    # STATUS
    # =====================================================

    def get_status(self, force=False):
        """Fast, shared Tailscale status query. Cached briefly to prevent module stampedes."""
        now = time.monotonic()
        if not force and self._status_cache is not None and now - self._status_cache_at < STATUS_CACHE_SECONDS:
            return dict(self._status_cache)

        base = {
            "installed": False, "running": False, "backend_state": "NotInstalled",
            "hostname": "", "tailscale_ip": "", "serving": False,
            "error": "", "auth_url": "",
        }
        if not self.is_installed():
            self._status_cache = base
            self._status_cache_at = now
            return dict(base)

        ok, out = self._run(["status", "--json"], timeout=5)
        if not ok:
            base.update({"installed": True, "backend_state": "Unavailable", "error": out})
            self._status_cache = base
            self._status_cache_at = time.monotonic()
            return dict(base)
        try:
            data = json.loads(out)
        except Exception as exc:
            base.update({"installed": True, "backend_state": "InvalidStatus",
                         "error": f"Invalid Tailscale status JSON: {exc}"})
            self._status_cache = base
            self._status_cache_at = time.monotonic()
            return dict(base)

        backend_state = data.get("BackendState", "Unknown")
        self_node = data.get("Self", {}) or {}
        ips = self_node.get("TailscaleIPs") or []
        dns_name = (self_node.get("DNSName") or "").rstrip(".")
        base.update({
            "installed": True, "running": backend_state == "Running",
            "backend_state": backend_state,
            "hostname": dns_name or self_node.get("HostName", ""),
            "tailscale_ip": ips[0] if ips else "",
        })
        if backend_state != "Running":
            base["error"] = f"Tailscale backend state is {backend_state}."
        self._status_cache = base
        self._status_cache_at = time.monotonic()
        return dict(base)

    def _invalidate_status(self):
        self._status_cache_at = 0.0

    def _is_serving(self):
        ok, out = self._run(["serve", "status", "--json"], timeout=4)
        if ok and out:
            try:
                data = json.loads(out)
                return bool(data)
            except Exception:
                pass

        ok, out = self._run(["serve", "status"], timeout=3)
        if not ok:
            return False
        text = (out or "").strip().lower()
        return bool(text) and "no serve" not in text and "not configured" not in text

    def _local_port_open(self, port):
        """Fast loopback check used before configuring Tailscale Serve."""
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=1.5):
                return True
        except OSError:
            return False

    def diagnostics(self):
        """
        Best-effort raw output for on-demand troubleshooting, shown verbatim
        in the app's "Diagnose" popup rather than the app trying to guess
        what's wrong. Never raises.
        """
        lines = []

        if not self.is_installed():
            lines.append("Tailscale CLI: NOT FOUND on PATH.")
            return "\n".join(lines)

        binary = self._binary()
        lines.append(f"Tailscale CLI: found at {binary}")
        lines.append("")

        ok, out = self._run(["status"])
        lines.append("$ tailscale status")
        lines.append(out if ok else f"(failed) {out}")
        lines.append("")

        ok, out = self._run(["serve", "status"])
        lines.append("$ tailscale serve status")
        lines.append(out if ok else f"(failed) {out}")
        lines.append("")

        ok, out = self._run(["cert", "--help"])  # cheap check the cert subcommand exists
        lines.append(
            "HTTPS certs / MagicDNS: if 'serve status' above shows nothing or an "
            "error instead of a live https:// mapping, this almost always means "
            "MagicDNS or HTTPS Certificates is disabled for your tailnet at "
            "https://login.tailscale.com/admin/dns rather than a problem on this device."
        )

        return "\n".join(lines)

    # =====================================================
    # UP / DOWN
    # =====================================================

    def connect(self, hostname=None, auth_key=None, accept_routes=True):
        """
        Join/rejoin the tailnet.

        If Tailscale needs interactive login, the CLI output normally contains
        a login URL. Because the desktop app launches the CLI without a
        console, open that URL ourselves and return a useful diagnostic.
        """
        current = self.get_status()
        if current.get("running"):
            return True, "Tailscale is already connected."

        args = ["up", "--reset"]
        if accept_routes:
            args.append("--accept-routes")
        if hostname:
            args += ["--hostname", hostname]
        if auth_key:
            args += ["--authkey", auth_key]

        ok, msg = self._run(args, timeout=60)
        self._invalidate_status()
        text = (msg or "").strip()

        # Tailscale may emit an auth URL even when `tailscale up` exits
        # non-zero because login/consent is still required.
        urls = re.findall(r"https?://[^\s<>\"]+", text)
        auth_url = next(
            (u.rstrip(".,)") for u in urls if "login.tailscale.com" in u),
            "",
        )
        if auth_url:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass
            return False, (
                "Tailscale needs you to finish sign-in/approval. "
                f"The login page was opened:\n{auth_url}"
            )

        if not ok:
            return False, text or "Tailscale could not connect."

        status = self.get_status()
        if not status.get("running"):
            return False, (
                f"Tailscale command completed, but the backend is "
                f"{status.get('backend_state') or 'not running'}."
                + (f"\n{status.get('error')}" if status.get("error") else "")
            )

        return True, text or "Tailscale connected."

    def disconnect(self):
        """Leave the tailnet (`tailscale down`). Also drops any active serve."""
        self.disable_serve()
        result = self._run(["down"])
        self._invalidate_status()
        return result

    # =====================================================
    # SERVE (HTTPS reverse proxy onto the tailnet)
    # =====================================================

    def enable_serve(self, port):
        """
        Legacy single-destination form — exposes http://127.0.0.1:<port>
        as https://<this-device>.<tailnet>/, taking over whatever else
        was on the default address. Kept only for backwards compatibility;
        enable_app_serve() below is what every app's Settings tab now
        uses, since it lets all three apps be live simultaneously.
        """
        return self._run(["serve", "--bg", f"http://127.0.0.1:{port}"], timeout=60)

    def disable_serve(self):
        """Full reset — clears EVERY serve entry (all apps + the hub page). Used on disconnect."""
        result = self._run(["serve", "reset"], timeout=15)
        self._serve_cache_at = 0.0
        return result

    def enable_app_serve(self, app_key, local_port):
        """
        Exposes http://127.0.0.1:<local_port> as
        https://<this-device>.<tailnet>:<app's own fixed port>/ — each
        app (see APP_HTTPS_PORTS) gets its own address, so turning one
        on never takes over another's. Same long timeout as the old
        enable_serve() for the same reason: first-run cert provisioning
        can take a while.
        """
        https_port = APP_HTTPS_PORTS.get(app_key)
        if not https_port:
            return False, f"Unknown app '{app_key}'."
        if not self._local_port_open(local_port):
            return False, (
                f"{app_key} is not listening on 127.0.0.1:{local_port}. "
                "The local app server must be running before Tailscale Serve can expose it."
            )
        result = self._run(
            ["serve", "--bg", "--yes", f"--https={https_port}", f"http://127.0.0.1:{local_port}"],
            timeout=8,
        )
        self._serve_cache_at = 0.0
        return result

    def disable_app_serve(self, app_key):
        https_port = APP_HTTPS_PORTS.get(app_key)
        if not https_port:
            return False, f"Unknown app '{app_key}'."
        result = self._run(["serve", "--yes", f"--https={https_port}", "off"], timeout=10)
        self._serve_cache_at = 0.0
        return result


    def get_serving_ports(self, force=False):
        """Return configured Serve HTTPS ports with a short shared cache."""
        now = time.monotonic()
        if not force and now - self._serve_cache_at < STATUS_CACHE_SECONDS:
            return set(self._serve_cache)

        ports = set()
        ok, out = self._run(["serve", "status", "--json"], timeout=4)
        if ok and out:
            try:
                data = json.loads(out)
                known = set(APP_HTTPS_PORTS.values()) | {HUB_HTTPS_PORT}
                text = json.dumps(data)
                for match in re.findall(r":(\d{2,5})(?:/|\b)", text):
                    port = int(match)
                    if port in known:
                        ports.add(port)
                # Some versions expose the port as a numeric JSON key.
                def walk(v):
                    if isinstance(v, dict):
                        for k, value in v.items():
                            if str(k).isdigit() and int(k) in known:
                                ports.add(int(k))
                            walk(value)
                    elif isinstance(v, list):
                        for value in v:
                            walk(value)
                walk(data)
            except Exception:
                ports = set()

        self._serve_cache = ports
        self._serve_cache_at = time.monotonic()
        return set(ports)

    def is_app_serving(self, app_key):
        """
        Best-effort check of whether this app's HTTPS Serve endpoint is live.
        """
        https_port = APP_HTTPS_PORTS.get(app_key)
        if not https_port:
            return False
        return int(https_port) in self.get_serving_ports()

    def enable_hub_proxy(self, local_port):
        """Expose the local Remote Hub HTTP server at the tailnet root.

        Using a loopback HTTP target avoids Tailscale's Windows administrator
        requirement for serving a filesystem path or Unix socket.
        """
        if not self._local_port_open(local_port):
            return False, (
                f"Remote Hub is not listening on 127.0.0.1:{local_port}. "
                "Start the local Hub server before enabling Tailscale Serve."
            )
        result = self._run([
            "serve", "--bg", "--yes", f"--https={HUB_HTTPS_PORT}",
            f"http://127.0.0.1:{int(local_port)}"
        ], timeout=8)
        self._serve_cache_at = 0.0
        return result

    def enable_hub_page(self, html_path):
        """Backward-compatible wrapper; prefer :meth:`enable_hub_proxy`."""
        return False, (
            "Serving a Hub HTML file directly is disabled on Windows. "
            "Start the local Hub HTTP server and use enable_hub_proxy()."
        )

    def disable_hub_page(self):
        result = self._run(["serve", "--yes", f"--https={HUB_HTTPS_PORT}", "off"], timeout=10)
        self._serve_cache_at = 0.0
        return result

    # =====================================================
    # AUTO-OFF TIMER
    # =====================================================
    # Runs on a background thread via threading.Timer so it fires even
    # if the Settings tab isn't the visible page. `on_auto_off` is
    # called from that background thread — callers touching Tkinter
    # widgets from it must hop back via `widget.after(0, ...)`.

    def start_auto_off_timer(self, minutes, on_auto_off):
        self.cancel_auto_off_timer()
        if not minutes or minutes <= 0:
            return
        self._on_auto_off = on_auto_off
        self._timer_minutes = minutes
        self._timer_started_at = _now()
        self._timer = threading.Timer(minutes * 60, self._fire_auto_off)
        self._timer.daemon = True
        self._timer.start()

    def _fire_auto_off(self):
        cb = self._on_auto_off
        self._timer = None
        self._timer_started_at = None
        if cb:
            cb()

    def cancel_auto_off_timer(self):
        if self._timer:
            try:
                self._timer.cancel()
            except Exception:
                pass
        self._timer = None
        self._timer_started_at = None

    def auto_off_remaining_seconds(self):
        if not self._timer or not self._timer_started_at:
            return None
        elapsed = _now() - self._timer_started_at
        remaining = (self._timer_minutes * 60) - elapsed
        return max(0, int(remaining))


def _now():
    import time
    return time.time()