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


class MicrosoftSignInDialog(ctk.CTkToplevel):
    """Walks the user through browser-based Microsoft sign-in and collects
    the redirect URL they paste back afterward.

    Set `self.result` to the pasted text on submit, or leave it None if the
    user cancels/closes the window. The caller (running on a worker thread)
    should show this via `master.after(0, ...)` and then `master.wait_window`
    on it, waking up once `self.result` is available.
    """

    def __init__(self, master, auth_url: str):
        super().__init__(master)
        self.auth_url = auth_url
        self.result: str | None = None

        self.title("Sign in with Microsoft")
        self.geometry("520x300")
        self.minsize(480, 280)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="A browser window has opened. Sign in with the Microsoft "
                 "account that owns Minecraft: Java Edition.",
            font=t.font(12), text_color=t.TEXT, wraplength=460, justify="left", anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))

        ctk.CTkLabel(
            self,
            text="After signing in, the page will look like it failed to "
                 "load — that's expected. Quickly select the address bar "
                 "(click it, then Ctrl+A, Ctrl+C) and paste the FULL address "
                 "below, then click Continue. Microsoft scrubs the token from "
                 "the visible address after a moment, so grab it fast — if you "
                 "see '?removed=true', sign in again.",
            font=t.font(11), text_color=t.MUTED, wraplength=460, justify="left", anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        self.entry = ctk.CTkEntry(
            self, fg_color=t.PANEL_2, border_color=t.BORDER,
            placeholder_text="https://login.live.com/oauth20_desktop.srf#access_token=...",
        )
        self.entry.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 4))
        self.entry.bind("<Return>", lambda _e: self._submit())
        self.entry.focus_set()

        self.error_label = ctk.CTkLabel(self, text="", font=t.font(10), text_color=t.DANGER, anchor="w")
        self.error_label.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew", padx=16, pady=(4, 16))
        ctk.CTkButton(bar, text="Reopen browser", width=120, **t.secondary_button_style(),
                      command=self._reopen_browser).pack(side="left")
        ctk.CTkButton(bar, text="Cancel", width=90, **t.secondary_button_style(),
                      command=self._cancel).pack(side="right")
        ctk.CTkButton(bar, text="Continue", width=90, **t.primary_button_style(),
                      command=self._submit).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _reopen_browser(self) -> None:
        import webbrowser
        webbrowser.open(self.auth_url)

    def _submit(self) -> None:
        value = self.entry.get().strip()
        if not value:
            self.error_label.configure(text="Paste the address you were redirected to first.")
            return
        self.result = value
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
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
