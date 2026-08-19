"""Clipboard Manager module settings — mounted in the ⚙ gear menu."""

from __future__ import annotations

import customtkinter as ctk

from core import theme

from .clipboard_history import (
    MAX_MAX_ITEMS,
    MIN_MAX_ITEMS,
    POLL_INTERVAL_CHOICES_MS,
    UNLIMITED,
)
from .ui import _get_or_create_monitor, apply_clipboard_settings, refresh_clipboard_module_ui



class ClipboardSettingsPanel(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        root_widget = manager.container
        _, _, self.settings = _get_or_create_monitor(root_widget)

        panel = ctk.CTkFrame(
            self, fg_color=theme.PANEL,
            corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER,
        )
        panel.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            panel, text="Capture & storage",
            font=theme.font(16, "bold"), text_color=theme.TEXT,
        ).pack(anchor="w", padx=16, pady=(16, 4))

        ctk.CTkLabel(
            panel,
            text="Clipboard history runs in the background while the app is open.",
            font=theme.font(11), text_color=theme.MUTED, wraplength=640, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        self.capture_var = ctk.BooleanVar(value=self.settings.capture_enabled)
        ctk.CTkSwitch(
            panel, text="Capture clipboard history",
            variable=self.capture_var, progress_color=theme.ACCENT,
            font=theme.font(13), text_color=theme.TEXT,
        ).pack(anchor="w", padx=16, pady=(8, 0))

        ctk.CTkLabel(
            panel, text=f"Max history size ({MIN_MAX_ITEMS}\u2013{MAX_MAX_ITEMS})",
            font=theme.font(12), text_color=theme.MUTED,
        ).pack(anchor="w", padx=16, pady=(14, 0))

        is_unlimited = self.settings.max_items == UNLIMITED
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(anchor="w", padx=16, pady=(4, 0))

        self.max_items_var = ctk.StringVar(
            value="" if is_unlimited else str(self.settings.max_items)
        )
        self.max_items_entry = ctk.CTkEntry(
            row, textvariable=self.max_items_var, width=100, fg_color=theme.PANEL_2,
        )
        self.max_items_entry.pack(side="left")

        self.unlimited_var = ctk.BooleanVar(value=is_unlimited)
        ctk.CTkCheckBox(
            row, text="Unlimited", variable=self.unlimited_var,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT,
            command=self._on_unlimited_toggled,
            font=theme.font(12), text_color=theme.TEXT,
        ).pack(side="left", padx=(12, 0))

        self._on_unlimited_toggled()

        ctk.CTkLabel(
            panel, text="Check clipboard every",
            font=theme.font(12), text_color=theme.MUTED,
        ).pack(anchor="w", padx=16, pady=(14, 0))

        self.interval_var = ctk.StringVar(value=f"{self.settings.poll_interval_ms} ms")
        ctk.CTkOptionMenu(
            panel, values=[f"{ms} ms" for ms in POLL_INTERVAL_CHOICES_MS],
            variable=self.interval_var,
            fg_color=theme.PANEL_2, button_color=theme.ACCENT, button_hover_color=theme.ACCENT,
            width=140,
        ).pack(anchor="w", padx=16, pady=(4, 0))

        self.error_label = ctk.CTkLabel(panel, text="", text_color=theme.DANGER)
        self.error_label.pack(anchor="w", padx=16, pady=(10, 0))

        ctk.CTkButton(
            panel, text="Save settings", fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_DIM, command=self._save,
        ).pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkButton(
            panel, text="Clear ALL history (including pinned)",
            fg_color=theme.DANGER, hover_color=theme.DANGER_HOVER,
            command=self._confirm_clear_all,
        ).pack(fill="x", padx=16, pady=(12, 16))

    def _on_unlimited_toggled(self) -> None:
        if self.unlimited_var.get():
            self.max_items_entry.configure(state="disabled")
        else:
            self.max_items_entry.configure(state="normal")

    def _save(self) -> None:
        if self.unlimited_var.get():
            max_items = UNLIMITED
        else:
            raw = self.max_items_var.get().strip()
            try:
                max_items = int(raw)
            except ValueError:
                self.error_label.configure(text="Max history size must be a whole number.")
                return
            if not (MIN_MAX_ITEMS <= max_items <= MAX_MAX_ITEMS):
                self.error_label.configure(
                    text=f"Max history size must be between {MIN_MAX_ITEMS} and {MAX_MAX_ITEMS}."
                )
                return

        poll_interval_ms = int(self.interval_var.get().split()[0])
        apply_clipboard_settings(
            self.manager.container,
            max_items=max_items,
            poll_interval_ms=poll_interval_ms,
            capture_enabled=self.capture_var.get(),
        )
        self.error_label.configure(text="Saved.", text_color=theme.SUCCESS)
        refresh_clipboard_module_ui(self.manager)

    def _confirm_clear_all(self) -> None:
        dialog = ctk.CTkInputDialog(
            text="This deletes ALL history, including pinned items, permanently.\n\nType YES to confirm:",
            title="Confirm Clear All",
        )
        answer = dialog.get_input()
        if answer is not None and answer.strip() == "YES":
            store, _, _ = _get_or_create_monitor(self.manager.container)
            store.clear_all()
            refresh_clipboard_module_ui(self.manager)