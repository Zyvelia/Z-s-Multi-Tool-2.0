import customtkinter as ctk
import random
import string
import datetime
from tkinter import filedialog

try:
    import pyperclip
except ImportError:
    pyperclip = None

from core import theme
from core.services.auth_service import AuthService
from .authenticator_tab import AuthenticatorTab
from .remote_access_tab import RemoteAccessTab

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2
CARD_HOVER = theme.PANEL_HOVER
BORDER = theme.BORDER

ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
ACCENT_GLOW = theme.ACCENT_GLOW

TEXT = theme.TEXT
MUTED = theme.MUTED
FAINT = theme.FAINT

ERROR = theme.ERROR
SUCCESS = theme.SUCCESS
DANGER = theme.DANGER

STRENGTH_COLORS = [DANGER, "#e0803f", "#e0c53f", "#8bd15a", SUCCESS]

CATEGORIES = ["General", "Email", "Gaming", "Work", "Banking", "Social"]


class PasswordVaultPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent)

        self.manager = manager
        self.vault = manager.container.vault_service

        self.visible_passwords = set()

        self.configure(fg_color=BG)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Generator option state lives on the page (not the modal) so your
        # settings persist between "Add Entry" opens.
        self.upper_var = ctk.BooleanVar(value=True)
        self.lower_var = ctk.BooleanVar(value=True)
        self.number_var = ctk.BooleanVar(value=True)
        self.symbol_var = ctk.BooleanVar(value=True)
        self.gen_length_var = ctk.IntVar(value=20)

        self.show_favorites_only = False

        self.build_ui()
        self.render()

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        # ---------------- HEADER ----------------

        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=theme.RADIUS)
        header.grid(row=0, column=0, sticky="ew", padx=15, pady=15)

        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="🔐 Security Vault",
            font=theme.font(24, "bold"),
            text_color=TEXT
        ).grid(row=0, column=0, sticky="w", padx=(15, 10), pady=12)

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=(0, 12), pady=12)

        self.favorites_toggle_button = ctk.CTkButton(
            actions, text="⭐ Favorites", command=self.toggle_favorites_filter,
            width=110, height=34, **theme.secondary_button_style()
        )
        self.favorites_toggle_button.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            actions, text="📤", width=38, height=34, command=self.export_vault,
            **theme.secondary_button_style()
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            actions, text="📥", width=38, height=34, command=self.import_vault,
            **theme.secondary_button_style()
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            actions, text="🔑 Master Password", command=self.open_change_password_dialog,
            width=150, height=34, **theme.secondary_button_style()
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            actions, text="➕ Add Entry", command=self.open_add_entry_dialog,
            width=130, height=34, **theme.primary_button_style()
        ).pack(side="left")

        # ---------------- TABS ----------------

        self.tabview = ctk.CTkTabview(
            self,
            fg_color=BG,
            segmented_button_fg_color=PANEL,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT,
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))

        passwords_tab = self.tabview.add("🔐 Passwords")
        authenticator_tab = self.tabview.add("🔑 Authenticator")
        settings_tab = self.tabview.add("⚙ Settings")

        passwords_tab.grid_rowconfigure(2, weight=1)
        passwords_tab.grid_columnconfigure(0, weight=1)

        authenticator_tab.grid_rowconfigure(0, weight=1)
        authenticator_tab.grid_columnconfigure(0, weight=1)

        settings_tab.grid_rowconfigure(0, weight=1)
        settings_tab.grid_columnconfigure(0, weight=1)

        AuthenticatorTab(authenticator_tab, self.manager).grid(row=0, column=0, sticky="nsew")
        RemoteAccessTab(settings_tab, self.manager).grid(row=0, column=0, sticky="nsew")

        # ---------------- STATS ----------------

        stats_frame = ctk.CTkFrame(passwords_tab, fg_color="transparent")
        stats_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for i in range(5):
            stats_frame.grid_columnconfigure(i, weight=1)

        self.stats_total_label = self._stat_pill(stats_frame, "Passwords", "0", 0)
        self.stats_favorites_label = self._stat_pill(stats_frame, "Favorites", "0", 1)
        self.stats_categories_label = self._stat_pill(stats_frame, "Categories", "0", 2)
        self.stats_sites_label = self._stat_pill(stats_frame, "Sites", "0", 3)
        self.security_label = self._stat_pill(stats_frame, "Security Score", "100/100", 4)

        # ---------------- SEARCH / FILTER ----------------

        search_frame = ctk.CTkFrame(passwords_tab, fg_color=PANEL, corner_radius=theme.RADIUS)
        search_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        search_frame.grid_columnconfigure(0, weight=1)

        self.search = ctk.CTkEntry(
            search_frame, placeholder_text="🔍 Search site or username…",
            height=36, fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM
        )
        self.search.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=10)
        self.search.bind("<KeyRelease>", lambda e: self.render())

        self.filter_category = ctk.CTkOptionMenu(
            search_frame, values=["All"] + CATEGORIES, command=lambda x: self.render(),
            width=140, height=36, fg_color=CARD, button_color=CARD,
            button_hover_color=CARD_HOVER, corner_radius=theme.RADIUS_SM
        )
        self.filter_category.set("All")
        self.filter_category.grid(row=0, column=1, padx=(6, 12), pady=10)

        # ---------------- PASSWORD LIST ----------------

        self.cards = ctk.CTkScrollableFrame(passwords_tab, fg_color=PANEL, corner_radius=theme.RADIUS)
        self.cards.grid(row=2, column=0, sticky="nsew")

    def _stat_pill(self, parent, label, value, col):
        pill = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=theme.RADIUS)
        pill.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 5, 0))

        value_label = ctk.CTkLabel(pill, text=value, font=theme.font(19, "bold"), text_color=TEXT)
        value_label.pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(pill, text=label, font=theme.font(11), text_color=MUTED).pack(anchor="w", padx=14, pady=(0, 10))

        return value_label

    # =====================================================
    # STRENGTH
    # =====================================================

    def get_strength(self, password):
        score = 0
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if any(c.isupper() for c in password):
            score += 1
        if any(c.isdigit() for c in password):
            score += 1
        if any(not c.isalnum() for c in password):
            score += 1

        if score <= 2:
            return "Weak"
        if score <= 4:
            return "Strong"
        return "Very Strong"

    def _strength_color(self, strength):
        if strength == "Strong":
            return "#f1c40f"
        if strength == "Very Strong":
            return SUCCESS
        return ERROR

    # =====================================================
    # ADD ENTRY (modal, with a bigger generator)
    # =====================================================

    def open_add_entry_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Entry")
        dialog.geometry("460x760")
        dialog.transient(self.master)
        dialog.configure(fg_color=PANEL)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text="➕ Add New Entry", font=theme.font(19, "bold"), text_color=TEXT
        ).pack(pady=(20, 16), padx=24, anchor="w")

        def field_label(text):
            ctk.CTkLabel(dialog, text=text, anchor="w", font=theme.font(12), text_color=MUTED).pack(
                fill="x", padx=24, pady=(0, 3)
            )

        field_label("Website / Service")
        site_entry = ctk.CTkEntry(
            dialog, placeholder_text="e.g. github.com", height=38,
            fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM
        )
        site_entry.pack(fill="x", padx=24, pady=(0, 12))

        field_label("Username")
        user_entry = ctk.CTkEntry(
            dialog, height=38, fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM
        )
        user_entry.pack(fill="x", padx=24, pady=(0, 12))

        field_label("Category")
        category_menu = ctk.CTkOptionMenu(
            dialog, values=CATEGORIES, height=38, fg_color=CARD,
            button_color=CARD, button_hover_color=CARD_HOVER, corner_radius=theme.RADIUS_SM
        )
        category_menu.set("General")
        category_menu.pack(fill="x", padx=24, pady=(0, 16))

        # ---------------- Password ----------------

        field_label("Password")
        pass_row = ctk.CTkFrame(dialog, fg_color="transparent")
        pass_row.pack(fill="x", padx=24, pady=(0, 4))
        pass_row.grid_columnconfigure(0, weight=1)

        pass_entry = ctk.CTkEntry(
            pass_row, height=38, font=theme.mono(13),
            fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM
        )
        pass_entry.grid(row=0, column=0, sticky="ew")

        strength_label = ctk.CTkLabel(dialog, text="Strength: —", font=theme.font(11), text_color=MUTED)
        strength_label.pack(anchor="w", padx=24, pady=(4, 16))

        def update_strength(_e=None):
            s = self.get_strength(pass_entry.get())
            strength_label.configure(text=f"Strength: {s}", text_color=self._strength_color(s))

        pass_entry.bind("<KeyRelease>", update_strength)

        # ---------------- Generator (bigger) ----------------

        gen_panel = ctk.CTkFrame(dialog, fg_color=CARD, corner_radius=theme.RADIUS)
        gen_panel.pack(fill="x", padx=24, pady=(0, 18))

        ctk.CTkLabel(
            gen_panel, text="🎲 Password Generator", font=theme.font(15, "bold"), text_color=TEXT
        ).pack(anchor="w", padx=18, pady=(16, 10))

        length_label = ctk.CTkLabel(
            gen_panel, text=f"Length: {self.gen_length_var.get()}",
            font=theme.font(13), text_color=MUTED
        )
        length_label.pack(fill="x", padx=18)

        def on_length_change(value):
            self.gen_length_var.set(int(float(value)))
            length_label.configure(text=f"Length: {int(float(value))}")

        length_slider = ctk.CTkSlider(
            gen_panel, from_=8, to=64, height=20,
            progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            command=on_length_change
        )
        length_slider.set(self.gen_length_var.get())
        length_slider.pack(fill="x", padx=18, pady=(6, 16))

        checks = ctk.CTkFrame(gen_panel, fg_color="transparent")
        checks.pack(fill="x", padx=18, pady=(0, 4))
        checks.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkCheckBox(checks, text="Uppercase (A-Z)", variable=self.upper_var,
                         font=theme.font(12), checkbox_width=20, checkbox_height=20).grid(
            row=0, column=0, sticky="w", pady=6)
        ctk.CTkCheckBox(checks, text="Lowercase (a-z)", variable=self.lower_var,
                         font=theme.font(12), checkbox_width=20, checkbox_height=20).grid(
            row=0, column=1, sticky="w", pady=6)
        ctk.CTkCheckBox(checks, text="Numbers (0-9)", variable=self.number_var,
                         font=theme.font(12), checkbox_width=20, checkbox_height=20).grid(
            row=1, column=0, sticky="w", pady=6)
        ctk.CTkCheckBox(checks, text="Symbols (!@#$)", variable=self.symbol_var,
                         font=theme.font(12), checkbox_width=20, checkbox_height=20).grid(
            row=1, column=1, sticky="w", pady=6)

        def do_generate():
            length = self.gen_length_var.get()
            char_pool = ""
            if self.upper_var.get():
                char_pool += string.ascii_uppercase
            if self.lower_var.get():
                char_pool += string.ascii_lowercase
            if self.number_var.get():
                char_pool += string.digits
            if self.symbol_var.get():
                char_pool += "!@#$%^&*()_+-="
            if not char_pool:
                char_pool = string.ascii_letters + string.digits + "!@#$%^&*()_+-="

            password = "".join(random.choice(char_pool) for _ in range(length))
            pass_entry.delete(0, "end")
            pass_entry.insert(0, password)
            update_strength()

        ctk.CTkButton(
            gen_panel, text="🎲  Generate Password", height=44, font=theme.font(14, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#0b0d10",
            corner_radius=theme.RADIUS_SM, command=do_generate
        ).pack(fill="x", padx=18, pady=(6, 18))

        # ---------------- Save ----------------

        status_label = ctk.CTkLabel(dialog, text="", font=theme.font(11), text_color=ERROR)
        status_label.pack(padx=24)

        def submit():
            site = site_entry.get().strip()
            user = user_entry.get().strip()
            password = pass_entry.get().strip()
            category = category_menu.get()

            if not site or not password:
                status_label.configure(text="Site and password are required.")
                return

            self.vault.add_entry(site, user, password, category)
            dialog.destroy()
            self.render()

        site_entry.bind("<Return>", lambda e: user_entry.focus_set())
        user_entry.bind("<Return>", lambda e: pass_entry.focus_set())
        pass_entry.bind("<Return>", lambda e: submit())

        ctk.CTkButton(
            dialog, text="➕ Save Entry", height=42, font=theme.font(14, "bold"),
            command=submit, **{k: v for k, v in theme.primary_button_style().items() if k != "font"}
        ).pack(fill="x", padx=24, pady=(0, 20))

        site_entry.focus_set()

    # =====================================================
    # DELETE
    # =====================================================

    def delete_entry(self, entry_id):
        self.vault.delete_entry(entry_id)
        if entry_id in self.visible_passwords:
            self.visible_passwords.remove(entry_id)
        self.render()

    # =====================================================
    # TOGGLE FAVORITE
    # =====================================================
    def toggle_favorites_filter(self):
        self.show_favorites_only = not self.show_favorites_only
        if self.show_favorites_only:
            self.favorites_toggle_button.configure(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#0b0d10")
        else:
            self.favorites_toggle_button.configure(fg_color=CARD, hover_color=CARD_HOVER, text_color=TEXT)
        self.render()

    def toggle_favorite(self, entry_id):
        self.vault.toggle_favorite(entry_id)
        self.render()

    def toggle_password_visibility(self, entry_id):
        if entry_id in self.visible_passwords:
            self.visible_passwords.remove(entry_id)
        else:
            self.visible_passwords.add(entry_id)
        self.render()

    # =====================================================
    # OPEN EDIT DIALOG
    # =====================================================
    def open_edit_dialog(self, entry):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Edit Entry")
        dialog.geometry("420x480")
        dialog.transient(self.master)
        dialog.configure(fg_color=PANEL)
        dialog.grab_set()

        entry_id = entry["id"]

        ctk.CTkLabel(dialog, text="✏ Edit Entry", font=theme.font(18, "bold"), text_color=TEXT).pack(
            pady=(20, 16), padx=24, anchor="w"
        )

        def field_label(text):
            ctk.CTkLabel(dialog, text=text, anchor="w", font=theme.font(12), text_color=MUTED).pack(
                fill="x", padx=24, pady=(0, 3)
            )

        field_label("Site")
        edit_site_entry = ctk.CTkEntry(dialog, height=38, fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM)
        edit_site_entry.insert(0, entry["site"])
        edit_site_entry.pack(fill="x", padx=24, pady=(0, 12))

        field_label("Username")
        edit_user_entry = ctk.CTkEntry(dialog, height=38, fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM)
        edit_user_entry.insert(0, entry["username"])
        edit_user_entry.pack(fill="x", padx=24, pady=(0, 12))

        field_label("Password")
        edit_pass_entry = ctk.CTkEntry(dialog, height=38, font=theme.mono(13), fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM)
        edit_pass_entry.insert(0, entry["password"])
        edit_pass_entry.pack(fill="x", padx=24, pady=(0, 12))

        field_label("Category")
        edit_category_menu = ctk.CTkOptionMenu(
            dialog, values=CATEGORIES, height=38, fg_color=CARD,
            button_color=CARD, button_hover_color=CARD_HOVER, corner_radius=theme.RADIUS_SM
        )
        edit_category_menu.set(entry["category"])
        edit_category_menu.pack(fill="x", padx=24, pady=(0, 20))

        def save_edited_entry():
            new_site = edit_site_entry.get().strip()
            new_user = edit_user_entry.get().strip()
            new_password = edit_pass_entry.get().strip()
            new_category = edit_category_menu.get()

            if not new_site or not new_password:
                return

            self.vault.update_entry(entry_id, new_site, new_user, new_password, new_category)
            dialog.destroy()
            self.render()

        ctk.CTkButton(
            dialog, text="Save Changes", height=42, font=theme.font(14, "bold"),
            command=save_edited_entry, **{k: v for k, v in theme.primary_button_style().items() if k != "font"}
        ).pack(fill="x", padx=24, pady=(0, 20))

    # =====================================================
    # CHANGE MASTER PASSWORD
    # =====================================================

    def open_change_password_dialog(self):

        auth = self.manager.container.auth_service

        dialog = ctk.CTkToplevel(self)
        dialog.title("Change Master Password")
        dialog.geometry("380x420")
        dialog.transient(self.master)
        dialog.configure(fg_color=PANEL)
        dialog.grab_set()  # modal — this touches vault security, don't let it get lost behind other windows

        ctk.CTkLabel(
            dialog,
            text="🔑 Change Master Password",
            font=theme.font(17, "bold"),
            text_color=TEXT
        ).pack(pady=(20, 4))

        ctk.CTkLabel(
            dialog,
            text="You'll need your current password to confirm.",
            font=theme.font(11),
            text_color=MUTED,
            wraplength=300
        ).pack(pady=(0, 16))

        def labeled_entry(text):
            ctk.CTkLabel(
                dialog, text=text, anchor="w", font=theme.font(12), text_color=MUTED
            ).pack(fill="x", padx=24, pady=(4, 2))
            e = ctk.CTkEntry(
                dialog, show="•", height=36,
                fg_color=CARD, border_color=BORDER, corner_radius=theme.RADIUS_SM
            )
            e.pack(fill="x", padx=24)
            return e

        current_entry = labeled_entry("Current password")
        new_entry = labeled_entry("New password")

        strength_bar = ctk.CTkProgressBar(
            dialog, height=4, corner_radius=2,
            progress_color=STRENGTH_COLORS[0], fg_color=BORDER
        )
        strength_bar.pack(fill="x", padx=24, pady=(6, 0))
        strength_bar.set(0)

        strength_label = ctk.CTkLabel(dialog, text=" ", font=theme.font(11), text_color=FAINT)
        strength_label.pack(anchor="e", padx=24)

        def update_strength(_event=None):
            score, label = AuthService.password_strength(new_entry.get())
            strength_bar.configure(progress_color=STRENGTH_COLORS[max(score - 1, 0)])
            strength_bar.set(score / 4)
            strength_label.configure(text=label if new_entry.get() else " ")

        new_entry.bind("<KeyRelease>", update_strength)

        confirm_entry = labeled_entry("Confirm new password")

        status_label = ctk.CTkLabel(dialog, text="", font=theme.font(11), text_color=ERROR, wraplength=300)
        status_label.pack(pady=(10, 0))

        def submit():
            current = current_entry.get()
            new = new_entry.get()
            confirm = confirm_entry.get()

            if len(new) < 8:
                status_label.configure(text_color=ERROR, text="New password must be at least 8 characters.")
                return

            if new != confirm:
                status_label.configure(text_color=ERROR, text="New passwords do not match.")
                return

            if new == current:
                status_label.configure(text_color=ERROR, text="New password must be different from the current one.")
                return

            if not auth.change_master_password(current, new):
                status_label.configure(text_color=ERROR, text="Current password is incorrect.")
                current_entry.delete(0, "end")
                return

            status_label.configure(text_color=SUCCESS, text="Master password changed.")
            dialog.after(700, dialog.destroy)

        current_entry.bind("<Return>", lambda e: new_entry.focus_set())
        new_entry.bind("<Return>", lambda e: confirm_entry.focus_set())
        confirm_entry.bind("<Return>", lambda e: submit())

        ctk.CTkButton(
            dialog,
            text="Change Password",
            height=38,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0b0d10",
            font=theme.font(13, "bold"),
            command=submit
        ).pack(fill="x", padx=24, pady=(18, 0))

        current_entry.focus_set()

    # =====================================================
    # IMPORT / EXPORT
    # =====================================================

    def export_vault(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.vault.export_json(path)

    def import_vault(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.vault.import_json(path)
            self.render()

    # =====================================================
    # COPY
    # =====================================================

    def copy_password(self, password):
        if pyperclip:
            pyperclip.copy(password)

    def copy_username(self, username):
        if pyperclip:
            pyperclip.copy(username)

    # =====================================================
    # RENDER
    # =====================================================

    def render(self):

        for widget in self.cards.winfo_children():
            widget.destroy()

        all_entries_from_vault = self.vault.get_entries()

        # Stats
        stats = self.vault.stats()
        self.stats_total_label.configure(text=str(stats["total"]))
        self.stats_favorites_label.configure(text=str(stats["favorites"]))
        self.stats_categories_label.configure(text=str(stats["categories"]))
        self.stats_sites_label.configure(text=str(stats["sites"]))

        security = self.vault.security_score()
        score = security["score"]

        color = SUCCESS
        if score < 80:
            color = "#f1c40f"
        if score < 60:
            color = ERROR

        self.security_label.configure(text=f"{score}/100", text_color=color)

        entries_to_render = all_entries_from_vault

        search_query = self.search.get().lower().strip()
        if search_query:
            entries_to_render = [
                e for e in entries_to_render
                if search_query in e["site"].lower() or
                   search_query in e["username"].lower() or
                   search_query in e["category"].lower()
            ]

        selected_category = self.filter_category.get()
        if selected_category != "All":
            entries_to_render = [e for e in entries_to_render if e["category"] == selected_category]

        if self.show_favorites_only:
            entries_to_render = [e for e in entries_to_render if e.get("favorite", False)]

        entries_to_render.sort(key=lambda x: x.get("updated", ""), reverse=True)

        if not entries_to_render:
            ctk.CTkLabel(
                self.cards,
                text="No entries yet — click ➕ Add Entry to save your first login."
                if not all_entries_from_vault else "No entries match your search/filter.",
                font=theme.font(13), text_color=MUTED
            ).pack(pady=30)

        for item in entries_to_render:
            self._render_card(item)

    def _render_card(self, item):
        card = ctk.CTkFrame(self.cards, fg_color=CARD, corner_radius=theme.RADIUS, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=6, pady=6)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=(12, 4))

        initial = (item["site"][:1] or "?").upper()
        ctk.CTkLabel(
            body, text=initial, width=42, height=42, corner_radius=21,
            fg_color=theme.hash_color(item["site"] or item["id"]),
            text_color="#0b0d10", font=theme.font(16, "bold")
        ).pack(side="left", padx=(0, 12))

        info = ctk.CTkFrame(body, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(fill="x", anchor="w")

        ctk.CTkLabel(title_row, text=item["site"], font=theme.font(16, "bold"), text_color=TEXT).pack(side="left")

        ctk.CTkLabel(
            title_row, text=f"  {item['category']}  ", font=theme.font(10, "bold"),
            text_color=ACCENT, fg_color=ACCENT_GLOW, corner_radius=theme.RADIUS_SM
        ).pack(side="left", padx=(8, 0))

        if item.get("favorite", False):
            ctk.CTkLabel(title_row, text="⭐", font=theme.font(11)).pack(side="left", padx=(6, 0))

        ctk.CTkLabel(info, text=item["username"] or "—", font=theme.font(12), text_color=MUTED).pack(
            anchor="w", pady=(3, 0)
        )

        is_visible = item["id"] in self.visible_passwords
        password_text = item["password"] if is_visible else "•" * 14
        ctk.CTkLabel(
            info, text=password_text, font=theme.mono(12), text_color=TEXT if is_visible else FAINT
        ).pack(anchor="w", pady=(3, 0))

        updated_date_str = item["updated"]
        if isinstance(updated_date_str, datetime.datetime):
            updated_date_str = updated_date_str.strftime("%Y-%m-%d")
        ctk.CTkLabel(body, text=f"Updated {updated_date_str[:10]}", font=theme.font(10), text_color=FAINT).pack(
            side="right", anchor="n"
        )

        # ---------------- action buttons ----------------

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(6, 12))

        def icon_btn(parent, text, cmd, width=38, style=None, **overrides):
            kw = dict(style or theme.secondary_button_style())
            kw.update(overrides)
            return ctk.CTkButton(parent, text=text, width=width, height=32, command=cmd, **kw)

        is_fav = item.get("favorite", False)
        icon_btn(
            buttons, "⭐" if is_fav else "☆", lambda eid=item["id"]: self.toggle_favorite(eid),
            style=theme.primary_button_style() if is_fav else theme.secondary_button_style()
        ).pack(side="left", padx=(0, 4))

        icon_btn(
            buttons, "🙈" if is_visible else "👁", lambda eid=item["id"]: self.toggle_password_visibility(eid)
        ).pack(side="left", padx=4)

        icon_btn(buttons, "📋", lambda p=item["password"]: self.copy_password(p), width=44).pack(side="left", padx=4)
        icon_btn(buttons, "👤📋", lambda u=item["username"]: self.copy_username(u), width=50).pack(side="left", padx=4)
        icon_btn(buttons, "✏", lambda e=item: self.open_edit_dialog(e), width=44).pack(side="left", padx=4)
        icon_btn(
            buttons, "🗑", lambda eid=item["id"]: self.delete_entry(eid), width=44,
            style=theme.danger_button_style()
        ).pack(side="right")
