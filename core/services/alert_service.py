# core/services/alert_service.py
#
# Sends real-time alerts (Discord webhook + push notification via
# ntfy.sh) whenever someone attempts to unlock the vault - either the
# local desktop lock screen or the remote web server (vault_web_server.py,
# reached over Tailscale). stdlib-only (urllib), matching the
# no-extra-dependency footprint of the rest of core/services.
#
# Config lives in alert_settings.json (paths.data_path) rather than env
# vars, same pattern as auth_service.py / totp_service.py - a desktop
# app's users configure things through a Settings tab, not env vars.

import os
import json
import time
import threading
import datetime
import urllib.request

from core import paths


class AlertService:

    FILE = paths.data_path("alert_settings.json")

    DEFAULTS = {
        "discord_webhook_url": "",
        "ntfy_topic": "",
        "ntfy_server": "https://ntfy.sh",

        # Local desktop lock screen (lock_screen.py)
        "alert_on_local_unlock_failure": True,
        "alert_on_local_unlock_success": False,   # off by default - you unlock your own machine constantly

        # Remote web server (vault_web_server.py, via Tailscale) - this
        # is the real attack surface, so both directions default on.
        "alert_on_remote_login_success": True,
        "alert_on_remote_login_failure": True,

        # Basic spam guard: a brute-force burst shouldn't turn into a
        # hundred pushes in ten seconds. This is on top of, not instead
        # of, vault_web_server.py's own MAX_FAILED_ATTEMPTS lockout.
        "min_seconds_between_alerts": 15,
    }

    def __init__(self):
        if not os.path.exists(self.FILE):
            with open(self.FILE, "w") as f:
                json.dump(self.DEFAULTS, f, indent=4)

        self.settings = self._load()
        self._last_sent = 0.0
        self._lock = threading.Lock()

    # =====================================================
    # SETTINGS
    # =====================================================

    def _load(self):
        try:
            with open(self.FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
        return {**self.DEFAULTS, **data}

    def _save(self):
        with open(self.FILE, "w") as f:
            json.dump(self.settings, f, indent=4)

    def update_settings(self, **kwargs):
        """Called from a future Settings tab UI to change webhook URL,
        ntfy topic, or which events trigger an alert."""
        self.settings.update(kwargs)
        self._save()

    def is_configured(self):
        return bool(self.settings.get("discord_webhook_url") or self.settings.get("ntfy_topic"))

    # =====================================================
    # LOW-LEVEL SENDERS
    # =====================================================

    def _post(self, url, data_bytes, headers):
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"[AlertService] Send failed ({url}): {e}")

    def _send_discord(self, title, description, color):
        url = self.settings.get("discord_webhook_url", "")
        if not url:
            return
        payload = json.dumps({
            "embeds": [{
                "title": title,
                "description": description,
                "color": color,
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }]
        }).encode("utf-8")
        self._post(url, payload, {"Content-Type": "application/json"})

    def _send_push(self, title, message, priority="urgent"):
        topic = self.settings.get("ntfy_topic", "")
        if not topic:
            return
        server = (self.settings.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
        self._post(
            f"{server}/{topic}",
            message.encode("utf-8"),
            {"Title": title, "Priority": priority, "Tags": "warning,lock"},
        )

    def _rate_limited(self):
        min_gap = self.settings.get("min_seconds_between_alerts", 15)
        with self._lock:
            now = time.time()
            if now - self._last_sent < min_gap:
                return True
            self._last_sent = now
            return False

    def _fire(self, discord_title, discord_desc, color, push_title, push_msg, priority):
        if self._rate_limited() or not self.is_configured():
            return
        # Fire-and-forget on background threads so a slow/offline
        # webhook never delays the actual login response.
        threading.Thread(
            target=self._send_discord, args=(discord_title, discord_desc, color), daemon=True
        ).start()
        threading.Thread(
            target=self._send_push, args=(push_title, push_msg, priority), daemon=True
        ).start()

    # =====================================================
    # PUBLIC EVENTS
    # =====================================================

    def local_unlock_attempt(self, success, source="Desktop app"):
        """Call from lock_screen.py's unlock_vault(), right after
        verify_master_password() returns."""
        key = "alert_on_local_unlock_success" if success else "alert_on_local_unlock_failure"
        if not self.settings.get(key, False):
            return

        when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if success:
            self._fire(
                "✅ Vault unlocked", f"**Source:** {source}\n**Time:** {when}", 0x2ECC71,
                "✅ Vault unlocked", f"{source} — {when}", "default"
            )
        else:
            self._fire(
                "🚨 Wrong master password entered", f"**Source:** {source}\n**Time:** {when}", 0xE74C3C,
                "🚨 Wrong master password", f"Failed unlock attempt on {source} — {when}", "max"
            )

    def remote_login_attempt(self, success, ip):
        """Call from vault_web_server.py's _handle_login(), right after
        verify_master_password() returns. This is the more important of
        the two - a remote attempt means it isn't just you at your own
        keyboard."""
        key = "alert_on_remote_login_success" if success else "alert_on_remote_login_failure"
        if not self.settings.get(key, False):
            return

        when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        desc = f"**IP:** {ip}\n**Time:** {when}"
        if success:
            self._fire(
                "🌐 Remote vault login (Tailscale)", desc, 0x3498DB,
                "🌐 Remote vault login", f"Login from {ip} — {when}", "default"
            )
        else:
            self._fire(
                "🚨 Remote login FAILED (Tailscale)", desc, 0xE74C3C,
                "🚨 Remote login failed", f"Wrong password from {ip} — {when}", "max"
            )
