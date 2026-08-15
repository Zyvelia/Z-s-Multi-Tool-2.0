# modules/quick_send/ui.py
#
# Desktop side of Quick Send: shows/changes the Inbox and Outbox
# folders, and a live list of recently received files. The actual
# transfer happens over HTTP via web_server.py — this tab is just
# configuration + visibility into what's arrived.

import os
import time
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import theme
from . import storage


def _format_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _time_ago(ts):
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _open_in_explorer(path):
    try:
        os.makedirs(path, exist_ok=True)
        os.startfile(path)  # Windows-only, matches the rest of this app
    except Exception as e:
        messagebox.showerror("Couldn't Open Folder", str(e))


class QuickSendPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager
        self._build_ui()
        self.refresh()

    # =====================================================
    # LAYOUT
    # =====================================================

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        ctk.CTkLabel(
            header, text="📤  Quick Send", font=theme.font(22, "bold"),
            text_color=theme.TEXT
        ).pack(side="left", padx=theme.PAD_LG, pady=14)

        ctk.CTkButton(
            header, text="⟳ Refresh", width=100, height=32,
            command=self.refresh, **theme.secondary_button_style()
        ).pack(side="right", padx=(0, theme.PAD_LG), pady=14)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        # ── Inbox folder ─────────────────────────────
        inbox_panel = ctk.CTkFrame(body, **theme.panel_style())
        inbox_panel.grid(row=0, column=0, sticky="ew", pady=(0, theme.PAD))
        inbox_panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            inbox_panel, text="INBOX  (files your phone sends land here)",
            font=theme.font(10, "bold"), text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=theme.PAD_LG, pady=(theme.PAD, 4))

        self.inbox_path_label = ctk.CTkLabel(
            inbox_panel, text="", font=theme.font(12), text_color=theme.MUTED,
            anchor="w"
        )
        self.inbox_path_label.grid(row=1, column=0, columnspan=1, sticky="ew",
                                    padx=(theme.PAD_LG, 6), pady=(0, theme.PAD))

        ctk.CTkButton(
            inbox_panel, text="Open Folder", width=110, height=30,
            command=lambda: _open_in_explorer(storage.get_config()["inbox_dir"]),
            **theme.secondary_button_style()
        ).grid(row=1, column=1, padx=6, pady=(0, theme.PAD))

        ctk.CTkButton(
            inbox_panel, text="Change...", width=90, height=30,
            command=self._change_inbox, **theme.secondary_button_style()
        ).grid(row=1, column=2, padx=(6, theme.PAD_LG), pady=(0, theme.PAD))

        # ── Outbox folder ─────────────────────────────
        outbox_panel = ctk.CTkFrame(body, **theme.panel_style())
        outbox_panel.grid(row=1, column=0, sticky="ew", pady=(0, theme.PAD))
        outbox_panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            outbox_panel, text="SHARED  (drop files here for your phone to pull down)",
            font=theme.font(10, "bold"), text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=theme.PAD_LG, pady=(theme.PAD, 4))

        self.outbox_path_label = ctk.CTkLabel(
            outbox_panel, text="", font=theme.font(12), text_color=theme.MUTED,
            anchor="w"
        )
        self.outbox_path_label.grid(row=1, column=0, sticky="ew",
                                     padx=(theme.PAD_LG, 6), pady=(0, theme.PAD))

        ctk.CTkButton(
            outbox_panel, text="Open Folder", width=110, height=30,
            command=lambda: _open_in_explorer(storage.get_config()["outbox_dir"]),
            **theme.secondary_button_style()
        ).grid(row=1, column=1, padx=6, pady=(0, theme.PAD))

        ctk.CTkButton(
            outbox_panel, text="Change...", width=90, height=30,
            command=self._change_outbox, **theme.secondary_button_style()
        ).grid(row=1, column=2, padx=(6, theme.PAD_LG), pady=(0, theme.PAD))

        # ── Recently received ─────────────────────────
        received_panel = ctk.CTkFrame(body, **theme.panel_style())
        received_panel.grid(row=2, column=0, sticky="nsew")
        received_panel.grid_rowconfigure(1, weight=1)
        received_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            received_panel, text="RECENTLY RECEIVED", font=theme.font(10, "bold"),
            text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=theme.PAD_LG, pady=(theme.PAD, 4))

        self.received_frame = ctk.CTkScrollableFrame(received_panel, fg_color="transparent")
        self.received_frame.grid(row=1, column=0, sticky="nsew", padx=(6, 6), pady=(0, 6))
        self.received_frame.grid_columnconfigure(0, weight=1)

    # =====================================================
    # ACTIONS
    # =====================================================

    def _change_inbox(self):
        current = storage.get_config()["inbox_dir"]
        chosen = filedialog.askdirectory(initialdir=current, title="Choose Inbox Folder")
        if chosen:
            storage.set_inbox_dir(chosen)
            self.refresh()

    def _change_outbox(self):
        current = storage.get_config()["outbox_dir"]
        chosen = filedialog.askdirectory(initialdir=current, title="Choose Shared Folder")
        if chosen:
            storage.set_outbox_dir(chosen)
            self.refresh()

    # =====================================================
    # REFRESH
    # =====================================================

    def refresh(self):
        cfg = storage.get_config()
        self.inbox_path_label.configure(text=cfg["inbox_dir"])
        self.outbox_path_label.configure(text=cfg["outbox_dir"])

        for w in self.received_frame.winfo_children():
            w.destroy()

        entries = storage.get_received_log()[:30]
        if not entries:
            ctk.CTkLabel(
                self.received_frame, text="Nothing received yet.",
                font=theme.font(12), text_color=theme.MUTED
            ).grid(row=0, column=0, sticky="w", padx=6, pady=10)
            return

        for i, entry in enumerate(entries):
            row = ctk.CTkFrame(self.received_frame, fg_color=theme.PANEL_2, corner_radius=theme.RADIUS_SM)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row, text=entry.get("filename", "?"), font=theme.font(13),
                text_color=theme.TEXT, anchor="w"
            ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))

            meta = f'{_format_size(entry.get("size", 0))} · {_time_ago(entry.get("received_at", 0))}'
            ctk.CTkLabel(
                row, text=meta, font=theme.font(11),
                text_color=theme.MUTED, anchor="w"
            ).grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def on_show(self):
        self.refresh()
