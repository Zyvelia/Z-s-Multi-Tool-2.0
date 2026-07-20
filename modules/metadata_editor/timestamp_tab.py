# modules/metadata_editor/timestamp_tab.py
#
# Modified/accessed time work on any file via os.utime (cross-platform).
# Creation time is a Windows-only filesystem concept and needs pywin32
# to set — the field just disables itself with an explanatory note if
# pywin32 isn't installed or we're not on Windows.

import os
import time
import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core import theme

try:
    import win32file
    import win32con
    import pywintypes
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
TEXT = theme.TEXT
MUTED = theme.MUTED
DANGER = theme.DANGER
PANEL_HOVER = theme.PANEL_HOVER

_BTN = dict(fg_color=PANEL_2, hover_color=PANEL_HOVER, text_color=TEXT,
            height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
                    height=34, corner_radius=8)


def _make_btn(parent, text, cmd, **overrides):
    kw = {**_BTN, **overrides}
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class FileTimestampsTab(ctk.CTkFrame):

    DATE_FMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self.current_path = None
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        top.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 6))
        top.grid_columnconfigure(1, weight=1)

        _make_btn(top, "Open File", self._open_file, width=110, **_BTN_ACCENT).grid(
            row=0, column=0, padx=10, pady=10)
        self.path_label = ctk.CTkLabel(top, text="No file loaded", text_color=MUTED, anchor="w")
        self.path_label.grid(row=0, column=1, sticky="ew", padx=6, pady=10)

        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        panel.grid_columnconfigure(1, weight=1)

        labels = ["Created", "Modified", "Accessed"]
        self.vars = {}
        for i, label in enumerate(labels):
            ctk.CTkLabel(panel, text=label, width=100, anchor="w", text_color=TEXT).grid(
                row=i, column=0, padx=(14, 6), pady=10, sticky="w")
            var = ctk.StringVar()
            entry = ctk.CTkEntry(panel, fg_color=PANEL_2, border_color=PANEL_2,
                                  textvariable=var, placeholder_text=self.DATE_FMT)
            entry.grid(row=i, column=1, padx=(0, 8), pady=10, sticky="ew")
            self.vars[label] = (var, entry)

        if not WIN32_AVAILABLE and os.name == "nt":
            note_text = "pywin32 not installed — Created time is read-only.\nRun: pip install pywin32"
            self.vars["Created"][1].configure(state="disabled")
        elif os.name != "nt":
            note_text = "Created time editing is Windows-only on this platform."
            self.vars["Created"][1].configure(state="disabled")
        else:
            note_text = "Format: YYYY-MM-DD HH:MM:SS"

        ctk.CTkLabel(panel, text=note_text, text_color=MUTED, justify="left", anchor="w").grid(
            row=len(labels), column=0, columnspan=2, padx=14, pady=(4, 14), sticky="w")

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=2, pady=8)

        _make_btn(btn_row, "Set to Now", self._set_now).pack(side="left", padx=(0, 8))
        _make_btn(btn_row, "Save Changes", self._save_changes, **_BTN_ACCENT).pack(side="left", padx=8)
        _make_btn(btn_row, "Reload / Discard", self._reload_current).pack(side="left", padx=8)

        self.panel = panel
        self.status_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 2))

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for label, (var, entry) in self.vars.items():
            if label == "Created" and (not WIN32_AVAILABLE or os.name != "nt"):
                continue  # stays disabled regardless
            entry.configure(state=state)

    def _set_status(self, msg, error=False):
        self.status_label.configure(text=msg, text_color=(DANGER if error else MUTED))

    def _open_file(self):
        path = filedialog.askopenfilename(title="Select file")
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            self.current_path = path
            self.path_label.configure(text=os.path.basename(path))
            st = os.stat(path)

            self.vars["Modified"][0].set(datetime.datetime.fromtimestamp(st.st_mtime).strftime(self.DATE_FMT))
            self.vars["Accessed"][0].set(datetime.datetime.fromtimestamp(st.st_atime).strftime(self.DATE_FMT))
            # st_ctime is "metadata change time" on POSIX but "creation time" on Windows
            self.vars["Created"][0].set(datetime.datetime.fromtimestamp(st.st_ctime).strftime(self.DATE_FMT))

            self._set_controls_enabled(True)
            self._set_status("Loaded successfully.")
        except Exception as e:
            self._set_status(f"Failed to load file: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not load file:\n{e}")

    def _reload_current(self):
        if self.current_path:
            self._load_file(self.current_path)

    def _set_now(self):
        now = datetime.datetime.now().strftime(self.DATE_FMT)
        for label, (var, entry) in self.vars.items():
            if entry.cget("state") != "disabled":
                var.set(now)

    def _parse(self, text):
        return datetime.datetime.strptime(text.strip(), self.DATE_FMT)

    def _save_changes(self):
        if not self.current_path:
            return
        try:
            mtime = self._parse(self.vars["Modified"][0].get())
            atime = self._parse(self.vars["Accessed"][0].get())
            os.utime(self.current_path, (atime.timestamp(), mtime.timestamp()))

            if WIN32_AVAILABLE and os.name == "nt" and self.vars["Created"][1].cget("state") != "disabled":
                ctime = self._parse(self.vars["Created"][0].get())
                self._set_windows_creation_time(self.current_path, ctime)

            self._set_status("Saved successfully.")
        except ValueError:
            self._set_status(f"Dates must match format: {self.DATE_FMT}", error=True)
        except Exception as e:
            self._set_status(f"Save failed: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not save changes:\n{e}")

    def _set_windows_creation_time(self, path, dt: datetime.datetime):
        handle = win32file.CreateFile(
            path, win32con.GENERIC_WRITE, win32con.FILE_SHARE_WRITE, None,
            win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None
        )
        try:
            wintime = pywintypes.Time(time.mktime(dt.timetuple()))
            win32file.SetFileTime(handle, wintime, None, None)
        finally:
            handle.close()
