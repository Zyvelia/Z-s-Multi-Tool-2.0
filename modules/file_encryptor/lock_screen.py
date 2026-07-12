import customtkinter as ctk

from .ui import FileEncryptorPage
from core import theme

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2

ACCENT = theme.ACCENT

TEXT = theme.TEXT
MUTED = theme.MUTED

ERROR = theme.ERROR


class FileEncryptorLockScreen(ctk.CTkFrame):

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
            height=350
        )

        card.place(
            relx=0.5,
            rely=0.5,
            anchor="center"
        )

        ctk.CTkLabel(
            card,
            text="🔒 File Encryptor",
            font=("Segoe UI", 28, "bold"),
            text_color=TEXT
        ).pack(pady=(30, 10))

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
            text="Unlock",
            fg_color=ACCENT,
            width=250,
            command=self.unlock
        ).pack(pady=(20, 20))

    # =====================================================
    # UNLOCK
    # =====================================================

    def unlock(self):

        password = self.password_entry.get()

        if self.auth.verify_master_password(password):
            self.open_encryptor()

        else:
            self.error_label.configure(
                text="Incorrect password."
            )

    # =====================================================
    # OPEN MODULE
    # =====================================================

    def open_encryptor(self):

        if "file_encryptor_dashboard" not in self.manager.pages:

            page = FileEncryptorPage(
                self.manager.container,
                self.manager
            )

            self.manager.add_page(
                "file_encryptor_dashboard",
                page
            )

        self.manager.show_page(
            "file_encryptor_dashboard"
        )