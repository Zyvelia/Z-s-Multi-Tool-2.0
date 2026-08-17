"""
ui.py
-----
The visual layer for the Folder Structure Generator module.

Responsibilities are strictly presentational: this file wires widgets
together and delegates all real work to game_database.py, tree_preview.py,
and generator.py. Generation runs on a background thread so the UI never
freezes, and results are marshalled back to the main thread through a
thread-safe queue polled via `after()`.
"""

from __future__ import annotations

import os
import queue
import threading
from tkinter import filedialog
from typing import List, Optional

import customtkinter as ctk

from .game_database import GameDatabase, GameRecord
from .generator import FolderStructureGenerator, GenerationResult
from .tree_preview import render_tree
from core import theme
from core import paths

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

_ENTRY = dict(fg_color=PANEL_2, border_color=PANEL_2, text_color=TEXT, height=34, corner_radius=8)


def _make_btn(parent, text, cmd, **overrides):
    return ctk.CTkButton(parent, text=text, command=cmd, **{**_BTN, **overrides})


class ScrollableDropdown:
    """A popup list attached to a button, scrollable when it has many entries.

    CTkOptionMenu's built-in popup doesn't scroll, which is painful once the
    game list gets long. This drives a small CTkToplevel containing a
    CTkScrollableFrame instead, so the list scrolls (mouse wheel or the
    scrollbar) no matter how many games are loaded.
    """

    MAX_VISIBLE_ROWS = 8
    ROW_HEIGHT = 30

    def __init__(self, anchor_widget, command, width: int = 320):
        self._anchor = anchor_widget
        self._command = command
        self._width = width
        self._values: List[str] = []
        self._toplevel: Optional[ctk.CTkToplevel] = None
        self._scroll_frame: Optional[ctk.CTkScrollableFrame] = None
        self._outside_click_id: Optional[str] = None

    def set_values(self, values: List[str]):
        self._values = list(values)
        if self._toplevel is not None:
            self._populate()

    def is_open(self) -> bool:
        return self._toplevel is not None

    def toggle(self):
        self.close() if self.is_open() else self.open()

    def open(self):
        if self.is_open() or not self._values:
            return

        self._toplevel = ctk.CTkToplevel(self._anchor)
        self._toplevel.overrideredirect(True)
        self._toplevel.attributes("-topmost", True)

        visible_rows = min(len(self._values), self.MAX_VISIBLE_ROWS)
        height = visible_rows * self.ROW_HEIGHT + 12

        self._scroll_frame = ctk.CTkScrollableFrame(
            self._toplevel, fg_color=PANEL_2, corner_radius=8,
            width=self._width, height=height,
        )
        self._scroll_frame.pack(fill="both", expand=True)

        self._populate()
        self._position(height)

        # Close the popup when a click lands OUTSIDE it (elsewhere in the
        # app / alt-tab away), instead of on <FocusOut>. <FocusOut> is a
        # race: a click on one of this popup's own game buttons can fire
        # focus-out and destroy the popup before the button's own click
        # registers, silently swallowing the selection. That race is timing
        # -sensitive — reliable running from source, but consistently loses
        # in the frozen exe where window-activation timing shifts slightly.
        # bind_all reaches every widget in the app, including this popup's
        # own rows, so we just check click coordinates against the popup's
        # bounds instead of trusting a focus event's timing.
        self._outside_click_id = self._anchor.bind_all(
            "<Button-1>", self._on_global_click, add="+"
        )
        self._toplevel.after(10, self._toplevel.focus_force)

    def _on_global_click(self, event):
        if self._toplevel is None:
            return
        tx = self._toplevel.winfo_rootx()
        ty = self._toplevel.winfo_rooty()
        tw = self._toplevel.winfo_width()
        th = self._toplevel.winfo_height()
        if not (tx <= event.x_root <= tx + tw and ty <= event.y_root <= ty + th):
            self.close()

    def _position(self, height: int):
        anchor = self._anchor
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height()

        screen_h = anchor.winfo_screenheight()
        if y + height > screen_h:
            # Not enough room below the button, flip it above instead.
            y = anchor.winfo_rooty() - height

        self._toplevel.geometry(f"{self._width}x{height}+{x}+{y}")

    def _populate(self):
        for child in self._scroll_frame.winfo_children():
            child.destroy()
        for name in self._values:
            ctk.CTkButton(
                self._scroll_frame, text=name, anchor="w",
                fg_color="transparent", hover_color=ACCENT, text_color=TEXT,
                height=28, corner_radius=6,
                command=lambda n=name: self._select(n),
            ).pack(fill="x", padx=2, pady=1)

    def _select(self, name: str):
        self.close()
        self._command(name)

    def close(self):
        if self._toplevel is not None:
            if self._outside_click_id is not None:
                # NOTE: unbind_all() clears every <Button-1> binding on the
                # app-wide "all" tag, not just this one — tkinter has no
                # by-id removal for bind_all. Fine today (nothing else in
                # the app uses bind_all for <Button-1>), but if another
                # popup-style widget ever adds one too, this needs a
                # different mechanism (e.g. a shared dispatcher) instead.
                self._anchor.unbind_all("<Button-1>")
                self._outside_click_id = None
            self._toplevel.destroy()
            self._toplevel = None
            self._scroll_frame = None


