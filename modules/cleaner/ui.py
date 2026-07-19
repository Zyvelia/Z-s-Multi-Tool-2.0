"""
ui.py
-----
The visual layer for the Cleaner module. Presentational only — all real
work is delegated to scanner.py and deleter.py. Scanning and deleting run
on background threads so the UI never freezes, with results marshalled
back to the main thread through a thread-safe queue polled via `after()`.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from tkinter import filedialog
from typing import Dict, List, Optional

import customtkinter as ctk

from .scanner import Category, default_categories, scan_sizes, find_pycache_dirs, human_size
from .deleter import delete_categories, delete_pycache_dirs
from .admin import is_admin, relaunch_as_admin
from core import theme

# ── Colours (matches the app's shared dark theme) ─────────────────────────
BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
DANGER = theme.DANGER
SUCCESS = theme.SUCCESS
TEXT = theme.TEXT
MUTED = theme.MUTED

_BTN = dict(fg_color=PANEL_2, hover_color=ACCENT, text_color=TEXT, height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=theme.ACCENT_DIM, text_color="white", height=34, corner_radius=8)
_BTN_DANGER = dict(fg_color=DANGER, hover_color=DANGER, text_color="white", height=34, corner_radius=8)

_ENTRY = dict(fg_color=PANEL_2, border_color=PANEL_2, text_color=TEXT, height=34, corner_radius=8)


def _make_btn(parent, text, cmd, **overrides):
    return ctk.CTkButton(parent, text=text, command=cmd, **{**_BTN, **overrides})


class CleanerPage(ctk.CTkFrame):
    """Main page for the Cleaner module."""

    PYCACHE_KEY = "__pycache__"

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager

        self._categories: List[Category] = []
        self._pycache_root: Optional[Path] = None
        self._pycache_dirs: List[Path] = []
        self._pycache_size = 0
        self._row_vars: Dict[str, ctk.BooleanVar] = {}
        self._scanning = False
        self._deleting = False

        # Cross-thread communication: worker threads never touch widgets
        # directly, they only push messages here.
        self._queue: "queue.Queue[tuple]" = queue.Queue()

        self._build_ui()
        self._poll_queue()
        self.start_scan()

    # ── Build ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_pycache_bar()
        self._build_main_panels()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(header, text="🧹 Cleaner", font=("Segoe UI", 18, "bold"), text_color=TEXT
                      ).pack(side="left", padx=12, pady=10)

        self._header_status = ctk.CTkLabel(header, text="", text_color=MUTED)
        self._header_status.pack(side="left", padx=8)

        admin_text = "🛡 Running as administrator" if is_admin() else "Not elevated"
        admin_color = SUCCESS if is_admin() else MUTED
        ctk.CTkLabel(header, text=admin_text, text_color=admin_color).pack(side="left", padx=8)

        btn_bar = ctk.CTkFrame(header, fg_color="transparent")
        btn_bar.pack(side="right", padx=8, pady=8)

        if not is_admin():
            _make_btn(btn_bar, "Restart as Administrator", self._restart_as_admin, width=170
                       ).pack(side="left", padx=4)

        self._scan_btn = _make_btn(btn_bar, "Rescan", self.start_scan, width=90)
        self._scan_btn.pack(side="left", padx=4)

        _make_btn(btn_bar, "Select All", lambda: self._set_all(True), width=100).pack(side="left", padx=4)
        _make_btn(btn_bar, "Select None", lambda: self._set_all(False), width=100).pack(side="left", padx=4)

        self._delete_btn = ctk.CTkButton(btn_bar, text="Delete Selected", width=140,
                                          command=self._confirm_delete, **_BTN_DANGER)
        self._delete_btn.pack(side="left", padx=4)

    def _build_pycache_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(bar, text="Also find __pycache__ dirs under:", text_color=TEXT
                      ).pack(side="left", padx=(12, 6), pady=8)

        self._pycache_path_var = ctk.StringVar(value=str(Path.home()))
        ctk.CTkEntry(bar, textvariable=self._pycache_path_var, width=340, **_ENTRY
                      ).pack(side="left", padx=4)

        _make_btn(bar, "Browse", self._browse_pycache_root, width=80).pack(side="left", padx=4)
        _make_btn(bar, "Rescan Folder", self.start_scan, width=110).pack(side="left", padx=4)

    def _build_main_panels(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        container.grid_columnconfigure(0, weight=3)
        container.grid_columnconfigure(1, weight=2)
        container.grid_rowconfigure(0, weight=1)

        self._build_list_panel(container)
        self._build_status_panel(container)

    def _build_list_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(top, text="What to clean", font=("Segoe UI", 15, "bold"), text_color=TEXT
                      ).pack(side="left")

        self._list_frame = ctk.CTkScrollableFrame(panel, fg_color=PANEL_2, corner_radius=8)
        self._list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        footer = ctk.CTkFrame(panel, fg_color="transparent")
        footer.pack(fill="x", padx=10, pady=(0, 10))
        self._total_lbl = ctk.CTkLabel(footer, text="Total reclaimable: —",
                                        font=("Segoe UI", 13, "bold"), text_color=TEXT)
        self._total_lbl.pack(side="left")

    def _build_status_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(top, text="Status", font=("Segoe UI", 15, "bold"), text_color=TEXT
                      ).pack(side="left")

        self._progress_bar = ctk.CTkProgressBar(panel, progress_color=ACCENT)
        self._progress_bar.pack(fill="x", padx=10, pady=(0, 6))
        self._progress_bar.set(0)

        self._status_box = ctk.CTkTextbox(
            panel, fg_color=PANEL_2, text_color=TEXT, corner_radius=8,
            font=("Consolas", 12), state="disabled",
        )
        self._status_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _browse_pycache_root(self):
        folder = filedialog.askdirectory(initialdir=self._pycache_path_var.get())
        if folder:
            self._pycache_path_var.set(folder)

    def _restart_as_admin(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Restart as administrator")
        dialog.geometry("380x160")
        dialog.configure(fg_color=BG)
        dialog.transient(self.winfo_toplevel())
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(10, dialog.focus_force)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="This restarts the app with a UAC prompt so system "
                 "folders like C:\\WINDOWS\\Temp can be cleared. The app "
                 "will close and reopen elevated.",
            justify="left", wraplength=340, text_color=TEXT,
        ).pack(padx=16, pady=16, fill="both", expand=True)

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(pady=(0, 16))
        _make_btn(btns, "Cancel", dialog.destroy, width=100).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Restart", width=100, command=self._do_restart_as_admin,
                       **_BTN_ACCENT).pack(side="left", padx=8)

    def _do_restart_as_admin(self):
        if relaunch_as_admin():
            # A new elevated instance is launching via UAC — close this one.
            # NOTE: this exits the process directly rather than going
            # through your app's normal quit path (tray quit-on-close,
            # etc.). If you'd rather route through that, swap this for
            # whatever `manager` exposes for a full app shutdown.
            os._exit(0)
        else:
            self._append_log("⚠ Elevation was cancelled or failed.")

    # ── Scanning ─────────────────────────────────────────────────────────

    def start_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(state="disabled", text="Scanning…")
        self._header_status.configure(text="Scanning…")
        self._clear_log()
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._row_vars.clear()

        pycache_root = self._pycache_path_var.get().strip()
        threading.Thread(target=self._scan_worker, args=(pycache_root,), daemon=True).start()

    def _scan_worker(self, pycache_root_str: str):
        try:
            categories = default_categories()
            scan_sizes(categories)
            self._queue.put(("categories", categories))

            if pycache_root_str:
                root = Path(pycache_root_str)
                if root.exists():
                    dirs = find_pycache_dirs(root)
                    size = sum(_safe_dir_size(d) for d in dirs)
                    self._queue.put(("pycache", root, dirs, size))
                else:
                    self._queue.put(("log", f"⚠ Folder not found: {root}"))
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the UI
            self._queue.put(("log", f"✕ Scan error: {exc}"))
        finally:
            self._queue.put(("scan_done", None))

    # ── Cross-thread queue polling ──────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, *payload = self._queue.get_nowait()
                if kind == "categories":
                    self._categories = payload[0]
                    self._render_categories()
                elif kind == "pycache":
                    self._pycache_root, self._pycache_dirs, self._pycache_size = payload
                    self._render_pycache_row()
                elif kind == "log":
                    self._append_log(payload[0])
                elif kind == "scan_done":
                    self._scanning = False
                    self._scan_btn.configure(state="normal", text="Rescan")
                    self._header_status.configure(text="Scan complete")
                    self._update_total()
                elif kind == "delete_done":
                    self._on_delete_done(payload[0])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ── Rendering ────────────────────────────────────────────────────────

    def _render_categories(self):
        for c in self._categories:
            row = ctk.CTkFrame(self._list_frame, fg_color=PANEL, corner_radius=6)
            row.pack(fill="x", pady=3, padx=4)

            var = ctk.BooleanVar(value=c.exists)
            self._row_vars[c.key] = var
            ctk.CTkCheckBox(row, text="", variable=var, width=20, command=self._update_total,
                             state="normal" if c.exists else "disabled"
                             ).pack(side="left", padx=(10, 6), pady=8)

            title = c.label + ("" if c.exists else "  (not found)")
            if c.risk == "caution":
                title += "  ⚠"
            ctk.CTkLabel(row, text=title, text_color=TEXT if c.exists else MUTED, anchor="w"
                          ).pack(side="left", padx=4, pady=8)
            ctk.CTkLabel(row, text=c.description, text_color=MUTED, anchor="w"
                          ).pack(side="left", padx=8, pady=8, fill="x", expand=True)
            ctk.CTkLabel(row, text=human_size(c.size) if c.exists else "-", width=90, text_color=TEXT
                          ).pack(side="right", padx=12, pady=8)

    def _render_pycache_row(self):
        row = ctk.CTkFrame(self._list_frame, fg_color=PANEL, corner_radius=6)
        row.pack(fill="x", pady=3, padx=4)

        has_dirs = bool(self._pycache_dirs)
        var = ctk.BooleanVar(value=has_dirs)
        self._row_vars[self.PYCACHE_KEY] = var
        ctk.CTkCheckBox(row, text="", variable=var, width=20, command=self._update_total,
                         state="normal" if has_dirs else "disabled"
                         ).pack(side="left", padx=(10, 6), pady=8)

        ctk.CTkLabel(row, text=f"__pycache__ dirs ({len(self._pycache_dirs)} found)",
                      text_color=TEXT, anchor="w").pack(side="left", padx=4, pady=8)
        ctk.CTkLabel(row, text=str(self._pycache_root), text_color=MUTED, anchor="w"
                      ).pack(side="left", padx=8, pady=8, fill="x", expand=True)
        ctk.CTkLabel(row, text=human_size(self._pycache_size), width=90, text_color=TEXT
                      ).pack(side="right", padx=12, pady=8)
        self._update_total()

    def _set_all(self, value: bool):
        for key, var in self._row_vars.items():
            if key == self.PYCACHE_KEY:
                if self._pycache_dirs:
                    var.set(value)
                continue
            cat = next((c for c in self._categories if c.key == key), None)
            if cat and cat.exists:
                var.set(value)
        self._update_total()

    def _update_total(self):
        total = 0
        for c in self._categories:
            var = self._row_vars.get(c.key)
            if var and var.get():
                total += c.size
        pycache_var = self._row_vars.get(self.PYCACHE_KEY)
        if pycache_var and pycache_var.get():
            total += self._pycache_size
        self._total_lbl.configure(text=f"Total reclaimable: {human_size(total)}")

    # ── Deletion ─────────────────────────────────────────────────────────

    def _confirm_delete(self):
        if self._deleting:
            return
        selected = [c for c in self._categories if self._row_vars.get(c.key) and self._row_vars[c.key].get()]
        pycache_var = self._row_vars.get(self.PYCACHE_KEY)
        pycache_selected = bool(pycache_var and pycache_var.get())

        if not selected and not pycache_selected:
            self._append_log("⚠ Nothing selected.")
            return

        names = [c.label for c in selected] + (["__pycache__ dirs"] if pycache_selected else [])

        # Height grows with the item count (so short lists stay compact)
        # but is capped, and the list itself scrolls past the cap — either
        # way the button row below is packed to the bottom FIRST, so it
        # can never be pushed out of the visible window by a long list.
        list_area_h = min(28 * len(names) + 20, 260)
        dialog_h = 130 + list_area_h

        dialog = ctk.CTkToplevel(self)
        dialog.title("Confirm delete")
        dialog.geometry(f"420x{dialog_h}")
        dialog.minsize(360, 220)
        dialog.configure(fg_color=BG)
        dialog.transient(self.winfo_toplevel())

        # Center on the main window rather than wherever the OS drops it,
        # and make sure it renders above the app (including the item list)
        # instead of behind it.
        self.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + (root.winfo_width() - 420) // 2
        y = root.winfo_rooty() + (root.winfo_height() - dialog_h) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(10, dialog.focus_force)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="This will permanently delete:", justify="left",
                      text_color=TEXT, anchor="w").pack(fill="x", padx=16, pady=(16, 6))

        # Buttons packed to the bottom BEFORE the scrollable list above them
        # is added, so they always stay put regardless of list length.
        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(side="bottom", pady=(8, 16))
        _make_btn(btns, "Cancel", dialog.destroy, width=100).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Delete", width=100,
                       command=lambda: (dialog.destroy(), self._run_delete(selected, pycache_selected)),
                       **_BTN_DANGER).pack(side="left", padx=8)

        list_frame = ctk.CTkScrollableFrame(dialog, fg_color=PANEL_2, corner_radius=8,
                                             height=list_area_h)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        for name in names:
            ctk.CTkLabel(list_frame, text=f"• {name}", justify="left", anchor="w", text_color=TEXT
                          ).pack(fill="x", padx=6, pady=2)

    def _run_delete(self, selected: List[Category], pycache_selected: bool):
        self._deleting = True
        self._delete_btn.configure(state="disabled", text="Deleting…")
        self._progress_bar.configure(mode="indeterminate")
        self._progress_bar.start()
        self._append_log(f"Deleting {len(selected) + (1 if pycache_selected else 0)} item(s)…")

        threading.Thread(target=self._delete_worker, args=(selected, pycache_selected), daemon=True).start()

    def _delete_worker(self, selected: List[Category], pycache_selected: bool):
        errors: List[str] = []
        try:
            errors = delete_categories(selected)
            if pycache_selected:
                errors += delete_pycache_dirs(self._pycache_dirs)
        except Exception as exc:  # noqa: BLE001 - never let this thread die silently
            errors.append(f"Unexpected error: {exc}")
        self._queue.put(("delete_done", errors))

    def _on_delete_done(self, errors: List[str]):
        self._deleting = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_bar.set(1.0 if not errors else 0.5)
        self._delete_btn.configure(state="normal", text="Delete Selected")

        if errors:
            self._append_log(f"⚠ {len(errors)} item(s) skipped (in use / locked):")
            for e in errors[:20]:
                self._append_log(f"  {e}")
            if len(errors) > 20:
                self._append_log(f"  …and {len(errors) - 20} more")
        else:
            self._append_log("✓ Deleted everything selected")
        self._append_log("✓ Finished — rescanning")
        self.start_scan()

    # ── Log helpers ──────────────────────────────────────────────────────

    def _append_log(self, message: str):
        self._status_box.configure(state="normal")
        self._status_box.insert("end", message + "\n")
        self._status_box.see("end")
        self._status_box.configure(state="disabled")

    def _clear_log(self):
        self._status_box.configure(state="normal")
        self._status_box.delete("1.0", "end")
        self._status_box.configure(state="disabled")

    # ── Lifecycle hook expected by the plugin manager ───────────────────

    def on_leave(self):
        """No background resources need releasing — scans/deletes are
        fire-and-forget daemon threads — but kept for interface parity."""
        pass


def _safe_dir_size(path: Path) -> int:
    from .scanner import dir_size
    return dir_size(path)
