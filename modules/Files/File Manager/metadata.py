"""
metadata.py — File metadata collector and right-side panel widget.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from .utils import (
    BG, BG_PANEL, BG_RAISED, BORDER, ACCENT, TEXT_HI, TEXT_MID, TEXT_LOW,
    FONT, FONT_MONO,
    human_size, file_hash, file_permissions, mime_type, format_ts,
)


def collect_metadata(path: str | Path) -> dict:
    """Collect all metadata for a file (blocking — run in thread for hashes)."""
    p    = Path(path)
    stat = p.stat()
    return {
        "Filename":    p.name,
        "Extension":   p.suffix or "(none)",
        "Size":        human_size(stat.st_size),
        "Created":     format_ts(stat.st_ctime),
        "Modified":    format_ts(stat.st_mtime),
        "Permissions": file_permissions(p),
        "MIME type":   mime_type(p),
        "SHA-256":     "computing…",
        "MD5":         "computing…",
    }


def compute_hashes(path: str | Path) -> dict:
    return {
        "SHA-256": file_hash(path, "sha256"),
        "MD5":     file_hash(path, "md5"),
    }


class MetadataPanel(ctk.CTkFrame):
    """Right-side panel showing file metadata."""

    def __init__(self, parent: ctk.CTkBaseClass, **kwargs):
        super().__init__(parent, fg_color=BG_PANEL,
                         corner_radius=10, border_width=1,
                         border_color=BORDER, width=220, **kwargs)
        self.grid_propagate(False)
        self._rows: dict[str, ctk.CTkLabel] = {}
        self._build()

    # ── build ─────────────────────────────────────────────

    def _build(self):
        ctk.CTkLabel(
            self, text="METADATA",
            text_color=TEXT_LOW, font=(FONT, 9, "bold")
        ).pack(anchor="w", padx=14, pady=(12, 6))

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=BORDER,
        )
        self._scroll.pack(fill="both", expand=True, padx=4, pady=(0, 8))

    def _add_row(self, key: str, value: str):
        frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        frame.pack(fill="x", pady=2)

        ctk.CTkLabel(
            frame, text=key,
            text_color=TEXT_LOW, font=(FONT, 9, "bold"),
            anchor="w"
        ).pack(fill="x", padx=8)

        lbl = ctk.CTkLabel(
            frame, text=value,
            text_color=TEXT_MID, font=(FONT_MONO, 9),
            anchor="w", justify="left", wraplength=180
        )
        lbl.pack(fill="x", padx=8, pady=(0, 4))
        self._rows[key] = lbl

    def _clear(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        self._rows.clear()

    # ── public ────────────────────────────────────────────

    def load(self, path: str | Path):
        """Load metadata for a file. Hashes computed in background thread."""
        self._clear()
        try:
            meta = collect_metadata(path)
        except OSError as e:
            self._add_row("Error", str(e))
            return

        for k, v in meta.items():
            self._add_row(k, v)

        # compute hashes in background
        def _bg():
            try:
                hashes = compute_hashes(path)
                self.after(0, lambda: self._update_hashes(hashes))
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _update_hashes(self, hashes: dict):
        for key, val in hashes.items():
            if key in self._rows:
                self._rows[key].configure(text=val)

    def clear(self):
        self._clear()
        ctk.CTkLabel(
            self._scroll, text="No file selected",
            text_color=TEXT_LOW, font=(FONT, 11)
        ).pack(pady=20)
