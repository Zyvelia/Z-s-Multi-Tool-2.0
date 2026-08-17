"""
Clipboard Manager — UI.

The monitor is attached to `manager.container` (the root App instance)
rather than to this frame, and only created once — so clipboard capture
keeps running in the background no matter which module page is currently
visible, and reopening this page doesn't spawn a second poller.
"""

from __future__ import annotations

import time

import customtkinter as ctk

from .clipboard_history import (
    ClipboardEntry,
    ClipboardMonitor,
    ClipboardSettings,
    ClipboardStore,
    MAX_MAX_ITEMS,
    MIN_MAX_ITEMS,
    POLL_INTERVAL_CHOICES_MS,
    UNLIMITED,
)

BG = "#0f1115"
PANEL = "#151922"
PANEL_2 = "#1b2030"
ACCENT = "#4ea1ff"
DANGER = "#ff5c5c"
MUTED = "#7d8494"

PREVIEW_LINE_LIMIT = 3
PREVIEW_CHAR_LIMIT = 220


def _get_or_create_monitor(root_widget) -> tuple[ClipboardStore, ClipboardMonitor, ClipboardSettings]:
    """Ensure only one store/monitor/settings triple exists for the app's
    lifetime, stashed on the root widget itself."""
    store = getattr(root_widget, "_clipboard_store", None)
    monitor = getattr(root_widget, "_clipboard_monitor", None)
    settings = getattr(root_widget, "_clipboard_settings", None)
    if settings is None:
        settings = ClipboardSettings.load()
        root_widget._clipboard_settings = settings
    if store is None:
        store = ClipboardStore(max_items=settings.max_items)
        root_widget._clipboard_store = store
    if monitor is None:
        monitor = ClipboardMonitor(root_widget, store, interval_ms=settings.poll_interval_ms)
        if settings.capture_enabled:
            monitor.start()
        root_widget._clipboard_monitor = monitor
    return store, monitor, settings


def _preview(text: str) -> str:
    lines = text.splitlines() or [text]
    snippet = "\n".join(lines[:PREVIEW_LINE_LIMIT])
    if len(snippet) > PREVIEW_CHAR_LIMIT:
        snippet = snippet[:PREVIEW_CHAR_LIMIT] + "…"
    if len(lines) > PREVIEW_LINE_LIMIT:
        snippet += "\n…"
    return snippet


def _format_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


