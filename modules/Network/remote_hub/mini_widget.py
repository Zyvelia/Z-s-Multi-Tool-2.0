# modules/remote_hub/mini_widget.py
#
# Compact "is the phone hub live" readout for the catalog card. Unlike
# the Music Player mini widget, this one doesn't need to wait for the
# full Remote Hub page to have been opened first — the hub's live/off
# state lives in Tailscale itself, not in anything the page creates.
# So it just talks straight to the same HubController the full page
# uses (see ui.py), which is what keeps this button and the page's own
# Go Live / Go Offline buttons doing the exact same thing.
#
# One button: tap to go live, tap again to take it back offline.

import threading

import customtkinter as ctk

from core import theme
from .ui import HubController

REFRESH_MS = 4000


class HubMiniWidget(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.controller = HubController(manager)

        self._busy = False
        self._live = False
        self._poll_job = None

        self.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            self,
            text="Checking…",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w"
        )
        self.status_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.toggle_btn = ctk.CTkButton(
            self,
            text="🟢 Go Live",
            command=self._on_toggle,
            height=26,
            fg_color=theme.PANEL_2,
            hover_color=theme.PANEL_HOVER,
            text_color=theme.TEXT,
            corner_radius=6,
            font=theme.font(12)
        )
        self.toggle_btn.grid(row=1, column=0, sticky="ew")

        self._refresh()

    def destroy(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        super().destroy()

    # ── status polling ───────────────────────────────────────

    def _refresh(self):
        if not self.winfo_exists():
            return

        def work():
            try:
                status, live_apps = self.controller.get_status_sync()
            except Exception:
                status, live_apps = None, {}
            if self.winfo_exists():
                self.after(0, lambda: self._apply_status(status, live_apps))

        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, status, live_apps):
        if not self.winfo_exists():
            return

        # A go-live/go-offline is in flight — leave the button alone,
        # its own completion callback will refresh once it's done.
        if not self._busy:
            live = bool(status and status.get("running") and any(live_apps.values()))
            self._live = live

            if status is None:
                self.status_label.configure(text="Status unavailable", text_color=theme.MUTED)
            elif not status["installed"]:
                self.status_label.configure(text="Tailscale not installed", text_color=theme.MUTED)
            elif live:
                self.status_label.configure(text="🟢 Live on tailnet", text_color=theme.SUCCESS)
            elif status["running"]:
                self.status_label.configure(text="Connected, not live", text_color=theme.MUTED)
            else:
                self.status_label.configure(text="Not connected", text_color=theme.MUTED)

            self.toggle_btn.configure(text="⚪ Go Offline" if live else "🟢 Go Live")

        self._poll_job = self.after(REFRESH_MS, self._refresh)

    # ── button ────────────────────────────────────────────────

    def _on_toggle(self):
        if self._busy:
            return

        self._busy = True
        going_live = not self._live
        self.toggle_btn.configure(state="disabled", text="Starting…" if going_live else "Stopping…")

        def work():
            if going_live:
                self.controller.go_live_sync()
            else:
                self.controller.go_offline_sync()
            if self.winfo_exists():
                self.after(0, self._on_toggle_done)

        threading.Thread(target=work, daemon=True).start()

    def _on_toggle_done(self):
        self._busy = False
        if not self.winfo_exists():
            return
        self.toggle_btn.configure(state="normal")
        self._refresh()


def build(parent, manager):
    return HubMiniWidget(parent, manager)
