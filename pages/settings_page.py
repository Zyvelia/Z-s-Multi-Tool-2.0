import webbrowser

import customtkinter as ctk
from PIL import Image

from core import theme
from core import paths
from core import updater

# ── About section links ──────────────────────────────────────────────────
# Fill in GITHUB_URL once the repo is uploaded — the button below enables
# itself automatically as soon as this isn't empty.
DISCORD_URL = "https://discord.gg/vSX49HJMHS"
GITHUB_URL = ""  # e.g. "https://github.com/your-username/Zs-Multi-Tool"

APP_VERSION = "1.0.0"


class SettingsPage(ctk.CTkFrame):

    def __init__(self, parent, manager, settings, plugin_manager):
        super().__init__(parent, fg_color=theme.BG)

        self.manager = manager
        self.settings = settings
        self.plugin_manager = plugin_manager

        self.tool_check_vars = {}

        self.build_ui()

    # =========================================================
    # UI
    # =========================================================

    def build_ui(self):

        # ---------------- HEADER ----------------
        header = ctk.CTkFrame(self, **theme.panel_style())
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        ctk.CTkLabel(
            header,
            text="⚙  Settings",
            font=theme.font(24, "bold"),
            text_color=theme.TEXT
        ).pack(side="left", padx=theme.PAD_LG, pady=theme.PAD)

        ctk.CTkButton(
            header,
            text="←  Back",
            width=110,
            height=36,
            command=lambda: self.manager.show_page("catalog"),
            **theme.secondary_button_style()
        ).pack(side="right", padx=theme.PAD_LG)

        # =====================================================
        # SYSTEM SETTINGS
        # =====================================================

        system_frame = ctk.CTkFrame(self, **theme.panel_style())
        system_frame.pack(fill="x", padx=theme.PAD_LG, pady=theme.PAD)

        self._section_title(system_frame, "🛠  System")

        system_row = ctk.CTkFrame(system_frame, fg_color="transparent")
        system_row.pack(fill="x", padx=theme.PAD_LG, pady=(4, theme.PAD))

        ctk.CTkButton(
            system_row,
            text="Save Settings",
            width=160,
            height=34,
            command=self.save_settings,
            **theme.primary_button_style()
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            system_row,
            text="Reset Settings",
            width=160,
            height=34,
            command=self.reset_settings,
            **theme.danger_button_style()
        ).pack(side="left")

        # =====================================================
        # UPDATES
        # =====================================================

        updates_frame = ctk.CTkFrame(self, **theme.panel_style())
        updates_frame.pack(fill="x", padx=theme.PAD_LG, pady=theme.PAD)

        self._section_title(updates_frame, "⬆  Updates")

        updates_row = ctk.CTkFrame(updates_frame, fg_color="transparent")
        updates_row.pack(fill="x", padx=theme.PAD_LG, pady=(4, theme.PAD))

        self.auto_update_switch = ctk.CTkSwitch(
            updates_row,
            text="Check for updates on launch",
            command=self._on_toggle_auto_update,
            font=theme.font(13),
            text_color=theme.TEXT,
            progress_color=theme.ACCENT
        )
        self.auto_update_switch.pack(side="left", padx=(0, 20))
        if self.settings.get("auto_update_check"):
            self.auto_update_switch.select()
        else:
            self.auto_update_switch.deselect()

        ctk.CTkButton(
            updates_row,
            text="Check for Updates Now",
            width=200,
            height=34,
            command=self._on_check_updates_clicked,
            **theme.secondary_button_style()
        ).pack(side="left")

        # =====================================================
        # MANAGE TOOLS (show/hide)
        # =====================================================

        tools_frame = ctk.CTkFrame(self, **theme.panel_style())
        tools_frame.pack(fill="x", padx=theme.PAD_LG, pady=theme.PAD)

        self._section_title(tools_frame, "🧩  Manage Tools")

        ctk.CTkLabel(
            tools_frame,
            text="Uncheck a tool to hide it from the home screen. "
                 "Use the ✕ on a tool card to hide it quickly instead.",
            font=theme.font(12),
            text_color=theme.MUTED,
            anchor="w",
            justify="left"
        ).pack(fill="x", padx=theme.PAD_LG, pady=(0, 8))

        tools_list = ctk.CTkScrollableFrame(
            tools_frame,
            fg_color=theme.PANEL_2,
            corner_radius=theme.RADIUS_SM,
            height=180
        )
        tools_list.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD))
        self.tools_list_frame = tools_list

        self._refresh_tools_list()

        # =====================================================
        # ABOUT
        # =====================================================

        about_frame = ctk.CTkFrame(self, **theme.panel_style())
        about_frame.pack(fill="x", padx=theme.PAD_LG, pady=theme.PAD)

        self._section_title(about_frame, "ℹ️  About")

        identity_row = ctk.CTkFrame(about_frame, fg_color="transparent")
        identity_row.pack(fill="x", padx=theme.PAD_LG, pady=(4, theme.PAD))

        icon_image = self._load_app_icon()
        if icon_image is not None:
            ctk.CTkLabel(
                identity_row,
                image=icon_image,
                text=""
            ).pack(side="left", padx=(0, 14))

        text_col = ctk.CTkFrame(identity_row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            text_col,
            text="Z's Multi Tool",
            font=theme.font(18, "bold"),
            text_color=theme.TEXT
        ).pack(anchor="w")

        ctk.CTkLabel(
            text_col,
            text=f"v{APP_VERSION}  •  Built by Z",
            font=theme.font(12),
            text_color=theme.MUTED
        ).pack(anchor="w", pady=(2, 0))

        links_row = ctk.CTkFrame(about_frame, fg_color="transparent")
        links_row.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD))

        ctk.CTkButton(
            links_row,
            text="💬  Discord",
            width=160,
            height=34,
            command=self._open_discord,
            **theme.secondary_button_style()
        ).pack(side="left", padx=(0, 8))

        github_btn = ctk.CTkButton(
            links_row,
            text="🐙  GitHub" if GITHUB_URL else "🐙  GitHub (coming soon)",
            width=200,
            height=34,
            command=self._open_github,
            **theme.secondary_button_style()
        )
        github_btn.pack(side="left")
        if not GITHUB_URL:
            github_btn.configure(state="disabled")

    # =========================================================
    # HELPERS
    # =========================================================

    def _section_title(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=text,
            font=theme.font(16, "bold"),
            text_color=theme.TEXT
        ).pack(anchor="w", padx=theme.PAD_LG, pady=(theme.PAD, 6))

    def _load_app_icon(self, size=48):
        try:
            img = Image.open(paths.resource_path("assets", "icon.ico"))
            return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
        except Exception as e:
            print(f"[SettingsPage] Could not load app icon: {e}")
            return None

    def _open_discord(self):
        webbrowser.open(DISCORD_URL)

    def _open_github(self):
        if GITHUB_URL:
            webbrowser.open(GITHUB_URL)

    # =========================================================
    # SETTINGS ACTIONS
    # =========================================================

    def save_settings(self):
        self.settings.save()

    def reset_settings(self):
        self.settings.reset()

    def _on_toggle_auto_update(self):
        self.settings.set("auto_update_check", bool(self.auto_update_switch.get()))

    def _on_check_updates_clicked(self):
        updater.check_and_prompt()

    def _refresh_tools_list(self):
        """(Re)builds the Manage Tools checkbox list from current settings.
        Called on initial build and again via on_show(), since the hidden
        set can change elsewhere (e.g. the ✕ button on a catalog card)
        while this page isn't visible."""

        for w in self.tools_list_frame.winfo_children():
            w.destroy()
        self.tool_check_vars.clear()

        hidden = set(self.settings.get("hidden_tools") or [])
        all_tools = sorted(
            self.plugin_manager.get_tools(),
            key=lambda t: t.get("name", "")
        )

        if not all_tools:
            ctk.CTkLabel(
                self.tools_list_frame,
                text="No tools loaded yet.",
                font=theme.font(12),
                text_color=theme.MUTED
            ).pack(anchor="w", padx=10, pady=8)
            return

        for tool in all_tools:
            name = tool.get("name", "")
            var = ctk.BooleanVar(value=(name not in hidden))
            self.tool_check_vars[name] = var

            ctk.CTkCheckBox(
                self.tools_list_frame,
                text=name,
                variable=var,
                font=theme.font(13),
                text_color=theme.TEXT,
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
                checkmark_color="#0b0d10",
                command=lambda n=name, v=var: self._on_toggle_tool_visible(n, v)
            ).pack(anchor="w", padx=10, pady=4)

    def on_show(self):
        """Called by PageManager every time this page becomes visible."""
        self._refresh_tools_list()

    def _on_toggle_tool_visible(self, name, var):
        hidden = set(self.settings.get("hidden_tools") or [])
        if var.get():
            hidden.discard(name)
        else:
            hidden.add(name)
        self.settings.set("hidden_tools", list(hidden))

        catalog_page = self.manager.pages.get("catalog")
        if catalog_page:
            catalog_page.render()