class ClipboardManagerModule(ctk.CTkFrame):
    """`manager` is the plugin manager / root App instance
    (manager.container is the root, per the shared convention)."""

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.manager = manager
        root_widget = manager.container if manager is not None else master

        self.store, self.monitor, self.settings = _get_or_create_monitor(root_widget)
        self._search_query = ""
        self._last_signature = None

        self._build_layout()
        self._refresh_list(force=True)

        # Poll the store for UI refresh only while this page is visible —
        # cheap, and independent of the monitor's own clipboard polling.
        self._ui_after_id = None
        self._schedule_ui_refresh()
        self.bind("<Destroy>", self._on_destroy)

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkLabel(
            self, text="Clipboard Manager",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white",
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            self,
            text="Runs in the background — capture continues while you're on other pages.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=1, column=0, sticky="e", padx=16, pady=(0, 12))

        self.search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            top_bar, placeholder_text="Search history…", width=220,
            fg_color=PANEL_2, textvariable=self.search_var,
        )
        search_entry.pack(side="left", padx=(0, 8))
        self.search_var.trace_add("write", lambda *_: self._on_search_changed())

        ctk.CTkButton(
            top_bar, text="Clear Unpinned", width=120,
            fg_color=PANEL_2, hover_color=DANGER,
            command=self._clear_unpinned,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            top_bar, text="⚙ Settings", width=100,
            fg_color=PANEL_2, hover_color=ACCENT,
            command=self._open_settings,
        ).pack(side="left")

        # ---- scrollable history list ----
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=PANEL, corner_radius=10)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))

    # --------------------------------------------------------------- state

    def _on_search_changed(self) -> None:
        self._search_query = self.search_var.get()
        self._refresh_list(force=True)

    def _clear_unpinned(self) -> None:
        self.store.clear_unpinned()
        self._refresh_list(force=True)

    def _schedule_ui_refresh(self) -> None:
        self._ui_after_id = self.after(800, self._ui_refresh_tick)

    def _ui_refresh_tick(self) -> None:
        self._refresh_list()
        self._schedule_ui_refresh()

    def _on_destroy(self, _event=None) -> None:
        # Only cancel our own UI-refresh loop — never touch self.monitor,
        # which belongs to the root widget and must keep running.
        if self._ui_after_id is not None:
            try:
                self.after_cancel(self._ui_after_id)
            except Exception:
                pass
            self._ui_after_id = None

    # ---------------------------------------------------------------- list

    def _refresh_list(self, force: bool = False) -> None:
        entries = self.store.search(self._search_query)
        signature = tuple((e.id, e.text, e.pinned) for e in entries)

        self.status_label.configure(
            text=f"{len(entries)} item(s)" + (f" matching '{self._search_query}'" if self._search_query else "")
        )

        if not force and signature == self._last_signature:
            return  # nothing changed — skip the destroy/rebuild to avoid flicker
        self._last_signature = signature

        for child in self.list_frame.winfo_children():
            child.destroy()

        if not entries:
            empty = ctk.CTkLabel(
                self.list_frame, text="  (nothing here yet — copy something to get started)",
                text_color=MUTED,
            )
            empty.grid(row=0, column=0, sticky="w", pady=8)
            return

        for row, entry in enumerate(entries):
            self._build_row(row, entry)

    def _build_row(self, row: int, entry: ClipboardEntry) -> None:
        card = ctk.CTkFrame(self.list_frame, fg_color=PANEL_2, corner_radius=8)
        card.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)

        text_label = ctk.CTkLabel(
            card, text=_preview(entry.text), text_color="white",
            justify="left", anchor="w", wraplength=520,
        )
        text_label.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))

        meta_label = ctk.CTkLabel(
            card, text=_format_time(entry.timestamp), text_color=MUTED,
            font=ctk.CTkFont(size=11),
        )
        meta_label.grid(row=1, column=0, sticky="w", padx=(12, 8), pady=(0, 10))

        btn_col = ctk.CTkFrame(card, fg_color="transparent")
        btn_col.grid(row=0, column=1, rowspan=2, sticky="ns", padx=8, pady=6)

        ctk.CTkButton(
            btn_col, text="Copy", width=64, height=26,
            fg_color=ACCENT, hover_color="#3d8fe0",
            command=lambda e=entry: self._copy_entry(e),
        ).pack(pady=2)

        pin_text = "Unpin" if entry.pinned else "Pin"
        ctk.CTkButton(
            btn_col, text=pin_text, width=64, height=26,
            fg_color=PANEL, hover_color=ACCENT,
            command=lambda e=entry: self._toggle_pin(e),
        ).pack(pady=2)

        ctk.CTkButton(
            btn_col, text="Delete", width=64, height=26,
            fg_color=PANEL, hover_color=DANGER,
            command=lambda e=entry: self._delete_entry(e),
        ).pack(pady=2)

    def _open_settings(self) -> None:
        _ClipboardSettingsDialog(self)

    def _apply_settings(self, *, max_items: int, poll_interval_ms: int, capture_enabled: bool) -> None:
        self.settings.max_items = max_items
        self.settings.poll_interval_ms = poll_interval_ms
        self.settings.capture_enabled = capture_enabled
        self.settings.save()

        self.store.set_max_items(max_items)
        self.monitor.set_interval(poll_interval_ms)
        if capture_enabled and not self.monitor.is_running():
            self.monitor.start()
        elif not capture_enabled and self.monitor.is_running():
            self.monitor.stop()

        self._refresh_list(force=True)

    def _clear_all(self) -> None:
        self.store.clear_all()
        self._refresh_list(force=True)

    # ------------------------------------------------------------- actions

    def _copy_entry(self, entry: ClipboardEntry) -> None:
        root_widget = self.manager.container if self.manager is not None else self
        root_widget.clipboard_clear()
        root_widget.clipboard_append(entry.text)
        # Copying re-surfaces this text on the clipboard, which the monitor
        # will see as "already last_seen" and correctly not re-capture.
        self.monitor._last_seen = entry.text
        self.status_label.configure(text="Copied to clipboard")

    def _toggle_pin(self, entry: ClipboardEntry) -> None:
        self.store.toggle_pin(entry.id)
        self._refresh_list(force=True)

    def _delete_entry(self, entry: ClipboardEntry) -> None:
        self.store.delete(entry.id)
        self._refresh_list(force=True)