class FolderStructureGeneratorPage(ctk.CTkFrame):
    """Main page for the Folder Structure Generator module."""

    def __init__(self, parent, manager, database_path: Optional[str] = None):
        super().__init__(parent, fg_color=BG)
        self.manager = manager
        self.database_path = database_path or paths.seed_from_resource(
            paths.data_path("folder_gen", "games.json"),
            "modules", "folder_gen", "games.json"
        )
        self._default_stub_path = os.path.join(os.path.dirname(__file__), "assets", "mGba.exe")

        self._games: List[GameRecord] = []
        self._visible_games: List[GameRecord] = []
        self._selected_game: Optional[GameRecord] = None
        self._generating = False

        # Cross-thread communication: the worker thread never touches
        # widgets directly, it only pushes messages here.
        self._log_queue: "queue.Queue[tuple]" = queue.Queue()

        self._build_ui()
        self._load_database()
        self._poll_log_queue()

    # ── Build ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_search_bar()
        self._build_game_bar()
        self._build_output_bar()
        self._build_stub_bar()
        self._build_options_bar()
        self._build_main_panels()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            header, text="🗂  Folder Structure Generator",
            font=("Segoe UI", 22, "bold"), text_color=TEXT,
        ).pack(side="left", padx=14, pady=10)

        self._header_status = ctk.CTkLabel(header, text="Loading database…", text_color=MUTED)
        self._header_status.pack(side="right", padx=14)

    def _build_search_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(inner, text="Search", text_color=MUTED, font=("Segoe UI", 11)).pack(
            anchor="w", pady=(0, 4)
        )

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_changed())
        ctk.CTkEntry(
            inner, textvariable=self._search_var,
            placeholder_text="Type to filter games…", **_ENTRY,
        ).pack(fill="x")

    def _build_game_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=(4, 10))

        ctk.CTkLabel(inner, text="Game", text_color=MUTED, font=("Segoe UI", 11)).pack(
            anchor="w", pady=(0, 4)
        )

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")

        self._game_var = ctk.StringVar(value="Loading…")
        self._game_menu = ctk.CTkButton(
            row, textvariable=self._game_var, anchor="w",
            fg_color=PANEL_2, hover_color="#232a3a", text_color=TEXT,
            width=320, height=34, corner_radius=8,
            command=lambda: self._game_dropdown.toggle(),
        )
        self._game_menu.pack(side="left")
        self._game_dropdown = ScrollableDropdown(
            self._game_menu, command=self._on_game_selected, width=320,
        )

        # Compact metadata strip: category / developer / publisher / platform.
        self._meta_label = ctk.CTkLabel(row, text="", text_color=MUTED, font=("Segoe UI", 11))
        self._meta_label.pack(side="left", padx=(16, 0))

    def _build_output_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(inner, text="Output Folder", text_color=MUTED, font=("Segoe UI", 11)).pack(
            anchor="w", pady=(0, 4)
        )

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")

        self._output_var = ctk.StringVar()
        # Re-render the preview live as the user types/edits the output path,
        # since the preview's root label is the output folder itself.
        self._output_var.trace_add("write", lambda *_: self._update_preview())
        ctk.CTkEntry(
            row, textvariable=self._output_var,
            placeholder_text=r"e.g. D:\Launchers", **_ENTRY,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        _make_btn(row, "Browse", self._browse_output, width=90).pack(side="left")

    def _build_stub_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(
            inner, text="Stub Executable (copied + renamed to each game's exe)",
            text_color=MUTED, font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 4))

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")

        # Default to assets/mGba.exe next to this module if it exists, so
        # the feature works out of the box once that file is dropped in.
        default_value = self._default_stub_path if os.path.isfile(self._default_stub_path) else ""
        self._stub_var = ctk.StringVar(value=default_value)
        ctk.CTkEntry(
            row, textvariable=self._stub_var,
            placeholder_text=r"e.g. C:\Tools\mGba.exe (leave blank for an empty placeholder)",
            **_ENTRY,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        _make_btn(row, "Browse", self._browse_stub, width=90).pack(side="left")

    def _build_options_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)

        self._create_file_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            inner, text="Create placeholder executable file", variable=self._create_file_var,
            text_color=TEXT, fg_color=ACCENT, hover_color="#2f7fd6",
        ).pack(side="left", padx=(0, 20))

        self._overwrite_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            inner, text="Overwrite if it already exists", variable=self._overwrite_var,
            text_color=TEXT, fg_color=DANGER, hover_color="#8b0000",
        ).pack(side="left")

    def _build_main_panels(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        self._build_preview_panel(container)
        self._build_status_panel(container)

    def _build_preview_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(top, text="Preview", font=("Segoe UI", 15, "bold"), text_color=TEXT).pack(
            side="left"
        )

        self._preview_box = ctk.CTkTextbox(
            panel, fg_color=PANEL_2, text_color=TEXT, corner_radius=8,
            font=("Consolas", 12), wrap="none", state="disabled",
        )
        self._preview_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._create_btn = ctk.CTkButton(
            panel, text="Create Folder Structure", command=self._on_create_clicked,
            font=("Segoe UI", 13, "bold"), **_BTN_ACCENT,
        )
        self._create_btn.pack(fill="x", padx=10, pady=(0, 10))

    def _build_status_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(top, text="Status", font=("Segoe UI", 15, "bold"), text_color=TEXT).pack(
            side="left"
        )
        self._progress_bar = ctk.CTkProgressBar(panel, progress_color=ACCENT)
        self._progress_bar.pack(fill="x", padx=10, pady=(0, 6))
        self._progress_bar.set(0)

        self._status_box = ctk.CTkTextbox(
            panel, fg_color=PANEL_2, text_color=TEXT, corner_radius=8,
            font=("Consolas", 12), state="disabled",
        )
        self._status_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ── Database loading & filtering ─────────────────────────────────────

    def _load_database(self):
        db = GameDatabase(self.database_path)
        games, warnings = db.load()

        self._games = games
        self._visible_games = games

        for warning in warnings:
            self._append_log(f"⚠ {warning}")

        self._refresh_game_menu()

        if games:
            self._header_status.configure(text=f"{len(games)} game(s) loaded")
        else:
            self._header_status.configure(text="No games found")

    def _refresh_game_menu(self):
        names = [g.name for g in self._visible_games]
        self._game_dropdown.set_values(names)

        if not names:
            self._game_dropdown.close()
            self._game_var.set("No matches")
            self._selected_game = None
            self._meta_label.configure(text="")
            self._update_preview()
            return

        # Keep the current selection if it's still visible, otherwise fall
        # back to the first match.
        current = self._selected_game.name if self._selected_game else None
        target = current if current in names else names[0]
        self._game_var.set(target)
        self._on_game_selected(target)

    def _on_search_changed(self):
        query = self._search_var.get().strip().lower()
        self._visible_games = (
            [g for g in self._games if query in g.name.lower()] if query else self._games
        )
        self._refresh_game_menu()

    def _on_game_selected(self, name: str):
        self._game_var.set(name)
        self._selected_game = next((g for g in self._games if g.name == name), None)
        self._meta_label.configure(text=self._format_meta(self._selected_game))
        self._update_preview()

    @staticmethod
    def _format_meta(game: Optional[GameRecord]) -> str:
        if not game:
            return ""
        parts = [v for v in (game.category, game.developer, game.publisher, game.platform) if v]
        return "  •  ".join(parts)

    def _update_preview(self):
        self._preview_box.configure(state="normal")
        self._preview_box.delete("1.0", "end")
        self._preview_box.insert("1.0", render_tree(self._selected_game, self._output_var.get()))
        self._preview_box.configure(state="disabled")

    # ── Output folder ────────────────────────────────────────────────────

    def _browse_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self._output_var.set(folder)

    def _browse_stub(self):
        path = filedialog.askopenfilename(filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self._stub_var.set(path)

    # ── Generation ───────────────────────────────────────────────────────

    def _on_create_clicked(self):
        if self._generating:
            return

        if not self._selected_game:
            self._append_log("✕ No game selected.")
            return

        output_root = self._output_var.get().strip()
        if not output_root:
            self._append_log("✕ Please choose an output folder first.")
            return
        if not os.path.isdir(output_root):
            self._append_log(f"✕ Output folder does not exist: {output_root}")
            return

        self._clear_log()
        self._generating = True
        self._create_btn.configure(state="disabled", text="Working…")
        self._progress_bar.set(0)
        self._progress_bar.configure(mode="indeterminate")
        self._progress_bar.start()

        self._append_log(f"Creating '{self._selected_game.name}' in {output_root}")

        stub_path = self._stub_var.get().strip() or None

        generator = FolderStructureGenerator(
            game=self._selected_game,
            output_root=output_root,
            create_placeholder_file=bool(self._create_file_var.get()),
            overwrite_file=bool(self._overwrite_var.get()),
            stub_exe_path=stub_path,
        )

        # Generation runs off the main thread so the UI never blocks.
        threading.Thread(target=self._run_generation, args=(generator,), daemon=True).start()

    def _run_generation(self, generator: FolderStructureGenerator):
        def progress(message: str):
            self._log_queue.put(("log", message))

        try:
            result = generator.generate(progress_callback=progress)
            self._log_queue.put(("done", result))
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the UI
            self._log_queue.put(("fatal", str(exc)))

    def _poll_log_queue(self):
        """Drain messages produced by the worker thread and apply them to the UI."""
        try:
            while True:
                kind, payload = self._log_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self._on_generation_done(payload)
                elif kind == "fatal":
                    self._on_generation_fatal(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _on_generation_done(self, result: GenerationResult):
        self._generating = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_bar.set(1.0 if result.success else 0.5)
        self._create_btn.configure(state="normal", text="Create Folder Structure")

        self._append_log(f"✓ Created {result.folders_created} folder(s)")
        if result.file_created and result.used_stub:
            self._append_log("✓ Copied and renamed stub executable")
        elif result.file_created:
            self._append_log("✓ Created empty placeholder executable file")
        if result.file_skipped:
            self._append_log("⚠ Skipped existing executable file")
        for error in result.errors:
            self._append_log(f"✕ {error}")

        self._append_log("✓ Finished" if result.success else "✕ Finished with errors")

    def _on_generation_fatal(self, message: str):
        self._generating = False
        self._progress_bar.stop()
        self._progress_bar.configure(mode="determinate")
        self._progress_bar.set(0)
        self._create_btn.configure(state="normal", text="Create Folder Structure")
        self._append_log(f"✕ Unexpected error: {message}")

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
        """No background resources to release, but kept for interface parity."""
        pass
