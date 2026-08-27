"""Optional FIDO2 security-key settings for Secure Vault."""

from __future__ import annotations

import customtkinter as ctk
from tkinter import simpledialog, messagebox

from core import theme


class HardwareKeyTab(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self.auth = manager.container.auth_service
        self.hw = manager.container.hardware_key_service

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Security key (optional)",
            font=theme.font(13, "bold"), text_color=theme.TEXT, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        ctk.CTkLabel(
            self,
            text="Use a FIDO2 USB key (YubiKey, etc.) to unlock the vault instead of typing your master password.",
            font=theme.font(11), text_color=theme.MUTED, anchor="w", justify="left", wraplength=520,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self._status = ctk.CTkLabel(
            self, text="", font=theme.font(11), text_color=theme.FAINT, anchor="w", justify="left", wraplength=520,
        )
        self._status.grid(row=2, column=0, sticky="ew", pady=(0, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)

        self._register_btn = ctk.CTkButton(
            btn_row, text="Register security key", height=36,
            command=self._register, **theme.primary_button_style(),
        )
        self._register_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self._remove_btn = ctk.CTkButton(
            btn_row, text="Remove", width=100, height=36,
            command=self._remove, **theme.secondary_button_style(),
        )
        self._remove_btn.grid(row=0, column=1, sticky="e")

        self._refresh_status()

    def _refresh_status(self):
        msg = self.hw.status_message()
        if self.hw.is_enabled():
            color = theme.SUCCESS
        elif not self.hw.library_available():
            color = theme.ERROR
        else:
            color = theme.FAINT
        self._status.configure(text=msg, text_color=color)
        self._remove_btn.configure(state="normal" if self.hw.is_enabled() else "disabled")

    def _confirm_master_password(self) -> bool:
        if not self.auth.is_initialized():
            messagebox.showerror("Secure Vault", "Create a master password first.")
            return False
        pwd = simpledialog.askstring(
            "Confirm master password",
            "Enter your master password to change security key settings:",
            show="•",
            parent=self.winfo_toplevel(),
        )
        if pwd is None:
            return False
        if not self.auth.verify_master_password(pwd):
            messagebox.showerror("Secure Vault", "Incorrect master password.")
            return False
        return True

    def _register(self):
        if not self._confirm_master_password():
            return
        try:
            self.hw.register_key()
            messagebox.showinfo(
                "Security key registered",
                "Your key is registered. Use “Unlock with security key” on the vault lock screen.",
            )
        except Exception as exc:
            messagebox.showerror("Registration failed", str(exc))
        self._refresh_status()

    def _remove(self):
        if not self._confirm_master_password():
            return
        if not messagebox.askyesno(
            "Remove security key",
            "Remove registered key unlock? You will need your master password to unlock.",
        ):
            return
        self.hw.disable()
        self._refresh_status()
