"""
Duplicate File Finder — UI.

Follows the shared ZsMultiTool module convention: exposes a CTkFrame
subclass the plugin manager instantiates into `manager.container`.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .backend import (
    DuplicateGroup,
    DuplicateScanWorker,
    ProgressEvent,
    ScanOptions,
    _human_size,
    delete_files,
)
from .style import theme as t

POLL_MS = 80

SIZE_CHOICES = {
    "Any size": 0,
    "≥ 100 KB": 100 * 1024,
    "≥ 1 MB": 1024 * 1024,
    "≥ 10 MB": 10 * 1024 * 1024,
}


class DuplicateFinderModule(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=t.BG, **kwargs)
        self.manager = manager

        self._roots: list[Path] = []
        self._worker: DuplicateScanWorker | None = None
        self._groups: list[DuplicateGroup] = []
        self._check_vars: dict[str, ctk.BooleanVar] = {}  # keyed by str(path)

        self._build_layout()
        self._refresh_roots_view()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        header = ctk.CTkLabel(
            self, text="🧬  Duplicate File Finder",
            font=t.font(20, "bold"), text_color=t.TEXT,
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            self,
            text=(
                "Finds byte-identical files by size, then content hash — nothing "
                "is ever matched on filename alone. Deletion here is permanent, "
                "not sent to the Recycle Bin."
            ),
            font=t.font(12), text_color=t.MUTED, anchor="w", justify="left",
            wraplength=760,
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        # ---- folder picker row ----
        picker = ctk.CTkFrame(self, **t.panel_style())
        picker.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        picker.grid_columnconfigure(0, weight=1)

        btn_row = ctk.CTkFrame(picker, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        ctk.CTkButton(
            btn_row, text="Add Folder", width=110,
            **t.secondary_button_style(),
            command=self._add_folder,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Clear", width=90,
            **t.secondary_button_style(),
            command=self._clear_roots,
        ).pack(side="left", padx=(0, 16))

        self.subfolders_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            btn_row, text="Include subfolders", variable=self.subfolders_var,
            fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.TEXT,
        ).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(btn_row, text="Minimum size:", text_color=t.MUTED, font=t.font(12)).pack(side="left")
        self.min_size_var = tk.StringVar(value="Any size")
        ctk.CTkOptionMenu(
            btn_row, values=list(SIZE_CHOICES.keys()), variable=self.min_size_var,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            width=120,
        ).pack(side="left", padx=(8, 0))

        self.roots_box = ctk.CTkTextbox(
            picker, fg_color=t.PANEL_2, text_color=t.TEXT, height=60,
            wrap="none", state="disabled",
        )
        self.roots_box.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        # ---- scan action row ----
        action_row = ctk.CTkFrame(self, fg_color="transparent")
        action_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        action_row.grid_columnconfigure(1, weight=1)

        self.scan_btn = ctk.CTkButton(
            action_row, text="Scan for Duplicates",
            **t.primary_button_style(),
            command=self._start_scan,
        )
        self.scan_btn.grid(row=0, column=0, sticky="w")

        self.progress = ctk.CTkProgressBar(action_row, progress_color=t.ACCENT)
        self.progress.set(0)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

        self.status_label = ctk.CTkLabel(self, text="Add one or more folders to begin.",
                                          text_color=t.MUTED, font=t.font(12), anchor="w")
        self.status_label.grid(row=3, column=0, sticky="sw", padx=16, pady=(36, 4))

        # ---- results ----
        self.results_frame = ctk.CTkScrollableFrame(self, **t.panel_style())
        self.results_frame.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.results_frame.grid_columnconfigure(0, weight=1)

        # ---- delete bar ----
        delete_row = ctk.CTkFrame(self, fg_color="transparent")
        delete_row.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 16))
        delete_row.grid_columnconfigure(1, weight=1)

        self.delete_btn = ctk.CTkButton(
            delete_row, text="Delete Selected", state="disabled",
            **t.danger_button_style(),
            command=self._confirm_delete,
        )
        self.delete_btn.grid(row=0, column=0, sticky="w")

        self.selection_label = ctk.CTkLabel(delete_row, text="", text_color=t.MUTED, font=t.font(12))
        self.selection_label.grid(row=0, column=1, sticky="w", padx=(12, 0))

    # -------------------------------------------------------------- roots

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="Select a folder to scan")
        if path:
            p = Path(path)
            if p not in self._roots:
                self._roots.append(p)
        self._refresh_roots_view()

    def _clear_roots(self) -> None:
        self._roots.clear()
        self._refresh_roots_view()

    def _refresh_roots_view(self) -> None:
        self.roots_box.configure(state="normal")
        self.roots_box.delete("1.0", "end")
        if not self._roots:
            self.roots_box.insert("end", "  (no folders selected — click Add Folder)\n")
        for p in self._roots:
            self.roots_box.insert("end", f"  {p}\n")
        self.roots_box.configure(state="disabled")

    # -------------------------------------------------------------- scan

    def _start_scan(self) -> None:
        if not self._roots:
            self.status_label.configure(text="Add at least one folder first.")
            return
        if self._worker is not None and self._worker.is_alive():
            return

        options = ScanOptions(
            roots=list(self._roots),
            include_subfolders=self.subfolders_var.get(),
            min_size_bytes=SIZE_CHOICES[self.min_size_var.get()],
        )

        self._clear_results()
        self.scan_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.status_label.configure(text="Scanning…")

        self._worker = DuplicateScanWorker(options)
        self._worker.start()
        self.after(POLL_MS, self._poll_worker)

    def _poll_worker(self) -> None:
        if self._worker is None:
            return
        try:
            while True:
                event: ProgressEvent = self._worker.events.get_nowait()
                self._handle_event(event)
        except Exception:
            pass  # queue.Empty — nothing more this tick

        if self._worker.is_alive():
            self.after(POLL_MS, self._poll_worker)

    def _handle_event(self, event: ProgressEvent) -> None:
        if event.kind in ("scanning",):
            self.status_label.configure(text=event.message)
        elif event.kind == "hashing":
            if event.total_count:
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self.progress.set(event.done_count / max(event.total_count, 1))
            self.status_label.configure(text=event.message)
        elif event.kind == "overall_done":
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(1 if event.groups else 0)
            self.status_label.configure(text=event.message)
            self.scan_btn.configure(state="normal")
            self._groups = event.groups
            self._render_groups()
            self._worker = None
        elif event.kind == "fatal_error":
            self.progress.stop()
            self.status_label.configure(text=f"Error: {event.message}")
            self.scan_btn.configure(state="normal")
            self._worker = None

    # -------------------------------------------------------------- results

    def _clear_results(self) -> None:
        for child in self.results_frame.winfo_children():
            child.destroy()
        self._check_vars.clear()
        self._update_selection_label()

    def _render_groups(self) -> None:
        self._clear_results()
        if not self._groups:
            ctk.CTkLabel(
                self.results_frame, text="  No duplicates found.",
                text_color=t.MUTED, font=t.font(12),
            ).grid(row=0, column=0, sticky="w", pady=8)
            return

        for row_idx, group in enumerate(self._groups):
            self._build_group_card(row_idx, group)
        self._update_selection_label()

    def _build_group_card(self, row_idx: int, group: DuplicateGroup) -> None:
        card = ctk.CTkFrame(self.results_frame, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        card.grid(row=row_idx, column=0, sticky="ew", pady=6, padx=2)
        card.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            card,
            text=f"{len(group.paths)} copies · {_human_size(group.size)} each · "
                 f"{_human_size(group.size * (len(group.paths) - 1))} reclaimable",
            font=t.font(13, "bold"), text_color=t.ACCENT, anchor="w",
        )
        title.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        # First file found in the group defaults to "keep" (unchecked);
        # the rest default to checked, since that's the common intent.
        for i, path in enumerate(group.paths):
            self._build_file_row(card, i + 1, path, default_checked=(i != 0))

    def _build_file_row(self, parent, row_idx: int, path: Path, default_checked: bool) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=row_idx, column=0, sticky="ew", padx=12, pady=2)
        row.grid_columnconfigure(1, weight=1)

        var = ctk.BooleanVar(value=default_checked)
        self._check_vars[str(path)] = var

        ctk.CTkCheckBox(
            row, text="", variable=var, width=20,
            fg_color=t.DANGER, hover_color=t.DANGER_HOVER,
            command=self._update_selection_label,
        ).grid(row=0, column=0, padx=(0, 8))

        ctk.CTkLabel(
            row, text=str(path), font=t.mono(11), text_color=t.TEXT if default_checked else t.MUTED,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew")

        ctk.CTkButton(
            row, text="Locate", width=60, height=24,
            **t.secondary_button_style(),
            command=lambda p=path: self._open_location(p),
        ).grid(row=0, column=2, padx=(8, 0))

    def _open_location(self, path: Path) -> None:
        try:
            os.startfile(path.parent)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass  # non-Windows / can't open — silently ignore, not critical

    def _update_selection_label(self) -> None:
        selected = [Path(p) for p, v in self._check_vars.items() if v.get()]
        self.delete_btn.configure(state="normal" if selected else "disabled")
        if selected:
            total = sum(p.stat().st_size for p in selected if p.exists())
            self.selection_label.configure(
                text=f"{len(selected)} file(s) selected · {_human_size(total)}"
            )
        else:
            self.selection_label.configure(text="")

    # -------------------------------------------------------------- delete

    def _confirm_delete(self) -> None:
        selected = [Path(p) for p, v in self._check_vars.items() if v.get()]
        if not selected:
            return
        count = len(selected)
        dialog = ctk.CTkInputDialog(
            text=(
                f"This will permanently delete {count} file(s). "
                f"This cannot be undone.\n\nType {count} to confirm:"
            ),
            title="Confirm Delete",
        )
        answer = dialog.get_input()
        if answer is None:
            return
        try:
            confirmed_count = int(answer.strip())
        except ValueError:
            confirmed_count = -1
        if confirmed_count != count:
            self.status_label.configure(text="Confirmation didn't match — nothing was deleted.")
            return

        results = delete_files(selected)
        ok = sum(1 for _p, success, _e in results if success)
        failed = [(p, e) for p, success, e in results if not success]
        self.status_label.configure(
            text=f"Deleted {ok}/{count} file(s)."
            + (f" {len(failed)} failed (locked/in-use)." if failed else "")
        )
        self._start_scan()  # re-scan so the results reflect what's left
