import customtkinter as ctk
import threading
from tkinter import filedialog, ttk
import os
import datetime

from .game_scanner import GameScanner
from .launcher import GameLauncher
from .save_manager import SaveManager
from .hub_settings_panel import GamingHubSettingsPanel, load_hub_settings
from .web_server import GamingHubWebServer
from core import theme

# ── Palette (shared app theme) ──────────────────────────────
# ─────────────────────────────────────────────────────────


def _name_color(name: str) -> str:
    """
    Maps a game name to one of a small set of muted neon hues
    via a stable hash — same name always gets the same color,
    regardless of scan order, AND across app restarts.

    Deliberately not using Python's built-in hash() here: string
    hashing is randomized per-process by default (PYTHONHASHSEED),
    so the same game would get a different color every time the app
    launched. Summing character codes instead is slower but always
    gives the same result for the same name, every run.
    """
    HUES = ["#4ea1ff", "#a78bfa", "#34d399", "#fb923c", "#f472b6"]
    total = sum(ord(c) for c in name)
    return HUES[total % len(HUES)]


class GamingHubUI(ctk.CTkFrame):

    MODULE_SETTINGS_TITLE = "Preferences"

    @staticmethod
    def build_module_settings(parent, manager):
        return GamingHubSettingsPanel(parent, manager)

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager
        self.scanner = GameScanner()
        self.launcher = GameLauncher()
        self.save_manager = SaveManager()
        self.games = []
        self.filtered_games = []
        self.hub_settings = load_hub_settings()

        # Lazily created + stashed on the manager (same pattern as Music
        # Player / YouTube Downloader) so it survives navigating away
        # from this page and phone requests can still launch games.
        self.web_server = getattr(manager, "gaming_hub_web_server", None) \
            or GamingHubWebServer()
        manager.gaming_hub_web_server = self.web_server

        self.build_ui()

        # Show last-known results instantly from cache (no scanning),
        # then optionally kick off a real rescan in the background if
        # auto_scan is enabled — the cached list gets replaced once
        # that finishes.
        cached_games = self.scanner.load_cache()
        if cached_games:
            self.display_games(cached_games)

        if self.hub_settings.get("auto_scan"):
            self.after(200, self.scan_games)

    # ── widget factories ─────────────────────────────────

    # MODIFIED: Renamed 'cmd' to 'command'
    def _btn(self, parent, text, command=None, width=120,
             fg=theme.ACCENT_GLOW, hover="#1a3a5c", text_color=theme.ACCENT, **kw):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, # Passed 'command'
            fg_color=fg, hover_color=hover, text_color=text_color,
            border_width=1, border_color=theme.ACCENT,
            corner_radius=6, font=(theme.FONT_FAMILY, 12, "bold"), **kw
        )

    # MODIFIED: Renamed 'cmd' to 'command'
    def _ghost_btn(self, parent, text, command=None, width=120, text_color=theme.MUTED, **kw):
        """Borderless dark button for secondary actions."""
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, # Passed 'command'
            fg_color=theme.PANEL_2, hover_color=theme.BORDER,
            text_color=text_color, border_width=0,
            corner_radius=6, font=(theme.FONT_FAMILY, 12), **kw
        )

    def _label(self, parent, text, size=13, weight="normal",
               color=theme.MUTED, **kw):
        return ctk.CTkLabel(
            parent, text=text, text_color=color,
            font=(theme.FONT_FAMILY, size, weight), **kw
        )

    def _section(self, parent, text):
        """Thin all-caps section label with a trailing rule."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkLabel(
            row, text=text.upper(),
            text_color=theme.FAINT, font=(theme.FONT_FAMILY, 9, "bold")
        ).pack(side="left")
        ctk.CTkFrame(row, height=1, fg_color=theme.BORDER).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    # ── layout ───────────────────────────────────────────

    def build_ui(self):
        self._build_header()
        self._build_tabs()

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=theme.PANEL,
                           corner_radius=0,
                           border_width=0)
        bar.pack(fill="x")

        # bottom border line
        ctk.CTkFrame(bar, height=1, fg_color=theme.BORDER).pack(
            fill="x", side="bottom")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=12)

        ctk.CTkLabel(
            inner, text="Gaming Hub",
            text_color=theme.TEXT, font=(theme.FONT_FAMILY, 20, "bold")
        ).pack(side="left")

        # right side group for game count, search, and scan button
        right_group = ctk.CTkFrame(inner, fg_color="transparent")
        right_group.pack(side="right")

        # Scan button
        self._btn(
            right_group, "⟳  Scan", command=self.scan_games, width=100
        ).pack(side="right")

        # Search entry
        self.search_entry = ctk.CTkEntry(
            right_group,
            width=220,
            placeholder_text="🔎 Search games...",
            fg_color=theme.PANEL_2,
            border_color=theme.BORDER,
            text_color=theme.TEXT,
            placeholder_text_color=theme.FAINT,
            font=(theme.FONT_FAMILY, 12)
        )
        self.search_entry.pack(
            side="right",
            padx=(0, 10)
        )
        self.search_entry.bind(
            "<KeyRelease>",
            self.filter_games
        )

        # Game count label
        self.game_count = ctk.CTkLabel(
            right_group, text="",
            text_color=theme.FAINT, font=(theme.FONT_FAMILY, 12)
        )
        self.game_count.pack(side="right", padx=(8, 0))


    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=theme.BG,
            segmented_button_fg_color=theme.PANEL,
            segmented_button_selected_color=theme.ACCENT_GLOW,
            segmented_button_selected_hover_color="#1a3a5c",
            segmented_button_unselected_color=theme.PANEL,
            segmented_button_unselected_hover_color=theme.PANEL_2,
            text_color=theme.MUTED,
            text_color_disabled=theme.FAINT,
            border_width=0,
        )
        self.tabs.pack(fill="both", expand=True)

        for name in ("Library", "Save Manager"):
            self.tabs.add(name)

        self._build_library_tab()
        self._build_save_tab()

    # ── Library tab ──────────────────────────────────────

    def _build_library_tab(self):
        tab = self.tabs.tab("Library")
        self.games_frame = ctk.CTkScrollableFrame(
            tab, fg_color=theme.BG,
            scrollbar_button_color=theme.BORDER,
            scrollbar_button_hover_color=theme.ACCENT_DIM
        )
        self.games_frame.pack(fill="both", expand=True, padx=12, pady=10)

    # ── Save Manager tab ─────────────────────────────────

    def _build_save_tab(self):
        tab = self.tabs.tab("Save Manager")

        panel = ctk.CTkFrame(tab, fg_color=theme.PANEL,
                             corner_radius=10, border_width=1,
                             border_color=theme.BORDER)
        panel.pack(fill="both", expand=True, padx=18, pady=14)

        self._label(panel, "Save Manager",
                    size=16, weight="bold", color=theme.TEXT).pack(
            anchor="w", padx=20, pady=(18, 2))
        self._label(panel, "Manage save file locations for your games.",
                    size=11, color=theme.FAINT).pack(anchor="w", padx=20)

        self._section(panel, "Select game")

        self.game_dropdown = ctk.CTkOptionMenu(
            panel, values=["No Games Found"],
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.BORDER,
            dropdown_fg_color=theme.PANEL,
            dropdown_hover_color=theme.PANEL_2,
            text_color=theme.TEXT,
            font=(theme.FONT_FAMILY, 13)
        )
        self.game_dropdown.pack(fill="x", padx=20, pady=(0, 4))
        self.game_dropdown.configure(
            command=lambda x: self.load_selected_game_path()
        )

        hide_row = ctk.CTkFrame(panel, fg_color="transparent")
        hide_row.pack(fill="x", padx=20, pady=(0, 4))

        self._ghost_btn(
            hide_row, "🙈 Hide from list",
            command=self.hide_save_game, width=140
        ).pack(side="left")

        self._ghost_btn(
            hide_row, "👁 Unhide a game…",
            command=self.open_unhide_menu, width=140
        ).pack(side="left", padx=(6, 0))

        self._ghost_btn(
            hide_row, "🧹 Clean up orphaned saves…",
            command=self.open_cleanup_menu, width=190
        ).pack(side="left", padx=(6, 0))

        self.unhide_row = ctk.CTkFrame(panel, fg_color="transparent")
        # packed on demand by open_unhide_menu(), not shown by default

        self.cleanup_row = ctk.CTkFrame(panel, fg_color="transparent")
        # packed on demand by open_cleanup_menu(), not shown by default

        self._section(panel, "Save folder")

        path_row = ctk.CTkFrame(panel, fg_color="transparent")
        path_row.pack(fill="x", padx=20, pady=(0, 8))

        self.save_path_entry = ctk.CTkEntry(
            path_row,
            placeholder_text="Path to save folder…",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT, placeholder_text_color=theme.FAINT,
            font=(theme.FONT_FAMILY, 12)
        )
        self.save_path_entry.pack(side="left", fill="x", expand=True)

        self._ghost_btn(
            path_row, "Browse", command=self.browse_save_folder, width=80
        ).pack(side="left", padx=(6, 0))

        self._btn(panel, "Save Path",
                  command=self.save_current_path).pack(
            fill="x", padx=20, pady=(0, 10))

        # ── Save Explorer ──────────────────────────────
        ctk.CTkLabel(
            panel,
            text="📂 Save Explorer",
            font=(theme.FONT_FAMILY, 18, "bold"),
            text_color=theme.TEXT
        ).pack(
            anchor="w",
            padx=20,
            pady=(5, 5)
        )

        tree_wrap = ctk.CTkFrame(panel, fg_color="transparent")
        tree_wrap.pack(fill="x", padx=20, pady=10)

        self.file_tree = ttk.Treeview(
            tree_wrap,
            show="tree",
            height=8
        )
        style = ttk.Style(panel)
        style.theme_use("clam")
        style.configure("Treeview",
                        background=theme.PANEL_2,
                        foreground=theme.TEXT,
                        fieldbackground=theme.PANEL_2,
                        bordercolor=theme.BORDER,
                        lightcolor=theme.BORDER,
                        darkcolor=theme.PANEL_2
                       )
        style.map('Treeview',
                  background=[('selected', theme.ACCENT_GLOW)],
                  foreground=[('selected', theme.ACCENT)]
                 )
        style.configure("Treeview.Heading",
                        font=(theme.FONT_FAMILY, 10, "bold"),
                        background=theme.PANEL_2,
                        foreground=theme.MUTED,
                        fieldbackground=theme.PANEL_2,
                        relief="flat"
                       )
        style.map("Treeview.Heading",
                  background=[('active', theme.BORDER)]
                 )

        style.configure("Save.Vertical.TScrollbar",
                        background=theme.PANEL_2,
                        troughcolor=theme.PANEL,
                        bordercolor=theme.BORDER,
                        arrowcolor=theme.MUTED,
                        lightcolor=theme.PANEL_2,
                        darkcolor=theme.PANEL_2,
                        relief="flat",
                        gripcount=0
                       )
        style.map("Save.Vertical.TScrollbar",
                  background=[('active', theme.BORDER), ('pressed', theme.BORDER)],
                  arrowcolor=[('active', theme.ACCENT)]
                 )

        tree_scroll = ttk.Scrollbar(
            tree_wrap, orient="vertical", command=self.file_tree.yview,
            style="Save.Vertical.TScrollbar"
        )
        self.file_tree.configure(yscrollcommand=tree_scroll.set)

        self.file_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.file_tree.bind(
            "<<TreeviewSelect>>",
            self.file_selected
        )

        self.file_info = ctk.CTkLabel(
            panel,
            text="No file selected.",
            text_color=theme.FAINT,
            font=(theme.FONT_FAMILY, 11)
        )
        self.file_info.pack(
            anchor="w",
            padx=20,
            pady=5
        )

        # ── Only two actions: Backup + Deny Write toggle ──
        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(5, 20))

        self._btn(
            btn_row, "💾  Backup", width=140,
            command=self.backup_selected_path
        ).pack(side="left", padx=(0, 8))

        self.deny_write_btn = self._ghost_btn(
            btn_row, "🔒 Deny Write", width=150,
            command=self.toggle_deny_write, text_color=theme.MUTED
        )
        self.deny_write_btn.pack(side="left")

    # ── scan ─────────────────────────────────────────────

    def scan_games(self):
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        self.hub_settings = load_hub_settings()
        drives = self.hub_settings.get("scan_drives")
        if drives is None:
            drives = GameScanner.detect_drives()
        games = self.scanner.scan(drives=drives)
        self.after(0, lambda: self.display_games(games))

    # ── display games ────────────────────────────────────

    def display_games(self, games):
        self.games = games
        # Scanner.scan() already wrote games_cache.json — refresh the
        # remote web server's in-memory copy so a phone request right
        # after a scan sees the new list without needing a restart.
        self.web_server.refresh_from_cache()
        count = len(games)
        self.game_count.configure(
            text=f"{count} {'game' if count == 1 else 'games'} found"
        )

        names = []
        for game in games:
            if not self.save_manager.is_blocked(game.name):
                names.append(game.name)
        names.sort(key=str.lower)

        if names:
            self.game_dropdown.configure(values=names)
            self.game_dropdown.set(names[0])
        else:
            self.game_dropdown.configure(values=["No Games Found"])
            self.game_dropdown.set("No Games Found")

        # CTkOptionMenu.set() above does NOT fire the dropdown's `command`
        # callback (that only fires on a manual user selection), so
        # without this the Save Manager tab would show the first game
        # selected but with no save path / file tree loaded until the
        # user manually reselects it. Load it explicitly here instead.
        self.load_selected_game_path()

        self.show_games(games)

    # ── game card ────────────────────────────────────────

    def _build_game_card(self, game):
        bar_color = _name_color(game.name)

        card = ctk.CTkFrame(
            self.games_frame, fg_color=theme.PANEL,
            corner_radius=8, border_width=1, border_color=theme.BORDER
        )
        card.pack(fill="x", padx=4, pady=5)

        ctk.CTkFrame(card, height=3, fg_color=bar_color,
                     corner_radius=0).pack(fill="x")

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=(10, 12))

        title_row = ctk.CTkFrame(body, fg_color="transparent")
        title_row.pack(fill="x")

        ctk.CTkLabel(
            title_row, text=game.name,
            text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14, "bold"),
            anchor="w"
        ).pack(side="left")

        launcher_tag = ctk.CTkLabel(
            title_row, text=game.launcher.upper(),
            text_color=theme.FAINT, font=(theme.FONT_FAMILY, 9, "bold"),
            fg_color=theme.PANEL_2, corner_radius=4,
            padx=7, pady=2
        )
        launcher_tag.pack(side="right")

        self._label(body, game.path, size=11,
                    color=theme.FAINT).pack(anchor="w", pady=(3, 10))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x")

        self._ghost_btn(
            btn_row, "📂  Folder", width=100,
            command=lambda g=game: self.open_game_folder(g)
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="Hide", width=70,
            fg_color=theme.PANEL_2, hover_color=theme.RED_DIM,
            text_color=theme.DANGER, border_width=0,
            corner_radius=6, font=(theme.FONT_FAMILY, 12),
            command=lambda g=game: self.hide_game(g)
        ).pack(side="left", padx=6)

        self._btn(
            btn_row, "▶  Launch", width=120,
            command=lambda g=game: self.launch_game(g)
        ).pack(side="right")

    # ── actions ──────────────────────────────────────────

    def launch_game(self, game):
        try:
            self.launcher.launch(game)
        except Exception as e:
            print(f"Launch failed: {e}")

    def browse_save_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.save_path_entry.delete(0, "end")
            self.save_path_entry.insert(0, folder)

    def save_current_path(self):
        game = self.game_dropdown.get()
        path = self.save_path_entry.get().strip().strip('"').strip("'")
        if not game or game == "No Games Found" or not path:
            return
        self.save_manager.set_path(game, path)
        # Reflect the cleaned-up value back into the field so what's
        # displayed matches what actually got saved.
        self.save_path_entry.delete(0, "end")
        self.save_path_entry.insert(0, self.save_manager.get_path(game))

    def load_selected_game_path(self):
        game = self.game_dropdown.get()
        self.save_path_entry.delete(0, "end")
        if game == "No Games Found":
            self.file_info.configure(text="No file selected.")
            self.file_tree.delete(*self.file_tree.get_children())
            self._refresh_deny_write_label()
            return
        path = self.save_manager.get_path(game)
        self.save_path_entry.insert(0, path)
        self.load_save_tree()

    def open_game_folder(self, game):
        if game.path and os.path.exists(game.path):
            try:
                os.startfile(game.path)
            except Exception as e:
                print(f"Failed to open folder for {game.name}: {e}")
        else:
            print(f"Game path not found or invalid: {game.path}")

    def hide_game(self, game):
        self.scanner.block_game(game.name)
        self._scan_thread()

    def hide_save_game(self):
        """Hides the currently selected game from the Save Manager
        dropdown only (the game still shows up fine in the Library tab -
        this doesn't touch the scanner's block list)."""
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        self.save_manager.block_game(game_name)
        self.display_games(self.games)

    def open_unhide_menu(self):
        """Shows a small dropdown of currently hidden games plus an
        Unhide button, so a game hidden by mistake can be brought back
        without having to remember its exact name. Calling this again
        while it's already open just closes it."""
        if self.unhide_row.winfo_ismapped():
            self.close_unhide_menu()
            return

        for widget in self.unhide_row.winfo_children():
            widget.destroy()

        hidden = self.save_manager.get_blocked_games()

        if not hidden:
            self._label(
                self.unhide_row, "No games are currently hidden.",
                size=11, color=theme.FAINT
            ).pack(side="left", padx=(0, 6))
            self._ghost_btn(
                self.unhide_row, "✕", width=32,
                command=self.close_unhide_menu
            ).pack(side="left")
            self.unhide_row.pack(fill="x", padx=20, pady=(0, 4))
            return

        self.unhide_dropdown = ctk.CTkOptionMenu(
            self.unhide_row, values=hidden,
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.BORDER,
            dropdown_fg_color=theme.PANEL,
            dropdown_hover_color=theme.PANEL_2,
            text_color=theme.TEXT,
            font=(theme.FONT_FAMILY, 13)
        )
        self.unhide_dropdown.pack(side="left", fill="x", expand=True)

        self._ghost_btn(
            self.unhide_row, "Unhide", width=90,
            command=self.unhide_selected_game
        ).pack(side="left", padx=(6, 0))

        self._ghost_btn(
            self.unhide_row, "✕", width=32,
            command=self.close_unhide_menu
        ).pack(side="left", padx=(6, 0))

        self.unhide_row.pack(fill="x", padx=20, pady=(0, 4))

    def close_unhide_menu(self):
        self.unhide_row.pack_forget()

    def unhide_selected_game(self):
        if not hasattr(self, "unhide_dropdown"):
            return

        game_name = self.unhide_dropdown.get()
        self.save_manager.unblock_game(game_name)
        self.display_games(self.games)
        self.close_unhide_menu()

    def open_cleanup_menu(self):
        """Shows a review list of save-path entries whose game name
        doesn't match anything from the last scan, so a stale entry can
        be removed deliberately. This is intentionally manual, not
        automatic - a game missing from a scan can just mean the
        scanner missed it (wrong drive, non-standard library folder,
        etc.), not that it's actually uninstalled. Calling this again
        while it's already open just closes it."""
        if self.cleanup_row.winfo_ismapped():
            self.close_cleanup_menu()
            return

        for widget in self.cleanup_row.winfo_children():
            widget.destroy()

        known_names = [g.name for g in self.games]
        orphaned = self.save_manager.get_orphaned_games(known_names)

        if not orphaned:
            row = ctk.CTkFrame(self.cleanup_row, fg_color="transparent")
            row.pack(fill="x")
            self._label(
                row, "No orphaned save paths right now.",
                size=11, color=theme.FAINT
            ).pack(side="left", padx=(0, 6))
            self._ghost_btn(
                row, "✕", width=32, command=self.close_cleanup_menu
            ).pack(side="left")
            self.cleanup_row.pack(fill="x", padx=20, pady=(0, 4))
            return

        self._label(
            self.cleanup_row,
            f"{len(orphaned)} saved path(s) don't match any game from the "
            "last scan. If a game you know is installed shows up here, "
            "rescan first - it likely just means the scan missed it.",
            size=11, color=theme.FAINT, wraplength=520, justify="left"
        ).pack(anchor="w", pady=(0, 6))

        control_row = ctk.CTkFrame(self.cleanup_row, fg_color="transparent")
        control_row.pack(fill="x")

        self.cleanup_dropdown = ctk.CTkOptionMenu(
            control_row, values=orphaned,
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.BORDER,
            dropdown_fg_color=theme.PANEL,
            dropdown_hover_color=theme.PANEL_2,
            text_color=theme.TEXT,
            font=(theme.FONT_FAMILY, 13)
        )
        self.cleanup_dropdown.pack(side="left", fill="x", expand=True)

        self._ghost_btn(
            control_row, "Remove", width=90,
            command=self.remove_orphaned_save_path
        ).pack(side="left", padx=(6, 0))

        self._ghost_btn(
            control_row, "✕", width=32,
            command=self.close_cleanup_menu
        ).pack(side="left", padx=(6, 0))

        self.cleanup_row.pack(fill="x", padx=20, pady=(0, 4))

    def close_cleanup_menu(self):
        self.cleanup_row.pack_forget()

    def remove_orphaned_save_path(self):
        if not hasattr(self, "cleanup_dropdown"):
            return

        game_name = self.cleanup_dropdown.get()
        self.save_manager.delete_path(game_name)

        if self.game_dropdown.get() == game_name:
            self.load_selected_game_path()

        self.open_cleanup_menu()  # re-open to refresh the list in place

    def filter_games(self, event=None):
        search = self.search_entry.get().lower()

        if not search:
            filtered = self.games
        else:
            filtered = []
            for game in self.games:
                if search in game.name.lower():
                    filtered.append(game)
        self.show_games(filtered)

    def show_games(self, games):
        for widget in self.games_frame.winfo_children():
            widget.destroy()

        if not games:
            wrap = ctk.CTkFrame(self.games_frame, fg_color=theme.PANEL,
                                corner_radius=10, border_width=1,
                                border_color=theme.BORDER)
            wrap.pack(fill="x", padx=4, pady=60)
            self._label(wrap, "No games found",
                        size=15, weight="bold", color=theme.MUTED).pack(pady=(28, 4))
            self._label(wrap, "Press  ⟳ Scan  to search your game libraries.",
                        size=11, color=theme.FAINT).pack(pady=(0, 28))
            return

        for game in games:
            self._build_game_card(game)

    def format_size(self, size):
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def file_selected(self, event=None):
        selected_items = self.file_tree.selection()
        if not selected_items:
            self.file_info.configure(text="No file selected.")
            self._refresh_deny_write_label()
            return

        item_id = selected_items[0]
        item = self.file_tree.item(item_id)
        values = item["values"]

        if not values:
            self.file_info.configure(text="No file selected.")
            self._refresh_deny_write_label()
            return

        path = values[0]

        lock_status = "🔒 Protected (read-only + ACL deny)" if self.save_manager.is_locked(path) else "🔓 Writable"

        if not os.path.isfile(path):
            self.file_info.configure(
                text=f"Selected: {os.path.basename(path)} (Folder) — {lock_status}"
            )
            self._refresh_deny_write_label()
            return

        size = self.format_size(os.path.getsize(path))
        modified = datetime.datetime.fromtimestamp(
            os.path.getmtime(path)
        )

        self.file_info.configure(
            text=(
                f"{os.path.basename(path)}\n"
                f"Size: {size} | {lock_status}\n"
                f"Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        )
        self._refresh_deny_write_label()

    def load_save_tree(self):
        game = self.game_dropdown.get()

        self.file_tree.delete(
            *self.file_tree.get_children()
        )

        if game == "No Games Found":
            self.file_info.configure(text="No game selected for Save Explorer.")
            self._refresh_deny_write_label()
            return

        try:
            data = self.save_manager.get_save_tree(game)

            if not data:
                self.file_info.configure(text="No save files found for this game.")
                self._refresh_deny_write_label()
                return

            for folder_path, files in data:
                parent_full_path = os.path.normpath(
                    os.path.join(self.save_manager.get_path(game), folder_path)
                )
                folder_lock = "🔒" if self.save_manager.is_locked(parent_full_path) else "📁"

                if folder_path == ".":
                    parent_id = self.file_tree.insert(
                        "",
                        "end",
                        text=f"{folder_lock} (Root Folder)",
                        values=(parent_full_path,),
                        open=True
                    )
                else:
                    parent_id = self.file_tree.insert(
                        "",
                        "end",
                        text=f"{folder_lock} {folder_path}",
                        values=(parent_full_path,),
                        open=True
                    )

                for file in files:
                    full_path = os.path.normpath(os.path.join(
                        self.save_manager.get_path(game),
                        folder_path,
                        file
                    ))
                    file_icon = "🔒" if self.save_manager.is_locked(full_path) else "📄"
                    self.file_tree.insert(
                        parent_id,
                        "end",
                        text=f"{file_icon} {file}",
                        values=(full_path,)
                    )
            self.file_info.configure(text="Select a file or folder above.")
            self._refresh_deny_write_label()

        except Exception as e:
            self.file_info.configure(text=f"Error loading save tree: {e}")
            print(f"Error loading save tree for {game}: {e}")

    def get_selected_path(self):
        selected = self.file_tree.selection()
        if not selected:
            return None

        item = self.file_tree.item(selected[0])
        values = item["values"]

        if not values:
            return None

        return values[0]

    def backup_selected_path(self):
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        # If something's highlighted in the Save Explorer, back up just
        # that file/folder. Otherwise fall back to the whole save folder.
        path = self.get_selected_path()

        try:
            backup = self.save_manager.backup_game(game_name, source_path=path)
            self.file_info.configure(text=f"Backed up to:\n{backup}")
        except Exception as e:
            self.file_info.configure(text=f"Backup failed: {e}")

    def toggle_deny_write(self):
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        # Same target rule as Backup: the highlighted item if there is
        # one, otherwise the whole configured save folder.
        path = self.get_selected_path() or self.save_manager.get_path(game_name)
        if not path:
            self.file_info.configure(text="No save folder set for this game.")
            return

        # lock_path()/unlock_path() walk every file in the folder AND
        # shell out to icacls with /T (recursive) - on a save folder with
        # a lot of files that can take a real chunk of time. Tkinter is
        # single-threaded, so running that directly on the UI thread
        # freezes the entire app (no redraws, no clicks) until it's
        # done. Doing the actual work in a background thread keeps the
        # UI responsive; only the final widget updates happen back on
        # the main thread via self.after, which is the thread-safe way
        # to touch Tkinter widgets from another thread.
        root_path = os.path.normpath(self.save_manager.get_path(game_name))
        self.deny_write_btn.configure(state="disabled")
        self.file_info.configure(text="Working…")
        threading.Thread(
            target=self._toggle_deny_write_thread,
            args=(path, root_path),
            daemon=True
        ).start()

    def _toggle_deny_write_thread(self, path, root_path):
        try:
            currently_locked = self.save_manager.is_locked(path)

            # Locking (deny-write) the ROOT save folder itself is
            # blocked - some games can't function at all with their
            # whole save directory write-denied, and it's confusing to
            # recover from. Unlocking the root is still allowed, in
            # case it's already locked from before this guard existed.
            # Locking/unlocking individual files or subfolders inside
            # it is unaffected.
            is_root = os.path.normpath(path) == root_path
            if is_root and not currently_locked:
                self.after(
                    0, self._toggle_deny_write_done,
                    "Can't deny write on the root save folder - select "
                    "a specific file or subfolder to lock instead.",
                    None, path
                )
                return

            if currently_locked:
                self.save_manager.unlock_path(path)
                message = f"🔓 {os.path.basename(path)} is now writable."
            else:
                self.save_manager.lock_path(path)
                message = f"🔒 {os.path.basename(path)} is now read-only (ACL deny applied)."
            self.after(0, self._toggle_deny_write_done, message, None, path)
        except Exception as e:
            self.after(0, self._toggle_deny_write_done, None, e, path)

    def _toggle_deny_write_done(self, message, error, path):
        self.deny_write_btn.configure(state="normal")
        if error is not None:
            self.file_info.configure(text=f"Failed: {error}")
        else:
            self.file_info.configure(text=message)
        # load_save_tree() rebuilds the tree from scratch (deletes and
        # re-inserts every item), so whatever was selected before this
        # action no longer exists afterward - reselect the same path
        # in the freshly-built tree so the highlight doesn't just
        # disappear.
        self.load_save_tree()
        self._select_tree_path(path)

    def _select_tree_path(self, target_path):
        if not target_path:
            return
        target_path = os.path.normpath(target_path)

        def _search(parent):
            for item_id in self.file_tree.get_children(parent):
                values = self.file_tree.item(item_id, "values")
                if values and os.path.normpath(values[0]) == target_path:
                    return item_id
                found = _search(item_id)
                if found:
                    return found
            return None

        match = _search("")
        if match:
            self.file_tree.selection_set(match)
            self.file_tree.focus(match)
            self.file_tree.see(match)

    def _refresh_deny_write_label(self):
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            self.deny_write_btn.configure(text="🔒 Deny Write")
            return

        path = self.get_selected_path() or self.save_manager.get_path(game_name)
        if not path:
            self.deny_write_btn.configure(text="🔒 Deny Write")
            return

        # is_locked() also walks the folder and can shell out to icacls -
        # same freeze risk as the toggle itself, so this runs in the
        # background too. The button briefly stays on its last known
        # label until the check finishes, which is harmless.
        threading.Thread(
            target=self._refresh_deny_write_label_thread,
            args=(path,),
            daemon=True
        ).start()

    def _refresh_deny_write_label_thread(self, path):
        try:
            locked = self.save_manager.is_locked(path)
        except Exception:
            locked = False
        self.after(0, self._refresh_deny_write_label_done, locked)

    def _refresh_deny_write_label_done(self, locked):
        if locked:
            self.deny_write_btn.configure(text="🔓 Allow Write")
        else:
            self.deny_write_btn.configure(text="🔒 Deny Write")