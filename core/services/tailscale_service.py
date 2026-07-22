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
import shutil
import subprocess
import sys
import threading

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
# Player, Security Vault, and YouTube Downloader all be reachable at the
# same time — see enable_app_serve() below. The default port 443 is left
# free for the Remote Hub's landing page (see hub_service.py), which is
# what your phone actually opens first and links out from.
APP_HTTPS_PORTS = {
    "vault": 8443,
    "music": 8444,
    "yt": 8445,
}
HUB_HTTPS_PORT = 443

# tailscale up/down and serve calls can hang if the daemon is in a
# weird state (e.g. waiting on a login flow) — never block the UI
# thread forever.
CLI_TIMEOUT = 20


class TailscaleService:

    def __init__(self):
        self._timer = None
        self._timer_started_at = None
        self._timer_minutes = None
        self._on_auto_off = None  # callback set by whoever starts the timer

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
        return shutil.which("tailscale")

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

    def get_status(self):
        """
        Returns a dict: {installed, running, backend_state, hostname,
        tailscale_ip, serving} — best-effort, never raises.
        """
        if not self.is_installed():
            return {
                "installed": False, "running": False, "backend_state": "NotInstalled",
                "hostname": "", "tailscale_ip": "", "serving": False,
            }

        ok, out = self._run(["status", "--json"])
        if not ok:
            return {
                "installed": True, "running": False, "backend_state": "Stopped",
                "hostname": "", "tailscale_ip": "", "serving": False,
            }

        try:
            data = json.loads(out)
        except Exception:
            data = {}

        backend_state = data.get("BackendState", "Unknown")
        self_node = data.get("Self", {}) or {}
        ips = self_node.get("TailscaleIPs") or []

        # DNSName is the full MagicDNS name (e.g. "my-desktop.tailnet-name.ts.net."),
        # which is what actually needs to go in https://.../ URLs. HostName is just
        # the short local name and won't resolve from other tailnet devices — using
        # it was why "open https://<hostname>/ on your phone" never worked.
        dns_name = (self_node.get("DNSName") or "").rstrip(".")
        display_hostname = dns_name or self_node.get("HostName", "")

        return {
            "installed": True,
            "running": backend_state == "Running",
            "backend_state": backend_state,
            "hostname": display_hostname,
            "tailscale_ip": ips[0] if ips else "",
            "serving": self._is_serving(),
        }

    def _is_serving(self):
        ok, out = self._run(["serve", "status"])
        if not ok:
            return False
        return bool(out) and "no serve" not in out.lower() and "not configured" not in out.lower()

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
        Join the tailnet (`tailscale up`). Safe to call if already up.

        --reset is always passed: without it, `tailscale up` refuses to
        change any setting that differs from whatever non-default flags
        are already active (from a previous run, another tool, or the
        Tailscale GUI) and errors out asking you to either add --reset
        or explicitly re-state every current non-default flag. Since
        this app's Settings tab is meant to be the source of truth for
        its own flags, --reset makes `up` fully apply exactly what's
        configured here instead of diffing against prior state.
        """
        args = ["up", "--reset"]
        if accept_routes:
            args.append("--accept-routes")
        if hostname:
            args += ["--hostname", hostname]
        if auth_key:
            args += ["--authkey", auth_key]
        return self._run(args, timeout=60)

    def disconnect(self):
        """Leave the tailnet (`tailscale down`). Also drops any active serve."""
        self.disable_serve()
        return self._run(["down"])

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
        return self._run(["serve", "reset"])

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
        return self._run(
            ["serve", "--bg", f"--https={https_port}", f"http://127.0.0.1:{local_port}"],
            timeout=60,
        )

    def disable_app_serve(self, app_key):
        https_port = APP_HTTPS_PORTS.get(app_key)
        if not https_port:
            return False, f"Unknown app '{app_key}'."
        return self._run(["serve", f"--https={https_port}", "off"], timeout=30)

    def is_app_serving(self, app_key):
        """
        Best-effort check of whether this app's own HTTPS port currently
        has a live serve entry. Same "never raise, just say no" philosophy
        as _is_serving() — this only drives a status label, not anything
        safety-critical.
        """
        https_port = APP_HTTPS_PORTS.get(app_key)
        if not https_port:
            return False
        ok, out = self._run(["serve", "status"])
        if not ok or not out:
            return False
        return f":{https_port}" in out

    def enable_hub_page(self, html_path):
        """
        Serves a small static HTML file (built by hub_service.py) at
        this device's default tailnet address — https://<this-device>.<tailnet>/
        — so opening that one URL on your phone gives you buttons to
        whichever of the three apps are currently live, each on its own
        port from enable_app_serve() above. `tailscale serve` can serve a
        static file directly with no local web server needed for this part.
        """
        return self._run(["serve", "--bg", html_path], timeout=60)

    def disable_hub_page(self):
        return self._run(["serve", f"--https={HUB_HTTPS_PORT}", "off"], timeout=30)

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