# modules/remote_hub/ui.py
#
# The whole point of this module: one page, one button, reachable from
# your phone as a single URL — https://<this-device>.<tailnet>/ — that
# links out to whichever of Music Player / Security Vault / YouTube
# Downloader you've got live, each on its own fixed Tailscale HTTPS port
# (see APP_HTTPS_PORTS in core/services/tailscale_service.py). No more
# hunting for three different addresses or flipping switches in three
# different apps before you can reach the one you actually want.
#
# "Go Live" does four things, in order:
#   1. Connects to your tailnet if you aren't already (tailscale up).
#   2. Makes sure each app's own local web server is running — creating
#      it on demand from its saved settings if you've never actually
#      opened that app's page this session (same lazy pattern App.__init__
#      already uses for its own auto-start-on-launch feature).
#   3. Points Tailscale's `serve` feature at each one on its own port.
#   4. Builds and serves the hub landing page itself on the default
#      address (443) — see core/services/hub_service.py.
#
# "Go Offline" reverses step 3 and 4 only — it leaves the loopback
# servers running (they're harmless; 127.0.0.1 only) so "Go Live" again
# is instant, but nothing is reachable from your tailnet until you do.

import json
import os
import threading

import customtkinter as ctk
from tkinter import messagebox

from core import theme
from core.services import hub_service

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2
ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
TEXT = theme.TEXT
MUTED = theme.MUTED
SUCCESS = theme.SUCCESS
DANGER = theme.DANGER
DANGER_BG = theme.DANGER_BG
DANGER_HOVER = theme.DANGER_HOVER

STATUS_POLL_MS = 4000

APPS = [
    ("vault", "🔒 Security Vault"),
    ("music", "🎵 Music Player"),
    ("yt", "⬇️ YouTube Downloader"),
]


class RemoteHubPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager
        self.tailscale = manager.container.tailscale_service

        self._poll_job = None

        wrap = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        self._build_header(wrap)
        self._build_go_live_panel(wrap)
        self._build_status_panel(wrap)

        self._refresh_status()
        self._start_polling()

    def destroy(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        super().destroy()

    # =====================================================
    # UI
    # =====================================================

    def _build_header(self, parent):
        ctk.CTkLabel(
            parent, text="📡 Remote Hub", font=("Segoe UI", 22, "bold"), text_color=TEXT
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            parent,
            text="One address for your phone that links to whichever of your apps are live, "
                 "instead of remembering three. Reachable only from devices on your own "
                 "Tailscale network.",
            font=("Segoe UI", 12), text_color=MUTED, anchor="w", justify="left", wraplength=760,
        ).pack(anchor="w", pady=(0, 16))

    def _build_go_live_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", pady=(0, 12))

        self.hub_status_label = ctk.CTkLabel(
            panel, text="Checking…", font=("Segoe UI", 14), text_color=MUTED,
            anchor="w", justify="left", wraplength=700,
        )
        self.hub_status_label.pack(fill="x", padx=16, pady=(16, 10))

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 16))

        self.go_live_btn = ctk.CTkButton(
            row, text="🟢 Go Live", fg_color=SUCCESS, hover_color="#33b57d",
            text_color="#0b0d10", height=42, font=("Segoe UI", 14, "bold"),
            command=self._on_go_live,
        )
        self.go_live_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.go_offline_btn = ctk.CTkButton(
            row, text="⚪ Go Offline", fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            text_color=DANGER, height=42, font=("Segoe UI", 14, "bold"),
            command=self._on_go_offline,
        )
        self.go_offline_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _build_status_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x")

        ctk.CTkLabel(
            panel, text="Per-app status", font=("Segoe UI", 14, "bold"), text_color=TEXT
        ).pack(anchor="w", padx=16, pady=(14, 6))

        self._app_labels = {}
        for key, label in APPS:
            row = ctk.CTkFrame(panel, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(row, text=label, font=("Segoe UI", 13), text_color=TEXT).pack(side="left")
            lbl = ctk.CTkLabel(row, text="⚪ Off", font=("Segoe UI", 13), text_color=MUTED)
            lbl.pack(side="right")
            self._app_labels[key] = lbl

        ctk.CTkLabel(
            panel,
            text="Fine-grained on/off for a single app still lives in that app's own "
                 "Settings tab — this page is for the phone-facing address as a whole.",
            font=("Segoe UI", 11), text_color=MUTED, anchor="w", justify="left", wraplength=700,
        ).pack(fill="x", padx=16, pady=(10, 14))

    # =====================================================
    # LAZY SERVER ACCESS — mirrors core/app.py's own auto-start logic,
    # for the case where you open Remote Hub before ever opening the
    # Music Player or YouTube Downloader page this session.
    # =====================================================

    def _get_vault_web_server(self):
        return self.manager.container.vault_web_server

    def _get_music_web_server(self):
        existing = getattr(self.manager, "music_web_server", None)
        if existing:
            return existing
        from modules.music_player import db as music_db
        from modules.music_player.web_server import MusicWebServer
        server = MusicWebServer(library=music_db.Library())
        self.manager.music_web_server = server
        return server

    def _get_yt_web_server(self):
        existing = getattr(self.manager, "yt_web_server", None)
        if existing:
            return existing
        from modules.yt_downloader import ui as yt_ui
        from modules.yt_downloader.web_server import YTWebServer
        settings = {}
        try:
            if os.path.exists(yt_ui.SETTINGS_FILE):
                with open(yt_ui.SETTINGS_FILE) as f:
                    settings = json.load(f)
        except Exception:
            settings = {}
        output_dir = settings.get("output_dir") or os.path.expanduser("~")
        server = YTWebServer(
            get_output_dir=lambda: output_dir,
            get_cookie_file=lambda: settings.get("cookie_file", ""),
            get_ffmpeg_dir=lambda: None,
            default_format=settings.get("format", "mp4"),
            default_type=settings.get("type", "video"),
            default_quality=settings.get("quality", "192"),
        )
        server.access_code = settings.get("access_code", "")
        self.manager.yt_web_server = server
        return server

    def _ports(self):
        vault_cfg = self.tailscale.load_config()
        from modules.music_player import db as music_db
        music_port = int(music_db.Library().get_setting("remote_port", "8766") or 8766)

        from modules.yt_downloader import ui as yt_ui
        yt_settings = {}
        try:
            if os.path.exists(yt_ui.SETTINGS_FILE):
                with open(yt_ui.SETTINGS_FILE) as f:
                    yt_settings = json.load(f)
        except Exception:
            pass
        yt_port = int(yt_settings.get("remote_port", 8767) or 8767)

        return {
            "vault": int(vault_cfg.get("web_port", 8765) or 8765),
            "music": music_port,
            "yt": yt_port,
        }

    # =====================================================
    # GO LIVE / GO OFFLINE
    # =====================================================

    def _on_go_live(self):
        self.go_live_btn.configure(state="disabled", text="Starting…")

        def work():
            errors = []

            status = self.tailscale.get_status()
            if not status["installed"]:
                self.after(0, lambda: self._go_live_failed(
                    "Tailscale isn't installed on this device."))
                return
            if not status["running"]:
                cfg = self.tailscale.load_config()
                ok, msg = self.tailscale.connect(
                    hostname=cfg.get("hostname") or None,
                    auth_key=cfg.get("auth_key") or None,
                    accept_routes=cfg.get("accept_routes", True),
                )
                if not ok:
                    self.after(0, lambda: self._go_live_failed(f"Couldn't connect to Tailscale: {msg}"))
                    return
                status = self.tailscale.get_status()

            ports = self._ports()

            vault_srv = self._get_vault_web_server()
            if not vault_srv.is_running():
                ok, msg = vault_srv.start(ports["vault"])
                if not ok:
                    errors.append(f"Security Vault server: {msg}")
            if vault_srv.is_running():
                ok, msg = self.tailscale.enable_app_serve("vault", ports["vault"])
                if not ok:
                    errors.append(f"Security Vault Tailscale: {msg}")

            music_srv = self._get_music_web_server()
            if not music_srv.is_running():
                ok, msg = music_srv.start(ports["music"])
                if not ok:
                    errors.append(f"Music Player server: {msg}")
            if music_srv.is_running():
                ok, msg = self.tailscale.enable_app_serve("music", ports["music"])
                if not ok:
                    errors.append(f"Music Player Tailscale: {msg}")

            yt_srv = self._get_yt_web_server()
            if not yt_srv.is_running():
                ok, msg = yt_srv.start(ports["yt"])
                if not ok:
                    errors.append(f"YouTube Downloader server: {msg}")
            if yt_srv.is_running():
                ok, msg = self.tailscale.enable_app_serve("yt", ports["yt"])
                if not ok:
                    errors.append(f"YouTube Downloader Tailscale: {msg}")

            live_apps = [key for key in ("vault", "music", "yt") if self.tailscale.is_app_serving(key)]
            hostname = status.get("hostname") or "this-device"
            hub_path = hub_service.write_hub_html(hostname, live_apps)
            ok, msg = self.tailscale.enable_hub_page(hub_path)
            if not ok:
                errors.append(f"Hub landing page: {msg}")

            self.after(0, lambda: self._go_live_done(errors))

        threading.Thread(target=work, daemon=True).start()

    def _go_live_failed(self, msg):
        self.go_live_btn.configure(state="normal", text="🟢 Go Live")
        messagebox.showerror("Couldn't go live", msg)
        self._refresh_status()

    def _go_live_done(self, errors):
        self.go_live_btn.configure(state="normal", text="🟢 Go Live")
        if errors:
            messagebox.showwarning(
                "Went live with some issues",
                "Some apps didn't come up cleanly:\n\n" + "\n".join(errors),
            )
        self._refresh_status()

    def _on_go_offline(self):
        self.go_offline_btn.configure(state="disabled", text="Stopping…")

        def work():
            self.tailscale.disable_hub_page()
            for key, _ in APPS:
                self.tailscale.disable_app_serve(key)
            self.after(0, self._go_offline_done)

        threading.Thread(target=work, daemon=True).start()

    def _go_offline_done(self):
        self.go_offline_btn.configure(state="normal", text="⚪ Go Offline")
        self._refresh_status()

    # =====================================================
    # STATUS POLLING
    # =====================================================

    def _start_polling(self):
        self._poll_job = self.after(STATUS_POLL_MS, self._poll_tick)

    def _poll_tick(self):
        self._refresh_status()
        self._poll_job = self.after(STATUS_POLL_MS, self._poll_tick)

    def _refresh_status(self):
        def work():
            status = self.tailscale.get_status()
            live_apps = {key: self.tailscale.is_app_serving(key) for key, _ in APPS} \
                if status["running"] else {key: False for key, _ in APPS}
            self.after(0, lambda: self._apply_status(status, live_apps))

        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, status, live_apps):
        if not self.winfo_exists():
            return

        for key, live in live_apps.items():
            lbl = self._app_labels.get(key)
            if lbl:
                lbl.configure(
                    text="🟢 Live" if live else "⚪ Off",
                    text_color=SUCCESS if live else MUTED,
                )

        if not status["installed"]:
            self.hub_status_label.configure(
                text="Tailscale isn't installed on this device — install it first "
                     "(any app's Settings tab has a shortcut).",
                text_color=MUTED,
            )
        elif not status["running"]:
            self.hub_status_label.configure(
                text="⚪ Not connected to your tailnet yet. Tap Go Live to connect and "
                     "bring everything up in one step.",
                text_color=MUTED,
            )
        elif any(live_apps.values()):
            hostname = status.get("hostname") or "this-device"
            self.hub_status_label.configure(
                text=f"🟢 Live — open https://{hostname}/ on your phone (signed into the "
                     f"same tailnet) to pick an app.",
                text_color=SUCCESS,
            )
        else:
            self.hub_status_label.configure(
                text="⚪ Connected to Tailscale, but nothing is live yet. Tap Go Live.",
                text_color=MUTED,
            )
