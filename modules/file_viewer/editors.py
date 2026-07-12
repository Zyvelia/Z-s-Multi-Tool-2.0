"""
editors.py — Viewer/editor widgets for each file type.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import Optional, Callable

import customtkinter as ctk
from tkinter import filedialog, messagebox, simpledialog

from .utils import (
    BG, BG_PANEL, BG_RAISED, BORDER, ACCENT, ACCENT_DIM, ACCENT_GLOW,
    RED, RED_DIM, GOLD, PURPLE, GREEN, TEAL,
    TEXT_HI, TEXT_MID, TEXT_LOW, FONT, FONT_MONO,
    safe_read_text, human_size,
)
from .file_handlers import (
    pil_available, open_image, image_to_photoimage,
    rotate_image, flip_image, resize_image, convert_image, image_metadata,
    mutagen_available, pygame_available, audio_metadata, audio_artwork,
    list_archive, extract_archive, add_to_zip, create_zip,
    hex_rows, patch_bytes, CHUNK_SIZE,
)
from .icons import (
    ICON_UNDO, ICON_REDO, ICON_FIND, ICON_REPLACE, ICON_WRAP, ICON_READONLY,
    ICON_PLAY, ICON_PAUSE, ICON_STOP, ICON_VOLUME,
    ICON_ZOOM_IN, ICON_ZOOM_OUT, ICON_FIT,
    ICON_ROTATE_L, ICON_ROTATE_R, ICON_FLIP_H, ICON_FLIP_V,
)

# ── extra colours shared across editors ──────────────────
HEX_OFFSET  = "#4a5568"
HEX_BYTE    = "#9aa4b2"
HEX_ASCII   = "#2dd4bf"
HEX_EDITED  = "#e6a817"
HEX_FOUND   = GOLD

TOOLBAR_H   = 40


# ── shared widget helpers ────────────────────────────────

def _tbtn(parent, text, cmd=None, w=80, active=False) -> ctk.CTkButton:
    """Standard toolbar button."""
    return ctk.CTkButton(
        parent, text=text, command=cmd, width=w, height=28,
        fg_color=ACCENT_GLOW if active else "transparent",
        hover_color=BG_RAISED,
        text_color=ACCENT if active else TEXT_MID,
        border_width=1 if active else 0,
        border_color=ACCENT if active else "transparent",
        corner_radius=5, font=(FONT, 10),
    )


def _sep(parent):
    """Vertical separator for toolbars."""
    ctk.CTkFrame(parent, width=1, height=20, fg_color=BORDER).pack(
        side="left", padx=6)


def _toolbar_frame(parent) -> ctk.CTkFrame:
    """Returns the inner row frame of a toolbar."""
    bar = ctk.CTkFrame(parent, fg_color=BG_PANEL,
                       corner_radius=0, height=TOOLBAR_H)
    bar.pack(fill="x")
    bar.pack_propagate(False)
    ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
    row = ctk.CTkFrame(bar, fg_color="transparent")
    row.pack(fill="both", expand=True, padx=8)
    return row


def _status_label(parent) -> ctk.CTkLabel:
    """Thin status bar at the bottom of an editor."""
    ctk.CTkFrame(parent, height=1, fg_color=BORDER).pack(fill="x", side="bottom")
    lbl = ctk.CTkLabel(
        parent, text="", anchor="w",
        fg_color=BG_PANEL, text_color=TEXT_LOW,
        font=(FONT, 10), corner_radius=0
    )
    lbl.pack(fill="x", side="bottom", ipady=4, padx=10)
    return lbl


# ═════════════════════════════════════════════════════════
# TEXT EDITOR
# ═════════════════════════════════════════════════════════

class TextEditor(ctk.CTkFrame):

    def __init__(self, parent, path: str,
                 on_modified: Callable | None = None, **kw):
        super().__init__(parent, fg_color=BG, **kw)
        self.path        = Path(path)
        self.on_modified = on_modified
        self._encoding   = "utf-8"
        self._read_only  = False
        self._wrap       = False
        self._modified   = False
        self._build()
        self._load()

    def _build(self):
        # ── toolbar ───────────────────────────────────────
        tb = _toolbar_frame(self)

        _tbtn(tb, f"{ICON_UNDO} Undo",    self._undo,         w=72).pack(side="left", padx=1)
        _tbtn(tb, f"{ICON_REDO} Redo",    self._redo,         w=72).pack(side="left", padx=1)
        _sep(tb)
        _tbtn(tb, f"{ICON_FIND} Find",    self._find_bar,     w=68).pack(side="left", padx=1)
        _tbtn(tb, f"↔ Replace",           self._replace_bar,  w=80).pack(side="left", padx=1)
        _sep(tb)
        self._wrap_btn = _tbtn(tb, "↵ Wrap",  self._toggle_wrap,    w=70)
        self._wrap_btn.pack(side="left", padx=1)
        self._ro_btn   = _tbtn(tb, "🔒 Lock",  self._toggle_readonly, w=72)
        self._ro_btn.pack(side="left", padx=1)

        self._enc_lbl = ctk.CTkLabel(tb, text="UTF-8",
                                     text_color=TEXT_LOW, font=(FONT_MONO, 9),
                                     fg_color=BG_RAISED, corner_radius=4,
                                     padx=6, pady=2)
        self._enc_lbl.pack(side="right", padx=4)

        # ── find bar (hidden) ─────────────────────────────
        self._find_frame = ctk.CTkFrame(self, fg_color=BG_PANEL,
                                        corner_radius=0, border_width=0)
        self._find_var = tk.StringVar()
        self._repl_var = tk.StringVar()

        # ── editor body ───────────────────────────────────
        body = tk.Frame(self, bg=BG, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True)

        # line number canvas
        self._ln_canvas = tk.Canvas(
            body, width=52, bg="#0d1017",
            highlightthickness=0, bd=0
        )
        self._ln_canvas.pack(side="left", fill="y")

        # thin separator
        tk.Frame(body, width=1, bg=BORDER).pack(side="left", fill="y")

        # scrollbars
        self._v_scrollbar = tk.Scrollbar(body, orient="vertical",
                                         bg=BG_PANEL, troughcolor=BG,
                                         bd=0, width=10, highlightthickness=0)
        self._v_scrollbar.pack(side="right", fill="y")
        h_sb = tk.Scrollbar(body, orient="horizontal",
                            bg=BG_PANEL, troughcolor=BG,
                            bd=0, width=10, highlightthickness=0)
        h_sb.pack(side="bottom", fill="x")

        self._text = tk.Text(
            body,
            bg="#0d1017", fg="#c9d1d9",
            insertbackground=ACCENT,
            selectbackground="#264f78",
            selectforeground="#ffffff",
            inactiveselectbackground="#1e3a52",
            font=(FONT_MONO, 12),
            wrap="none", undo=True,
            yscrollcommand=self._on_yscroll,
            xscrollcommand=h_sb.set,
            bd=0, highlightthickness=0,
            padx=12, pady=6,
            spacing1=2, spacing3=2,
        )
        self._text.pack(fill="both", expand=True)
        self._v_scrollbar.config(command=self._on_vscroll)
        h_sb.config(command=self._text.xview)

        self._text.bind("<<Modified>>",    self._on_text_modified)
        self._text.bind("<KeyRelease>",    lambda e: self._update_line_numbers())
        self._text.bind("<ButtonRelease>", lambda e: self._update_cursor())

        # syntax-like tag colours
        self._text.tag_configure("found", background=GOLD, foreground=BG)

        self._status = _status_label(self)

    # ── scroll sync ───────────────────────────────────────

    def _on_yscroll(self, *args):
        self._v_scrollbar.set(*args)
        self._update_line_numbers()

    def _on_vscroll(self, *args):
        self._text.yview(*args)
        self._update_line_numbers()

    # ── line numbers ──────────────────────────────────────

    def _update_line_numbers(self):
        self._ln_canvas.delete("all")
        i = self._text.index("@0,0")
        while True:
            dline = self._text.dlineinfo(i)
            if dline is None:
                break
            y   = dline[1]
            num = str(i).split(".")[0]
            self._ln_canvas.create_text(
                44, y + 6, anchor="ne",
                text=num, fill="#3d4f63",
                font=(FONT_MONO, 11)
            )
            next_i = self._text.index(f"{i}+1line")
            if next_i == i:
                break
            i = next_i

    # ── load / save ───────────────────────────────────────

    def _load(self):
        try:
            text, enc = safe_read_text(self.path)
            self._encoding = enc
            self._enc_lbl.configure(text=enc.upper())
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            self._text.insert("1.0", text)
            self._text.edit_reset()
            self._text.edit_modified(False)
            self._modified = False
            self.after(50, self._update_line_numbers)
            self._set_status(f"Loaded  ·  {enc.upper()}")
        except Exception as e:
            self._text.insert("1.0", f"[Error loading file]\n{e}")
            self._set_status(f"Error: {e}")

    def save(self, path=None):
        dest = Path(path) if path else self.path
        if self._read_only and dest == self.path:
            messagebox.showwarning("Read-only", "Unlock the file first.")
            return
        try:
            dest.write_text(self._text.get("1.0", "end-1c"),
                            encoding=self._encoding)
            self._modified = False
            self._text.edit_modified(False)
            if self.on_modified:
                self.on_modified(False)
            self._set_status(f"Saved  ·  {dest.name}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def save_as(self):
        dest = filedialog.asksaveasfilename(
            initialfile=self.path.name,
            defaultextension=self.path.suffix)
        if dest:
            self.save(dest)

    # ── editing ───────────────────────────────────────────

    def _undo(self):
        try: self._text.edit_undo()
        except tk.TclError: pass

    def _redo(self):
        try: self._text.edit_redo()
        except tk.TclError: pass

    def _toggle_wrap(self):
        self._wrap = not self._wrap
        self._text.configure(wrap="word" if self._wrap else "none")
        self._wrap_btn.configure(
            text_color=ACCENT if self._wrap else TEXT_MID,
            fg_color=ACCENT_GLOW if self._wrap else "transparent",
            border_width=1 if self._wrap else 0,
        )

    def _toggle_readonly(self):
        self._read_only = not self._read_only
        self._text.configure(state="disabled" if self._read_only else "normal")
        self._ro_btn.configure(
            text_color=ACCENT if self._read_only else TEXT_MID,
            fg_color=ACCENT_GLOW if self._read_only else "transparent",
            border_width=1 if self._read_only else 0,
        )

    def _on_text_modified(self, event=None):
        if self._text.edit_modified():
            self._modified = True
            if self.on_modified:
                self.on_modified(True)
            self._update_cursor()

    def _update_cursor(self):
        pos  = self._text.index("insert")
        row, col = pos.split(".")
        total = int(self._text.index("end-1c").split(".")[0])
        self._set_status(f"Ln {row}  Col {int(col)+1}  ·  {total} lines")

    # ── find / replace ────────────────────────────────────

    def _find_bar(self):
        self._show_find_replace(replace=False)

    def _replace_bar(self):
        self._show_find_replace(replace=True)

    def _show_find_replace(self, replace=False):
        for w in self._find_frame.winfo_children():
            w.destroy()
        self._find_frame.pack(fill="x", after=self.winfo_children()[0])

        row1 = ctk.CTkFrame(self._find_frame, fg_color="transparent")
        row1.pack(fill="x", padx=8, pady=(5, 2))

        ctk.CTkLabel(row1, text="Find", text_color=TEXT_LOW,
                     font=(FONT, 10, "bold"), width=52).pack(side="left")
        fe = ctk.CTkEntry(row1, textvariable=self._find_var,
                          fg_color=BG_RAISED, border_color=BORDER,
                          text_color=TEXT_HI, font=(FONT, 11),
                          border_width=1, height=28)
        fe.pack(side="left", fill="x", expand=True, padx=(4, 4))

        _tbtn(row1, "Next",  lambda: self._do_find(self._find_var.get()), w=60
              ).pack(side="left", padx=2)
        _tbtn(row1, "Prev",  lambda: self._do_find(self._find_var.get(), backward=True), w=60
              ).pack(side="left", padx=2)
        ctk.CTkButton(row1, text="✕", width=26, height=26,
                      fg_color="transparent", hover_color=RED_DIM,
                      text_color=TEXT_LOW, border_width=0, font=(FONT, 12),
                      command=self._hide_find).pack(side="right", padx=4)

        if replace:
            row2 = ctk.CTkFrame(self._find_frame, fg_color="transparent")
            row2.pack(fill="x", padx=8, pady=(0, 5))
            ctk.CTkLabel(row2, text="Replace", text_color=TEXT_LOW,
                         font=(FONT, 10, "bold"), width=52).pack(side="left")
            ctk.CTkEntry(row2, textvariable=self._repl_var,
                         fg_color=BG_RAISED, border_color=BORDER,
                         text_color=TEXT_HI, font=(FONT, 11),
                         border_width=1, height=28).pack(
                side="left", fill="x", expand=True, padx=(4, 4))
            _tbtn(row2, "Replace",     self._do_replace,     w=76).pack(side="left", padx=2)
            _tbtn(row2, "Replace All", self._do_replace_all, w=90).pack(side="left", padx=2)

        fe.focus()

    def _hide_find(self):
        self._find_frame.pack_forget()
        self._text.tag_remove("found", "1.0", "end")

    def _do_find(self, term, start="insert", backward=False):
        self._text.tag_remove("found", "1.0", "end")
        if not term:
            return
        idx = self._text.search(term, start, stopindex="1.0" if backward else "end",
                                backwards=backward)
        if not idx:
            idx = self._text.search(term, "end" if backward else "1.0",
                                    stopindex="1.0" if backward else "end",
                                    backwards=backward)
        if idx:
            end = f"{idx}+{len(term)}c"
            self._text.tag_add("found", idx, end)
            self._text.mark_set("insert", end)
            self._text.see(idx)

    def _do_replace(self):
        term = self._find_var.get()
        repl = self._repl_var.get()
        if not term:
            return
        idx = self._text.search(term, "insert", stopindex="end")
        if idx:
            self._text.delete(idx, f"{idx}+{len(term)}c")
            self._text.insert(idx, repl)

    def _do_replace_all(self):
        term  = self._find_var.get()
        repl  = self._repl_var.get()
        count = 0
        idx   = "1.0"
        while True:
            idx = self._text.search(term, idx, stopindex="end")
            if not idx:
                break
            self._text.delete(idx, f"{idx}+{len(term)}c")
            self._text.insert(idx, repl)
            count += 1
        self._set_status(f"Replaced {count} occurrence(s)")

    def _set_status(self, msg):
        self._status.configure(text=msg)

    @property
    def is_modified(self): return self._modified


# ═════════════════════════════════════════════════════════
# HEX VIEWER
# ═════════════════════════════════════════════════════════

class HexViewer(ctk.CTkFrame):

    ROWS = 512

    def __init__(self, parent, path: str, **kw):
        super().__init__(parent, fg_color=BG, **kw)
        self.path    = Path(path)
        self._offset = 0
        self._size   = self.path.stat().st_size
        self._edits: dict[int, int] = {}
        self._build()
        self._load_page(0)

    def _build(self):
        tb = _toolbar_frame(self)

        _tbtn(tb, "Jump to…",    self._jump_dialog,  w=80).pack(side="left", padx=1)
        _tbtn(tb, "Search hex",  self._search_hex,   w=86).pack(side="left", padx=1)
        _tbtn(tb, "Search text", self._search_text,  w=88).pack(side="left", padx=1)
        _sep(tb)
        _tbtn(tb, "Copy bytes",  self._copy_sel,     w=86).pack(side="left", padx=1)
        _tbtn(tb, "Edit byte",   self._edit_byte,    w=76).pack(side="left", padx=1)
        _tbtn(tb, "💾 Save edits", self._save_edits, w=90).pack(side="left", padx=1)

        self._edit_count_lbl = ctk.CTkLabel(
            tb, text="", text_color=GOLD,
            font=(FONT, 10), fg_color="transparent"
        )
        self._edit_count_lbl.pack(side="right", padx=8)

        # hex body
        body = tk.Frame(self, bg="#0a0c10", bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True)

        v_sb = tk.Scrollbar(body, orient="vertical",
                            bg=BG_PANEL, troughcolor=BG,
                            bd=0, width=10, highlightthickness=0)
        v_sb.pack(side="right", fill="y")
        h_sb = tk.Scrollbar(body, orient="horizontal",
                            bg=BG_PANEL, troughcolor=BG,
                            bd=0, width=10, highlightthickness=0)
        h_sb.pack(side="bottom", fill="x")

        self._text = tk.Text(
            body,
            bg="#0a0c10", fg=HEX_BYTE,
            insertbackground=ACCENT,
            selectbackground=ACCENT_GLOW,
            selectforeground=TEXT_HI,
            font=(FONT_MONO, 11),
            wrap="none", state="disabled",
            bd=0, highlightthickness=0,
            padx=14, pady=8,
            spacing1=3, spacing3=3,
            yscrollcommand=v_sb.set,
            xscrollcommand=h_sb.set,
        )
        self._text.pack(fill="both", expand=True)
        v_sb.config(command=self._text.yview)
        h_sb.config(command=self._text.xview)

        self._text.tag_configure("offset", foreground=HEX_OFFSET, font=(FONT_MONO, 11, "bold"))
        self._text.tag_configure("hex",    foreground=HEX_BYTE)
        self._text.tag_configure("sep",    foreground=BORDER)
        self._text.tag_configure("ascii",  foreground=HEX_ASCII)
        self._text.tag_configure("edited", foreground=HEX_EDITED, font=(FONT_MONO, 11, "bold"))
        self._text.tag_configure("found",  background=GOLD, foreground=BG)

        # page nav
        nav = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=34)
        nav.pack(fill="x")
        nav.pack_propagate(False)
        ctk.CTkFrame(nav, height=1, fg_color=BORDER).pack(fill="x", side="top")

        nav_inner = ctk.CTkFrame(nav, fg_color="transparent")
        nav_inner.pack(fill="both", expand=True, padx=8)

        _tbtn(nav_inner, "◀  Prev", self._prev_page, w=76).pack(side="left")
        self._page_lbl = ctk.CTkLabel(
            nav_inner, text="",
            text_color=TEXT_LOW, font=(FONT_MONO, 9)
        )
        self._page_lbl.pack(side="left", padx=12)
        _tbtn(nav_inner, "Next  ▶", self._next_page, w=76).pack(side="left")

        self._status = _status_label(self)

    def _load_page(self, offset: int):
        self._offset = max(0, min(offset, max(0, self._size - 1)))
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")

        for off_s, hex_s, asc_s in hex_rows(self.path, self._offset, self.ROWS):
            row_off = int(off_s, 16)

            self._text.insert("end", off_s, "offset")
            self._text.insert("end", "  │  ", "sep")

            # split hex into two groups of 8
            parts = hex_s.split()
            for i, part in enumerate(parts):
                if i == 8:
                    self._text.insert("end", "  ", "sep")
                byte_off = row_off + i
                tag = "edited" if byte_off in self._edits else "hex"
                self._text.insert("end", part + " ", tag)

            self._text.insert("end", " │  ", "sep")
            self._text.insert("end", asc_s + "\n", "ascii")

        self._text.configure(state="disabled")

        rows_per_page = CHUNK_SIZE * self.ROWS
        page  = self._offset // rows_per_page if rows_per_page else 0
        total = max(1, (self._size // rows_per_page) if rows_per_page else 1)
        self._page_lbl.configure(
            text=f"Page {page + 1} / {total + 1}   ·   "
                 f"Offset  0x{self._offset:08X}   ·   "
                 f"File size  {human_size(self._size)}"
        )
        n_edits = len(self._edits)
        self._edit_count_lbl.configure(
            text=f"  {n_edits} unsaved edit{'s' if n_edits != 1 else ''}" if n_edits else ""
        )
        self._status.configure(text=f"{self.path.name}")

    def _prev_page(self):
        self._load_page(self._offset - CHUNK_SIZE * self.ROWS)

    def _next_page(self):
        self._load_page(self._offset + CHUNK_SIZE * self.ROWS)

    def _jump_dialog(self):
        val = simpledialog.askstring("Jump to offset",
                                     "Decimal or 0x hex offset:")
        if not val:
            return
        try:
            off = int(val, 0)
            self._load_page(off - (off % CHUNK_SIZE))
        except ValueError:
            messagebox.showerror("Invalid", "Could not parse offset.")

    def _search_hex(self):
        val = simpledialog.askstring("Search hex", "Hex bytes  e.g.  FF D8 FF:")
        if not val:
            return
        try:
            needle = bytes.fromhex(val.replace(" ", ""))
        except ValueError:
            messagebox.showerror("Invalid", "Not valid hex.")
            return
        self._find_bytes(needle)

    def _search_text(self):
        val = simpledialog.askstring("Search text", "Text to find:")
        if val:
            self._find_bytes(val.encode("utf-8"))

    def _find_bytes(self, needle: bytes):
        try:
            data = self.path.read_bytes()
            idx  = data.find(needle)
            if idx == -1:
                messagebox.showinfo("Not found", "Pattern not found.")
                return
            page_off = (idx // (CHUNK_SIZE * self.ROWS)) * (CHUNK_SIZE * self.ROWS)
            self._load_page(page_off)
            self._status.configure(text=f"Found at offset 0x{idx:08X}")
        except OSError as e:
            messagebox.showerror("Error", str(e))

    def _copy_sel(self):
        try:
            sel = self._text.get("sel.first", "sel.last")
            self.clipboard_clear()
            self.clipboard_append(sel)
            self._status.configure(text="Copied selection.")
        except tk.TclError:
            self._status.configure(text="No selection.")

    def _edit_byte(self):
        val = simpledialog.askstring("Edit byte",
                                     "Offset  value  (e.g.  0x1A2B  FF):")
        if not val:
            return
        parts = val.split()
        if len(parts) != 2:
            messagebox.showerror("Invalid", "Enter offset and byte value.")
            return
        try:
            off  = int(parts[0], 0)
            byte = int(parts[1], 16)
            assert 0 <= byte <= 255
        except (ValueError, AssertionError):
            messagebox.showerror("Invalid", "Bad offset or byte value.")
            return
        self._edits[off] = byte
        self._load_page(self._offset)

    def _save_edits(self):
        if not self._edits:
            self._status.configure(text="No edits to save.")
            return
        if not messagebox.askyesno("Save edits",
                                   f"Write {len(self._edits)} byte change(s) to disk?"):
            return
        try:
            for off, val in self._edits.items():
                patch_bytes(self.path, off, bytes([val]))
            self._edits.clear()
            self._load_page(self._offset)
        except OSError as e:
            messagebox.showerror("Save failed", str(e))

    def save(self, path=None): self._save_edits()
    def save_as(self): self._save_edits()

    @property
    def is_modified(self): return bool(self._edits)


# ═════════════════════════════════════════════════════════
# IMAGE VIEWER
# ═════════════════════════════════════════════════════════

class ImageViewer(ctk.CTkFrame):

    def __init__(self, parent, path: str, **kw):
        super().__init__(parent, fg_color="#080a0e", **kw)
        self.path      = Path(path)
        self._pil_orig = None
        self._pil_work = None
        self._zoom     = 1.0
        self._photo    = None
        self._build()
        self._load()

    def _build(self):
        tb = _toolbar_frame(self)

        _tbtn(tb, "🔍+",       self._zoom_in,           w=44).pack(side="left", padx=1)
        _tbtn(tb, "🔍−",       self._zoom_out,          w=44).pack(side="left", padx=1)
        _tbtn(tb, "⛶ Fit",    self._fit,               w=64).pack(side="left", padx=1)
        _tbtn(tb, "1:1",       self._zoom_reset,        w=44).pack(side="left", padx=1)
        _sep(tb)
        _tbtn(tb, "↺",         lambda: self._rotate(-90), w=36).pack(side="left", padx=1)
        _tbtn(tb, "↻",         lambda: self._rotate(90),  w=36).pack(side="left", padx=1)
        _tbtn(tb, "↔",         lambda: self._flip(True),  w=36).pack(side="left", padx=1)
        _tbtn(tb, "↕",         lambda: self._flip(False), w=36).pack(side="left", padx=1)
        _sep(tb)
        _tbtn(tb, "Resize…",   self._resize_dialog,   w=78).pack(side="left", padx=1)
        _tbtn(tb, "Convert…",  self._convert_dialog,  w=80).pack(side="left", padx=1)
        _tbtn(tb, "Info",      self._show_meta,        w=52).pack(side="left", padx=1)

        self._zoom_lbl = ctk.CTkLabel(
            tb, text="100%", text_color=TEXT_LOW,
            font=(FONT_MONO, 10), fg_color="transparent"
        )
        self._zoom_lbl.pack(side="right", padx=8)

        self._canvas = tk.Canvas(
            self, bg="#080a0e", highlightthickness=0, cursor="crosshair"
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        self._canvas.bind("<Button-4>",   lambda e: self._zoom_in())
        self._canvas.bind("<Button-5>",   lambda e: self._zoom_out())
        self._canvas.bind("<Configure>",  lambda e: self._render())

        self._status = _status_label(self)

    def _load(self):
        if not pil_available():
            self._status.configure(
                text="⚠  Pillow not installed — run:  pip install Pillow")
            return
        try:
            self._pil_orig = open_image(self.path)
            self._pil_work = self._pil_orig.copy()
            self.after(60, self._fit)
        except Exception as e:
            self._status.configure(text=f"Error: {e}")

    def _render(self):
        if not self._pil_work:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        from PIL import Image
        new_w = max(1, int(self._pil_work.width  * self._zoom))
        new_h = max(1, int(self._pil_work.height * self._zoom))
        thumb = self._pil_work.resize((new_w, new_h), Image.LANCZOS)
        self._photo = image_to_photoimage(thumb)
        self._canvas.delete("all")
        self._canvas.create_image(cw // 2, ch // 2, anchor="center",
                                  image=self._photo)
        self._zoom_lbl.configure(text=f"{self._zoom:.0%}")
        self._status.configure(
            text=f"{self.path.name}   ·   "
                 f"{self._pil_work.width} × {self._pil_work.height} px   ·   "
                 f"Zoom {self._zoom:.0%}"
        )

    def _zoom_in(self):
        self._zoom = min(self._zoom * 1.2, 16.0); self._render()

    def _zoom_out(self):
        self._zoom = max(self._zoom / 1.2, 0.03); self._render()

    def _zoom_reset(self):
        self._zoom = 1.0; self._render()

    def _fit(self):
        if not self._pil_work:
            return
        self._canvas.update_idletasks()
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        if cw > 1 and ch > 1:
            self._zoom = min(cw / self._pil_work.width,
                             ch / self._pil_work.height, 1.0)
        self._render()

    def _on_wheel(self, e):
        if e.delta > 0: self._zoom_in()
        else: self._zoom_out()

    def _rotate(self, deg):
        if self._pil_work:
            self._pil_work = rotate_image(self._pil_work, deg)
            self._render()

    def _flip(self, horiz):
        if self._pil_work:
            self._pil_work = flip_image(self._pil_work, horiz)
            self._render()

    def _resize_dialog(self):
        if not self._pil_work: return
        val = simpledialog.askstring(
            "Resize",
            f"New size WxH  (current: {self._pil_work.width}×{self._pil_work.height}):")
        if not val: return
        try:
            w, h = (int(x) for x in val.lower().replace("x", " ").split())
            self._pil_work = resize_image(self._pil_work, w, h)
            self._render()
        except Exception:
            messagebox.showerror("Invalid", "Enter format like  800x600")

    def _convert_dialog(self):
        if not self._pil_work: return
        fmt = simpledialog.askstring("Convert", "Format (PNG JPEG BMP WEBP):")
        if not fmt: return
        dest = filedialog.asksaveasfilename(
            defaultextension=f".{fmt.lower()}",
            initialfile=self.path.stem + f".{fmt.lower()}")
        if dest:
            try:
                convert_image(self._pil_work, fmt, dest)
                self._status.configure(text=f"Saved as {dest}")
            except Exception as e:
                messagebox.showerror("Convert failed", str(e))

    def _show_meta(self):
        if not self._pil_orig: return
        meta = image_metadata(self._pil_orig)
        messagebox.showinfo("Image info",
                            "\n".join(f"{k}: {v}" for k, v in meta.items()))

    def save(self, path=None):
        if not self._pil_work: return
        dest = Path(path) if path else self.path
        try:
            self._pil_work.save(str(dest))
            self._status.configure(text=f"Saved  {dest.name}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def save_as(self):
        dest = filedialog.asksaveasfilename(
            initialfile=self.path.name, defaultextension=self.path.suffix)
        if dest: self.save(dest)

    @property
    def is_modified(self): return False


# ═════════════════════════════════════════════════════════
# AUDIO PLAYER
# ═════════════════════════════════════════════════════════

class AudioPlayer(ctk.CTkFrame):

    def __init__(self, parent, path: str, **kw):
        super().__init__(parent, fg_color=BG, **kw)
        self.path     = Path(path)
        self._playing = False
        self._paused  = False
        self._build()
        self._load_meta()

    def _build(self):
        # centre everything
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.place(relx=0.5, rely=0.5, anchor="center")

        # artwork card
        card = ctk.CTkFrame(outer, fg_color=BG_PANEL,
                            corner_radius=16, border_width=1,
                            border_color=BORDER, width=480)
        card.pack(ipadx=24, ipady=20)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(20, 0))

        self._art_lbl = ctk.CTkLabel(
            top, text="🎵",
            font=(FONT, 52), text_color="#1e2d3d",
            fg_color=BG_RAISED, corner_radius=10,
            width=110, height=110
        )
        self._art_lbl.pack(side="left")

        meta = ctk.CTkFrame(top, fg_color="transparent")
        meta.pack(side="left", fill="both", expand=True, padx=(20, 0))

        self._title_lbl = ctk.CTkLabel(
            meta, text=self.path.stem,
            text_color=TEXT_HI, font=(FONT, 16, "bold"),
            anchor="w", justify="left", wraplength=280
        )
        self._title_lbl.pack(anchor="w")

        self._artist_lbl = ctk.CTkLabel(
            meta, text="",
            text_color=TEXT_MID, font=(FONT, 12),
            anchor="w"
        )
        self._artist_lbl.pack(anchor="w", pady=(2, 0))

        self._info_lbl = ctk.CTkLabel(
            meta, text="",
            text_color=TEXT_LOW, font=(FONT, 10),
            anchor="w"
        )
        self._info_lbl.pack(anchor="w", pady=(4, 0))

        # seek bar
        seek_area = ctk.CTkFrame(card, fg_color="transparent")
        seek_area.pack(fill="x", padx=24, pady=(18, 0))

        self._seek_var = ctk.DoubleVar(value=0)
        ctk.CTkSlider(
            seek_area, from_=0, to=100,
            variable=self._seek_var,
            button_color=ACCENT, button_hover_color=ACCENT_DIM,
            progress_color=ACCENT, fg_color=BORDER,
            height=4,
        ).pack(fill="x")

        time_row = ctk.CTkFrame(seek_area, fg_color="transparent")
        time_row.pack(fill="x", pady=(2, 0))
        self._pos_lbl = ctk.CTkLabel(time_row, text="0:00",
                                     text_color=TEXT_LOW, font=(FONT_MONO, 9))
        self._pos_lbl.pack(side="left")
        self._dur_lbl = ctk.CTkLabel(time_row, text="0:00",
                                     text_color=TEXT_LOW, font=(FONT_MONO, 9))
        self._dur_lbl.pack(side="right")

        # controls
        ctrl = ctk.CTkFrame(card, fg_color="transparent")
        ctrl.pack(pady=14)

        def _ctrl_btn(text, cmd, accent=False):
            return ctk.CTkButton(
                ctrl, text=text, command=cmd,
                width=80, height=34,
                fg_color=ACCENT_GLOW if accent else BG_RAISED,
                hover_color="#1a3a5c" if accent else BORDER,
                text_color=ACCENT if accent else TEXT_MID,
                border_width=1 if accent else 0,
                border_color=ACCENT if accent else "transparent",
                corner_radius=8, font=(FONT, 12)
            )

        _ctrl_btn(f"{ICON_STOP} Stop",   self._stop).pack(side="left", padx=4)
        _ctrl_btn(f"{ICON_PLAY} Play",   self._play,  accent=True).pack(side="left", padx=4)
        _ctrl_btn(f"{ICON_PAUSE} Pause", self._pause).pack(side="left", padx=4)

        # volume
        vol = ctk.CTkFrame(card, fg_color="transparent")
        vol.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(vol, text=f"{ICON_VOLUME}",
                     text_color=TEXT_LOW, font=(FONT, 13)).pack(side="left", padx=(0, 8))
        self._vol_var = ctk.DoubleVar(value=80)
        ctk.CTkSlider(
            vol, from_=0, to=100,
            variable=self._vol_var,
            button_color=TEXT_LOW, progress_color=TEXT_LOW,
            fg_color=BORDER, height=4,
            command=self._on_volume,
        ).pack(fill="x", expand=True)

        ctk.CTkButton(
            card, text="✏  Rename file",
            width=120, height=28,
            fg_color="transparent", hover_color=BG_RAISED,
            text_color=TEXT_LOW, border_width=0,
            font=(FONT, 10), command=self._rename
        ).pack(pady=(0, 4))

        self._status = _status_label(self)

    def _load_meta(self):
        if not mutagen_available():
            self._status.configure(
                text="⚠  mutagen not installed — run:  pip install mutagen")
            return
        meta = audio_metadata(self.path)
        self._title_lbl.configure(text=meta.get("Title", self.path.stem))
        self._artist_lbl.configure(
            text=meta.get("Artist", "") +
                 (f"  ·  {meta['Album']}" if meta.get("Album") else "")
        )
        dur = meta.get("Duration", "")
        br  = meta.get("Bitrate", "")
        self._info_lbl.configure(
            text="  ·  ".join(p for p in [dur, br] if p))
        if dur:
            self._dur_lbl.configure(text=dur)

        # artwork
        art = audio_artwork(self.path)
        if art and pil_available():
            try:
                from PIL import Image, ImageTk
                import io
                img = Image.open(io.BytesIO(art)).resize((110, 110))
                self._art_photo = ImageTk.PhotoImage(img)
                self._art_lbl.configure(text="", image=self._art_photo)
            except Exception:
                pass

        self._status.configure(text=str(self.path))

    def _init_pygame(self) -> bool:
        if not pygame_available():
            self._status.configure(
                text="⚠  pygame not installed — run:  pip install pygame")
            return False
        import pygame
        if not pygame.mixer.get_init():
            try: pygame.mixer.init()
            except Exception as e:
                self._status.configure(text=f"Audio init error: {e}")
                return False
        return True

    def _play(self):
        if not self._init_pygame(): return
        import pygame
        if self._paused:
            pygame.mixer.music.unpause(); self._paused = False
        else:
            try:
                pygame.mixer.music.load(str(self.path))
                pygame.mixer.music.play()
                self._playing = True
                self._update_pos()
            except Exception as e:
                self._status.configure(text=f"Playback error: {e}")

    def _pause(self):
        if not pygame_available(): return
        import pygame
        pygame.mixer.music.pause(); self._paused = True

    def _stop(self):
        if not pygame_available(): return
        import pygame
        pygame.mixer.music.stop()
        self._playing = self._paused = False
        self._seek_var.set(0)
        self._pos_lbl.configure(text="0:00")

    def _on_volume(self, v):
        if not pygame_available(): return
        import pygame
        pygame.mixer.music.set_volume(float(v) / 100)

    def _update_pos(self):
        if self._playing and not self._paused:
            try:
                import pygame
                pos = pygame.mixer.music.get_pos() / 1000
                m, s = divmod(int(pos), 60)
                self._pos_lbl.configure(text=f"{m}:{s:02d}")
            except Exception: pass
            self.after(500, self._update_pos)

    def _rename(self):
        new = simpledialog.askstring("Rename", "New filename:",
                                     initialvalue=self.path.name)
        if not new or new == self.path.name: return
        dest = self.path.parent / new
        try:
            self.path.rename(dest)
            self.path = dest
            self._status.configure(text=f"Renamed to {dest.name}")
        except OSError as e:
            messagebox.showerror("Rename failed", str(e))

    def save(self, path=None): pass
    def save_as(self): pass

    @property
    def is_modified(self): return False


# ═════════════════════════════════════════════════════════
# ARCHIVE VIEWER
# ═════════════════════════════════════════════════════════

class ArchiveViewer(ctk.CTkFrame):

    def __init__(self, parent, path: str, **kw):
        super().__init__(parent, fg_color=BG, **kw)
        self.path     = Path(path)
        self._entries = []
        self._build()
        self._load()

    def _build(self):
        tb = _toolbar_frame(self)

        _tbtn(tb, "⬇  Extract selected", self._extract_sel, w=130).pack(side="left", padx=1)
        _tbtn(tb, "⬇  Extract all",      self._extract_all, w=110).pack(side="left", padx=1)
        _sep(tb)
        _tbtn(tb, "＋  Add files…",       self._add_files,  w=100).pack(side="left", padx=1)
        _tbtn(tb, "🗜  New archive…",     self._create_new, w=110).pack(side="left", padx=1)
        _tbtn(tb, "↺  Refresh",           self._load,       w=80).pack(side="left", padx=1)

        self._entry_count = ctk.CTkLabel(
            tb, text="", text_color=TEXT_LOW, font=(FONT, 10)
        )
        self._entry_count.pack(side="right", padx=8)

        # tree frame
        tree_frame = tk.Frame(self, bg=BG_RAISED, bd=0, highlightthickness=0)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=8)

        v_sb = ttk.Scrollbar(tree_frame, orient="vertical",
                             style="Vertical.TScrollbar")
        v_sb.pack(side="right", fill="y")
        h_sb = ttk.Scrollbar(tree_frame, orient="horizontal")
        h_sb.pack(side="bottom", fill="x")

        self._tree = ttk.Treeview(
            tree_frame,
            columns=("size", "compressed", "modified"),
            style="Archive.Treeview",
            selectmode="extended",
            yscrollcommand=v_sb.set,
            xscrollcommand=h_sb.set,
        )
        self._tree.heading("#0",         text="  Name", anchor="w")
        self._tree.heading("size",       text="Size",       anchor="e")
        self._tree.heading("compressed", text="Compressed", anchor="e")
        self._tree.heading("modified",   text="Modified",   anchor="w")
        self._tree.column("#0",         width=360, minwidth=200)
        self._tree.column("size",       width=80,  anchor="e")
        self._tree.column("compressed", width=90,  anchor="e")
        self._tree.column("modified",   width=160, anchor="w")

        v_sb.config(command=self._tree.yview)
        h_sb.config(command=self._tree.xview)
        self._tree.pack(fill="both", expand=True)

        self._status = _status_label(self)

    def _load(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        try:
            self._entries = list_archive(self.path)
        except Exception as e:
            self._status.configure(text=f"Error: {e}")
            return

        dirs  = sum(1 for e in self._entries if e.is_dir)
        files = len(self._entries) - dirs

        for entry in self._entries:
            icon = "📁  " if entry.is_dir else "📄  "
            self._tree.insert("", "end",
                text=icon + entry.name,
                values=(human_size(entry.size),
                        human_size(entry.compressed_size),
                        entry.modified),
                tags=("dir" if entry.is_dir else "file",),
            )

        self._tree.tag_configure("dir",  foreground=ACCENT)
        self._tree.tag_configure("file", foreground=TEXT_MID)

        self._entry_count.configure(
            text=f"{files} file{'s' if files != 1 else ''}  ·  {dirs} folder{'s' if dirs != 1 else ''}")
        self._status.configure(text=str(self.path))

    def _selected_names(self):
        return [
            self._tree.item(iid, "text").lstrip("📁📄 ").strip()
            for iid in self._tree.selection()
        ]

    def _extract_sel(self):
        names = self._selected_names()
        if not names:
            self._status.configure(text="No files selected.")
            return
        dest = filedialog.askdirectory(title="Extract to…")
        if not dest: return
        try:
            extract_archive(self.path, dest, names)
            self._status.configure(text=f"Extracted {len(names)} item(s) to {dest}")
        except Exception as e:
            messagebox.showerror("Extract failed", str(e))

    def _extract_all(self):
        dest = filedialog.askdirectory(title="Extract all to…")
        if not dest: return
        try:
            extract_archive(self.path, dest)
            self._status.configure(text=f"Extracted all to {dest}")
        except Exception as e:
            messagebox.showerror("Extract failed", str(e))

    def _add_files(self):
        if not str(self.path).endswith(".zip"):
            messagebox.showinfo("Not supported", "Only ZIP archives support adding files.")
            return
        files = filedialog.askopenfilenames(title="Add files")
        if not files: return
        try:
            add_to_zip(self.path, list(files))
            self._load()
        except Exception as e:
            messagebox.showerror("Add failed", str(e))

    def _create_new(self):
        files = filedialog.askopenfilenames(title="Select files for new archive")
        if not files: return
        dest = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP archive", "*.zip")])
        if not dest: return
        try:
            create_zip(dest, list(files))
            self._status.configure(text=f"Created {dest}")
        except Exception as e:
            messagebox.showerror("Create failed", str(e))

    def save(self, path=None): pass
    def save_as(self): pass

    @property
    def is_modified(self): return False
