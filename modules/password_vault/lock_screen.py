import customtkinter as ctk

from .ui import PasswordVaultPage
from core import theme

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2

ACCENT = theme.ACCENT

TEXT = theme.TEXT
MUTED = theme.MUTED

ERROR = theme.ERROR


class PasswordVaultLockScreen(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent)

        self.manager = manager

        self.auth = manager.container.auth_service

        self.configure(fg_color=BG)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.build_ui()

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        card = ctk.CTkFrame(
            self,
            fg_color=PANEL,
            width=500,
            height=400
        )

        card.place(
            relx=0.5,
            rely=0.5,
            anchor="center"
        )

        ctk.CTkLabel(
            card,
            text="🔐 Password Vault",
            font=("Segoe UI", 28, "bold"),
            text_color=TEXT
        ).pack(pady=(30, 10))

        # -------------------------------------------------
        # FIRST RUN
        # -------------------------------------------------

        if not self.auth.is_initialized():

            ctk.CTkLabel(
                card,
                text="Create Master Password",
                text_color=MUTED
            ).pack(pady=(0, 15))

            self.password_entry = ctk.CTkEntry(
                card,
                placeholder_text="Master Password",
                show="*",
                width=300
            )
            self.password_entry.pack(pady=5)

            self.confirm_entry = ctk.CTkEntry(
                card,
                placeholder_text="Confirm Password",
                show="*",
                width=300
            )
            self.confirm_entry.pack(pady=5)

            self.error_label = ctk.CTkLabel(
                card,
                text="",
                text_color=ERROR
            )
            self.error_label.pack(pady=5)

            ctk.CTkButton(
                card,
                text="Create Vault",
                fg_color=ACCENT,
                width=250,
                command=self.create_master_password
            ).pack(pady=20)

        # -------------------------------------------------
        # LOGIN
        # -------------------------------------------------

        else:

            ctk.CTkLabel(
                card,
                text="Enter Master Password",
                text_color=MUTED
            ).pack(pady=(0, 15))

            self.password_entry = ctk.CTkEntry(
                card,
                placeholder_text="Master Password",
                show="*",
                width=300
            )
            self.password_entry.pack(pady=5)

            self.error_label = ctk.CTkLabel(
                card,
                text="",
                text_color=ERROR
            )
            self.error_label.pack(pady=5)

            ctk.CTkButton(
                card,
                text="Unlock Vault",
                fg_color=ACCENT,
                width=250,
                command=self.unlock_vault
            ).pack(pady=20)

    # =====================================================
    # CREATE MASTER PASSWORD
    # =====================================================

    def create_master_password(self):

        password = self.password_entry.get()
        confirm = self.confirm_entry.get()

        if len(password) < 6:
            self.error_label.configure(
                text="Password must be at least 6 characters."
            )
            return

        if password != confirm:
            self.error_label.configure(
                text="Passwords do not match."
            )
            return

        self.auth.create_master_password(password)

        self.open_vault()

    # =====================================================
    # LOGIN
    # =====================================================

    def unlock_vault(self):

        password = self.password_entry.get()

        if self.auth.verify_master_password(password):
            self.open_vault()
        else:
            self.error_label.configure(
                text="Incorrect password."
            )

    # =====================================================
    # OPEN VAULT
    # =====================================================

    def open_vault(self):

        if "vault_dashboard" not in self.manager.pages:

            vault_page = PasswordVaultPage(
                self.manager.container,
                self.manager
            )

            self.manager.add_page(
                "vault_dashboard",
                vault_page
            )

        self.manager.show_page(
            "vault_dashboard"
        )