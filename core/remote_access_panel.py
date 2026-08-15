# core/remote_access_panel.py
#
# A small, reusable "Remote Access" strip — a toggle button + status
# label + optional access-code field — that starts/stops a module's
# local web server and points Tailscale's `serve` at it, exactly like
# the bespoke versions in modules/yt_downloader/ui.py and
# modules/Security_Vault/remote_access_tab.py, just factored out so
# Gaming Hub and Soundboard don't each need their own copy of the
# ~150 lines of connect/start/stop/poll plumbing.
#
# Usage (dropped into any module page's build_ui()):
#
#   from core.remote_access_panel import RemoteAccessPanel
#   self.remote_panel = RemoteAccessPanel(
#       self, manager=self.manager, app_key="games",
#       web_server=self.web_server, port=8446,
#   )
#   self.remote_panel.pack(fill="x", padx=16, pady=(0, 12))

import threading

import customtkinter as ctk
from tkinter import messagebox

from core import theme

BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
DANGER = theme.DANGER
SUCCESS = theme.SUCCESS
TEXT = theme.TEXT
MUTED = theme.MUTED

STATUS_POLL_MS = 4000


class RemoteAccessPanel(ctk.CTkFrame):
    """
    app_key: the APP_HTTPS_PORTS / hub_service.APPS key ("games", "soundboard", ...)
    web_server: an object with .is_running(), .start(port), .access_code
    port: the fixed external port for this app (APP_HTTPS_PORTS[app_key])
    """

    def __init__(self, parent, manager, app_key, web_server, port, **kw):
        super().__init__(parent, fg_color=PANEL, corner_radius=10, **kw)
        self.manager = manager
        self.app_key = app_key
        self.web_server = web_server
        self.port = port
        self.tailscale = manager.container.tailscale_service
        self._poll_job = None

        self._build()
        self._refresh_status()

    def _build(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)

        self._start_btn = ctk.CTkButton(
            row, text="\u25b6 Start Remote Access", command=self._start,
            fg_color=ACCENT, hover_color=theme.ACCENT_DIM, text_color="white",
            height=32, corner_radius=8, width=180,
        )
        self._start_btn.pack(side="left")

        self._stop_btn = ctk.CTkButton(
            row, text="\u25a0 Stop", command=self._stop,
            fg_color=DANGER, hover_color=theme.DANGER_HOVER, text_color="white",
            height=32, corner_radius=8, width=80,
        )
        self._stop_btn.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(row, text="Access code (optional)", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))
        self._code_entry = ctk.CTkEntry(
            row, width=110, show="\u2022", fg_color=PANEL_2, text_color=TEXT,
            border_color=PANEL_2, corner_radius=8)
        self._code_entry.pack(side="left")

        self._status_label = ctk.CTkLabel(
            self, text="Checking status\u2026", text_color=MUTED,
            font=("Segoe UI", 12), anchor="w")
        self._status_label.pack(fill="x", padx=12, pady=(0, 10))

    def _start(self):
        self.web_server.access_code = self._code_entry.get().strip()

        status = self.tailscale.get_status()
        if not status["installed"]:
            messagebox.showwarning(
                "Tailscale not installed",
                "Install Tailscale first (see the Security Vault Settings tab).")
            return
        if not status["running"]:
            if not messagebox.askyesno(
                "Not connected",
                "You're not connected to Tailscale yet. Connect now, then start remote access?",
            ):
                return
            cfg = self.tailscale.load_config()
            self.tailscale.connect(
                hostname=cfg.get("hostname") or None,
                auth_key=cfg.get("auth_key") or None,
                accept_routes=cfg.get("accept_routes", True),
            )

        self._start_btn.configure(state="disabled", text="Starting\u2026")

        def work():
            ok, msg = (True, "already running") if self.web_server.is_running() \
                else self.web_server.start(self.port)
            if ok:
                ok2, msg2 = self.tailscale.enable_app_serve(self.app_key, self.port)
                if not ok2:
                    ok, msg = ok2, msg2
            self.after(0, lambda: self._after_start(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_start(self, ok, msg):
        if not self.winfo_exists():
            return
        self._start_btn.configure(state="normal", text="\u25b6 Start Remote Access")
        if not ok:
            messagebox.showerror("Couldn't start remote access", msg)
        self._refresh_status()

    def _stop(self):
        self.tailscale.disable_app_serve(self.app_key)
        self._refresh_status()

    def _refresh_status(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass

        def work():
            status = self.tailscale.get_status()
            live = status["running"] and self.tailscale.is_app_serving(self.app_key)
            self.after(0, lambda: self._apply_status(status, live))

        threading.Thread(target=work, daemon=True).start()
        self._poll_job = self.after(STATUS_POLL_MS, self._refresh_status)

    def _apply_status(self, status, live):
        if not self.winfo_exists():
            return
        if live:
            hostname = status.get("hostname") or "this-device"
            self._status_label.configure(
                text=f"\U0001f7e2 Live \u2014 https://{hostname}:{self.port}/",
                text_color=SUCCESS,
            )
        else:
            self._status_label.configure(
                text="\u26aa Off \u2014 tap Start Remote Access to reach this from your phone",
                text_color=MUTED,
            )

    def on_leave(self):
        """Call from the parent page's on_leave() to stop polling."""
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
