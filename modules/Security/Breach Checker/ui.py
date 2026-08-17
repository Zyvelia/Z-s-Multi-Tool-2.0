import threading
import webbrowser

import customtkinter as ctk

try:
    import pyperclip
except ImportError:
    pyperclip = None

from core import theme

from .hibp_api import check_password, check_account, HIBPError
from .security import InMemorySecret

BG     = theme.BG
PANEL  = theme.PANEL
CARD   = theme.PANEL_2
ACCENT = theme.ACCENT
TEXT   = theme.TEXT
MUTED  = theme.MUTED
DANGER = theme.DANGER
SUCCESS = theme.SUCCESS

_BTN = dict(height=34, corner_radius=8, fg_color=CARD,
            hover_color=ACCENT, text_color=TEXT)
_BTN_ACC = dict(height=34, corner_radius=8, fg_color=ACCENT,
                 hover_color="#2f7fd6", text_color="white")


def _btn(parent, text, cmd, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class BreachCheckerPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager
        self.api_key = InMemorySecret()
        self._build_ui()

    # ── UI shell ──────────────────────────────────────────────

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 6))

        ctk.CTkLabel(
            header, text="🕵️  Breach Checker",
            font=("Segoe UI", 22, "bold"), text_color=TEXT
        ).pack(side="left", padx=10, pady=10)

        ctk.CTkLabel(
            header, text="Powered by Have I Been Pwned",
            font=("Segoe UI", 11), text_color=MUTED
        ).pack(side="left", padx=(0, 10))

        self.tabs = ctk.CTkTabview(self, fg_color=PANEL, corner_radius=10)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.tabs.add("Password Check")
        self.tabs.add("Email Lookup")

        self._build_password_tab()
        self._build_email_tab()

    # ── Password Check tab (free, no API key, k-anonymity) ────

    def _build_password_tab(self):
        tab = self.tabs.tab("Password Check")

        ctk.CTkLabel(
            tab,
            text="Checks a password against known breach dumps using the "
                 "Pwned Passwords k-anonymity API - only a 5-character hash "
                 "prefix ever leaves this device, never the password itself. "
                 "No API key needed.",
            font=("Segoe UI", 11), text_color=MUTED,
            wraplength=560, justify="left"
        ).pack(anchor="w", padx=14, pady=(14, 10))

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=14)

        self.pw_entry = ctk.CTkEntry(
            row, placeholder_text="Enter a password to check",
            show="\u2022", fg_color=CARD, corner_radius=8,
            text_color=TEXT, border_width=0, height=36
        )
        self.pw_entry.pack(side="left", fill="x", expand=True)
        self.pw_entry.bind("<Return>", lambda e: self.check_password_clicked())

        self.pw_show_var = ctk.BooleanVar(value=False)

        def toggle_show():
            self.pw_entry.configure(show="" if self.pw_show_var.get() else "\u2022")

        ctk.CTkCheckBox(
            row, text="Show", variable=self.pw_show_var, command=toggle_show,
            width=20, checkbox_width=18, checkbox_height=18,
            text_color=MUTED, font=("Segoe UI", 11)
        ).pack(side="left", padx=(10, 0))

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(10, 0))

        self.pw_check_btn = _btn(btn_row, "Check Password", self.check_password_clicked, **_BTN_ACC)
        self.pw_check_btn.pack(side="left")

        self.pw_status = ctk.CTkLabel(
            btn_row, text="", font=("Segoe UI", 11), text_color=MUTED
        )
        self.pw_status.pack(side="left", padx=(12, 0))

        result_card = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=10)
        result_card.pack(fill="x", padx=14, pady=(16, 14))

        self.pw_result_title = ctk.CTkLabel(
            result_card, text="No password checked yet",
            font=("Segoe UI", 16, "bold"), text_color=MUTED
        )
        self.pw_result_title.pack(anchor="w", padx=16, pady=(14, 2))

        self.pw_result_detail = ctk.CTkLabel(
            result_card, text="", font=("Segoe UI", 12), text_color=MUTED,
            wraplength=560, justify="left"
        )
        self.pw_result_detail.pack(anchor="w", padx=16, pady=(0, 14))

    def check_password_clicked(self):
        password = self.pw_entry.get()
        if not password:
            self.pw_status.configure(text="Enter a password first.", text_color=DANGER)
            return

        self.pw_check_btn.configure(state="disabled", text="Checking...")
        self.pw_status.configure(text="Contacting Pwned Passwords API...", text_color=MUTED)

        def worker():
            try:
                count = check_password(password)
                error = None
            except HIBPError as e:
                count = None
                error = str(e)

            self.after(0, lambda: self._on_password_result(count, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_password_result(self, count, error):
        self.pw_check_btn.configure(state="normal", text="Check Password")

        if error:
            self.pw_status.configure(text="Failed", text_color=DANGER)
            self.pw_result_title.configure(text="⚠️ Lookup failed", text_color=DANGER)
            self.pw_result_detail.configure(text=error)
            return

        self.pw_status.configure(text="Done", text_color=SUCCESS)

        if count == 0:
            self.pw_result_title.configure(
                text="✅ Not found in any known breach", text_color=SUCCESS
            )
            self.pw_result_detail.configure(
                text="This password wasn't found in the Pwned Passwords dataset. "
                     "That doesn't guarantee it's strong - just that it hasn't "
                     "shown up in a breach dump HIBP has indexed yet."
            )
        else:
            severity = DANGER if count >= 100 else "#e0a030"
            self.pw_result_title.configure(
                text=f"⚠️ Seen in {count:,} breach{'es' if count != 1 else ''}",
                text_color=severity
            )
            self.pw_result_detail.configure(
                text="This password has appeared in known data breaches and "
                     "should be considered compromised. Stop using it anywhere, "
                     "and turn on a unique password (a password manager helps) "
                     "plus two-factor authentication where it's available."
            )

    # ── Email Lookup tab (needs the user's own HIBP API key) ──

    def _build_email_tab(self):
        tab = self.tabs.tab("Email Lookup")

        ctk.CTkLabel(
            tab,
            text="Checks an email address against HIBP's breach database. "
                 "This endpoint requires your own HIBP API key (a paid, "
                 "personal subscription) - it's kept in memory for this "
                 "session only and is never saved to disk.",
            font=("Segoe UI", 11), text_color=MUTED,
            wraplength=560, justify="left"
        ).pack(anchor="w", padx=14, pady=(14, 10))

        key_row = ctk.CTkFrame(tab, fg_color="transparent")
        key_row.pack(fill="x", padx=14)

        self.key_entry = ctk.CTkEntry(
            key_row, placeholder_text="HIBP API key",
            show="\u2022", fg_color=CARD, corner_radius=8,
            text_color=TEXT, border_width=0, height=36
        )
        self.key_entry.pack(side="left", fill="x", expand=True)

        _btn(key_row, "Get a key", self._open_hibp_key_page,
             **_BTN, width=90).pack(side="left", padx=(8, 0))

        email_row = ctk.CTkFrame(tab, fg_color="transparent")
        email_row.pack(fill="x", padx=14, pady=(10, 0))

        self.email_entry = ctk.CTkEntry(
            email_row, placeholder_text="you@example.com",
            fg_color=CARD, corner_radius=8,
            text_color=TEXT, border_width=0, height=36
        )
        self.email_entry.pack(side="left", fill="x", expand=True)
        self.email_entry.bind("<Return>", lambda e: self.check_email_clicked())

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(10, 0))

        self.email_check_btn = _btn(btn_row, "Check Email", self.check_email_clicked, **_BTN_ACC)
        self.email_check_btn.pack(side="left")

        self.email_status = ctk.CTkLabel(
            btn_row, text="", font=("Segoe UI", 11), text_color=MUTED
        )
        self.email_status.pack(side="left", padx=(12, 0))

        self.email_results_scroll = ctk.CTkScrollableFrame(
            tab, fg_color="transparent"
        )
        self.email_results_scroll.pack(fill="both", expand=True, padx=14, pady=(16, 14))

        self._render_email_placeholder("No email checked yet.")

    def _open_hibp_key_page(self):
        webbrowser.open("https://haveibeenpwned.com/API/Key")

    def _clear_email_results(self):
        for child in self.email_results_scroll.winfo_children():
            child.destroy()

    def _render_email_placeholder(self, text, color=None):
        self._clear_email_results()
        ctk.CTkLabel(
            self.email_results_scroll, text=text,
            font=("Segoe UI", 12), text_color=color or MUTED
        ).pack(anchor="w", padx=4, pady=8)

    def check_email_clicked(self):
        email = self.email_entry.get().strip()
        key = self.key_entry.get().strip()

        if not email:
            self.email_status.configure(text="Enter an email first.", text_color=DANGER)
            return
        if not key:
            self.email_status.configure(text="An HIBP API key is required.", text_color=DANGER)
            return

        self.api_key.set(key)

        self.email_check_btn.configure(state="disabled", text="Checking...")
        self.email_status.configure(text="Contacting HIBP...", text_color=MUTED)
        self._render_email_placeholder("Checking...")

        def worker():
            try:
                breaches = check_account(email, self.api_key.get())
                error = None
            except HIBPError as e:
                breaches = None
                error = str(e)

            self.after(0, lambda: self._on_email_result(breaches, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_email_result(self, breaches, error):
        self.email_check_btn.configure(state="normal", text="Check Email")

        if error:
            self.email_status.configure(text="Failed", text_color=DANGER)
            self._render_email_placeholder(f"⚠️ {error}", color=DANGER)
            return

        if not breaches:
            self.email_status.configure(text="Done", text_color=SUCCESS)
            self._render_email_placeholder("✅ No known breaches found for this address.", color=SUCCESS)
            return

        self.email_status.configure(
            text=f"Found {len(breaches)} breach{'es' if len(breaches) != 1 else ''}",
            text_color=DANGER
        )
        self._clear_email_results()
        for breach in breaches:
            self._render_breach_card(breach)

    def _render_breach_card(self, breach: dict):
        name = breach.get("Title") or breach.get("Name") or "Unknown breach"
        domain = breach.get("Domain") or ""
        date = breach.get("BreachDate") or "Unknown date"
        classes = breach.get("DataClasses") or []
        description = breach.get("Description") or ""
        verified = breach.get("IsVerified", True)

        card = ctk.CTkFrame(self.email_results_scroll, fg_color=CARD, corner_radius=10)
        card.pack(fill="x", pady=(0, 10))

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 2))

        title_text = name if not domain else f"{name}  ({domain})"
        ctk.CTkLabel(
            top, text=title_text, font=("Segoe UI", 14, "bold"), text_color=TEXT
        ).pack(side="left")

        if not verified:
            ctk.CTkLabel(
                top, text="UNVERIFIED", font=("Segoe UI", 9, "bold"),
                text_color="#e0a030"
            ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            card, text=f"Breach date: {date}",
            font=("Segoe UI", 11), text_color=MUTED
        ).pack(anchor="w", padx=14, pady=(0, 4))

        if classes:
            ctk.CTkLabel(
                card, text="Exposed data: " + ", ".join(classes),
                font=("Segoe UI", 11), text_color=DANGER,
                wraplength=560, justify="left"
            ).pack(anchor="w", padx=14, pady=(0, 4))

        if description:
            # HIBP descriptions are HTML; strip tags for a plain-text summary.
            import re
            plain = re.sub(r"<[^>]+>", "", description)
            ctk.CTkLabel(
                card, text=plain, font=("Segoe UI", 11), text_color=MUTED,
                wraplength=560, justify="left"
            ).pack(anchor="w", padx=14, pady=(0, 12))
        else:
            ctk.CTkFrame(card, fg_color="transparent", height=8).pack()
