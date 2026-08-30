"""Simple vector-style icons drawn on Tk canvas (emoji render poorly on Windows)."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from core import theme as t


def _draw_server_glyph(canvas: tk.Canvas, accent: str, scale: float = 1.0) -> None:
    s = scale
    # Filled screen
    canvas.create_rectangle(
        7 * s, 5 * s, 29 * s, 21 * s,
        outline=accent, width=max(2, int(2.5 * s)), fill=t.PANEL_HOVER,
    )
    # Inner highlight line
    canvas.create_line(9 * s, 8 * s, 27 * s, 8 * s, fill=accent, width=max(1, int(1 * s)))
    # Stand
    canvas.create_line(18 * s, 21 * s, 18 * s, 26 * s, fill=accent, width=max(2, int(2 * s)))
    canvas.create_line(11 * s, 26 * s, 25 * s, 26 * s, fill=accent, width=max(2, int(2 * s)))
    # Status LEDs
    for i, x in enumerate((11, 16, 21)):
        on = i < 2
        canvas.create_oval(
            x * s, 12 * s, (x + 3) * s, 15 * s,
            fill=accent if on else t.BORDER,
            outline="",
        )


def server_icon_frame(
    master,
    size: int = 44,
    *,
    fg_color: str | None = None,
    accent: str | None = None,
) -> ctk.CTkFrame:
    """Rounded badge with a drawn server/monitor icon."""
    bg = fg_color or t.ACCENT_GLOW
    color = accent or t.ACCENT
    wrap = ctk.CTkFrame(
        master, fg_color=bg, corner_radius=t.RADIUS_SM, width=size, height=size,
    )
    wrap.grid_propagate(False)
    inner = size - 10
    scale = inner / 36.0
    canvas = tk.Canvas(
        wrap, width=inner, height=inner, bg=bg, highlightthickness=0, bd=0,
    )
    canvas.place(relx=0.5, rely=0.5, anchor="center")
    _draw_server_glyph(canvas, color, scale)
    return wrap
