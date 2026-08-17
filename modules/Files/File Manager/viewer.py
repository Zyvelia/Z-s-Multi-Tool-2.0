"""
viewer.py — Main FileViewerUI shell.
"""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

from .utils import (
    BG, BG_PANEL, BG_RAISED, BORDER, ACCENT, ACCENT_DIM, ACCENT_GLOW,
    RED, RED_DIM, TEXT_HI, TEXT_MID, TEXT_LOW, FONT, FONT_MONO,
    detect_viewer, human_size,
)
from .icons import (
    ICON_OPEN, ICON_SAVE, ICON_SAVE_AS, ICON_FIND, ICON_REPLACE,
    ICON_REFRESH, ICON_CLOSE, file_icon,
)
from .metadata import MetadataPanel
from .editors import TextEditor, HexViewer, ImageViewer, AudioPlayer, ArchiveViewer

# ── extra colours ─────────────────────────────────────────
TAB_ACTIVE_BG   = "#1e2a3a"
TAB_ACTIVE_LINE = ACCENT
SIDEBAR_W       = 230
META_W          = 210
STATUSBAR_H     = 28

VIEWER_COLORS = {
    "text":    ("#4ea1ff", "📝"),
    "hex":     ("#a78bfa", "🔢"),
    "image":   ("#34d399", "🖼"),
    "audio":   ("#f59e0b", "🎵"),
    "archive": ("#fb923c", "🗜"),
}


# ── _Tab ─────────────────────────────────────────────────

class _Tab:
    __slots__ = ("path", "viewer_type", "widget", "tab_id",
                 "label_var", "_btn_frame", "_btn", "_indicator")

    def __init__(self, path: str, viewer_type: str,
                 widget, tab_id: str, label_var: tk.StringVar):
        self.path        = path
        self.viewer_type = viewer_type
        self.widget      = widget
        self.tab_id      = tab_id
        self.label_var   = label_var
        self._btn_frame  = None
        self._btn        = None
        self._indicator  = None


# ═════════════════════════════════════════════════════════

