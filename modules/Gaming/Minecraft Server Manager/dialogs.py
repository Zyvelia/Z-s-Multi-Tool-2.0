"""Small dialogs for the Game Server Manager UI."""

from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from . import server_files as sf
from core import theme as t


class FileEditorDialog(ctk.CTkToplevel):
    def __init__(self, master, file_path: Path, on_saved=None):
        super().__init__(master)
        self.file_path = file_path
        self.on_saved = on_saved
        self.title(f"Edit — {file_path.name}")
        self.geometry("720x520")
        self.minsize(480, 320)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text=str(file_path), font=t.mono(10), text_color=t.MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))

        self.editor = ctk.CTkTextbox(
            self, fg_color=t.PANEL_2, text_color=t.TEXT, font=t.mono(11), wrap="none",
        )
        self.editor.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        try:
            self.editor.insert("1.0", sf.read_text_file(file_path))
        except OSError as e:
            self.editor.insert("1.0", f"(could not read file: {e})")
            self.editor.configure(state="disabled")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="e", padx=16, pady=(0, 16))
        ctk.CTkButton(bar, text="Cancel", width=90, **t.secondary_button_style(),
                      command=self.destroy).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="Save", width=90, **t.primary_button_style(),
                      command=self._save).pack(side="left")

    def _save(self) -> None:
        if str(self.editor.cget("state")) == "disabled":
            self.destroy()
            return
        try:
            sf.write_text_file(self.file_path, self.editor.get("1.0", "end-1c"))
        except OSError as e:
            messagebox.showerror("Save failed", str(e), parent=self)
            return
        if self.on_saved:
            self.on_saved()
        self.destroy()


class PalworldSaveHintDialog(ctk.CTkToplevel):
    """One-time hint before saving Palworld server settings."""

    def __init__(self, master, *, running: bool):
        super().__init__(master)
        self.title("Palworld settings")
        self.geometry("460x260")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self.proceed = False
        self.dismiss_forever = False
        self._dont_show = ctk.BooleanVar(value=False)

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Before saving Palworld settings", font=t.font(16, "bold"), text_color=t.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        lines = [
            "Palworld loads settings from PalWorldSettings.ini at startup.",
            "Stop the server before saving — it rewrites that file on shutdown.",
        ]
        if running:
            lines.append("")
            lines.append("The server is running right now. Changes you save may be lost when it stops.")

        ctk.CTkLabel(
            self, text="\n".join(lines), font=t.font(12), text_color=t.MUTED,
            wraplength=400, justify="left", anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))

        ctk.CTkCheckBox(
            self, text="Don't show this again", variable=self._dont_show,
            fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.TEXT,
        ).grid(row=2, column=0, sticky="w", padx=20, pady=(0, 12))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="e", padx=20, pady=(0, 20))
        ctk.CTkButton(bar, text="Cancel", width=90, **t.secondary_button_style(),
                      command=self._cancel).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="Save anyway", width=110, **t.primary_button_style(),
                      command=self._ok).pack(side="left")

    def _ok(self) -> None:
        self.proceed = True
        self.dismiss_forever = bool(self._dont_show.get())
        self.destroy()

    def _cancel(self) -> None:
        self.destroy()
