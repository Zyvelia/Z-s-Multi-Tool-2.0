# modules/notification_mirror/ui.py
#
# Desktop side is intentionally light: turn mirroring on/off (which is
# also where the one-time Windows permission prompt happens), start
# remote access so the phone can reach it, and a live log so you can see
# it's actually working. The richer controls from the spec's mockup
# (per-app checklist, privacy mode, per-option toggles) live on the
# phone — see mobile/lib/screens/notifications_screen.dart — since
# that's the surface you'd actually be reaching for day to day. All of
# those settings are already wired through storage.py / web_server.py
# regardless of which side changes them.

import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

from core import theme
from core.remote_access_panel import RemoteAccessPanel
from core.services.tailscale_service import APP_HTTPS_PORTS
from . import storage
from .listener import ListenerStatus, AccessResult

BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
TEXT = theme.TEXT
MUTED = theme.MUTED
SUCCESS = theme.SUCCESS
DANGER = theme.DANGER

MAX_LOG_LINES = 40


class NotificationMirrorPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager

        # Same lazy-create-and-stash pattern as every other remote-access
        # module — Remote Hub's HubController creates this first if Go
        # Live was pressed before this page was ever opened; either way
        # whoever gets here first wins and the other reuses it.
        existing = getattr(manager, "notification_mirror_web_server", None)
        if existing:
            self.web_server = existing
        else:
            from .web_server import NotificationWebServer
            self.web_server = NotificationWebServer(settings=storage.get_settings())
            manager.notification_mirror_web_server = self.web_server

        self._poll_job = None

        wrap = ctk.CTkScrollableFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        self._build_header(wrap)
        self._build_toggle_panel(wrap)

        self.remote_panel = RemoteAccessPanel(
            wrap, manager=manager, app_key="notifications",
            web_server=self.web_server, port=APP_HTTPS_PORTS["notifications"],
        )
        self.remote_panel.pack(fill="x", pady=(0, 12))

        self._build_log_panel(wrap)

        self._refresh_toggle_state()
        self._start_polling()

    def destroy(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        if hasattr(self, "remote_panel"):
            self.remote_panel.on_leave()
        super().destroy()

    # =====================================================
    # UI
    # =====================================================

    def _build_header(self, parent):
        ctk.CTkLabel(
            parent, text="🔔 Z Connect Notifications",
            font=("Segoe UI", 22, "bold"), text_color=TEXT,
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            parent,
            text="Mirrors notifications from Discord, Steam, Chrome, and other Windows "
                 "apps to your phone. Off by default — nothing is sent until you turn "
                 "this on. Per-app filtering, privacy mode, and history live in the "
                 "Notifications tab of the phone app.",
            font=("Segoe UI", 12), text_color=MUTED, anchor="w", justify="left",
            wraplength=760,
        ).pack(anchor="w", pady=(0, 16))

    def _build_toggle_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", pady=(0, 12))

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(16, 6))

        ctk.CTkLabel(row, text="Notification Mirroring", font=("Segoe UI", 14, "bold"),
                     text_color=TEXT).pack(side="left")

        self._toggle = ctk.CTkSwitch(
            row, text="", command=self._on_toggle,
            progress_color=SUCCESS, button_color="white",
        )
        self._toggle.pack(side="right")

        self._status_label = ctk.CTkLabel(
            panel, text="Checking…", font=("Segoe UI", 12), text_color=MUTED,
            anchor="w", justify="left", wraplength=700,
        )
        self._status_label.pack(fill="x", padx=16, pady=(0, 16))

    def _build_log_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="both", expand=True)

        ctk.CTkLabel(panel, text="Recent activity", font=("Segoe UI", 14, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=16, pady=(14, 6))

        self._log_box = ctk.CTkTextbox(
            panel, fg_color=PANEL_2, text_color=MUTED, font=("Consolas", 11),
            height=220, wrap="word",
        )
        self._log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._log_box.configure(state="disabled")

        # Hooks directly into the listener's callbacks for a live feed —
        # this runs in-process, so it doesn't need to go through the web
        # server/SSE round trip the phone uses.
        original_on_event = self.web_server.listener._on_event

        def tapped(kind, payload):
            original_on_event(kind, payload)
            if kind == "added":
                self.after(0, lambda: self._append_log(
                    f"{payload['app_name']}: {payload['title'] or '(no title)'}"
                ))

        self.web_server.listener._on_event = tapped

    def _append_log(self, text):
        if not self.winfo_exists():
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{stamp}] {text}\n")
        # Trim from the top so this stays a rolling window, not an
        # ever-growing widget.
        lines = self._log_box.get("1.0", "end").splitlines()
        if len(lines) > MAX_LOG_LINES:
            self._log_box.delete("1.0", "end")
            self._log_box.insert("end", "\n".join(lines[-MAX_LOG_LINES:]) + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    # =====================================================
    # TOGGLE
    # =====================================================

    def _on_toggle(self):
        wants_on = bool(self._toggle.get())

        if not wants_on:
            settings = storage.get_settings()
            settings["enabled"] = False
            storage.save_settings(settings)
            self.web_server.listener.stop()
            self._refresh_toggle_state()
            return

        # Turning ON: request the Windows permission on THIS (UI) thread —
        # UserNotificationListener.RequestAccessAsync is documented to
        # need a UI-thread caller, and this button click already is one.
        result = self.web_server.listener.request_access()

        if result == AccessResult.WINRT_UNAVAILABLE:
            messagebox.showerror(
                "Not available",
                "The Windows notification-listener packages aren't installed. "
                "Run: pip install winrt-Windows.UI.Notifications.Management "
                "winrt-Windows.UI.Notifications",
            )
            self._toggle.deselect()
            return

        if result == AccessResult.NO_PACKAGE_IDENTITY:
            messagebox.showerror(
                "Not available",
                "Windows notification mirroring isn't available in this "
                "build of Z's Multi Tool.",
            )
            self._toggle.deselect()
            return

        if result == AccessResult.DENIED:
            messagebox.showwarning(
                "Permission needed",
                "Windows notification access was denied.\n\n"
                "Open Settings > Privacy & security > Notifications > "
                "Let apps access your notifications, enable it for Z's "
                "Multi Tool, then try again.",
            )
            self._toggle.deselect()
            return

        if result == AccessResult.UNSPECIFIED:
            messagebox.showinfo(
                "Try again",
                "The permission prompt was closed without a choice. "
                "Click the toggle again to re-open it.",
            )
            self._toggle.deselect()
            return

        if result == AccessResult.ERROR:
            messagebox.showerror(
                "Unexpected error",
                "Something went wrong requesting notification access. "
                "Check the Recent activity log below for details.",
            )
            self._toggle.deselect()
            return

        # result == AccessResult.ALLOWED
        settings = storage.get_settings()
        settings["enabled"] = True
        storage.save_settings(settings)
        self.web_server.listener.start()
        self._refresh_toggle_state()

    def _refresh_toggle_state(self):
        enabled = storage.get_settings().get("enabled", False)
        if enabled:
            self._toggle.select()
        else:
            self._toggle.deselect()
        self._apply_status_label()

    def _apply_status_label(self):
        status = self.web_server.listener.status
        text_map = {
            ListenerStatus.STOPPED: ("⚪ Off", MUTED),
            ListenerStatus.STARTING: ("🟡 Starting…", MUTED),
            ListenerStatus.RUNNING: ("🟢 Watching for notifications", SUCCESS),
            ListenerStatus.ACCESS_DENIED: (
                "🔴 Windows denied notification access — check Settings > "
                "Privacy & security > Notifications", DANGER),
            ListenerStatus.UNAVAILABLE: (
                "🔴 WinRT notification packages not installed", DANGER),
            ListenerStatus.NO_PACKAGE_IDENTITY: (
                "🔴 Requires the packaged build — see packaging/README.md", DANGER),
            ListenerStatus.ERROR: ("🔴 Listener error — see console log", DANGER),
        }
        text, color = text_map.get(status, ("Unknown", MUTED))
        self._status_label.configure(text=text, text_color=color)

    def _start_polling(self):
        self._apply_status_label()
        self._poll_job = self.after(3000, self._start_polling)
