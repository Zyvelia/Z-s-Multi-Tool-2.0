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

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2

ACCENT = theme.ACCENT

TEXT = theme.TEXT
MUTED = theme.MUTED


class PasswordVaultPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent)

        self.manager = manager
        self.vault = manager.container.vault_service

        self.visible_passwords = set()

        self.configure(fg_color=BG)

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Better Generator - Checkbox variables
        self.upper_var = ctk.BooleanVar(value=True)
        self.lower_var = ctk.BooleanVar(value=True)
        self.number_var = ctk.BooleanVar(value=True)
        self.symbol_var = ctk.BooleanVar(value=True)

        self.show_favorites_only = False

        self.build_ui()
        self.render()

    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        # ---------------- HEADER ----------------

        header = ctk.CTkFrame(self, fg_color=PANEL)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=15,
            pady=15
        )

        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(
            header,
            text="🔐 Password Vault",
            font=("Segoe UI", 26, "bold"),
            text_color=TEXT
        ).grid(row=0, column=1, sticky="w", padx=(10, 0))

        # Favorites Only Toggle Button
        self.favorites_toggle_button = ctk.CTkButton(
            header,
            text="⭐ Favorites",
            command=self.toggle_favorites_filter,
            fg_color=CARD,
            hover_color=ACCENT
        )
        self.favorites_toggle_button.grid(row=0, column=2, padx=10, pady=10)


        # ---------------- STATS (Better Dashboard Stats Card) ----------------

        stats_frame = ctk.CTkFrame(self, fg_color=PANEL)
        stats_frame.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=15,
            pady=(0, 10)
        )
        # Configure columns for the new dashboard layout (4 stats + 1 security score)
        stats_frame.grid_columnconfigure(0, weight=1)
        stats_frame.grid_columnconfigure(1, weight=1)
        stats_frame.grid_columnconfigure(2, weight=1)
        stats_frame.grid_columnconfigure(3, weight=1)
        stats_frame.grid_columnconfigure(4, weight=1) # For the security score label

        self.stats_total_label = ctk.CTkLabel(
            stats_frame,
            text="Passwords: 0",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT
        )
        self.stats_total_label.grid(row=0, column=0, sticky="w", padx=15, pady=10)

        self.stats_favorites_label = ctk.CTkLabel(
            stats_frame,
            text="Favorites: 0",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT
        )
        self.stats_favorites_label.grid(row=0, column=1, sticky="w", pady=10)

        self.stats_categories_label = ctk.CTkLabel(
            stats_frame,
            text="Categories: 0",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT
        )
        self.stats_categories_label.grid(row=0, column=2, sticky="w", pady=10)

        self.stats_sites_label = ctk.CTkLabel(
            stats_frame,
            text="Sites: 0",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT
        )
        self.stats_sites_label.grid(row=0, column=3, sticky="w", pady=10)

        # ADDED: Security Score Label
        self.security_label = ctk.CTkLabel(
            stats_frame,
            text="🔐 Score: 100/100", # Initial text
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT # Initial color, will be updated
        )
        self.security_label.grid(row=0, column=4, sticky="e", padx=15, pady=10)


        # ---------------- MAIN ----------------

        main = ctk.CTkFrame(
            self,
            fg_color=BG
        )

        main.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=15,
            pady=(0, 15)
        )

        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=2)

        # =================================================
        # LEFT PANEL (Add Entry Section)
        # =================================================

        left = ctk.CTkFrame(
            main,
            fg_color=PANEL
        )

        left.grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="nsew",
            padx=(0, 10)
        )

        ctk.CTkLabel(
            left,
            text="Add New Entry",
            font=("Segoe UI", 18, "bold")
        ).pack(
            pady=(15, 5)
        )

        self.site_entry = ctk.CTkEntry(
            left,
            placeholder_text="Website / Service"
        )

        self.site_entry.pack(
            fill="x",
            padx=10,
            pady=5
        )

        self.user_entry = ctk.CTkEntry(
            left,
            placeholder_text="Username"
        )

        self.user_entry.pack(
            fill="x",
            padx=10,
            pady=5
        )

        self.pass_entry = ctk.CTkEntry(
            left,
            placeholder_text="Password"
        )

        self.pass_entry.pack(
            fill="x",
            padx=10,
            pady=5
        )

        self.strength_label = ctk.CTkLabel(
            left,
            text="Strength: -",
            text_color=MUTED
        )

        self.strength_label.pack(
            anchor="w",
            padx=12,
            pady=(0, 5)
        )

        self.pass_entry.bind(
            "<KeyRelease>",
            lambda e: self.update_strength()
        )

        ctk.CTkLabel(left, text="Category:", font=("Segoe UI", 12), text_color=MUTED).pack(anchor="w", padx=10, pady=(5,0))
        self.category_menu = ctk.CTkOptionMenu(
            left,
            values=[
                "General",
                "Email",
                "Gaming",
                "Work",
                "Banking",
                "Social"
            ]
        )
        self.category_menu.set("General")
        self.category_menu.pack(
            fill="x",
            padx=10,
            pady=5
        )

        # Length slider for generator
        self.length_label = ctk.CTkLabel(
            left,
            text="Length: 20",
            font=("Segoe UI", 12),
            text_color=MUTED,
            anchor="w"
        )
        self.length_label.pack(fill="x", padx=10, pady=(5, 0))

        self.length_slider = ctk.CTkSlider(
            left,
            from_=8,
            to=64,
            command=self._update_length_label
        )
        self.length_slider.set(20)
        self.length_slider.pack(fill="x", padx=10, pady=(0, 5))

        # Checkboxes for generator options
        ctk.CTkCheckBox(
            left,
            text="Uppercase",
            variable=self.upper_var
        ).pack(anchor="w", padx=10, pady=2)

        ctk.CTkCheckBox(
            left,
            text="Lowercase",
            variable=self.lower_var
        ).pack(anchor="w", padx=10, pady=2)

        ctk.CTkCheckBox(
            left,
            text="Numbers",
            variable=self.number_var
        ).pack(anchor="w", padx=10, pady=2)

        ctk.CTkCheckBox(
            left,
            text="Symbols",
            variable=self.symbol_var
        ).pack(anchor="w", padx=10, pady=2)

        ctk.CTkButton(
            left,
            text="🎲 Generate Password",
            fg_color=ACCENT,
            command=self.generate_password
        ).pack(
            fill="x",
            padx=10,
            pady=5
        )

        ctk.CTkButton(
            left,
            text="➕ Save Entry",
            command=self.add_entry
        ).pack(
            fill="x",
            padx=10,
            pady=10
        )
        
        # Export Vault Button
        ctk.CTkButton(
            left,
            text="📤 Export Vault",
            command=self.export_vault
        ).pack(
            fill="x",
            padx=10,
            pady=5
        )

        # Import Vault Button
        ctk.CTkButton(
            left,
            text="📥 Import Vault",
            command=self.import_vault
        ).pack(
            fill="x",
            padx=10,
            pady=5
        )


        # =================================================
        # SEARCH AND CATEGORY FILTER
        # =================================================

        search_frame = ctk.CTkFrame(main, fg_color=PANEL)
        search_frame.grid(
            row=0,
            column=1,
            sticky="ew"
        )
        search_frame.grid_columnconfigure(0, weight=1)
        search_frame.grid_columnconfigure(1, weight=0)

        self.search = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search site or username..."
        )

        self.search.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(10, 5),
            pady=10
        )

        self.search.bind(
            "<KeyRelease>",
            lambda e: self.render()
        )

        # Category Filter
        self.filter_category = ctk.CTkOptionMenu(
            search_frame,
            values=[
                "All",
                "General",
                "Email",
                "Gaming",
                "Work",
                "Banking",
                "Social"
            ],
            command=lambda x: self.render()
        )
        self.filter_category.set("All")
        self.filter_category.grid(
            row=0,
            column=1,
            padx=(5, 10),
            pady=10
        )


        # =================================================
        # PASSWORD LIST
        # =================================================

        self.cards = ctk.CTkScrollableFrame(
            main,
            fg_color=PANEL
        )

        self.cards.grid(
            row=1,
            column=1,
            sticky="nsew",
            pady=(10, 0)
        )
    
    def _update_length_label(self, value):
        self.length_label.configure(text=f"Length: {int(value)}")


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

    def update_strength(self):

        password = self.pass_entry.get()

        strength = self.get_strength(password)

        color = "#ff5e57"

        if strength == "Strong":
            color = "#f1c40f"

        if strength == "Very Strong":
            color = "#2ecc71"

        self.strength_label.configure(
            text=f"Strength: {strength}",
            text_color=color
        )

    # =====================================================
    # GENERATOR
    # =====================================================

    def generate_password(self):

        length = int(self.length_slider.get())
        
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
            char_pool = (
                string.ascii_letters +
                string.digits +
                "!@#$%^&*()_+-="
            )

        password = "".join(
            random.choice(char_pool)
            for _ in range(length)
        )

        self.pass_entry.delete(0, "end")
        self.pass_entry.insert(0, password)

        self.update_strength()

    # =====================================================
    # ADD
    # =====================================================

    def add_entry(self):

        site = self.site_entry.get().strip()
        user = self.user_entry.get().strip()
        password = self.pass_entry.get().strip()
        category = self.category_menu.get()

        if not site or not password:
            return

        self.vault.add_entry(
            site,
            user,
            password,
            category
        )

        self.site_entry.delete(0, "end")
        self.user_entry.delete(0, "end")
        self.pass_entry.delete(0, "end")
        self.category_menu.set("General")

        self.strength_label.configure(
            text="Strength: -",
            text_color=MUTED
        )

        self.render()

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
            self.favorites_toggle_button.configure(fg_color=ACCENT, hover_color=CARD)
        else:
            self.favorites_toggle_button.configure(fg_color=CARD, hover_color=ACCENT)
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
        dialog.geometry("400x450")
        dialog.transient(self.master)

        entry_id = entry["id"]

        ctk.CTkLabel(dialog, text="Edit Entry", font=("Segoe UI", 18, "bold")).pack(pady=10)

        ctk.CTkLabel(dialog, text="Site:", anchor="w").pack(fill="x", padx=20, pady=(5,0))
        edit_site_entry = ctk.CTkEntry(dialog)
        edit_site_entry.insert(0, entry["site"])
        edit_site_entry.pack(fill="x", padx=20, pady=(0,5))

        ctk.CTkLabel(dialog, text="Username:", anchor="w").pack(fill="x", padx=20, pady=(5,0))
        edit_user_entry = ctk.CTkEntry(dialog)
        edit_user_entry.insert(0, entry["username"])
        edit_user_entry.pack(fill="x", padx=20, pady=(0,5))

        ctk.CTkLabel(dialog, text="Password:", anchor="w").pack(fill="x", padx=20, pady=(5,0))
        edit_pass_entry = ctk.CTkEntry(dialog)
        edit_pass_entry.insert(0, entry["password"])
        edit_pass_entry.pack(fill="x", padx=20, pady=(0,5))

        ctk.CTkLabel(dialog, text="Category:", anchor="w").pack(fill="x", padx=20, pady=(5,0))
        edit_category_menu = ctk.CTkOptionMenu(
            dialog,
            values=[
                "General", "Email", "Gaming", "Work", "Banking", "Social"
            ]
        )
        edit_category_menu.set(entry["category"])
        edit_category_menu.pack(fill="x", padx=20, pady=(0,10))

        def save_edited_entry():
            new_site = edit_site_entry.get().strip()
            new_user = edit_user_entry.get().strip()
            new_password = edit_pass_entry.get().strip()
            new_category = edit_category_menu.get()

            if not new_site or not new_password:
                return

            self.vault.update_entry(
                entry_id,
                new_site,
                new_user,
                new_password,
                new_category
            )
            dialog.destroy()
            self.render()

        ctk.CTkButton(dialog, text="Save Changes", command=save_edited_entry).pack(pady=10)


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

        # Update Better Dashboard Stats Card
        stats = self.vault.stats()
        self.stats_total_label.configure(text=f"Passwords: {stats['total']}")
        self.stats_favorites_label.configure(text=f"Favorites: {stats['favorites']}")
        self.stats_categories_label.configure(text=f"Categories: {stats['categories']}")
        self.stats_sites_label.configure(text=f"Sites: {stats['sites']}")

        # ADDED: Security Score Update logic
        security = self.vault.security_score() # Call security_score()
        score = security["score"]

        color = "#2ecc71" # Green
        if score < 80:
            color = "#f1c40f" # Yellow
        if score < 60:
            color = "#e74c3c" # Red

        self.security_label.configure(
            text=(
                f"🔐 Score: {score}/100   "
                f"Weak: {security['weak']}   "
                f"Duplicates: {security['duplicates']}"
            ),
            text_color=color
        )
        # END ADDED block

        entries_to_render = all_entries_from_vault

        # Apply Search Filter
        search_query = self.search.get().lower().strip()
        if search_query:
            entries_to_render = [
                e for e in entries_to_render
                if search_query in e["site"].lower() or \
                   search_query in e["username"].lower() or \
                   search_query in e["category"].lower()
            ]

        # Apply Category Filter
        selected_category = self.filter_category.get()
        if selected_category != "All":
            entries_to_render = [
                e for e in entries_to_render
                if e["category"] == selected_category
            ]

        # Apply Favorites Only Toggle
        if self.show_favorites_only:
            entries_to_render = [
                e for e in entries_to_render
                if e.get("favorite", False)
            ]

        entries_to_render.sort(
            key=lambda x: x.get("updated", ""),
            reverse=True
        )


        for item in entries_to_render:

            card = ctk.CTkFrame(
                self.cards,
                fg_color=CARD
            )

            card.pack(
                fill="x",
                padx=5,
                pady=5
            )

            ctk.CTkLabel(
                card,
                text=item["site"],
                font=("Segoe UI", 18, "bold"),
                text_color=TEXT
            ).pack(
                anchor="w",
                padx=10,
                pady=(10, 0)
            )

            ctk.CTkLabel(
                card,
                text=item["username"],
                text_color=MUTED
            ).pack(
                anchor="w",
                padx=10
            )

            ctk.CTkLabel(
                card,
                text=f"📂 {item['category']}",
                text_color=ACCENT
            ).pack(
                anchor="w",
                padx=10
            )

            created_date_str = item['created']
            if isinstance(created_date_str, datetime.datetime):
                created_date_str = created_date_str.strftime('%Y-%m-%d')
            ctk.CTkLabel(
                card,
                text=f"Created: {created_date_str[:10]}",
                text_color=MUTED
            ).pack(
                anchor="w",
                padx=10
            )

            updated_date_str = item['updated']
            if isinstance(updated_date_str, datetime.datetime):
                updated_date_str = updated_date_str.strftime('%Y-%m-%d')
            ctk.CTkLabel(
                card,
                text=f"Updated: {updated_date_str[:10]}",
                text_color=MUTED
            ).pack(
                anchor="w",
                padx=10
            )

            password_text = "••••••••••••••••"
            if item["id"] in self.visible_passwords:
                password_text = item["password"]

            ctk.CTkLabel(
                card,
                text=password_text,
                text_color=MUTED
            ).pack(
                anchor="w",
                padx=10,
                pady=(0, 10)
            )

            buttons = ctk.CTkFrame(
                card,
                fg_color="transparent"
            )

            buttons.pack(
                fill="x",
                padx=10,
                pady=(0, 10)
            )

            # FAVORITES BUTTON
            star_text = "⭐" if item.get("favorite", False) else "☆"
            ctk.CTkButton(
                buttons,
                text=star_text,
                width=40,
                fg_color=ACCENT if item.get("favorite", False) else CARD,
                hover_color=ACCENT if not item.get("favorite", False) else "#3a8de6",
                command=lambda eid=item["id"]:
                self.toggle_favorite(eid)
            ).pack(side="left", padx=2)

            button_text = "🙈 Hide"
            if item["id"] not in self.visible_passwords:
                button_text = "👁 Show"

            ctk.CTkButton(
                buttons,
                text=button_text,
                width=90,
                command=lambda eid=item["id"]:
                self.toggle_password_visibility(eid)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                buttons,
                text="📋 Copy",
                width=90,
                command=lambda p=item["password"]:
                self.copy_password(p)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                buttons,
                text="👤 Copy User",
                width=100,
                command=lambda u=item["username"]:
                self.copy_username(u)
            ).pack(side="left", padx=2)

            # EDIT BUTTON
            ctk.CTkButton(
                buttons,
                text="✏ Edit",
                width=90,
                fg_color="#f39c12",
                hover_color="#e67e22",
                command=lambda e=item:
                self.open_edit_dialog(e)
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                buttons,
                text="🗑 Delete",
                width=90,
                fg_color="#b33939",
                hover_color="#d63031",
                command=lambda eid=item["id"]:
                self.delete_entry(eid)
            ).pack(side="right", padx=2)