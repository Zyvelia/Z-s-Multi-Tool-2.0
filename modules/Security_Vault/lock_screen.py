import customtkinter as ctk

from .ui import PasswordVaultPage
from core import theme
from core.services.auth_service import AuthService

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2
BORDER = theme.BORDER

ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER

TEXT = theme.TEXT
MUTED = theme.MUTED
FAINT = theme.FAINT

ERROR = theme.ERROR
SUCCESS = theme.SUCCESS
DANGER = theme.DANGER

MIN_PASSWORD_LENGTH = 8

# Strength meter: index 0-4, matching AuthService.password_strength()
STRENGTH_COLORS = [DANGER, "#e0803f", "#e0c53f", "#8bd15a", SUCCESS]


class PasswordVaultLockScreen(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent)

        self.manager = manager

        self.auth = manager.container.auth_service
        self.alert = manager.container.alert_service

        self.configure(fg_color=BG)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._password_visible = False
        self._confirm_visible = False

        self.build_ui()

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        # Outer card gets a subtle border + rounded corners so it reads
        # as a distinct "sheet" against the app background instead of a
        # flat rectangle, matching the rest of the app's card language.
        card = ctk.CTkFrame(
            self,
            fg_color=PANEL,
            border_width=1,
            border_color=BORDER,
            corner_radius=theme.RADIUS,
            width=440
        )

        card.place(
            relx=0.5,
            rely=0.5,
            anchor="center"
        )

        # Thin accent bar across the top edge of the card — a small
        # signature detail that ties the card back to the app's accent
        # color without relying on another icon asset. Flat corners here
        # read fine against the card's rounded ones at this thickness.
        ctk.CTkFrame(
            card,
            fg_color=ACCENT,
            corner_radius=0,
            height=3
        ).pack(fill="x", side="top")

        # Content sizes itself naturally (no locked width/height on this
        # frame) — labels below use a fixed wraplength and entries use a
        # fixed width, so the layout still reads as a consistent column
        # without risking content getting clipped off the bottom.
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=40, pady=(32, 32))

        # -- Brand mark ---------------------------------------------------
        # Two soft concentric rings behind the badge fake a glow without
        # needing real alpha blending — each ring a touch dimmer than the
        # one inside it, so the icon reads as lit from the center out.
        halo = ctk.CTkFrame(
            inner,
            fg_color=theme.ACCENT_MUTED,
            corner_radius=999,
            width=88,
            height=88
        )
        halo.pack(pady=(0, 18))
        halo.pack_propagate(False)

        badge = ctk.CTkFrame(
            halo,
            fg_color=theme.ACCENT_GLOW,
            corner_radius=999,
            width=64,
            height=64
        )
        badge.place(relx=0.5, rely=0.5, anchor="center")
        badge.pack_propagate(False)

        ctk.CTkLabel(
            badge,
            text="🔐",
            font=theme.font(26)
        ).place(relx=0.5, rely=0.5, anchor="center")

        # -- Eyebrow + title ------------------------------------------------
        ctk.CTkLabel(
            inner,
            text="E N D - T O - E N D   E N C R Y P T E D",
            font=theme.font(10, "bold"),
            text_color=ACCENT
        ).pack()

        ctk.CTkLabel(
            inner,
            text="Security Vault",
            font=theme.font(23, "bold"),
            text_color=TEXT
        ).pack(pady=(4, 0))

        first_run = not self.auth.is_initialized()

        ctk.CTkLabel(
            inner,
            text=(
                "Choose a master password to protect your vault."
                if first_run else
                "Enter your master password to continue."
            ),
            font=theme.font(12),
            text_color=MUTED,
            wraplength=320,
            justify="center"
        ).pack(pady=(6, 20))

        # Divider between the identity block above and the form below —
        # a quiet structural cue that these are two different jobs
        # (who this app is / what you need to do right now).
        divider = ctk.CTkFrame(inner, fg_color=BORDER, height=1, width=320)
        divider.pack(pady=(0, 20))

        if first_run:
            self._build_create_form(inner)
        else:
            self._build_login_form(inner)

        # Error state as a quiet inline chip rather than bare red text.
        self.error_label = ctk.CTkLabel(
            inner,
            text="",
            font=theme.font(12),
            text_color=ERROR,
            wraplength=320,
            justify="center"
        )
        self.error_label.pack(pady=(12, 0))

        # A small technical footnote — real, not decorative: it's the
        # actual scheme protecting this vault (matches AuthService), and
        # gives a security-focused product the credibility of specifics
        # instead of a generic "your data is safe" line.
        ctk.CTkLabel(
            inner,
            text=f"PBKDF2-HMAC-SHA256 · {self.auth.PBKDF2_ITERATIONS:,} rounds",
            font=theme.mono(10),
            text_color=FAINT
        ).pack(pady=(20, 0))

        self.password_entry.focus_set()

    def _entry_row(self, parent, placeholder, on_toggle):
        """A password entry with a show/hide button docked next to it."""

        # 320px wide, matching the label wraplength above it — the row's
        # own requested width (rather than a size locked on some parent
        # frame) is what keeps the form a consistent column.
        row = ctk.CTkFrame(parent, fg_color="transparent", width=320)
        row.pack(fill="x", pady=6)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=0)
        row.grid_propagate(False)

        entry = ctk.CTkEntry(
            row,
            placeholder_text=placeholder,
            show="•",
            height=40,
            corner_radius=theme.RADIUS_SM,
            fg_color=CARD,
            border_color=BORDER,
            font=theme.font(13)
        )
        entry.grid(row=0, column=0, sticky="ew")

        # A dedicated column for the toggle (instead of place()-ing it on
        # top of the entry) so the entry's own text/cursor never runs
        # underneath the button — it simply never occupies that space.
        # Plain text instead of an emoji glyph: emoji-eye characters
        # don't reliably resolve to a real icon on every font/platform
        # and can render as an empty box.
        toggle = ctk.CTkButton(
            row,
            text="Show",
            width=52,
            height=40,
            corner_radius=theme.RADIUS_SM,
            fg_color=CARD,
            hover_color=PANEL,
            text_color=MUTED,
            font=theme.font(11),
            command=on_toggle
        )
        toggle.grid(row=0, column=1, sticky="ns", padx=(6, 0))

        entry.bind("<Return>", lambda e: self._on_submit())

        return entry, toggle

    # -------------------------------------------------
    # FIRST RUN
    # -------------------------------------------------

    def _build_create_form(self, parent):

        self.password_entry, self.password_toggle = self._entry_row(
            parent, "Master password", self._toggle_password
        )
        self.password_entry.bind("<KeyRelease>", lambda e: self._update_strength())

        # Strength meter: a thin 4-segment bar + label, filled as the
        # user types. Keeps feedback lightweight instead of a blocking
        # "password not strong enough" dialog.
        meter_row = ctk.CTkFrame(parent, fg_color="transparent")
        meter_row.pack(fill="x", pady=(2, 2))
        meter_row.grid_columnconfigure(0, weight=1)

        self.strength_bar = ctk.CTkProgressBar(
            meter_row,
            height=4,
            corner_radius=2,
            progress_color=STRENGTH_COLORS[0],
            fg_color=BORDER
        )
        self.strength_bar.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.strength_bar.set(0)

        self.strength_label = ctk.CTkLabel(
            meter_row,
            text=" ",
            font=theme.font(11),
            text_color=FAINT,
            width=80,
            anchor="e"
        )
        self.strength_label.grid(row=0, column=1, sticky="e")

        self.confirm_entry, self.confirm_toggle = self._entry_row(
            parent, "Confirm password", self._toggle_confirm
        )

        ctk.CTkLabel(
            parent,
            text=f"Minimum {MIN_PASSWORD_LENGTH} characters. This password can't be recovered if you forget it.",
            font=theme.font(11),
            text_color=FAINT,
            wraplength=320,
            justify="left"
        ).pack(fill="x", pady=(4, 16))

        ctk.CTkButton(
            parent,
            text="Create Vault",
            height=42,
            corner_radius=theme.RADIUS_SM,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0b0d10",
            font=theme.font(13, "bold"),
            command=self.create_master_password
        ).pack(fill="x", pady=(4, 0))

    def _update_strength(self):
        score, label = AuthService.password_strength(self.password_entry.get())
        self.strength_bar.configure(progress_color=STRENGTH_COLORS[max(score - 1, 0)])
        self.strength_bar.set(score / 4)
        self.strength_label.configure(
            text=label if self.password_entry.get() else " "
        )

    # -------------------------------------------------
    # LOGIN
    # -------------------------------------------------

    def _build_login_form(self, parent):

        self.password_entry, self.password_toggle = self._entry_row(
            parent, "Master password", self._toggle_password
        )

        ctk.CTkButton(
            parent,
            text="Unlock Vault",
            height=42,
            corner_radius=theme.RADIUS_SM,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0b0d10",
            font=theme.font(13, "bold"),
            command=self.unlock_vault
        ).pack(fill="x", pady=(18, 0))

    # -------------------------------------------------
    # SHOW / HIDE PASSWORD
    # -------------------------------------------------

    def _toggle_password(self):
        self._password_visible = not self._password_visible
        self.password_entry.configure(show="" if self._password_visible else "•")
        self.password_toggle.configure(text="Hide" if self._password_visible else "Show")

    def _toggle_confirm(self):
        self._confirm_visible = not self._confirm_visible
        self.confirm_entry.configure(show="" if self._confirm_visible else "•")
        self.confirm_toggle.configure(text="Hide" if self._confirm_visible else "Show")

    def _on_submit(self):
        if self.auth.is_initialized():
            self.unlock_vault()
        else:
            self.create_master_password()

    # =====================================================
    # CREATE MASTER PASSWORD
    # =====================================================

    def create_master_password(self):

        password = self.password_entry.get()
        confirm = self.confirm_entry.get()

        if len(password) < MIN_PASSWORD_LENGTH:
            self.error_label.configure(
                text=f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
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
            self.alert.local_unlock_attempt(True)
            self.open_vault()
        else:
            self.alert.local_unlock_attempt(False)
            self.error_label.configure(
                text="Incorrect password."
            )
            self.password_entry.delete(0, "end")
            self.password_entry.focus_set()

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