# modules/Icon Favicon Generator/ui.py
#
# Load an image, pick which outputs you want (multi-size .ico, the
# standard favicon/app-icon PNG sizes, a site.webmanifest), pick a
# destination folder, and generate the whole set in one go.

from __future__ import annotations

import os
import subprocess
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from .generator import HTML_SNIPPET, IconGeneratorError, generate
from core import theme

SUCCESS = "#4caf7d"

PREVIEW_MAX = 220


class IconFaviconGeneratorPage(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=theme.BG, **kwargs)
        self.manager = manager
        self.root_widget = manager.container if manager is not None else master

        self.source_path: str | None = None
        self.output_dir: str | None = None
        self._preview_img = None
        self._last_written: list[str] = []

        self._build_layout()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=360)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self, text="Icon / Favicon Generator",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
        )
        header.grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 4))

        # ---------------------------------------------------------- left
        left = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        left.grid_columnconfigure(0, weight=1)

        self.preview = ctk.CTkLabel(
            left, text="No image loaded", height=PREVIEW_MAX, corner_radius=8,
            fg_color=theme.PANEL_2, text_color=theme.MUTED,
        )
        self.preview.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        ctk.CTkButton(
            left, text="Choose Source Image...", fg_color=theme.ACCENT, hover_color="#3d8fe0",
            command=self._choose_source,
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))

        self.source_label = ctk.CTkLabel(left, text="", text_color=theme.MUTED, wraplength=320, justify="left")
        self.source_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))

        ctk.CTkLabel(left, text="Non-square images", text_color=theme.MUTED,
                     font=ctk.CTkFont(weight="bold")).grid(row=3, column=0, sticky="w", padx=12, pady=(4, 2))

        self.fit_mode_var = ctk.StringVar(value="fit")
        mode_row = ctk.CTkFrame(left, fg_color="transparent")
        mode_row.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 10))
        ctk.CTkRadioButton(
            mode_row, text="Fit (pad with transparency)", variable=self.fit_mode_var, value="fit",
            fg_color=theme.ACCENT,
        ).pack(anchor="w", pady=2)
        ctk.CTkRadioButton(
            mode_row, text="Fill (crop to square)", variable=self.fit_mode_var, value="fill",
            fg_color=theme.ACCENT,
        ).pack(anchor="w", pady=2)

        ctk.CTkLabel(left, text="Outputs", text_color=theme.MUTED,
                     font=ctk.CTkFont(weight="bold")).grid(row=5, column=0, sticky="w", padx=12, pady=(4, 2))

        self.make_png_var = ctk.BooleanVar(value=True)
        self.make_ico_var = ctk.BooleanVar(value=True)
        self.make_manifest_var = ctk.BooleanVar(value=True)

        ctk.CTkCheckBox(
            left, text="PNG set (16 to 512px, incl. apple-touch-icon)",
            variable=self.make_png_var, fg_color=theme.ACCENT,
        ).grid(row=6, column=0, sticky="w", padx=12, pady=2)
        ctk.CTkCheckBox(
            left, text="favicon.ico (16/32/48px multi-size)",
            variable=self.make_ico_var, fg_color=theme.ACCENT,
        ).grid(row=7, column=0, sticky="w", padx=12, pady=2)
        ctk.CTkCheckBox(
            left, text="site.webmanifest",
            variable=self.make_manifest_var, fg_color=theme.ACCENT,
        ).grid(row=8, column=0, sticky="w", padx=12, pady=(2, 10))

        self.app_name_entry = ctk.CTkEntry(left, placeholder_text="App name (used in manifest)", fg_color=theme.PANEL_2)
        self.app_name_entry.grid(row=9, column=0, sticky="ew", padx=12, pady=(0, 10))

        ctk.CTkButton(
            left, text="Choose Output Folder...", fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=self._choose_output,
        ).grid(row=10, column=0, sticky="ew", padx=12, pady=(0, 4))

        self.output_label = ctk.CTkLabel(left, text="", text_color=theme.MUTED, wraplength=320, justify="left")
        self.output_label.grid(row=11, column=0, sticky="ew", padx=12, pady=(0, 10))

        self.generate_btn = ctk.CTkButton(
            left, text="Generate", fg_color=theme.ACCENT, hover_color="#3d8fe0",
            command=self._generate_clicked, state="disabled",
        )
        self.generate_btn.grid(row=12, column=0, sticky="ew", padx=12, pady=(4, 4))

        self.status_label = ctk.CTkLabel(left, text="", text_color=theme.MUTED, wraplength=320, justify="left")
        self.status_label.grid(row=13, column=0, sticky="ew", padx=12, pady=(0, 12))

        # --------------------------------------------------------- right
        right = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 16))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        top_row = ctk.CTkFrame(right, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top_row, text="Generated Files", text_color=theme.MUTED,
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")

        self.open_folder_btn = ctk.CTkButton(
            top_row, text="Open Folder", width=110, fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=self._open_output_folder, state="disabled",
        )
        self.open_folder_btn.grid(row=0, column=1, sticky="e")

        self.results_frame = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.results_frame.grid_columnconfigure(0, weight=1)

        self._render_empty_results()

        snippet_label = ctk.CTkLabel(
            right, text="HTML <head> snippet (copied files use these exact names):",
            text_color=theme.MUTED, anchor="w",
        )
        snippet_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 2))

        self.snippet_box = ctk.CTkTextbox(right, height=110, fg_color=theme.PANEL_2, text_color=theme.MUTED)
        self.snippet_box.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.snippet_box.insert("1.0", HTML_SNIPPET)
        self.snippet_box.configure(state="disabled")

        ctk.CTkButton(
            right, text="Copy Snippet", width=110, fg_color=theme.PANEL_2, hover_color=theme.ACCENT,
            command=lambda: self._copy_text(HTML_SNIPPET),
        ).grid(row=4, column=0, sticky="e", padx=16, pady=(0, 16))

    # ---------------------------------------------------------------- image

    def _choose_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a source image",
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
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Icon/Favicon Generator", f"Couldn't open that image:\n{e}")
            return

        self.source_path = path
        self.source_label.configure(text=os.path.basename(path))
        self._update_generate_state()
        self.status_label.configure(text="")

        thumb = img.copy()
        thumb.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        self._preview_img = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=thumb.size)
        self.preview.configure(image=self._preview_img, text="")

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(title="Choose output folder")
        if not chosen:
            return
        self.output_dir = chosen
        self.output_label.configure(text=chosen)
        self._update_generate_state()

    def _update_generate_state(self) -> None:
        ready = bool(self.source_path and self.output_dir)
        self.generate_btn.configure(state="normal" if ready else "disabled")

    # ------------------------------------------------------------ generate

    def _generate_clicked(self) -> None:
        if not (self.source_path and self.output_dir):
            return

        if not (self.make_png_var.get() or self.make_ico_var.get() or self.make_manifest_var.get()):
            self.status_label.configure(text="Pick at least one output.", text_color=theme.DANGER)
            return

        self.generate_btn.configure(state="disabled", text="Generating...")
        self.status_label.configure(text="Generating...", text_color=theme.MUTED)

        source_path = self.source_path
        output_dir = self.output_dir
        fit_mode = self.fit_mode_var.get()
        make_png = self.make_png_var.get()
        make_ico = self.make_ico_var.get()
        make_manifest = self.make_manifest_var.get()
        app_name = self.app_name_entry.get().strip() or "App"

        def worker():
            try:
                written = generate(
                    source_path, output_dir,
                    fit_mode=fit_mode,
                    make_png=make_png, make_ico=make_ico, make_manifest=make_manifest,
                    app_name=app_name,
                )
                error = None
            except IconGeneratorError as e:
                written = None
                error = str(e)

            self.after(0, lambda: self._on_generated(written, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_generated(self, written, error) -> None:
        self.generate_btn.configure(state="normal", text="Generate")

        if error:
            self.status_label.configure(text=error, text_color=theme.DANGER)
            return

        self._last_written = written
        self.status_label.configure(text=f"Generated {len(written)} file(s).", text_color=SUCCESS)
        self.open_folder_btn.configure(state="normal")
        self._render_results(written)

    # --------------------------------------------------------------- render

    def _render_empty_results(self) -> None:
        for child in self.results_frame.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self.results_frame,
            text="Choose a source image and an output folder, then hit Generate.",
            text_color=theme.MUTED, wraplength=420, justify="left",
        ).grid(row=0, column=0, sticky="w", padx=4, pady=8)

    def _render_results(self, written: list[str]) -> None:
        for child in self.results_frame.winfo_children():
            child.destroy()

        if not written:
            self._render_empty_results()
            return

        for row, path in enumerate(written):
            size_kb = os.path.getsize(path) / 1024
            ctk.CTkLabel(
                self.results_frame, text=f"✅ {os.path.basename(path)}   ({size_kb:.1f} KB)",
                text_color=theme.MUTED, anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=4, pady=3)

    # --------------------------------------------------------------- actions

    def _open_output_folder(self) -> None:
        if not self.output_dir:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.output_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.output_dir])
            else:
                subprocess.Popen(["xdg-open", self.output_dir])
        except Exception as e:
            messagebox.showerror("Icon/Favicon Generator", f"Couldn't open the folder:\n{e}")

    def _copy_text(self, text: str) -> None:
        self.root_widget.clipboard_clear()
        self.root_widget.clipboard_append(text)
        self.status_label.configure(text="Snippet copied.", text_color=theme.MUTED)