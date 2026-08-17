"""
Folder Shredder — UI.

Follows the shared ZsMultiTool module convention: exposes a CTkFrame
subclass that the plugin manager instantiates and packs into
`manager.container`. Palette matches the rest of the app.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .shredder import PassPattern, ProgressEvent, ShredderWorker, collect_targets

BG = "#0f1115"
PANEL = "#151922"
PANEL_2 = "#1b2030"
ACCENT = "#4ea1ff"
DANGER = "#ff5c5c"
OK_COLOR = "#3ddc84"
MUTED = "#7d8494"

POLL_MS = 60


class FolderShredderModule(ctk.CTkFrame):
    """Secure-delete module. `manager` is the plugin manager / root App
    instance (manager.container is the root, per the shared convention)."""

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.manager = manager

        self._targets: list[Path] = []
        self._worker: ShredderWorker | None = None
        self._total_items = 0

        self._build_layout()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkLabel(
            self, text="Folder Shredder",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white",
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))

        subtitle = ctk.CTkLabel(
            self,
            text=(
                "Overwrites files before deleting them, then removes the "
                "folder. This cannot be undone."
            ),
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        # ---- controls row ----
        controls = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        controls.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_rowconfigure(1, weight=1)

        btn_row = ctk.CTkFrame(controls, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew", padx=12, pady=12)

        ctk.CTkButton(
            btn_row, text="Add Files", width=110,
            fg_color=PANEL_2, hover_color=ACCENT,
            command=self._add_files,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Add Folder", width=110,
            fg_color=PANEL_2, hover_color=ACCENT,
            command=self._add_folder,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row, text="Clear Queue", width=110,
            fg_color=PANEL_2, hover_color=DANGER,
            command=self._clear_queue,
        ).pack(side="left")

        self.pattern_var = tk.StringVar(value=PassPattern.ZERO.value)
        pattern_menu = ctk.CTkOptionMenu(
            btn_row,
            values=[p.value for p in PassPattern],
            variable=self.pattern_var,
            fg_color=PANEL_2, button_color=ACCENT, button_hover_color=ACCENT,
            width=200,
        )
        pattern_menu.pack(side="right")

        # ---- queue list ----
        self.queue_box = ctk.CTkTextbox(
            controls, fg_color=PANEL_2, text_color="white",
            wrap="none", state="disabled",
        )
        self.queue_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        # ---- shred bar ----
        action_row = ctk.CTkFrame(self, fg_color="transparent")
        action_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        action_row.grid_columnconfigure(1, weight=1)

        self.shred_btn = ctk.CTkButton(
            action_row, text="Shred Queue", fg_color=DANGER, hover_color="#e04545",
            command=self._confirm_and_shred,
        )
        self.shred_btn.grid(row=0, column=0, sticky="w")

        self.progress = ctk.CTkProgressBar(action_row, progress_color=ACCENT)
        self.progress.set(0)
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

        self.status_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))

        # ---- log ----
        log_header = ctk.CTkLabel(self, text="Log", text_color="white", font=ctk.CTkFont(weight="bold"))
        log_header.grid(row=5, column=0, sticky="w", padx=16, pady=(4, 4))

        self.log_box = ctk.CTkTextbox(
            self, fg_color=PANEL, text_color=MUTED, height=140, state="disabled",
        )
        self.log_box.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 16))

    # ------------------------------------------------------------- actions

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Select files to shred")
        self._targets.extend(Path(p) for p in paths)
        self._refresh_queue_view()

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="Select a folder to shred")
        if path:
            self._targets.append(Path(path))
        self._refresh_queue_view()

    def _clear_queue(self) -> None:
        self._targets.clear()
        self._refresh_queue_view()

    def _refresh_queue_view(self) -> None:
        self.queue_box.configure(state="normal")
        self.queue_box.delete("1.0", "end")
        if not self._targets:
            self.queue_box.insert("end", "  (queue is empty — add files or a folder above)\n")
        for p in self._targets:
            kind = "DIR " if p.is_dir() else "FILE"
            self.queue_box.insert("end", f"  [{kind}] {p}\n")
        self.queue_box.configure(state="disabled")

    def _log(self, text: str, color: str = MUTED) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    # ------------------------------------------------------- confirmation

    def _confirm_and_shred(self) -> None:
        if not self._targets:
            self.status_label.configure(text="Queue is empty — nothing to shred.")
            return
        if self._worker is not None and self._worker.is_alive():
            return

        count = len(self._targets)
        dialog = ctk.CTkInputDialog(
            text=(
                f"This will permanently destroy {count} item(s). "
                f"This cannot be undone.\n\nType {count} to confirm:"
            ),
            title="Confirm Shred",
        )
        answer = dialog.get_input()
        if answer is None:
            return
        try:
            confirmed_count = int(answer.strip())
        except ValueError:
            confirmed_count = -1
        if confirmed_count != count:
            self.status_label.configure(text="Confirmation didn't match — nothing was shredded.")
            return

        self._start_shred()

    # ------------------------------------------------------------- worker

    def _start_shred(self) -> None:
        pattern = next(p for p in PassPattern if p.value == self.pattern_var.get())
        items = collect_targets(self._targets)
        self._total_items = len(items)

        self.shred_btn.configure(state="disabled")
        self.progress.set(0)
        self.status_label.configure(text=f"Shredding {self._total_items} item(s)…")
        self._log(f"--- starting shred of {self._total_items} item(s), pattern: {pattern.value} ---")

        self._worker = ShredderWorker(items, pattern)
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
        if event.kind == "item_start":
            return
        if event.kind == "item_done":
            r = event.result
            if r and r.ok:
                self._log(f"shredded: {r.path}")
            elif r:
                self._log(f"SKIPPED ({r.error}): {r.path}", color=DANGER)
            if event.total_count:
                self.progress.set(event.done_count / event.total_count)
                self.status_label.configure(
                    text=f"{event.done_count}/{event.total_count} processed"
                )
        elif event.kind == "overall_done":
            self._log(f"--- {event.message} ---")
            self.status_label.configure(text=event.message)
            self.shred_btn.configure(state="normal")
            self._targets.clear()
            self._refresh_queue_view()
            self._worker = None
        elif event.kind == "fatal_error":
            self._log(f"FATAL: {event.message}", color=DANGER)
            self.status_label.configure(text="Error — see log")
            self.shred_btn.configure(state="normal")
            self._worker = None