class _ClipboardSettingsDialog(ctk.CTkToplevel):
    """Modal settings panel for the Clipboard Manager module."""

    def __init__(self, parent: ClipboardManagerModule):
        super().__init__(parent)
        self.parent = parent
        self.title("Clipboard Manager Settings")
        self.geometry("360x360")
        self.configure(fg_color=BG)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        settings = parent.settings
        pad = {"padx": 20, "pady": (12, 0)}

        ctk.CTkLabel(
            self, text="Clipboard Manager Settings",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="white",
        ).pack(anchor="w", padx=20, pady=(20, 4))

        # ---- capture enabled ----
        self.capture_var = ctk.BooleanVar(value=settings.capture_enabled)
        ctk.CTkSwitch(
            self, text="Capture clipboard history",
            variable=self.capture_var, progress_color=ACCENT,
        ).pack(anchor="w", **pad)

        # ---- max history size ----
        ctk.CTkLabel(
            self, text=f"Max history size ({MIN_MAX_ITEMS}\u2013{MAX_MAX_ITEMS})",
            text_color=MUTED,
        ).pack(anchor="w", **pad)

        is_unlimited = settings.max_items == UNLIMITED
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(anchor="w", padx=20, pady=(4, 0))

        self.max_items_var = ctk.StringVar(
            value="" if is_unlimited else str(settings.max_items)
        )
        self.max_items_entry = ctk.CTkEntry(
            row, textvariable=self.max_items_var, width=100, fg_color=PANEL_2,
        )
        self.max_items_entry.pack(side="left")

        self.unlimited_var = ctk.BooleanVar(value=is_unlimited)
        ctk.CTkCheckBox(
            row, text="Unlimited", variable=self.unlimited_var,
            fg_color=ACCENT, hover_color=ACCENT,
            command=self._on_unlimited_toggled,
        ).pack(side="left", padx=(12, 0))

        self._on_unlimited_toggled()  # sync entry enabled/disabled state on open

        # ---- poll interval ----
        ctk.CTkLabel(self, text="Check clipboard every", text_color=MUTED).pack(anchor="w", **pad)
        self.interval_var = ctk.StringVar(value=f"{settings.poll_interval_ms} ms")
        ctk.CTkOptionMenu(
            self, values=[f"{ms} ms" for ms in POLL_INTERVAL_CHOICES_MS],
            variable=self.interval_var,
            fg_color=PANEL_2, button_color=ACCENT, button_hover_color=ACCENT,
            width=140,
        ).pack(anchor="w", padx=20, pady=(4, 0))

        self.error_label = ctk.CTkLabel(self, text="", text_color=DANGER)
        self.error_label.pack(anchor="w", padx=20, pady=(10, 0))

        # ---- danger zone ----
        ctk.CTkButton(
            self, text="Clear ALL history (including pinned)", fg_color=DANGER,
            hover_color="#e04545", command=self._confirm_clear_all,
        ).pack(fill="x", padx=20, pady=(16, 0))

        # ---- save / cancel ----
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=20, side="bottom")
        ctk.CTkButton(
            btn_row, text="Cancel", fg_color=PANEL_2, hover_color=PANEL,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row, text="Save", fg_color=ACCENT, hover_color="#3d8fe0",
            command=self._save,
        ).pack(side="right")

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

        self.parent._apply_settings(
            max_items=max_items,
            poll_interval_ms=poll_interval_ms,
            capture_enabled=self.capture_var.get(),
        )
        self.destroy()

    def _confirm_clear_all(self) -> None:
        dialog = ctk.CTkInputDialog(
            text="This deletes ALL history, including pinned items, permanently.\n\nType YES to confirm:",
            title="Confirm Clear All",
        )
        answer = dialog.get_input()
        if answer is not None and answer.strip() == "YES":
            self.parent._clear_all()
            self.destroy()
