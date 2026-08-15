# modules/qr_generator/ui.py
#
# QR Code Generator — pick a type (plain text/URL, Wi-Fi, email, phone,
# SMS), fill in the relevant fields, and get a live-updating QR preview
# you can save as a PNG or copy the raw encoded text from.
#
# `manager` follows the shared convention (manager.container is the root
# App instance) even though this module doesn't currently need it beyond
# the constructor signature every module page is expected to accept.

from __future__ import annotations

from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from .qr_builder import (
    DEFAULT_ERROR_CORRECTION,
    ERROR_CORRECTION_LEVELS,
    QR_TYPES,
    QRBuildError,
    WIFI_SECURITY_TYPES,
    EmailFields,
    SmsFields,
    WifiFields,
    build_payload,
    generate_image,
)

BG = "#0f1115"
PANEL = "#151922"
PANEL_2 = "#1b2030"
ACCENT = "#4ea1ff"
DANGER = "#ff5c5c"
MUTED = "#7d8494"

PREVIEW_SIZE = 320
REGENERATE_DELAY_MS = 300


class QRGeneratorModule(ctk.CTkFrame):

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=BG, **kwargs)
        self.manager = manager
        self.root_widget = manager.container if manager is not None else master

        self._regen_after_id = None
        self._current_image: Image.Image | None = None
        self._current_payload: str = ""
        self._field_vars: dict[str, ctk.StringVar] = {}
        self._field_widgets_frame: ctk.CTkFrame | None = None

        self._build_layout()
        self._rebuild_type_fields()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=340)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self, text="QR Code Generator",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
        )
        header.grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 4))

        # ---- left: controls ----
        left = ctk.CTkScrollableFrame(self, fg_color=PANEL, corner_radius=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        left.grid_columnconfigure(0, weight=1)
        self._left = left

        ctk.CTkLabel(left, text="Type", text_color=MUTED).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 2)
        )
        self.type_var = ctk.StringVar(value=QR_TYPES[0])
        ctk.CTkOptionMenu(
            left, values=QR_TYPES, variable=self.type_var,
            fg_color=PANEL_2, button_color=ACCENT, button_hover_color=ACCENT,
            command=lambda _v: self._rebuild_type_fields(),
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

        # Type-specific fields get rebuilt into this frame each time the
        # type changes.
        self._field_widgets_frame = ctk.CTkFrame(left, fg_color="transparent")
        self._field_widgets_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        self._field_widgets_frame.grid_columnconfigure(0, weight=1)

        # ---- options ----
        ctk.CTkLabel(left, text="Error Correction", text_color=MUTED).grid(
            row=3, column=0, sticky="w", padx=12, pady=(16, 2)
        )
        self.ec_var = ctk.StringVar(value=DEFAULT_ERROR_CORRECTION)
        ctk.CTkOptionMenu(
            left, values=list(ERROR_CORRECTION_LEVELS.keys()), variable=self.ec_var,
            fg_color=PANEL_2, button_color=ACCENT, button_hover_color=ACCENT,
            command=lambda _v: self._schedule_regenerate(),
        ).grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))

        color_row = ctk.CTkFrame(left, fg_color="transparent")
        color_row.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 12))
        color_row.grid_columnconfigure((0, 1), weight=1)

        fg_col = ctk.CTkFrame(color_row, fg_color="transparent")
        fg_col.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(fg_col, text="Foreground", text_color=MUTED).pack(anchor="w")
        self.fg_var = ctk.StringVar(value="#000000")
        ctk.CTkEntry(fg_col, textvariable=self.fg_var, width=90, fg_color=PANEL_2).pack(anchor="w", pady=(2, 0))
        self.fg_var.trace_add("write", lambda *_: self._schedule_regenerate())

        bg_col = ctk.CTkFrame(color_row, fg_color="transparent")
        bg_col.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(bg_col, text="Background", text_color=MUTED).pack(anchor="w")
        self.bg_var = ctk.StringVar(value="#ffffff")
        ctk.CTkEntry(bg_col, textvariable=self.bg_var, width=90, fg_color=PANEL_2).pack(anchor="w", pady=(2, 0))
        self.bg_var.trace_add("write", lambda *_: self._schedule_regenerate())

        self.error_label = ctk.CTkLabel(left, text="", text_color=DANGER, wraplength=300, justify="left")
        self.error_label.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 8))

        # ---- right: preview ----
        right = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 16))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)

        self.preview_label = ctk.CTkLabel(right, text="", fg_color="transparent")
        self.preview_label.grid(row=0, column=0, pady=(24, 12))

        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.grid(row=1, column=0, pady=(0, 16))

        ctk.CTkButton(
            btn_row, text="Save as PNG…", width=140,
            fg_color=ACCENT, hover_color="#3d8fe0", command=self._save_png,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_row, text="Copy Encoded Text", width=160,
            fg_color=PANEL_2, hover_color=ACCENT, command=self._copy_payload,
        ).pack(side="left", padx=6)

        self.status_label = ctk.CTkLabel(right, text="", text_color=MUTED)
        self.status_label.grid(row=2, column=0, pady=(0, 16))

    # -------------------------------------------------------- type fields

    def _rebuild_type_fields(self) -> None:
        for child in self._field_widgets_frame.winfo_children():
            child.destroy()
        self._field_vars = {}

        qr_type = self.type_var.get()
        row = 0

        def add_field(key: str, label: str, *, show: str | None = None) -> ctk.StringVar:
            nonlocal row
            ctk.CTkLabel(self._field_widgets_frame, text=label, text_color=MUTED).grid(
                row=row, column=0, sticky="w", padx=12, pady=(8, 2)
            )
            row += 1
            var = ctk.StringVar()
            entry = ctk.CTkEntry(self._field_widgets_frame, textvariable=var, fg_color=PANEL_2, show=show or "")
            entry.grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 4))
            row += 1
            var.trace_add("write", lambda *_: self._schedule_regenerate())
            self._field_vars[key] = var
            return var

        if qr_type == "Text / URL":
            add_field("text", "Text or URL")

        elif qr_type == "Wi-Fi Network":
            add_field("ssid", "Network Name (SSID)")
            add_field("password", "Password", show="*")
            ctk.CTkLabel(self._field_widgets_frame, text="Security", text_color=MUTED).grid(
                row=row, column=0, sticky="w", padx=12, pady=(8, 2)
            )
            row += 1
            sec_var = ctk.StringVar(value=WIFI_SECURITY_TYPES[0])
            ctk.CTkOptionMenu(
                self._field_widgets_frame, values=WIFI_SECURITY_TYPES, variable=sec_var,
                fg_color=PANEL_2, button_color=ACCENT, button_hover_color=ACCENT,
                command=lambda _v: self._schedule_regenerate(),
            ).grid(row=row, column=0, sticky="ew", padx=12, pady=(0, 4))
            row += 1
            self._field_vars["security"] = sec_var
            hidden_var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(
                self._field_widgets_frame, text="Hidden network", variable=hidden_var,
                fg_color=ACCENT, hover_color=ACCENT, command=self._schedule_regenerate,
            ).grid(row=row, column=0, sticky="w", padx=12, pady=(4, 4))
            row += 1
            self._field_vars["hidden"] = hidden_var

        elif qr_type == "Email":
            add_field("address", "Email Address")
            add_field("subject", "Subject (optional)")
            add_field("body", "Body (optional)")

        elif qr_type == "Phone Number":
            add_field("phone", "Phone Number")

        elif qr_type == "SMS":
            add_field("number", "Phone Number")
            add_field("message", "Message (optional)")

        self._schedule_regenerate()

    # --------------------------------------------------------- generation

    def _schedule_regenerate(self) -> None:
        if self._regen_after_id is not None:
            try:
                self.after_cancel(self._regen_after_id)
            except Exception:
                pass
        self._regen_after_id = self.after(REGENERATE_DELAY_MS, self._regenerate)

    def _build_current_payload(self) -> str:
        qr_type = self.type_var.get()
        v = self._field_vars

        if qr_type == "Text / URL":
            return build_payload(qr_type, text=v["text"].get())

        if qr_type == "Wi-Fi Network":
            return build_payload(qr_type, wifi=WifiFields(
                ssid=v["ssid"].get(),
                password=v["password"].get(),
                security=v["security"].get(),
                hidden=bool(v["hidden"].get()),
            ))

        if qr_type == "Email":
            return build_payload(qr_type, email=EmailFields(
                address=v["address"].get(),
                subject=v["subject"].get(),
                body=v["body"].get(),
            ))

        if qr_type == "Phone Number":
            return build_payload(qr_type, phone=v["phone"].get())

        if qr_type == "SMS":
            return build_payload(qr_type, sms=SmsFields(
                number=v["number"].get(),
                message=v["message"].get(),
            ))

        return build_payload(qr_type)

    def _regenerate(self) -> None:
        self._regen_after_id = None
        self.error_label.configure(text="")

        try:
            payload = self._build_current_payload()
        except QRBuildError as e:
            self._show_placeholder(str(e))
            return

        fg = self.fg_var.get().strip() or "#000000"
        bg = self.bg_var.get().strip() or "#ffffff"
        for value, name in ((fg, "Foreground"), (bg, "Background")):
            if not (value.startswith("#") and len(value) in (4, 7)):
                self.error_label.configure(text=f"{name} color must be a hex code like #000000.")
                return

        try:
            img = generate_image(
                payload,
                error_correction=self.ec_var.get(),
                fill_color=fg,
                back_color=bg,
            )
        except QRBuildError as e:
            self._show_placeholder(str(e))
            return
        except Exception as e:
            self.error_label.configure(text=f"Couldn't generate QR code: {e}")
            return

        self._current_image = img
        self._current_payload = payload

        display = img.copy()
        display.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=display, dark_image=display, size=display.size)
        self.preview_label.configure(image=ctk_img, text="")
        self.preview_label.image = ctk_img  # keep a reference
        self.status_label.configure(text=f"{len(payload)} character(s) encoded")

    def _show_placeholder(self, message: str) -> None:
        self._current_image = None
        self._current_payload = ""
        self.preview_label.configure(image=None, text=message, text_color=MUTED, wraplength=260)
        self.preview_label.image = None
        self.status_label.configure(text="")

    # ------------------------------------------------------------- actions

    def _save_png(self) -> None:
        if self._current_image is None:
            self.status_label.configure(text="Nothing to save yet — fix the fields above first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            initialfile="qrcode.png",
            title="Save QR Code",
        )
        if not path:
            return
        try:
            self._current_image.save(path)
            self.status_label.configure(text=f"Saved to {path}")
        except Exception as e:
            self.status_label.configure(text=f"Couldn't save: {e}")

    def _copy_payload(self) -> None:
        if not self._current_payload:
            self.status_label.configure(text="Nothing to copy yet — fix the fields above first.")
            return
        self.root_widget.clipboard_clear()
        self.root_widget.clipboard_append(self._current_payload)
        self.status_label.configure(text="Encoded text copied to clipboard")
