# modules/Image Palette Extractor/ui.py
#
# Load an image, pull out its N most dominant colors (median-cut +
# k-means quantization), and get each one back as a copyable hex/RGB
# swatch. Independent from the Color Picker tool (that one is about
# picking/harmonizing a single color by hand) - this one is about
# reading colors out of an existing image.

from __future__ import annotations

import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from .palette_math import PaletteError, extract_palette, readable_text_color
from core import theme


PREVIEW_MAX = 320
SWATCH_HEIGHT = 64


class ImagePaletteExtractorPage(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=theme.BG, **kwargs)
        self.manager = manager
        self.root_widget = manager.container if manager is not None else master

        self.image_path: str | None = None
        self._preview_img = None  # keep a reference alive
        self._palette: list[dict] = []

        self._build_layout()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=360)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self, text="Image Palette Extractor",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
        )
        header.grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 4))

        # ---------------------------------------------------------- left
        left = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        left.grid_columnconfigure(0, weight=1)

        self.preview = ctk.CTkLabel(
            left, text="No image loaded", height=PREVIEW_MAX, corner_radius=8,
            fg_color=theme.PANEL_2, text_color=theme.MUTED,
        )
        self.preview.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 12))

        ctk.CTkButton(
            left, text="Choose Image...", fg_color=theme.ACCENT, hover_color="#3d8fe0",
            command=self._choose_image,
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.file_label = ctk.CTkLabel(left, text="", text_color=theme.MUTED, wraplength=320, justify="left")
        self.file_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))

        count_row = ctk.CTkFrame(left, fg_color="transparent")
        count_row.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 4))
        count_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(count_row, text="Colors", text_color=theme.MUTED, width=50).grid(row=0, column=0)
        self.count_var = ctk.IntVar(value=6)
        self.count_label = ctk.CTkLabel(count_row, text="6", text_color="white", width=24)
        self.count_label.grid(row=0, column=2)

        def on_count_change(v):
            self.count_label.configure(text=str(round(float(v))))

        ctk.CTkSlider(
            count_row, from_=2, to=16, number_of_steps=14, variable=self.count_var,
            progress_color=theme.ACCENT, button_color=theme.ACCENT, button_hover_color="#3d8fe0",
            command=on_count_change,
        ).grid(row=0, column=1, sticky="ew", padx=8)

        self.extract_btn = ctk.CTkButton(
            left, text="Extract Palette", fg_color=theme.ACCENT, hover_color="#3d8fe0",
            command=self._extract_clicked, state="disabled",
        )
        self.extract_btn.grid(row=4, column=0, sticky="ew", padx=12, pady=(8, 4))

        self.status_label = ctk.CTkLabel(left, text="", text_color=theme.MUTED)
        self.status_label.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))

        # --------------------------------------------------------- right
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 16))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        top_row = ctk.CTkFrame(right, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top_row, text="Extracted Palette", text_color=theme.MUTED,
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")

        self.copy_all_btn = ctk.CTkButton(
            top_row, text="Copy All Hex", width=110, fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=self._copy_all, state="disabled",
        )
        self.copy_all_btn.grid(row=0, column=1, sticky="e")

        self.palette_frame = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.palette_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.palette_frame.grid_columnconfigure(0, weight=1)

        self._render_empty_palette()

    # ---------------------------------------------------------------- image

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an image",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            img = Image.open(path)
            img.verify()
            img = Image.open(path).convert("RGB")
        except Exception as e:
            messagebox.showerror("Image Palette Extractor", f"Couldn't open that image:\n{e}")
            return

        self.image_path = path
        self.file_label.configure(text=os.path.basename(path))
        self.extract_btn.configure(state="normal")
        self.status_label.configure(text="")

        thumb = img.copy()
        thumb.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        self._preview_img = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=thumb.size)
        self.preview.configure(image=self._preview_img, text="")

    # -------------------------------------------------------------- extract

    def _extract_clicked(self) -> None:
        if not self.image_path:
            return

        self.extract_btn.configure(state="disabled", text="Extracting...")
        self.status_label.configure(text="Extracting palette...", text_color=theme.MUTED)
        n_colors = int(self.count_var.get())
        path = self.image_path

        def worker():
            try:
                palette = extract_palette(path, n_colors)
                error = None
            except PaletteError as e:
                palette = None
                error = str(e)

            self.after(0, lambda: self._on_extracted(palette, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_extracted(self, palette, error) -> None:
        self.extract_btn.configure(state="normal", text="Extract Palette")

        if error:
            self.status_label.configure(text=error, text_color=theme.DANGER)
            return

        self._palette = palette
        self.status_label.configure(text=f"{len(palette)} colors extracted", text_color=theme.MUTED)
        self.copy_all_btn.configure(state="normal" if palette else "disabled")
        self._render_palette()

    # --------------------------------------------------------------- render

    def _render_empty_palette(self) -> None:
        for child in self.palette_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self.palette_frame, text="Choose an image and hit Extract Palette to see its colors here.",
            text_color=theme.MUTED, wraplength=420, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=4, pady=8)

    def _render_palette(self) -> None:
        for child in self.palette_frame.winfo_children():
            child.destroy()

        if not self._palette:
            self._render_empty_palette()
            return

        for row, swatch in enumerate(self._palette):
            self._build_swatch_row(row, swatch)

    def _build_swatch_row(self, row: int, swatch: dict) -> None:
        hex_color = swatch["hex"]
        r, g, b = swatch["rgb"]
        text_color = readable_text_color(r, g, b)
        rgb_text = f"rgb({r}, {g}, {b})"

        card = ctk.CTkFrame(self.palette_frame, fg_color=hex_color, corner_radius=8)
        card.grid(row=row, column=0, sticky="ew", pady=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text="", width=SWATCH_HEIGHT, height=SWATCH_HEIGHT,
        ).grid(row=0, column=0, padx=(4, 0), pady=4)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew", padx=12, pady=6)

        ctk.CTkLabel(
            info, text=f"{hex_color}   {rgb_text}", text_color=text_color,
            font=ctk.CTkFont(weight="bold"), anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            info, text=f"{swatch['percent']}% of image", text_color=text_color, anchor="w",
        ).pack(anchor="w")

        btn_col = ctk.CTkFrame(card, fg_color="transparent")
        btn_col.grid(row=0, column=2, padx=8)

        ctk.CTkButton(
            btn_col, text="Copy HEX", width=90, height=26, fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=lambda: self._copy_text(hex_color),
        ).pack(pady=(0, 4))
        ctk.CTkButton(
            btn_col, text="Copy RGB", width=90, height=26, fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=lambda: self._copy_text(rgb_text),
        ).pack()

    # --------------------------------------------------------------- actions

    def _copy_text(self, text: str) -> None:
        self.root_widget.clipboard_clear()
        self.root_widget.clipboard_append(text)
        self.status_label.configure(text=f"Copied {text}", text_color=theme.MUTED)

    def _copy_all(self) -> None:
        if not self._palette:
            return
        text = ", ".join(s["hex"] for s in self._palette)
        self._copy_text(text)