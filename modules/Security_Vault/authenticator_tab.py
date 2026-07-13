# modules/password_vault/authenticator_tab.py
#
# The "Authenticator" tab inside the Vault page. Same idea as the
# Google/Microsoft Authenticator app or Discord's "authenticator app"
# 2FA option — TOTP codes generated from a secret you paste in once
# when you set up 2FA on an account. See core/services/totp_service.py
# for the actual RFC 6238 algorithm.

import customtkinter as ctk
from tkinter import messagebox

from core import theme

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2
ACCENT = theme.ACCENT
TEXT = theme.TEXT
MUTED = theme.MUTED
ERROR = theme.ERROR

try:
    import pyperclip
except ImportError:
    pyperclip = None

from core.services import totp_service as totp


class AuthenticatorTab(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")

        self.manager = manager
        self.totp = manager.container.totp_service

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.cards = {}   # entry id -> {"code_label":..., "ring":..., "entry": {...}}
        self._tick_job = None

        self._build_add_panel()
        self._build_list()

        self.render()
        self._start_ticking()

    def destroy(self):
        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
        super().destroy()

    # =====================================================
    # ADD PANEL
    # =====================================================

    def _build_add_panel(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL)
        panel.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel, text="Add authenticator code", font=("Segoe UI", 16, "bold"), text_color=TEXT
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=15, pady=(15, 8))

        self.name_entry = ctk.CTkEntry(panel, placeholder_text="Account name (e.g. Discord)")
        self.name_entry.grid(row=1, column=0, sticky="ew", padx=(15, 5), pady=(0, 15))

        self.secret_entry = ctk.CTkEntry(
            panel, placeholder_text="Secret key from the site's 2FA setup — or paste a full otpauth:// URI"
        )
        self.secret_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=(0, 15))

        ctk.CTkButton(
            panel, text="➕ Add", width=90, fg_color=ACCENT, command=self.add_entry
        ).grid(row=1, column=3, padx=(5, 15), pady=(0, 15))

        ctk.CTkLabel(
            panel,
            text="This is the same manual-entry key a site shows as a fallback to scanning its QR code — "
                 "on Discord it's under Settings → My Account → Enable Authenticator App.",
            font=("Segoe UI", 11), text_color=MUTED, anchor="w", justify="left", wraplength=560,
        ).grid(row=2, column=0, columnspan=4, sticky="ew", padx=15, pady=(0, 15))

    def add_entry(self):
        name = self.name_entry.get().strip()
        raw = self.secret_entry.get().strip()

        if not raw:
            messagebox.showwarning("Missing secret", "Paste the secret key (or otpauth:// URI) first.")
            return

        parsed = totp.parse_otpauth_uri(raw)
        if parsed:
            secret = parsed["secret"]
            name = name or parsed["name"]
            issuer = parsed["issuer"]
        else:
            secret = raw
            issuer = ""

        if not totp.is_valid_secret(secret):
            messagebox.showerror(
                "Invalid secret",
                "That doesn't look like a valid authenticator key. It should be a short block of "
                "letters/numbers (base32) — double check you copied the manual-entry code, not something else.",
            )
            return

        try:
            self.totp.add_entry(name or "Account", secret, issuer)
        except ValueError as e:
            messagebox.showerror("Invalid secret", str(e))
            return

        self.name_entry.delete(0, "end")
        self.secret_entry.delete(0, "end")
        self.render()

    # =====================================================
    # LIST
    # =====================================================

    def _build_list(self):
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)

    def render(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.cards.clear()

        entries = self.totp.get_entries()

        if not entries:
            ctk.CTkLabel(
                self.list_frame, text="No authenticator codes yet — add one above.",
                font=("Segoe UI", 13), text_color=MUTED
            ).grid(row=0, column=0, pady=40)
            return

        for i, entry in enumerate(entries):
            self._build_card(entry, i)

        self._refresh_codes()

    def _build_card(self, entry, row):
        card = ctk.CTkFrame(self.list_frame, fg_color=CARD, corner_radius=10)
        card.grid(row=row, column=0, sticky="ew", pady=5, padx=2)
        card.grid_columnconfigure(1, weight=1)

        title = entry["name"] + (f"  ·  {entry['issuer']}" if entry.get("issuer") else "")
        ctk.CTkLabel(
            card, text=title, font=("Segoe UI", 14, "bold"), text_color=TEXT, anchor="w"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=15, pady=(12, 0))

        code_label = ctk.CTkLabel(
            card, text="------", font=("Consolas", 26, "bold"), text_color=ACCENT, anchor="w"
        )
        code_label.grid(row=1, column=0, sticky="w", padx=15, pady=(0, 12))

        progress = ctk.CTkProgressBar(card, width=140, height=8, progress_color=ACCENT)
        progress.set(1)
        progress.grid(row=1, column=1, sticky="e", padx=(0, 10))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=0, column=2, rowspan=2, padx=15, pady=10)

        ctk.CTkButton(
            btns, text="📋", width=34, height=30, fg_color=PANEL, hover_color=ACCENT,
            command=lambda e=entry: self.copy_code(e)
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btns, text="✕", width=34, height=30, fg_color=PANEL, hover_color=ERROR,
            command=lambda e=entry: self.remove_entry(e)
        ).pack(side="left")

        self.cards[entry["id"]] = {
            "code_label": code_label,
            "progress": progress,
            "entry": entry,
        }

    def copy_code(self, entry):
        code = totp.generate_code(entry["secret"])
        if pyperclip:
            pyperclip.copy(code)
        else:
            print(f"[Authenticator] pyperclip unavailable — code was: {code}")

    def remove_entry(self, entry):
        if messagebox.askyesno("Remove code", f"Remove the authenticator code for \"{entry['name']}\"?"):
            self.totp.delete_entry(entry["id"])
            self.render()

    # =====================================================
    # LIVE REFRESH
    # =====================================================

    def _refresh_codes(self):
        for card in self.cards.values():
            entry = card["entry"]
            code = totp.generate_code(entry["secret"])
            remaining = totp.seconds_remaining()

            display = f"{code[:3]} {code[3:]}"
            card["code_label"].configure(text=display)
            card["progress"].set(remaining / totp.DEFAULT_PERIOD)

    def _start_ticking(self):
        self._refresh_codes()
        self._tick_job = self.after(1000, self._start_ticking)
