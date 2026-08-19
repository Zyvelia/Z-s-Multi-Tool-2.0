import customtkinter as ctk
from tkinter import filedialog
import hashlib

try:
    import pyperclip
except ImportError:
    pyperclip = None

from core import theme


def _btn(parent, text, cmd, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class HashToolsPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager
        self.selected_file = None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(
            header, text="🔐  Hash Tools",
            font=("Segoe UI", 22, "bold"), text_color=theme.TEXT
        ).pack(side="left", padx=10, pady=10)

        # Tabs
        self.tabs = ctk.CTkTabview(self, fg_color=theme.PANEL, corner_radius=10)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.tabs.add("Generate")
        self.tabs.add("Verify")

        self._build_generate_tab()
        self._build_verify_tab()

    # ── Generate Tab ──────────────────────────────────────────

    def _build_generate_tab(self):
        tab = self.tabs.tab("Generate")

        # Text input section
        ctk.CTkLabel(tab, text="theme.TEXT INPUT",
                     font=("Segoe UI", 10, "bold"), text_color=theme.MUTED
                     ).pack(anchor="w", padx=14, pady=(14, 4))

        self.text_input = ctk.CTkTextbox(
            tab, height=100, fg_color=theme.PANEL_2, corner_radius=8,
            text_color=theme.TEXT, border_width=0)
        self.text_input.pack(fill="x", padx=14)

        text_btns = ctk.CTkFrame(tab, fg_color="transparent")
        text_btns.pack(fill="x", padx=14, pady=(8, 0))

        _btn(text_btns, "Generate from Text", self.generate_text_hashes,
             **theme.primary_button_kwargs()).pack(side="left", padx=(0, 8))
        _btn(text_btns, "🗑  Clear All", self.clear_hashes,
             **theme.danger_button_kwargs()).pack(side="left")

        # Hash output boxes
        ctk.CTkLabel(tab, text="HASH OUTPUT",
                     font=("Segoe UI", 10, "bold"), text_color=theme.MUTED
                     ).pack(anchor="w", padx=14, pady=(16, 4))

        self.md5_var    = ctk.StringVar()
        self.sha1_var   = ctk.StringVar()
        self.sha256_var = ctk.StringVar()
        self.sha512_var = ctk.StringVar()

        for label, var in [
            ("MD5",    self.md5_var),
            ("SHA-1",  self.sha1_var),
            ("SHA-256", self.sha256_var),
            ("SHA-512", self.sha512_var),
        ]:
            self._make_hash_row(tab, label, var)

        # File hashing section
        ctk.CTkLabel(tab, text="FILE INPUT",
                     font=("Segoe UI", 10, "bold"), text_color=theme.MUTED
                     ).pack(anchor="w", padx=14, pady=(16, 4))

        file_row = ctk.CTkFrame(tab, fg_color=theme.PANEL_2, corner_radius=8)
        file_row.pack(fill="x", padx=14, pady=(0, 4))

        self.file_label = ctk.CTkLabel(
            file_row, text="No file selected", text_color=theme.MUTED, anchor="w")
        self.file_label.pack(side="left", fill="x", expand=True, padx=12, pady=10)

        _btn(file_row, "Browse", self.select_file,
             width=80, **theme.secondary_button_kwargs()).pack(side="right", padx=8, pady=8)

        _btn(tab, "Generate from File", self.generate_file_hashes,
             **theme.primary_button_kwargs()).pack(anchor="w", padx=14, pady=(6, 14))

    # ── Verify Tab ────────────────────────────────────────────

    def _build_verify_tab(self):
        tab = self.tabs.tab("Verify")

        ctk.CTkLabel(tab, text="FILE",
                     font=("Segoe UI", 10, "bold"), text_color=theme.MUTED
                     ).pack(anchor="w", padx=14, pady=(14, 4))

        file_row = ctk.CTkFrame(tab, fg_color=theme.PANEL_2, corner_radius=8)
        file_row.pack(fill="x", padx=14)

        self.verify_file_label = ctk.CTkLabel(
            file_row, text="No file selected", text_color=theme.MUTED, anchor="w")
        self.verify_file_label.pack(side="left", fill="x", expand=True, padx=12, pady=10)

        _btn(file_row, "Browse", self.select_verify_file,
             width=80, **theme.secondary_button_kwargs()).pack(side="right", padx=8, pady=8)

        ctk.CTkLabel(tab, text="ALGORITHM",
                     font=("Segoe UI", 10, "bold"), text_color=theme.MUTED
                     ).pack(anchor="w", padx=14, pady=(14, 4))

        self.algorithm = ctk.CTkOptionMenu(
            tab, values=["MD5", "SHA1", "SHA256", "SHA512"],
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color="#2f7fd6", text_color=theme.TEXT,
            corner_radius=8)
        self.algorithm.pack(fill="x", padx=14)

        ctk.CTkLabel(tab, text="EXPECTED HASH",
                     font=("Segoe UI", 10, "bold"), text_color=theme.MUTED
                     ).pack(anchor="w", padx=14, pady=(14, 4))

        self.expected_hash = ctk.CTkEntry(
            tab, placeholder_text="Paste expected hash here…",
            fg_color=theme.PANEL_2, border_width=0, corner_radius=8,
            text_color=theme.TEXT, height=36)
        self.expected_hash.pack(fill="x", padx=14)

        _btn(tab, "Verify Hash", self.verify_hash,
             **theme.primary_button_kwargs()).pack(anchor="w", padx=14, pady=(12, 8))

        self.verify_result = ctk.CTkLabel(tab, text="", font=("Segoe UI", 13, "bold"))
        self.verify_result.pack(anchor="w", padx=14)

    # ── Hash Row ──────────────────────────────────────────────

    def _make_hash_row(self, parent, label, variable):
        row = ctk.CTkFrame(parent, fg_color=theme.PANEL_2, corner_radius=8)
        row.pack(fill="x", padx=14, pady=3)

        ctk.CTkLabel(row, text=label, width=68,
                     font=("Segoe UI", 11, "bold"), text_color=theme.MUTED
                     ).pack(side="left", padx=10, pady=8)

        ctk.CTkEntry(row, textvariable=variable, fg_color=theme.BG,
                     border_width=0, text_color=theme.TEXT, corner_radius=6
                     ).pack(side="left", fill="x", expand=True, padx=(0, 6), pady=6)

        _btn(row, "Copy", lambda v=variable: self._copy(v.get()),
             width=64, height=28, corner_radius=6,
             fg_color=theme.PANEL, hover_color=theme.ACCENT, text_color=theme.MUTED
             ).pack(side="right", padx=6, pady=6)

    # ── Hashing Logic ─────────────────────────────────────────

    def generate_text_hashes(self):
        data = self.text_input.get("1.0", "end").strip().encode()
        self._set_hashes(data)

    def select_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.selected_file = path
            self.file_label.configure(text=path, text_color=theme.TEXT)

    def generate_file_hashes(self):
        if not self.selected_file:
            return
        with open(self.selected_file, "rb") as f:
            data = f.read()
        self._set_hashes(data)

    def _set_hashes(self, data):
        self.md5_var.set(hashlib.md5(data).hexdigest())
        self.sha1_var.set(hashlib.sha1(data).hexdigest())
        self.sha256_var.set(hashlib.sha256(data).hexdigest())
        self.sha512_var.set(hashlib.sha512(data).hexdigest())

    # ── Verify ────────────────────────────────────────────────

    def select_verify_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.selected_file = path
            self.verify_file_label.configure(text=path, text_color=theme.TEXT)

    def verify_hash(self):
        if not self.selected_file:
            return

        algo_map = {
            "MD5":    hashlib.md5,
            "SHA1":   hashlib.sha1,
            "SHA256": hashlib.sha256,
            "SHA512": hashlib.sha512,
        }
        with open(self.selected_file, "rb") as f:
            data = f.read()

        actual   = algo_map[self.algorithm.get()](data).hexdigest()
        expected = self.expected_hash.get().strip().lower()

        if actual.lower() == expected:
            self.verify_result.configure(text="✅  Match", text_color="#2ecc71")
        else:
            self.verify_result.configure(text="❌  Mismatch", text_color="#e74c3c")

    # ── Copy / Clear ──────────────────────────────────────────

    def _copy(self, value):
        if pyperclip and value:
            pyperclip.copy(value)

    def clear_hashes(self):
        self.text_input.delete("1.0", "end")
        for var in (self.md5_var, self.sha1_var, self.sha256_var, self.sha512_var):
            var.set("")
        self.selected_file = None
        self.file_label.configure(text="No file selected", text_color=theme.MUTED)
        self.verify_file_label.configure(text="No file selected", text_color=theme.MUTED)
        self.expected_hash.delete(0, "end")
        self.verify_result.configure(text="")