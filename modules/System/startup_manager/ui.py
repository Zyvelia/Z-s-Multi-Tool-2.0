"""
Startup Manager — UI.

Follows the shared ZsMultiTool module convention: exposes a CTkFrame
subclass the plugin manager instantiates into `manager.container`.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from .backend import (
    REGISTRY_AVAILABLE,
    StartupItem,
    list_startup_items,
    open_containing_folder,
    remove_item,
    set_enabled,
)
from core import theme as t

SOURCE_BADGE_COLORS = {
    "Registry (Current User)": t.ACCENT,
    "Registry (All Users)": t.ACCENT_DIM,
    "Registry (All Users, 32-bit)": t.ACCENT_DIM,
    "Startup Folder (Current User)": "#34d399",
    "Startup Folder (All Users)": "#2dd4bf",
}


class StartupManagerModule(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=t.BG, **kwargs)
        self.manager = manager

        self._items: list[StartupItem] = []
        self._rows: dict[str, ctk.CTkFrame] = {}
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._render_rows())

        self._build_layout()

        if REGISTRY_AVAILABLE:
            self.refresh()
        else:
            self.status_label.configure(
                text="This module reads the Windows registry and Startup folder — "
                     "unavailable on this platform."
            )

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkLabel(
            self, text="🚀  Startup Manager",
            font=t.font(20, "bold"), text_color=t.TEXT,
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            self,
            text=(
                "Everything Windows launches at sign-in — registry Run entries "
                "and Startup folder shortcuts. Disabling matches Task Manager's "
                "Startup tab exactly and can be undone here at any time."
            ),
            font=t.font(12), text_color=t.MUTED, anchor="w", justify="left",
            wraplength=760,
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        # ---- controls row ----
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        controls.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(
            controls, placeholder_text="Filter by name…", textvariable=self.search_var,
            fg_color=t.PANEL_2, border_color=t.BORDER, text_color=t.TEXT,
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            controls, text="⟳ Refresh", width=100,
            **t.secondary_button_style(),
            command=self.refresh,
        ).grid(row=0, column=1)

        self.count_label = ctk.CTkLabel(
            controls, text="", font=t.font(12), text_color=t.MUTED,
        )
        self.count_label.grid(row=0, column=2, padx=(12, 0))

        # ---- results list ----
        self.list_frame = ctk.CTkScrollableFrame(self, **t.panel_style())
        self.list_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.list_frame.grid_columnconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            self, text="", font=t.font(12), text_color=t.MUTED, anchor="w",
        )
        self.status_label.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        self.status_label.configure(text="Scanning…")
        self.update_idletasks()
        self._items = list_startup_items()
        self._render_rows()
        enabled_count = sum(1 for i in self._items if i.enabled)
        self.status_label.configure(
            text=f"{len(self._items)} startup item(s) found, {enabled_count} enabled."
        )

    def _render_rows(self) -> None:
        for row in self._rows.values():
            row.destroy()
        self._rows.clear()

        query = self.search_var.get().strip().lower()
        visible = [i for i in self._items if query in i.name.lower()] if query else self._items

        self.count_label.configure(text=f"{len(visible)} shown")

        if not visible:
            empty = ctk.CTkLabel(
                self.list_frame, text="  No startup items match.",
                text_color=t.MUTED, font=t.font(12),
            )
            empty.grid(row=0, column=0, sticky="w", pady=8)
            self._rows["__empty__"] = empty
            return

        for row_idx, item in enumerate(visible):
            self._build_row(row_idx, item)

    def _build_row(self, row_idx: int, item: StartupItem) -> None:
        key = f"{item.kind}:{item.source}:{item.name}"
        card = ctk.CTkFrame(self.list_frame, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        card.grid(row=row_idx, column=0, columnspan=3, sticky="ew", pady=4, padx=2)
        card.grid_columnconfigure(1, weight=1)
        self._rows[key] = card

        switch_var = ctk.BooleanVar(value=item.enabled)
        switch = ctk.CTkSwitch(
            card, text="", variable=switch_var, width=40,
            progress_color=t.ACCENT,
            command=lambda i=item, v=switch_var: self._toggle(i, v),
        )
        switch.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=10)

        name_row = ctk.CTkFrame(card, fg_color="transparent")
        name_row.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))

        ctk.CTkLabel(
            name_row, text=item.name, font=t.font(13, "bold"), text_color=t.TEXT,
        ).pack(side="left")

        badge_color = SOURCE_BADGE_COLORS.get(item.source, t.MUTED)
        ctk.CTkLabel(
            name_row, text=item.source, font=t.font(10, "bold"), text_color=badge_color,
        ).pack(side="left", padx=(10, 0))

        cmd_text = item.command if len(item.command) <= 110 else item.command[:107] + "…"
        ctk.CTkLabel(
            card, text=cmd_text, font=t.mono(11), text_color=t.MUTED, anchor="w",
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))

        btn_col = ctk.CTkFrame(card, fg_color="transparent")
        btn_col.grid(row=0, column=2, rowspan=2, padx=(0, 12))

        if item.kind == "shortcut":
            ctk.CTkButton(
                btn_col, text="Locate", width=70, height=26,
                **t.secondary_button_style(),
                command=lambda i=item: open_containing_folder(i),
            ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_col, text="Remove", width=70, height=26,
            **t.danger_button_style(),
            command=lambda i=item: self._confirm_remove(i),
        ).pack(side="left")

    # -------------------------------------------------------------- actions

    def _toggle(self, item: StartupItem, switch_var: ctk.BooleanVar) -> None:
        enabled = switch_var.get()
        try:
            set_enabled(item, enabled)
            self.status_label.configure(
                text=f"{'Enabled' if enabled else 'Disabled'} \"{item.name}\"."
            )
        except OSError as e:
            switch_var.set(not enabled)  # revert the switch, the write failed
            self.status_label.configure(text=f"Couldn't change \"{item.name}\": {e}")

    def _confirm_remove(self, item: StartupItem) -> None:
        confirm = ctk.CTkInputDialog(
            text=(
                f"Permanently remove \"{item.name}\" from startup?\n"
                f"This deletes it outright (not just disables it) and can't be "
                f"undone here.\n\nType YES to confirm:"
            ),
            title="Confirm Removal",
        )
        answer = confirm.get_input()
        if answer is None or answer.strip().upper() != "YES":
            return
        try:
            remove_item(item)
            self.status_label.configure(text=f"Removed \"{item.name}\".")
        except OSError as e:
            self.status_label.configure(text=f"Couldn't remove \"{item.name}\": {e}")
        self.refresh()