class FileViewerUI(ctk.CTkFrame):

    def __init__(self, parent, manager, **kw):
        super().__init__(parent, fg_color=BG, **kw)
        self.manager          = manager
        self._tabs: list[_Tab] = []
        self._active_tab: Optional[_Tab] = None
        self._browser_root    = Path.home()
        self._apply_treeview_style()
        self._build()
        self._refresh_browser(self._browser_root)

    # ── treeview global style ─────────────────────────────

    def _apply_treeview_style(self):
        style = ttk.Style()
        style.theme_use("default")

        # browser
        style.configure("Browser.Treeview",
                        background=BG_PANEL, fieldbackground=BG_PANEL,
                        foreground=TEXT_MID, rowheight=26,
                        font=(FONT, 10), borderwidth=0, relief="flat")
        style.configure("Browser.Treeview.Heading",
                        background=BG_PANEL, foreground=TEXT_LOW,
                        font=(FONT, 9, "bold"), relief="flat", borderwidth=0)
        style.map("Browser.Treeview",
                  background=[("selected", TAB_ACTIVE_BG)],
                  foreground=[("selected", ACCENT)])

        # archive
        style.configure("Archive.Treeview",
                        background=BG_RAISED, fieldbackground=BG_RAISED,
                        foreground=TEXT_MID, rowheight=24,
                        font=(FONT_MONO, 10), borderwidth=0)
        style.configure("Archive.Treeview.Heading",
                        background=BG_PANEL, foreground=TEXT_LOW,
                        font=(FONT, 9, "bold"), relief="flat")
        style.map("Archive.Treeview",
                  background=[("selected", TAB_ACTIVE_BG)],
                  foreground=[("selected", ACCENT)])

        # scrollbar
        style.configure("Vertical.TScrollbar",
                        background=BG_RAISED, troughcolor=BG_PANEL,
                        borderwidth=0, arrowsize=12)
        style.map("Vertical.TScrollbar",
                  background=[("active", BORDER)])

    # ── build ─────────────────────────────────────────────

    def _build(self):
        self._build_top_toolbar()
        self._build_body()
        self._build_status_bar()

    # ── top toolbar ───────────────────────────────────────

    def _build_top_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL,
                           corner_radius=0, border_width=0, height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(fill="x", side="bottom")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14)

        # divider
        ctk.CTkFrame(inner, width=1, height=24,
                     fg_color=BORDER).pack(side="left", padx=(0, 14))

        # title
        ctk.CTkLabel(
            inner, text="Universal File Viewer",
            text_color=TEXT_HI, font=(FONT, 15, "bold")
        ).pack(side="left")

        # right-side buttons
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")

        def _primary(text, cmd, w=90):
            b = ctk.CTkButton(
                right, text=text, command=cmd, width=w, height=30,
                fg_color=ACCENT_GLOW, hover_color="#1e3f60",
                text_color=ACCENT, border_width=1, border_color="#2a5a8a",
                corner_radius=6, font=(FONT, 11, "bold")
            )
            b.pack(side="left", padx=2)
            return b

        def _ghost(text, cmd, w=80):
            b = ctk.CTkButton(
                right, text=text, command=cmd, width=w, height=30,
                fg_color="transparent", hover_color=BG_RAISED,
                text_color=TEXT_MID, border_width=1, border_color=BORDER,
                corner_radius=6, font=(FONT, 11)
            )
            b.pack(side="left", padx=2)
            return b

        _primary(f"{ICON_OPEN}  Open",    self._open_file,        100)
        _ghost(f"{ICON_SAVE}  Save",      self._save_current,      80)
        _ghost(f"{ICON_SAVE_AS}  Save As", self._save_as_current,  90)

        ctk.CTkFrame(right, width=1, height=24,
                     fg_color=BORDER).pack(side="left", padx=8)

        _ghost(f"{ICON_FIND}  Find",      self._find_in_current,   76)
        _ghost(f"{ICON_REPLACE}  Replace", self._replace_in_current, 88)

        ctk.CTkFrame(right, width=1, height=24,
                     fg_color=BORDER).pack(side="left", padx=8)

        _ghost(f"{ICON_REFRESH}  Refresh", self._refresh_current,  88)

    # ── body ─────────────────────────────────────────────

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body)
        self._build_center(body)
        self._build_meta_panel(body)

    # ── sidebar ──────────────────────────────────────────

    def _build_sidebar(self, parent):
        sidebar = ctk.CTkFrame(
            parent, fg_color=BG_PANEL,
            corner_radius=0, border_width=0,
            width=SIDEBAR_W
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # right border
        ctk.CTkFrame(sidebar, width=1, fg_color=BORDER).pack(
            side="right", fill="y")

        inner = ctk.CTkFrame(sidebar, fg_color="transparent")
        inner.pack(fill="both", expand=True)

        # ── section header ────────────────────────────────
        hdr = ctk.CTkFrame(inner, fg_color="transparent", height=36)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="FILE BROWSER",
            text_color=TEXT_LOW, font=(FONT, 9, "bold")
        ).pack(side="left", padx=12, pady=8)

        ctk.CTkButton(
            hdr, text="↑", width=26, height=22,
            fg_color="transparent", hover_color=BG_RAISED,
            text_color=TEXT_LOW, border_width=0,
            corner_radius=4, font=(FONT, 13),
            command=self._go_up
        ).pack(side="right", padx=8)

        ctk.CTkFrame(inner, height=1, fg_color=BORDER).pack(fill="x")

        # path bar
        path_bar = ctk.CTkFrame(inner, fg_color="transparent", height=32)
        path_bar.pack(fill="x")
        path_bar.pack_propagate(False)

        self._path_var = tk.StringVar(value=str(self._browser_root))
        pe = ctk.CTkEntry(
            path_bar, textvariable=self._path_var,
            fg_color=BG_PANEL, border_color=BG_PANEL,
            text_color=TEXT_LOW, font=(FONT_MONO, 8),
            border_width=0, corner_radius=0,
        )
        pe.pack(fill="x", padx=10, pady=4)
        pe.bind("<Return>",
                lambda e: self._refresh_browser(Path(self._path_var.get())))

        ctk.CTkFrame(inner, height=1, fg_color=BORDER).pack(fill="x")

        # tree
        tree_wrap = tk.Frame(inner, bg=BG_PANEL, bd=0, highlightthickness=0)
        tree_wrap.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(tree_wrap, orient="vertical", style="Vertical.TScrollbar")
        sb.pack(side="right", fill="y")

        self._browser_tree = ttk.Treeview(
            tree_wrap, style="Browser.Treeview",
            show="tree", selectmode="browse",
            yscrollcommand=sb.set,
        )
        sb.config(command=self._browser_tree.yview)
        self._browser_tree.pack(fill="both", expand=True)

        self._browser_tree.bind("<Double-1>",         self._on_browser_double)
        self._browser_tree.bind("<<TreeviewSelect>>", self._on_browser_select)

    def _refresh_browser(self, root: Path):
        try:
            root = root.resolve()
        except Exception:
            return
        if not root.exists():
            return
        self._browser_root = root
        self._path_var.set(str(root))

        for item in self._browser_tree.get_children():
            self._browser_tree.delete(item)

        try:
            entries = sorted(root.iterdir(),
                             key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            self._set_status("⚠  Permission denied.")
            return

        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                icon = "📁  "
            else:
                icon = file_icon(entry.suffix) + "  "
            size = ""
            if entry.is_file():
                try:
                    size = human_size(entry.stat().st_size)
                except OSError:
                    pass
            self._browser_tree.insert(
                "", "end",
                text=icon + entry.name,
                values=(str(entry), size),
                tags=("dir" if entry.is_dir() else "file",),
            )

    def _on_browser_double(self, event):
        iid = self._browser_tree.focus()
        if not iid:
            return
        vals = self._browser_tree.item(iid, "values")
        if not vals:
            return
        path = Path(vals[0])
        if path.is_dir():
            self._refresh_browser(path)
        else:
            self.open_file(str(path))

    def _on_browser_select(self, event):
        iid = self._browser_tree.focus()
        if not iid:
            return
        vals = self._browser_tree.item(iid, "values")
        if vals:
            path = Path(vals[0])
            if path.is_file():
                self._metadata_panel.load(path)

    def _go_up(self):
        self._refresh_browser(self._browser_root.parent)

    # ── center (tab bar + editor host) ───────────────────

    def _build_center(self, parent):
        center = ctk.CTkFrame(parent, fg_color=BG, corner_radius=0)
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)

        # ── tab bar ───────────────────────────────────────
        tab_bar_outer = ctk.CTkFrame(
            center, fg_color=BG_PANEL,
            corner_radius=0, height=38
        )
        tab_bar_outer.grid(row=0, column=0, sticky="ew")
        tab_bar_outer.grid_propagate(False)
        ctk.CTkFrame(tab_bar_outer, height=1,
                     fg_color=BORDER).pack(fill="x", side="bottom")

        self._tab_scroll = ctk.CTkScrollableFrame(
            tab_bar_outer, fg_color="transparent",
            orientation="horizontal", height=36,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT_DIM,
        )
        self._tab_scroll.pack(fill="both", expand=True)

        # ── welcome ───────────────────────────────────────
        self._welcome = ctk.CTkFrame(center, fg_color=BG, corner_radius=0)
        self._welcome.grid(row=1, column=0, sticky="nsew")
        self._build_welcome(self._welcome)

        # ── editor host ───────────────────────────────────
        self._editor_host = ctk.CTkFrame(center, fg_color=BG, corner_radius=0)
        self._editor_host.grid(row=1, column=0, sticky="nsew")
        self._editor_host.grid_remove()

    def _build_welcome(self, parent):
        mid = ctk.CTkFrame(parent, fg_color="transparent")
        mid.place(relx=0.5, rely=0.45, anchor="center")

        ctk.CTkLabel(mid, text="📁",
                     font=(FONT, 56), text_color="#1e2a3a").pack(pady=(0, 12))

        ctk.CTkLabel(mid, text="No file open",
                     text_color=TEXT_MID, font=(FONT, 18, "bold")).pack()

        ctk.CTkLabel(mid,
                     text="Browse the panel on the left or click  Open  above.",
                     text_color=TEXT_LOW, font=(FONT, 12)).pack(pady=(6, 24))

        tips = ctk.CTkFrame(mid, fg_color=BG_PANEL,
                            corner_radius=10, border_width=1,
                            border_color=BORDER)
        tips.pack(fill="x", ipadx=20, ipady=10)

        rows = [
            ("📝", "Text / Code",    "TXT LOG JSON XML YAML INI CFG CSV MD"),
            ("🔢", "Hex Viewer",     "Any unknown or binary file"),
            ("🖼", "Image Viewer",   "PNG JPG BMP GIF WEBP ICO"),
            ("🎵", "Audio Player",   "MP3 WAV FLAC AAC OGG"),
            ("🗜", "Archive Viewer", "ZIP 7Z TAR GZ"),
        ]
        for icon, label, exts in rows:
            row = ctk.CTkFrame(tips, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(row, text=icon, font=(FONT, 14),
                         text_color=TEXT_MID, width=24).pack(side="left")
            ctk.CTkLabel(row, text=label, font=(FONT, 11, "bold"),
                         text_color=TEXT_MID, width=110,
                         anchor="w").pack(side="left", padx=(6, 12))
            ctk.CTkLabel(row, text=exts, font=(FONT, 10),
                         text_color=TEXT_LOW, anchor="w").pack(side="left")

    # ── metadata panel (right) ────────────────────────────

    def _build_meta_panel(self, parent):
        meta_outer = ctk.CTkFrame(
            parent, fg_color=BG_PANEL,
            corner_radius=0, border_width=0,
            width=META_W
        )
        meta_outer.grid(row=0, column=2, sticky="nsew")
        meta_outer.grid_propagate(False)

        # left border
        ctk.CTkFrame(meta_outer, width=1, fg_color=BORDER).pack(
            side="left", fill="y")

        inner = ctk.CTkFrame(meta_outer, fg_color="transparent")
        inner.pack(fill="both", expand=True)

        hdr = ctk.CTkFrame(inner, fg_color="transparent", height=36)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="PROPERTIES",
            text_color=TEXT_LOW, font=(FONT, 9, "bold")
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkFrame(inner, height=1, fg_color=BORDER).pack(fill="x")

        self._metadata_panel = MetadataPanel(inner)
        self._metadata_panel.pack(fill="both", expand=True)
        self._metadata_panel.clear()

    # ── status bar ────────────────────────────────────────

    def _build_status_bar(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL,
                           corner_radius=0, height=STATUSBAR_H)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(fill="x", side="top")

        self._status_lbl = ctk.CTkLabel(
            bar, text="Ready", anchor="w",
            text_color=TEXT_LOW, font=(FONT, 10)
        )
        self._status_lbl.pack(side="left", padx=12, pady=4)

        # viewer type badge on right
        self._vtype_frame = ctk.CTkFrame(bar, fg_color=BG_RAISED,
                                         corner_radius=4)
        self._vtype_frame.pack(side="right", padx=12, pady=5)
        self._viewer_type_lbl = ctk.CTkLabel(
            self._vtype_frame, text="",
            text_color=TEXT_LOW, font=(FONT, 9, "bold"),
            padx=8, pady=0
        )
        self._viewer_type_lbl.pack()

    def _set_status(self, msg: str):
        self._status_lbl.configure(text=msg)

    def _set_viewer_badge(self, viewer_type: str):
        color, icon = VIEWER_COLORS.get(viewer_type, (TEXT_LOW, ""))
        self._viewer_type_lbl.configure(
            text=f"{icon}  {viewer_type.upper()}",
            text_color=color
        )
        self._vtype_frame.configure(
            fg_color=BG_RAISED, border_width=1,
            border_color=color
        )

    # ── file opening ──────────────────────────────────────

    def _open_file(self):
        path = filedialog.askopenfilename(title="Open file")
        if path:
            self.open_file(path)

    def open_file(self, path: str):
        for tab in self._tabs:
            if tab.path == path:
                self._activate_tab(tab)
                return

        viewer_type = detect_viewer(path)
        widget      = self._make_viewer(path, viewer_type)
        if widget is None:
            return

        name = Path(path).name
        lv   = tk.StringVar(value=name)
        tid  = f"tab_{id(widget)}"

        tab = _Tab(path=path, viewer_type=viewer_type,
                   widget=widget, tab_id=tid, label_var=lv)
        self._tabs.append(tab)
        self._add_tab_button(tab)
        self._activate_tab(tab)

        self._metadata_panel.load(path)
        name_short = name if len(name) <= 40 else "…" + name[-38:]
        self._set_status(f"  {name_short}")
        self._set_viewer_badge(viewer_type)

    def _make_viewer(self, path: str, viewer_type: str):
        host = self._editor_host
        try:
            if viewer_type == "text":
                return TextEditor(host, path,
                                  on_modified=lambda m: self._on_tab_modified(path, m))
            elif viewer_type == "image":
                return ImageViewer(host, path)
            elif viewer_type == "audio":
                return AudioPlayer(host, path)
            elif viewer_type == "archive":
                return ArchiveViewer(host, path)
            else:
                return HexViewer(host, path)
        except Exception as e:
            messagebox.showerror("Open failed", f"Could not open file:\n{e}")
            return None

    # ── tab button ────────────────────────────────────────

    def _add_tab_button(self, tab: _Tab):
        color, icon = VIEWER_COLORS.get(tab.viewer_type, (TEXT_LOW, "📄"))

        tab._btn_frame = ctk.CTkFrame(
            self._tab_scroll, fg_color="transparent",
            corner_radius=0
        )
        tab._btn_frame.pack(side="left", padx=(0, 1))

        # coloured left accent line
        tab._indicator = ctk.CTkFrame(
            tab._btn_frame, width=3, fg_color=BORDER, corner_radius=0
        )
        tab._indicator.pack(side="left", fill="y")

        content = ctk.CTkFrame(tab._btn_frame, fg_color="transparent",
                               corner_radius=0)
        content.pack(side="left")

        name = Path(tab.path).name
        display = name if len(name) <= 22 else name[:20] + "…"

        tab._btn = ctk.CTkButton(
            content,
            text=f"{icon}  {display}",
            width=0,
            fg_color="transparent",
            hover_color=BG_RAISED,
            text_color=TEXT_LOW,
            border_width=0,
            corner_radius=0,
            font=(FONT, 11),
            anchor="w",
            command=lambda t=tab: self._activate_tab(t)
        )
        tab._btn.pack(side="left", padx=(8, 0), pady=0, ipady=8)

        ctk.CTkButton(
            content, text="×", width=22, height=22,
            fg_color="transparent", hover_color="#3a1a1a",
            text_color=TEXT_LOW, border_width=0,
            corner_radius=4, font=(FONT, 13),
            command=lambda t=tab: self._close_tab(t)
        ).pack(side="left", padx=(2, 6))

    def _activate_tab(self, tab: _Tab):
        for t in self._tabs:
            t.widget.pack_forget()
            if t._btn:
                t._btn.configure(text_color=TEXT_LOW, fg_color="transparent")
            if t._indicator:
                t._indicator.configure(fg_color=BORDER)
            if t._btn_frame:
                t._btn_frame.configure(fg_color="transparent")

        self._welcome.grid_remove()
        self._editor_host.grid()
        tab.widget.pack(fill="both", expand=True)
        self._active_tab = tab

        color, _ = VIEWER_COLORS.get(tab.viewer_type, (ACCENT, ""))
        if tab._btn:
            tab._btn.configure(text_color=TEXT_HI, fg_color=TAB_ACTIVE_BG)
        if tab._indicator:
            tab._indicator.configure(fg_color=color)
        if tab._btn_frame:
            tab._btn_frame.configure(fg_color=TAB_ACTIVE_BG)

        self._metadata_panel.load(tab.path)
        self._set_viewer_badge(tab.viewer_type)
        name = Path(tab.path).name
        self._set_status(f"  {name}")

    def _close_tab(self, tab: _Tab):
        if getattr(tab.widget, "is_modified", False):
            if not messagebox.askyesno(
                    "Unsaved changes",
                    f"{Path(tab.path).name} has unsaved changes. Close anyway?"):
                return

        tab.widget.pack_forget()
        tab.widget.destroy()

        if tab._btn_frame:
            tab._btn_frame.destroy()

        self._tabs.remove(tab)

        if self._active_tab is tab:
            self._active_tab = None
            if self._tabs:
                self._activate_tab(self._tabs[-1])
            else:
                self._editor_host.grid_remove()
                self._welcome.grid()
                self._metadata_panel.clear()
                self._viewer_type_lbl.configure(text="")
                self._vtype_frame.configure(fg_color=BG_RAISED, border_width=0)
                self._set_status("Ready")

    def _on_tab_modified(self, path: str, modified: bool):
        for tab in self._tabs:
            if tab.path == path:
                name    = Path(path).name
                display = name if len(name) <= 22 else name[:20] + "…"
                _, icon = VIEWER_COLORS.get(tab.viewer_type, (TEXT_LOW, "📄"))
                dot     = "  ●" if modified else ""
                tab.label_var.set(f"{icon}  {display}{dot}")
                if tab._btn:
                    tab._btn.configure(text=tab.label_var.get())
                break

    # ── toolbar actions ───────────────────────────────────

    def _save_current(self):
        if self._active_tab:
            self._active_tab.widget.save()

    def _save_as_current(self):
        if self._active_tab:
            self._active_tab.widget.save_as()

    def _find_in_current(self):
        if self._active_tab and hasattr(self._active_tab.widget, "_find_bar"):
            self._active_tab.widget._find_bar()

    def _replace_in_current(self):
        if self._active_tab and hasattr(self._active_tab.widget, "_replace_bar"):
            self._active_tab.widget._replace_bar()

    def _refresh_current(self):
        if self._active_tab:
            path = self._active_tab.path
            self._close_tab(self._active_tab)
            self.open_file(path)