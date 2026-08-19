# modules/color_picker/ui.py
#
# Color Picker & Palette Tool — pick a color via hex/RGB/HSV/eyedropper,
# see a live preview, and generate harmony palettes (complementary,
# analogous, shades, etc.) from it. Clicking a generated swatch makes it
# the active color (so you can drill into a harmony color further); the
# small hex label under each swatch copies that swatch specifically
# without disturbing the active color.

from __future__ import annotations

import customtkinter as ctk

from core import theme
from .color_utils import (
    HARMONY_SCHEMES,
    InvalidColorError,
    harmony_palette,
    hex_to_rgb,
    hsv_to_rgb,
    normalize_hex,
    readable_text_color,
    rgb_to_hex,
    rgb_to_hsv,
)
from .eyedropper import open_eyedropper


SWATCH_SIZE = 64


class ColorPickerModule(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=theme.BG, **kwargs)
        self.manager = manager
        self.root_widget = manager.container if manager is not None else master

        self._updating = False  # guards against slider<->hex feedback loops
        self._rgb = hex_to_rgb(theme.ACCENT)

        self._build_layout()
        self._apply_rgb(*self._rgb, source=None)

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=340)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self, text="Color Picker & Palette Tool",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
        )
        header.grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 4))

        # ---------------------------------------------------------- left
        left = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        left.grid_columnconfigure(0, weight=1)

        self.preview = ctk.CTkLabel(
            left, text="", height=100, corner_radius=8, fg_color=theme.ACCENT,
        )
        self.preview.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 12))

        # ---- hex entry + eyedropper ----
        hex_row = ctk.CTkFrame(left, fg_color="transparent")
        hex_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        hex_row.grid_columnconfigure(0, weight=1)

        self.hex_var = ctk.StringVar(value=theme.ACCENT)
        self.hex_entry = ctk.CTkEntry(hex_row, textvariable=self.hex_var, fg_color=theme.PANEL_2)
        self.hex_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.hex_entry.bind("<Return>", lambda _e: self._on_hex_changed())
        self.hex_entry.bind("<FocusOut>", lambda _e: self._on_hex_changed())

        ctk.CTkButton(
            hex_row, text="Pick 🎯", width=70, fg_color=theme.ACCENT, hover_color="#3d8fe0",
            command=self._start_eyedropper,
        ).grid(row=0, column=1)

        self.error_label = ctk.CTkLabel(left, text="", text_color=theme.DANGER, wraplength=300, justify="left")
        self.error_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))

        # ---- RGB sliders ----
        ctk.CTkLabel(left, text="RGB", text_color=theme.MUTED, font=ctk.CTkFont(weight="bold")).grid(
            row=3, column=0, sticky="w", padx=12, pady=(8, 2)
        )
        self.r_var = self._add_slider(left, 4, "R", 0, 255, self._on_rgb_slider)
        self.g_var = self._add_slider(left, 6, "G", 0, 255, self._on_rgb_slider)
        self.b_var = self._add_slider(left, 8, "B", 0, 255, self._on_rgb_slider)

        # ---- HSV sliders ----
        ctk.CTkLabel(left, text="HSV", text_color=theme.MUTED, font=ctk.CTkFont(weight="bold")).grid(
            row=10, column=0, sticky="w", padx=12, pady=(12, 2)
        )
        self.h_var = self._add_slider(left, 11, "H", 0, 360, self._on_hsv_slider)
        self.s_var = self._add_slider(left, 13, "S", 0, 100, self._on_hsv_slider)
        self.v_var = self._add_slider(left, 15, "V", 0, 100, self._on_hsv_slider)

        # ---- copy buttons ----
        copy_row = ctk.CTkFrame(left, fg_color="transparent")
        copy_row.grid(row=17, column=0, sticky="ew", padx=12, pady=(16, 12))
        ctk.CTkButton(
            copy_row, text="Copy HEX", fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=lambda: self._copy_text(self.hex_var.get()),
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(
            copy_row, text="Copy RGB", fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=lambda: self._copy_text(f"rgb({self._rgb[0]}, {self._rgb[1]}, {self._rgb[2]})"),
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.status_label = ctk.CTkLabel(left, text="", text_color=theme.MUTED)
        self.status_label.grid(row=18, column=0, sticky="ew", padx=12, pady=(0, 12))

        # --------------------------------------------------------- right
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 16))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        scheme_row = ctk.CTkFrame(right, fg_color="transparent")
        scheme_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        ctk.CTkLabel(scheme_row, text="Palette:", text_color=theme.MUTED).pack(side="left", padx=(0, 8))

        self.scheme_var = ctk.StringVar(value=HARMONY_SCHEMES[0])
        ctk.CTkOptionMenu(
            scheme_row, values=HARMONY_SCHEMES, variable=self.scheme_var,
            fg_color=theme.PANEL_2, button_color=theme.ACCENT, button_hover_color=theme.ACCENT,
            command=lambda _v: self._refresh_palette(),
        ).pack(side="left")

        self.palette_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.palette_frame.grid(row=1, column=0, sticky="n", padx=16, pady=(0, 16))

    def _add_slider(self, parent, row: int, label: str, lo: int, hi: int, callback) -> ctk.DoubleVar:
        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.grid(row=row, column=0, sticky="ew", padx=12, pady=(2, 0))
        row_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row_frame, text=label, text_color=theme.MUTED, width=16).grid(row=0, column=0)
        var = ctk.DoubleVar(value=lo)
        value_label = ctk.CTkLabel(row_frame, text=str(lo), text_color="white", width=36)
        value_label.grid(row=0, column=2)

        def on_change(v):
            value_label.configure(text=str(round(float(v))))
            callback()

        slider = ctk.CTkSlider(
            row_frame, from_=lo, to=hi, variable=var, progress_color=theme.ACCENT,
            button_color=theme.ACCENT, button_hover_color="#3d8fe0", command=on_change,
        )
        slider.grid(row=0, column=1, sticky="ew", padx=8)
        var._value_label = value_label  # for programmatic updates below
        return var

    # --------------------------------------------------------- state sync

    def _apply_rgb(self, r: int, g: int, b: int, *, source: str | None) -> None:
        """Single source of truth for a color change: updates internal
        state plus every widget except the one that triggered it (avoids
        feedback loops and cursor-jumping in the entry the user is
        actively typing in)."""
        self._updating = True
        try:
            r, g, b = (max(0, min(255, round(c))) for c in (r, g, b))
            self._rgb = (r, g, b)
            hex_color = rgb_to_hex(r, g, b)
            h, s, v = rgb_to_hsv(r, g, b)

            self.preview.configure(fg_color=hex_color)

            if source != "hex":
                self.hex_var.set(hex_color)
            if source != "rgb":
                self._set_slider(self.r_var, r)
                self._set_slider(self.g_var, g)
                self._set_slider(self.b_var, b)
            if source != "hsv":
                self._set_slider(self.h_var, h)
                self._set_slider(self.s_var, s)
                self._set_slider(self.v_var, v)

            self.error_label.configure(text="")
        finally:
            self._updating = False

        self._refresh_palette()

    def _set_slider(self, var: ctk.DoubleVar, value: float) -> None:
        var.set(value)
        label = getattr(var, "_value_label", None)
        if label is not None:
            label.configure(text=str(round(value)))

    def _on_hex_changed(self) -> None:
        if self._updating:
            return
        try:
            normalized = normalize_hex(self.hex_var.get())
        except InvalidColorError as e:
            self.error_label.configure(text=str(e))
            return
        self._apply_rgb(*hex_to_rgb(normalized), source="hex")

    def _on_rgb_slider(self) -> None:
        if self._updating:
            return
        self._apply_rgb(self.r_var.get(), self.g_var.get(), self.b_var.get(), source="rgb")

    def _on_hsv_slider(self) -> None:
        if self._updating:
            return
        r, g, b = hsv_to_rgb(self.h_var.get(), self.s_var.get(), self.v_var.get())
        self._apply_rgb(r, g, b, source="hsv")

    # ------------------------------------------------------------- palette

    def _refresh_palette(self) -> None:
        for child in self.palette_frame.winfo_children():
            child.destroy()

        hex_color = rgb_to_hex(*self._rgb)
        try:
            swatches = harmony_palette(hex_color, self.scheme_var.get())
        except InvalidColorError:
            return

        for col, swatch_hex in enumerate(swatches):
            self._build_swatch(col, swatch_hex)

    def _build_swatch(self, col: int, swatch_hex: str) -> None:
        r, g, b = hex_to_rgb(swatch_hex)
        text_color = readable_text_color(r, g, b)

        card = ctk.CTkFrame(self.palette_frame, fg_color="transparent")
        card.grid(row=0, column=col, padx=6)

        swatch = ctk.CTkButton(
            card, text="", width=SWATCH_SIZE, height=SWATCH_SIZE, corner_radius=8,
            fg_color=swatch_hex, hover_color=swatch_hex, border_width=1, border_color=theme.PANEL_2,
            command=lambda hx=swatch_hex: self._apply_rgb(*hex_to_rgb(hx), source=None),
        )
        swatch.pack()

        ctk.CTkButton(
            card, text=swatch_hex, width=SWATCH_SIZE, height=22, corner_radius=6,
            fg_color=theme.PANEL_2, hover_color=theme.ACCENT, text_color=theme.MUTED,
            font=ctk.CTkFont(size=10),
            command=lambda hx=swatch_hex: self._copy_text(hx),
        ).pack(pady=(4, 0))

    # ------------------------------------------------------------- actions

    def _start_eyedropper(self) -> None:
        open_eyedropper(self.root_widget, lambda hex_color: self._apply_rgb(*hex_to_rgb(hex_color), source=None))

    def _copy_text(self, text: str) -> None:
        self.root_widget.clipboard_clear()
        self.root_widget.clipboard_append(text)
        self.status_label.configure(text=f"Copied {text}")