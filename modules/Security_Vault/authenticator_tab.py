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
DANGER = theme.DANGER
DANGER_BG = theme.DANGER_BG
DANGER_HOVER = theme.DANGER_HOVER
SUCCESS = theme.SUCCESS
BORDER = theme.BORDER

# How long the "Removed <name> · Undo" toast stays on screen before the
# undo option disappears (the entry itself is still recoverable from
# Recently Deleted after that — this is just the fast path).
UNDO_TOAST_MS = 7000

# How long a single code stays revealed after you click it while
# Streaming Mode is on, before it re-masks itself automatically.
REVEAL_MS = 6000

MASK_TEXT = "•••  •••"

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
        self._undo_job = None
        self._toast = None
        self._trash_expanded = False

        self._reveal_jobs = {}    # entry id -> after() job for auto re-mask
        self._revealed_ids = set()

        self._build_add_panel()
        self._build_list()
        self._build_trash_panel()

        self.render()
        self._start_ticking()

    def destroy(self):
        if self._tick_job:
            try:
                self.after_cancel(self._tick_job)
            except Exception:
                pass
        if self._undo_job:
            try:
                self.after_cancel(self._undo_job)
            except Exception:
                pass
        for job in self._reveal_jobs.values():
            try:
                self.after_cancel(job)
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
                 "on Discord it's under Settings → My Account → Enable Authenticator App.\n"
                 "Codes are hidden by default — click one to reveal it for a few seconds. Copying "
                 "still works without revealing.",
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
            card, text="------", font=("Consolas", 26, "bold"), text_color=ACCENT, anchor="w", cursor="hand2",
        )
        code_label.grid(row=1, column=0, sticky="w", padx=15, pady=(0, 12))
        code_label.bind("<Button-1>", lambda e, eid=entry["id"]: self._reveal_code(eid))

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
        if not self._confirm_remove(entry):
            return

        self.totp.delete_entry(entry["id"])
        self.render()
        self._render_trash_toggle()
        self._show_undo_toast(entry)

    def _confirm_remove(self, entry):
        """Modal confirm with 'Cancel' as the safe default (focused, and
        what Enter/Space triggers) so an accidental keypress or a fast
        double-click doesn't remove anything. 'Remove' still requires a
        deliberate click on the danger-colored button."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Remove code?")
        dialog.configure(fg_color=PANEL)
        dialog.resizable(False, False)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()

        result = {"confirmed": False}

        title = entry["name"] + (f" ({entry['issuer']})" if entry.get("issuer") else "")

        ctk.CTkLabel(
            dialog, text=f"Remove \"{title}\"?", font=("Segoe UI", 15, "bold"),
            text_color=TEXT,
        ).pack(padx=20, pady=(20, 6), anchor="w")

        ctk.CTkLabel(
            dialog,
            text="It'll move to Recently Deleted for 30 days, so you can bring it back if this "
                 "was a mistake. After that it's gone for good — this app can't regenerate a 2FA "
                 "secret on its own, so make sure the account has another way in first.",
            font=("Segoe UI", 12), text_color=MUTED, justify="left", wraplength=340,
        ).pack(padx=20, pady=(0, 18), anchor="w")

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(padx=20, pady=(0, 20), fill="x")

        def on_cancel():
            result["confirmed"] = False
            dialog.destroy()

        def on_remove():
            result["confirmed"] = True
            dialog.destroy()

        cancel_btn = ctk.CTkButton(
            btns, text="Cancel", fg_color=PANEL, hover_color=theme.PANEL_HOVER,
            text_color=TEXT, command=on_cancel,
        )
        cancel_btn.pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btns, text="Remove", fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            text_color=DANGER, command=on_remove,
        ).pack(side="right")

        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        dialog.update_idletasks()
        parent_x = self.winfo_toplevel().winfo_x()
        parent_y = self.winfo_toplevel().winfo_y()
        parent_w = self.winfo_toplevel().winfo_width()
        parent_h = self.winfo_toplevel().winfo_height()
        dw, dh = dialog.winfo_width(), dialog.winfo_height()
        dialog.geometry(f"+{parent_x + (parent_w - dw) // 2}+{parent_y + (parent_h - dh) // 2}")

        cancel_btn.focus_set()  # Enter/Space defaults to the safe choice
        dialog.wait_window()
        return result["confirmed"]

    # =====================================================
    # UNDO TOAST
    # =====================================================

    def _show_undo_toast(self, entry):
        if self._undo_job:
            self.after_cancel(self._undo_job)
        if self._toast:
            self._toast.destroy()

        toast = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10, border_width=1, border_color=BORDER)
        toast.place(relx=0.5, rely=1.0, anchor="s", y=-16)

        ctk.CTkLabel(
            toast, text=f"Removed \"{entry['name']}\"", font=("Segoe UI", 12), text_color=TEXT,
        ).pack(side="left", padx=(16, 10), pady=12)

        def on_undo():
            self.totp.restore_entry(entry["id"])
            self.render()
            self._render_trash_toggle()
            self._dismiss_toast()

        ctk.CTkButton(
            toast, text="Undo", width=60, height=26, fg_color=ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#0b0d10", font=("Segoe UI", 12, "bold"), command=on_undo,
        ).pack(side="left", padx=(0, 16), pady=12)

        self._toast = toast
        self._undo_job = self.after(UNDO_TOAST_MS, self._dismiss_toast)

    def _dismiss_toast(self):
        if self._toast:
            self._toast.destroy()
            self._toast = None
        self._undo_job = None

    # =====================================================
    # RECENTLY DELETED
    # =====================================================

    def _build_trash_panel(self):
        self.trash_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.trash_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.trash_panel.grid_columnconfigure(0, weight=1)

        self.trash_toggle_btn = ctk.CTkButton(
            self.trash_panel, text="", anchor="w", fg_color="transparent", hover_color=PANEL,
            text_color=MUTED, font=("Segoe UI", 12), command=self._toggle_trash,
        )
        self.trash_toggle_btn.grid(row=0, column=0, sticky="ew")

        self.trash_list = ctk.CTkFrame(self.trash_panel, fg_color="transparent")
        # Not gridded until expanded.

        self._render_trash_toggle()

    def _render_trash_toggle(self):
        count = len(self.totp.get_trash())
        if count == 0:
            self.trash_toggle_btn.configure(text="")
            self.trash_panel.grid_remove()
            return

        self.trash_panel.grid()
        arrow = "▾" if self._trash_expanded else "▸"
        label = "code" if count == 1 else "codes"
        self.trash_toggle_btn.configure(text=f"{arrow} Recently Deleted ({count} {label})")

        if self._trash_expanded:
            self._render_trash_list()

    def _toggle_trash(self):
        self._trash_expanded = not self._trash_expanded
        if self._trash_expanded:
            self.trash_list.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self._render_trash_list()
        else:
            self.trash_list.grid_remove()
        self._render_trash_toggle()

    def _render_trash_list(self):
        for w in self.trash_list.winfo_children():
            w.destroy()

        for i, entry in enumerate(self.totp.get_trash()):
            row = ctk.CTkFrame(self.trash_list, fg_color=PANEL, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)

            title = entry["name"] + (f"  ·  {entry['issuer']}" if entry.get("issuer") else "")
            ctk.CTkLabel(
                row, text=title, font=("Segoe UI", 12), text_color=MUTED, anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=12, pady=8)

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.grid(row=0, column=1, padx=8, pady=6)

            ctk.CTkButton(
                btns, text="Restore", width=70, height=26, fg_color=PANEL, hover_color=SUCCESS,
                text_color=TEXT, font=("Segoe UI", 11), command=lambda e=entry: self._restore_from_trash(e),
            ).pack(side="left", padx=(0, 6))

            ctk.CTkButton(
                btns, text="Delete forever", width=110, height=26, fg_color=PANEL, hover_color=DANGER_HOVER,
                text_color=DANGER, font=("Segoe UI", 11), command=lambda e=entry: self._purge_from_trash(e),
            ).pack(side="left")

    def _restore_from_trash(self, entry):
        self.totp.restore_entry(entry["id"])
        self.render()
        self._render_trash_toggle()
        if self._trash_expanded:
            self._render_trash_list()

    def _purge_from_trash(self, entry):
        if not messagebox.askyesno(
            "Delete forever",
            f"Permanently delete the code for \"{entry['name']}\"? This can't be undone — "
            "make sure you have another way to sign in first.",
            icon="warning",
        ):
            return
        self.totp.purge_entry(entry["id"])
        self._render_trash_toggle()
        if self._trash_expanded:
            self._render_trash_list()

    # =====================================================
    # HIDDEN CODES (click to reveal)
    # =====================================================

    def _reveal_code(self, entry_id):
        if entry_id in self._revealed_ids:
            # Clicking an already-revealed code re-masks it immediately.
            self._mask_code(entry_id)
            return

        self._revealed_ids.add(entry_id)
        self._refresh_codes()

        if entry_id in self._reveal_jobs:
            try:
                self.after_cancel(self._reveal_jobs[entry_id])
            except Exception:
                pass
        self._reveal_jobs[entry_id] = self.after(REVEAL_MS, lambda: self._mask_code(entry_id))

    def _mask_code(self, entry_id):
        self._revealed_ids.discard(entry_id)
        self._reveal_jobs.pop(entry_id, None)
        self._refresh_codes()

    # =====================================================
    # LIVE REFRESH
    # =====================================================

    def _refresh_codes(self):
        for entry_id, card in self.cards.items():
            entry = card["entry"]
            code = totp.generate_code(entry["secret"])
            remaining = totp.seconds_remaining()

            hidden = entry_id not in self._revealed_ids
            display = MASK_TEXT if hidden else f"{code[:3]} {code[3:]}"
            card["code_label"].configure(text=display)
            card["progress"].set(remaining / totp.DEFAULT_PERIOD)

    def _start_ticking(self):
        self._refresh_codes()
        self._tick_job = self.after(1000, self._start_ticking)
