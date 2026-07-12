import customtkinter as ctk
from tkinter import filedialog
import os # Ensure os is imported for os.path.basename
import subprocess # Added import for subprocess

from core import theme

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2

ACCENT = theme.ACCENT

TEXT = theme.TEXT
MUTED = theme.MUTED


class FileEncryptorPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent)

        self.manager = manager

        self.crypto = (
            manager.container.crypto_service
        )

        self.selected_file = None
        self.last_output = None # Added to remember output file

        self.configure(fg_color=BG)

        self.build_ui()

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        header = ctk.CTkFrame(
            self,
            fg_color=PANEL
        )

        header.pack(
            fill="x",
            padx=15,
            pady=15
        )

        ctk.CTkLabel(
            header,
            text="🔒 File Encryptor",
            font=("Segoe UI", 26, "bold"),
            text_color=TEXT
        ).pack(
            side="left",
            padx=10
        )

        # New file_label and status_label as requested
        self.file_label = ctk.CTkLabel(
            self,
            text="No file selected",
            text_color=MUTED
        )
        self.file_label.pack(
            pady=(10, 5)
        )

        # Added size_label
        self.size_label = ctk.CTkLabel(
            self,
            text="Size: --",
            text_color=MUTED
        )
        self.size_label.pack(
            pady=(0, 5)
        )

        self.status_label = ctk.CTkLabel(
            self,
            text="Ready",
            text_color=ACCENT
        )
        self.status_label.pack(
            pady=(0, 15)
        )

        # Replaced the giant page with a tabview
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=(0, 15)
        )

        encrypt_tab = self.tabs.add("Encrypt")
        decrypt_tab = self.tabs.add("Decrypt")

        # Encrypt Section - moved to encrypt_tab
        ctk.CTkLabel(
            encrypt_tab,
            text="Encrypt File",
            font=("Segoe UI", 20, "bold"),
            text_color=TEXT
        ).pack(pady=(20, 5))

        ctk.CTkButton(
            encrypt_tab,
            text="Select File",
            fg_color=ACCENT,
            command=self.select_encrypt_file
        ).pack(pady=5)

        self.encrypt_password = ctk.CTkEntry(
            encrypt_tab,
            placeholder_text="Password",
            show="*"
        )
        self.encrypt_password.pack(
            fill="x",
            padx=20,
            pady=5
        )

        self.confirm_password = ctk.CTkEntry(
            encrypt_tab,
            placeholder_text="Confirm Password",
            show="*"
        )
        self.confirm_password.pack(
            fill="x",
            padx=20,
            pady=5
        )

        ctk.CTkButton(
            encrypt_tab,
            text="🔒 Encrypt File",
            command=self.encrypt_file
        ).pack(pady=10)

        # Decrypt Section - moved to decrypt_tab
        ctk.CTkLabel(
            decrypt_tab,
            text="Decrypt File",
            font=("Segoe UI", 20, "bold"),
            text_color=TEXT
        ).pack(pady=(30, 5))

        ctk.CTkButton(
            decrypt_tab,
            text="Select .enc File",
            fg_color=ACCENT,
            command=self.select_decrypt_file
        ).pack(pady=5)

        self.decrypt_password = ctk.CTkEntry(
            decrypt_tab,
            placeholder_text="Password",
            show="*"
        )
        self.decrypt_password.pack(
            fill="x",
            padx=20,
            pady=5
        )

        ctk.CTkButton(
            decrypt_tab,
            text="🔓 Decrypt File",
            command=self.decrypt_file
        ).pack(pady=10)

        # Added Open Folder Button (remains outside tabs)
        self.open_folder_btn = ctk.CTkButton(
            self,
            text="📂 Open Output Folder",
            command=self.open_output_folder,
            state="disabled"
        )
        self.open_folder_btn.pack(
            pady=10
        )

    # =====================================================
    # FILE SELECTION
    # =====================================================

    def select_encrypt_file(self):
        self.selected_file = filedialog.askopenfilename()

        if self.selected_file:
            self.file_label.configure(
                text=os.path.basename(
                    self.selected_file
                )
            )
            # Added file size display
            size = os.path.getsize(
                self.selected_file
            )
            size_mb = round(
                size / (1024 * 1024),
                2
            )
            self.size_label.configure(
                text=f"Size: {size_mb} MB"
            )

            self.status_label.configure(
                text="File Selected",
                text_color=ACCENT
            )
        else:
            self.file_label.configure(text="No file selected")
            self.size_label.configure(text="Size: --") # Reset size label
            self.status_label.configure(text="Ready", text_color=ACCENT)


    def select_decrypt_file(self):
        self.selected_file = filedialog.askopenfilename(
            filetypes=[
                ("Encrypted Files", "*.enc")
            ]
        )

        if self.selected_file:
            self.file_label.configure(
                text=os.path.basename(
                    self.selected_file
                )
            )
            # Added file size display
            size = os.path.getsize(
                self.selected_file
            )
            size_mb = round(
                size / (1024 * 1024),
                2
            )
            self.size_label.configure(
                text=f"Size: {size_mb} MB"
            )

            self.status_label.configure(
                text="Encrypted File Selected",
                text_color=ACCENT
            )
        else:
            self.file_label.configure(text="No file selected")
            self.size_label.configure(text="Size: --") # Reset size label
            self.status_label.configure(text="Ready", text_color=ACCENT)


    # =====================================================
    # ENCRYPT LOGIC
    # =====================================================

    def encrypt_file(self):
        if not self.selected_file:
            self.status_label.configure(
                text="No file selected",
                text_color="red"
            )
            return

        password = self.encrypt_password.get()
        confirm = self.confirm_password.get()

        if not password or password != confirm:
            self.status_label.configure(
                text="Passwords do not match or are empty",
                text_color="red"
            )
            return

        try:
            # Replaced 'output' with 'self.last_output'
            self.last_output = (
                self.manager.container.crypto_service.encrypt_file(
                    self.selected_file,
                    password
                )
            )

            self.status_label.configure(
                text=f"Encrypted: {os.path.basename(self.last_output)}", # Used self.last_output
                text_color="#2ecc71"
            )
            self.encrypt_password.delete(0, ctk.END)
            self.confirm_password.delete(0, ctk.END)
            self.selected_file = None
            self.file_label.configure(text="No file selected")
            self.size_label.configure(text="Size: --") # Reset size label
            self.open_folder_btn.configure(state="normal") # Enabled button

        except Exception as e:
            self.status_label.configure(
                text=f"Error: {e}",
                text_color="red"
            )


    # =====================================================
    # DECRYPT LOGIC
    # =====================================================

    def decrypt_file(self):
        if not self.selected_file:
            self.status_label.configure(
                text="No file selected",
                text_color="red"
            )
            return

        password = self.decrypt_password.get()

        if not password:
            self.status_label.configure(
                text="Password cannot be empty",
                text_color="red"
            )
            return

        try:
            # Replaced 'output' with 'self.last_output'
            self.last_output = (
                self.manager.container.crypto_service.decrypt_file(
                    self.selected_file,
                    password
                )
            )

            self.status_label.configure(
                text=f"Decrypted: {os.path.basename(self.last_output)}", # Used self.last_output
                text_color="#2ecc71"
            )
            self.decrypt_password.delete(0, ctk.END)
            self.selected_file = None
            self.file_label.configure(text="No file selected")
            self.size_label.configure(text="Size: --") # Reset size label
            self.open_folder_btn.configure(state="normal") # Enabled button


        except Exception:
            self.status_label.configure(
                text="Incorrect password or corrupted file",
                text_color="red"
            )

    # Added open_output_folder method
    def open_output_folder(self):

        if not self.last_output:
            return

        folder = os.path.dirname(
            self.last_output
        )

        subprocess.Popen(
            f'explorer "{folder}"'
        )