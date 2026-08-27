import customtkinter as ctk

from core import theme
from .library import Library


def build(parent, manager):
    frame = ctk.CTkFrame(parent, fg_color=theme.PANEL_2, corner_radius=10)
    lib = Library()
    recent = lib.recent_progress(limit=1)

    if not recent:
        ctk.CTkLabel(frame, text="📖 No manga in progress", text_color=theme.FAINT).pack(padx=10, pady=8)
        return frame

    _, manga_title, chapter_label, page_index, _ = recent[0]
    ctk.CTkLabel(
        frame, text=f"📖 {manga_title}", font=ctk.CTkFont(size=13, weight="bold"), text_color=theme.TEXT,
    ).pack(padx=10, pady=(8, 0), anchor="w")
    ctk.CTkLabel(
        frame, text=f"{chapter_label} · page {page_index + 1}", text_color=theme.FAINT,
    ).pack(padx=10, pady=(0, 8), anchor="w")
    return frame
