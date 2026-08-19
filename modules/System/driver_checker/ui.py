"""
Driver/Update Checker — UI.

Follows the shared ZsMultiTool module convention: exposes a CTkFrame
subclass the plugin manager instantiates into `manager.container`.

Each tab's scan runs on a plain background thread (a single blocking
call rather than a stream of progress events, so the lighter-weight
threading.Thread + self.after(0, ...) callback pattern is used here
instead of the queue-polling worker convention from File Shredder /
Duplicate File Finder).
"""

from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from .backend import (
    WIN32COM_AVAILABLE,
    DriverInfo,
    SoftwareUpdateInfo,
    UpdateInfo,
    check_driver_updates,
    check_software_updates,
    list_installed_drivers,
)
from core import theme as t


class DriverCheckerModule(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=t.BG, **kwargs)
        self.manager = manager

        self._drivers: list[DriverInfo] = []
        self.driver_search_var = tk.StringVar()
        self.driver_search_var.trace_add("write", lambda *_: self._render_driver_rows())

        self._build_layout()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkLabel(
            self, text="🔧  Driver / Update Checker",
            font=t.font(20, "bold"), text_color=t.TEXT,
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            self,
            text=(
                "Installed drivers, pending driver updates via Windows Update, "
                "and pending app/package updates via winget — three separate "
                "checks, each run on demand."
            ),
            font=t.font(12), text_color=t.MUTED, anchor="w", justify="left",
            wraplength=760,
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        self.tabview = ctk.CTkTabview(
            self, fg_color=t.PANEL,
            segmented_button_fg_color=t.PANEL_2,
            segmented_button_selected_color=t.ACCENT,
            segmented_button_selected_hover_color=t.ACCENT_HOVER,
            text_color=t.TEXT,
        )
        self.tabview.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))

        self.tabview.add("Installed Drivers")
        self.tabview.add("Driver Updates")
        self.tabview.add("Software Updates")

        self._build_drivers_tab(self.tabview.tab("Installed Drivers"))
        self._build_driver_updates_tab(self.tabview.tab("Driver Updates"))
        self._build_software_updates_tab(self.tabview.tab("Software Updates"))

    # ---------------------------------------------------------- shared bits

    def _tab_header_row(self, parent, scan_label: str, scan_command) -> tuple[ctk.CTkButton, ctk.CTkLabel]:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(4, 8))
        btn = ctk.CTkButton(row, text=scan_label, **t.primary_button_style(), command=scan_command)
        btn.pack(side="left")
        status = ctk.CTkLabel(row, text="", text_color=t.MUTED, font=t.font(12))
        status.pack(side="left", padx=(12, 0))
        return btn, status

    def _scroll_area(self, parent) -> ctk.CTkScrollableFrame:
        area = ctk.CTkScrollableFrame(parent, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        area.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        area.grid_columnconfigure(0, weight=1)
        return area

    # -------------------------------------------------------- installed drivers

    def _build_drivers_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        self.drivers_btn, self.drivers_status = self._tab_header_row(
            parent, "Scan Installed Drivers", self._start_driver_scan,
        )

        search = ctk.CTkEntry(
            parent, placeholder_text="Filter by device name…",
            textvariable=self.driver_search_var,
            fg_color=t.PANEL_2, border_color=t.BORDER, text_color=t.TEXT,
        )
        search.pack(fill="x", padx=4, pady=(0, 8))

        self.drivers_area = self._scroll_area(parent)

    def _start_driver_scan(self) -> None:
        self.drivers_btn.configure(state="disabled")
        self.drivers_status.configure(text="Querying installed drivers…")

        def work():
            drivers, error = list_installed_drivers()
            self.after(0, lambda: self._finish_driver_scan(drivers, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_driver_scan(self, drivers: list[DriverInfo], error: str) -> None:
        self.drivers_btn.configure(state="normal")
        self._drivers = drivers
        if error:
            self.drivers_status.configure(text=error)
        else:
            self.drivers_status.configure(text=f"{len(drivers)} driver(s) found.")
        self._render_driver_rows()

    def _render_driver_rows(self) -> None:
        for child in self.drivers_area.winfo_children():
            child.destroy()

        query = self.driver_search_var.get().strip().lower()
        visible = [d for d in self._drivers if query in d.device_name.lower()] if query else self._drivers

        if not visible:
            ctk.CTkLabel(
                self.drivers_area,
                text="  No drivers to show — run a scan above." if not self._drivers else "  No matches.",
                text_color=t.MUTED, font=t.font(12),
            ).grid(row=0, column=0, sticky="w", pady=8)
            return

        for i, d in enumerate(visible):
            row = ctk.CTkFrame(self.drivers_area, fg_color=t.PANEL, corner_radius=t.RADIUS_SM)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(row, text=d.device_name, font=t.font(13, "bold"), text_color=t.TEXT, anchor="w"
                         ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
            detail = f"{d.manufacturer or 'Unknown manufacturer'} · v{d.version or '?'} · {d.date or 'no date'} · {d.device_class or 'Unclassified'}"
            ctk.CTkLabel(row, text=detail, font=t.font(11), text_color=t.MUTED, anchor="w"
                         ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

    # -------------------------------------------------------- driver updates

    def _build_driver_updates_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        self.driver_upd_btn, self.driver_upd_status = self._tab_header_row(
            parent, "Check Windows Update for Drivers", self._start_driver_update_check,
        )
        if not WIN32COM_AVAILABLE:
            self.driver_upd_btn.configure(state="disabled")
            self.driver_upd_status.configure(text="Requires pywin32 (not installed on this machine).")

        self.driver_upd_area = self._scroll_area(parent)

    def _start_driver_update_check(self) -> None:
        self.driver_upd_btn.configure(state="disabled")
        self.driver_upd_status.configure(text="Checking Windows Update — this can take a minute…")

        def work():
            updates, error = check_driver_updates()
            self.after(0, lambda: self._finish_driver_update_check(updates, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_driver_update_check(self, updates: list[UpdateInfo], error: str) -> None:
        self.driver_upd_btn.configure(state="normal")
        for child in self.driver_upd_area.winfo_children():
            child.destroy()

        if error:
            self.driver_upd_status.configure(text=error)
            return
        self.driver_upd_status.configure(
            text=f"{len(updates)} pending driver update(s)." if updates else "No pending driver updates."
        )
        for i, u in enumerate(updates):
            row = ctk.CTkFrame(self.driver_upd_area, fg_color=t.PANEL, corner_radius=t.RADIUS_SM)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=u.title, font=t.font(13, "bold"), text_color=t.TEXT, anchor="w"
                         ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
            desc = (u.description[:180] + "…") if len(u.description) > 180 else u.description
            if u.kb_articles:
                desc = f"{u.kb_articles} — {desc}" if desc else u.kb_articles
            ctk.CTkLabel(row, text=desc or "(no description)", font=t.font(11), text_color=t.MUTED,
                         anchor="w", wraplength=680, justify="left"
                         ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

    # -------------------------------------------------------- software updates

    def _build_software_updates_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        self.sw_upd_btn, self.sw_upd_status = self._tab_header_row(
            parent, "Check winget for Updates", self._start_software_update_check,
        )
        self.sw_upd_area = self._scroll_area(parent)

    def _start_software_update_check(self) -> None:
        self.sw_upd_btn.configure(state="disabled")
        self.sw_upd_status.configure(text="Checking installed packages against winget…")

        def work():
            updates, error = check_software_updates()
            self.after(0, lambda: self._finish_software_update_check(updates, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_software_update_check(self, updates: list[SoftwareUpdateInfo], error: str) -> None:
        self.sw_upd_btn.configure(state="normal")
        for child in self.sw_upd_area.winfo_children():
            child.destroy()

        if error:
            self.sw_upd_status.configure(text=error)
            return
        self.sw_upd_status.configure(
            text=f"{len(updates)} update(s) available." if updates else "Everything is up to date."
        )
        for i, u in enumerate(updates):
            row = ctk.CTkFrame(self.sw_upd_area, fg_color=t.PANEL, corner_radius=t.RADIUS_SM)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=f"{u.name}  ({u.id})", font=t.font(13, "bold"), text_color=t.TEXT, anchor="w"
                         ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
            detail = f"{u.current_version or '?'} → {u.available_version or '?'} · {u.source or 'unknown source'}"
            ctk.CTkLabel(row, text=detail, font=t.font(11), text_color=t.MUTED, anchor="w"
                         ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
