import customtkinter as ctk
import threading
import json
from tkinter import filedialog, ttk
import os
import datetime

from .game_scanner import GameScanner
from .launcher import GameLauncher
from .save_manager import SaveManager
from core import theme
from core import paths

# ── Palette (shared app theme) ──────────────────────────────
BG          = theme.BG           # base background
BG_PANEL    = theme.PANEL        # cards / panels
BG_RAISED   = theme.PANEL_2      # inputs, inner rows
BORDER      = theme.BORDER       # subtle borders
ACCENT      = theme.ACCENT       # blue accent
ACCENT_DIM  = theme.ACCENT_DIM   # hover
ACCENT_GLOW = theme.ACCENT_GLOW  # faint tinted fill
RED         = theme.DANGER       # danger / hide
RED_DIM     = theme.RED_DIM
TEXT_HI     = theme.TEXT         # primary text
TEXT_MID    = theme.MUTED        # secondary text
TEXT_LOW    = theme.FAINT        # disabled / placeholder
FONT        = theme.FONT_FAMILY
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

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager
        self.scanner = GameScanner()
        self.launcher = GameLauncher()
        self.save_manager = SaveManager()
        self.games = []
        self.filtered_games = []
        self.drive_checkboxes = {}
        self.hub_settings = self.load_hub_settings()
        self.build_ui()

        if self.hub_settings.get("auto_scan"):
            self.after(200, self.scan_games)

    # ── widget factories ─────────────────────────────────

    # MODIFIED: Renamed 'cmd' to 'command'
    def _btn(self, parent, text, command=None, width=120,
             fg=ACCENT_GLOW, hover="#1a3a5c", text_color=ACCENT, **kw):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, # Passed 'command'
            fg_color=fg, hover_color=hover, text_color=text_color,
            border_width=1, border_color=ACCENT,
            corner_radius=6, font=(FONT, 12, "bold"), **kw
        )

    # MODIFIED: Renamed 'cmd' to 'command'
    def _ghost_btn(self, parent, text, command=None, width=120, text_color=TEXT_MID, **kw):
        """Borderless dark button for secondary actions."""
        return ctk.CTkButton(
            parent, text=text, command=command, width=width, # Passed 'command'
            fg_color=BG_RAISED, hover_color=BORDER,
            text_color=text_color, border_width=0,
            corner_radius=6, font=(FONT, 12), **kw
        )

    def _label(self, parent, text, size=13, weight="normal",
               color=TEXT_MID, **kw):
        return ctk.CTkLabel(
            parent, text=text, text_color=color,
            font=(FONT, size, weight), **kw
        )

    def _section(self, parent, text):
        """Thin all-caps section label with a trailing rule."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkLabel(
            row, text=text.upper(),
            text_color=TEXT_LOW, font=(FONT, 9, "bold")
        ).pack(side="left")
        ctk.CTkFrame(row, height=1, fg_color=BORDER).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    # ── layout ───────────────────────────────────────────

    def build_ui(self):
        self._build_header()
        self._build_tabs()

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL,
                           corner_radius=0,
                           border_width=0)
        bar.pack(fill="x")

        # bottom border line
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(
            fill="x", side="bottom")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=12)

        ctk.CTkLabel(
            inner, text="Gaming Hub",
            text_color=TEXT_HI, font=(FONT, 20, "bold")
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
            fg_color=BG_RAISED,
            border_color=BORDER,
            text_color=TEXT_HI,
            placeholder_text_color=TEXT_LOW,
            font=(FONT, 12)
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
            text_color=TEXT_LOW, font=(FONT, 12)
        )
        self.game_count.pack(side="right", padx=(8, 0))


    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=BG,
            segmented_button_fg_color=BG_PANEL,
            segmented_button_selected_color=ACCENT_GLOW,
            segmented_button_selected_hover_color="#1a3a5c",
            segmented_button_unselected_color=BG_PANEL,
            segmented_button_unselected_hover_color=BG_RAISED,
            text_color=TEXT_MID,
            text_color_disabled=TEXT_LOW,
            border_width=0,
        )
        self.tabs.pack(fill="both", expand=True)

        for name in ("Library", "Save Manager", "Settings"):
            self.tabs.add(name)

        self._build_library_tab()
        self._build_save_tab()
        self._build_settings_tab()

    # ── Library tab ──────────────────────────────────────

    def _build_library_tab(self):
        tab = self.tabs.tab("Library")
        self.games_frame = ctk.CTkScrollableFrame(
            tab, fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT_DIM
        )
        self.games_frame.pack(fill="both", expand=True, padx=12, pady=10)

    # ── Save Manager tab ─────────────────────────────────

    def _build_save_tab(self):
        tab = self.tabs.tab("Save Manager")

        panel = ctk.CTkFrame(tab, fg_color=BG_PANEL,
                             corner_radius=10, border_width=1,
                             border_color=BORDER)
        panel.pack(fill="both", expand=True, padx=18, pady=14)

        self._label(panel, "Save Manager",
                    size=16, weight="bold", color=TEXT_HI).pack(
            anchor="w", padx=20, pady=(18, 2))
        self._label(panel, "Manage save file locations for your games.",
                    size=11, color=TEXT_LOW).pack(anchor="w", padx=20)

        self._section(panel, "Select game")

        self.game_dropdown = ctk.CTkOptionMenu(
            panel, values=["No Games Found"],
            fg_color=BG_RAISED, button_color=BG_RAISED,
            button_hover_color=BORDER,
            dropdown_fg_color=BG_PANEL,
            dropdown_hover_color=BG_RAISED,
            text_color=TEXT_HI,
            font=(FONT, 13)
        )
        self.game_dropdown.pack(fill="x", padx=20, pady=(0, 4))
        self.game_dropdown.configure(
            command=lambda x: self.load_selected_game_path()
        )

        self._section(panel, "Save folder")

        path_row = ctk.CTkFrame(panel, fg_color="transparent")
        path_row.pack(fill="x", padx=20, pady=(0, 8))

        self.save_path_entry = ctk.CTkEntry(
            path_row,
            placeholder_text="Path to save folder…",
            fg_color=BG_RAISED, border_color=BORDER,
            text_color=TEXT_HI, placeholder_text_color=TEXT_LOW,
            font=(FONT, 12)
        )
        self.save_path_entry.pack(side="left", fill="x", expand=True)

        self._ghost_btn(
            path_row, "Browse", command=self.browse_save_folder, width=80
        ).pack(side="left", padx=(6, 0))

        self._btn(panel, "Save Path",
                  command=self.save_current_path).pack(
            fill="x", padx=20, pady=(0, 4))
        
        self._ghost_btn(panel, "🚫 Hide From Save Manager",
                        command=self.block_save_game, text_color=RED).pack(
            fill="x", padx=20, pady=(4, 10))

        # STEP 2: Add Save Explorer Label
        ctk.CTkLabel(
            panel,
            text="📂 Save Explorer",
            font=(FONT, 18, "bold"),
            text_color=TEXT_HI
        ).pack(
            anchor="w",
            padx=20,
            pady=(15, 5)
        )

        # STEP 2: Add Treeview for Save Explorer
        self.file_tree = ttk.Treeview(
            panel,
            show="tree headings"
        )
        style = ttk.Style(panel)
        style.theme_use("clam")
        style.configure("Treeview",
                        background=BG_RAISED,
                        foreground=TEXT_HI,
                        fieldbackground=BG_RAISED,
                        bordercolor=BORDER,
                        lightcolor=BORDER,
                        darkcolor=BG_RAISED
                       )
        style.map('Treeview',
                  background=[('selected', ACCENT_GLOW)],
                  foreground=[('selected', ACCENT)]
                 )
        style.configure("Treeview.Heading",
                        font=(FONT, 10, "bold"),
                        background=BG_RAISED,
                        foreground=TEXT_MID,
                        fieldbackground=BG_RAISED,
                        relief="flat"
                       )
        style.map("Treeview.Heading",
                  background=[('active', BORDER)]
                 )

        self.file_tree.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=10
        )
        # STEP 4: Detect Selection
        self.file_tree.bind(
            "<<TreeviewSelect>>",
            self.file_selected
        )
        
        # STEP 3: Add File Information Panel
        self.file_info = ctk.CTkLabel(
            panel,
            text="No file selected.",
            text_color=TEXT_LOW,
            font=(FONT, 11)
        )
        self.file_info.pack(
            anchor="w",
            padx=20,
            pady=5
        )

        # STEP 12: Add new buttons under file_info
        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.pack(
            fill="x",
            padx=20,
            pady=5
        )

        # Using _ghost_btn for consistent styling
        self._ghost_btn(
            buttons,
            "📂 Open File",
            command=self.open_selected_file,
            width=100
        ).pack(
            side="left",
            padx=(0, 5)
        )

        self._ghost_btn(
            buttons,
            "📁 Open Folder",
            command=self.open_selected_folder,
            width=120
        ).pack(
            side="left",
            padx=5
        )

        self._ghost_btn(
            buttons,
            "🗑 Delete",
            command=self.delete_selected_file,
            width=80,
            text_color=RED
        ).pack(
            side="left",
            padx=5
        )


        self._section(panel, "Actions")

        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 20))

        self._ghost_btn(btn_row, "📂  Open Folder", width=130,
                        command=self.open_selected_save_folder).pack(
            side="left", padx=(0, 8))

        self._btn(btn_row, "💾  Backup", width=110,
                  command=self.backup_selected_game).pack(
            side="left", padx=(0, 8))
            
        self._ghost_btn(btn_row, "🔒 Protect Saves", width=110,
                        command=self.lock_selected_game, text_color=TEXT_MID).pack(
            side="left", padx=(0, 8))

        self._ghost_btn(btn_row, "🔓 Unprotect Saves", width=110,
                        command=self.unlock_selected_game, text_color=TEXT_MID).pack(
            side="left", padx=(0, 8))


        self._ghost_btn(btn_row, "♻  Restore", width=110).pack(side="left")

    # ── Settings tab ─────────────────────────────────────

    def _build_settings_tab(self):
        tab = self.tabs.tab("Settings")

        panel = ctk.CTkFrame(tab, fg_color=BG_PANEL,
                             corner_radius=10, border_width=1,
                             border_color=BORDER)
        panel.pack(fill="both", expand=True, padx=18, pady=14)

        self._label(panel, "Settings",
                    size=16, weight="bold", color=TEXT_HI).pack(
            anchor="w", padx=20, pady=(18, 2))
        self._label(panel, "Configure your Gaming Hub preferences.",
                    size=11, color=TEXT_LOW).pack(anchor="w", padx=20)

        self._section(panel, "General")

        for attr, title, sub in [
            ("auto_scan",   "Scan on startup",
             "Find installed games automatically when the app opens"),
            ("auto_backup", "Auto-backup saves",
             "Backup save files automatically when they change"),
        ]:
            row = ctk.CTkFrame(panel, fg_color=BG_RAISED,
                               corner_radius=8, border_width=1,
                               border_color=BORDER)
            row.pack(fill="x", padx=20, pady=4)

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True, padx=14, pady=10)

            self._label(text_col, title, size=13,
                        weight="bold", color=TEXT_HI).pack(anchor="w")
            self._label(text_col, sub, size=11,
                        color=TEXT_LOW).pack(anchor="w")

            cb = ctk.CTkCheckBox(
                row, text="",
                fg_color=ACCENT_GLOW, hover_color="#1a3a5c",
                checkmark_color=ACCENT, border_color=BORDER,
                width=24,
                command=lambda a=attr: self._on_toggle_setting(a)
            )
            cb.pack(side="right", padx=16)
            setattr(self, attr, cb)

            if self.hub_settings.get(attr):
                cb.select()

        # ── Drives to Scan ────────────────────────────────

        self._section(panel, "Drives to Scan")
        self._label(
            panel,
            "Steam and Epic can be installed on any drive. Uncheck a "
            "drive to skip it — useful for slow external/network drives.",
            size=11, color=TEXT_LOW
        ).pack(anchor="w", padx=20, pady=(0, 6))

        drives = GameScanner.detect_drives()
        selected = set(self.hub_settings.get("scan_drives") or drives)

        drives_row = ctk.CTkFrame(panel, fg_color="transparent")
        drives_row.pack(fill="x", padx=20, pady=(0, 4))

        for drive in drives:
            chip = ctk.CTkFrame(drives_row, fg_color=BG_RAISED,
                                 corner_radius=8, border_width=1,
                                 border_color=BORDER)
            chip.pack(side="left", padx=(0, 8), pady=4)

            cb = ctk.CTkCheckBox(
                chip, text=drive,
                fg_color=ACCENT_GLOW, hover_color="#1a3a5c",
                checkmark_color=ACCENT, border_color=BORDER,
                font=(FONT, 12, "bold"), text_color=TEXT_HI,
                width=24,
                command=lambda d=drive: self._on_toggle_drive(d)
            )
            cb.pack(padx=10, pady=8)

            if drive in selected:
                cb.select()

            self.drive_checkboxes[drive] = cb

        if not drives:
            self._label(panel, "No drives detected.",
                        size=11, color=TEXT_LOW).pack(anchor="w", padx=20)

    # ── hub settings (persisted to AppData) ──────────────

    HUB_SETTINGS_FILE = paths.data_path("gaming_hub", "hub_settings.json")

    def load_hub_settings(self):
        detected = GameScanner.detect_drives()
        defaults = {
            "auto_scan": False,
            "auto_backup": False,
            "scan_drives": detected,
        }
        try:
            with open(self.HUB_SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            saved = {}

        merged = {**defaults, **saved}

        # If a drive wasn't known about last time (e.g. a new external HDD),
        # default it to checked so scanning "just works" without the user
        # having to dig back into Settings.
        known = set(merged.get("scan_drives") or [])
        for drive in detected:
            if drive not in known and drive not in (saved.get("_seen_drives") or []):
                merged["scan_drives"].append(drive)

        merged["_seen_drives"] = detected
        return merged

    def save_hub_settings(self):
        try:
            with open(self.HUB_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.hub_settings, f, indent=4)
        except Exception as e:
            print(f"[GamingHub] Failed saving settings: {e}")

    def _on_toggle_setting(self, attr):
        cb = getattr(self, attr)
        self.hub_settings[attr] = bool(cb.get())
        self.save_hub_settings()

    def _on_toggle_drive(self, drive):
        cb = self.drive_checkboxes[drive]
        drives = set(self.hub_settings.get("scan_drives") or [])
        if cb.get():
            drives.add(drive)
        else:
            drives.discard(drive)
        self.hub_settings["scan_drives"] = sorted(drives)
        self.save_hub_settings()

    # ── scan ─────────────────────────────────────────────

    def scan_games(self):
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        drives = self.hub_settings.get("scan_drives")
        if drives is None:
            drives = GameScanner.detect_drives()
        games = self.scanner.scan(drives=drives)
        self.after(0, lambda: self.display_games(games))

    # ── display games ────────────────────────────────────

    def display_games(self, games):
        self.games = games
        count = len(games)
        self.game_count.configure(
            text=f"{count} {'game' if count == 1 else 'games'} found"
        )

        names = []
        for game in games:
            if not self.save_manager.is_blocked(game.name):
                names.append(game.name)

        if names:
            self.game_dropdown.configure(values=names)
            self.game_dropdown.set(names[0])
        else:
            self.game_dropdown.configure(values=["No Games Found"])
            self.game_dropdown.set("No Games Found")

        self.show_games(games)

    # ── game card ────────────────────────────────────────

    def _build_game_card(self, game):
        bar_color = _name_color(game.name)

        card = ctk.CTkFrame(
            self.games_frame, fg_color=BG_PANEL,
            corner_radius=8, border_width=1, border_color=BORDER
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
            text_color=TEXT_HI, font=(FONT, 14, "bold"),
            anchor="w"
        ).pack(side="left")

        launcher_tag = ctk.CTkLabel(
            title_row, text=game.launcher.upper(),
            text_color=TEXT_LOW, font=(FONT, 9, "bold"),
            fg_color=BG_RAISED, corner_radius=4,
            padx=7, pady=2
        )
        launcher_tag.pack(side="right")

        self._label(body, game.path, size=11,
                    color=TEXT_LOW).pack(anchor="w", pady=(3, 10))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x")

        self._ghost_btn(
            btn_row, "📂  Folder", width=100,
            command=lambda g=game: self.open_game_folder(g)
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="Hide", width=70,
            fg_color=BG_RAISED, hover_color=RED_DIM,
            text_color=RED, border_width=0,
            corner_radius=6, font=(FONT, 12),
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
        path = self.save_path_entry.get().strip()
        if not game or game == "No Games Found" or not path:
            return
        self.save_manager.set_path(game, path)

    def load_selected_game_path(self):
        game = self.game_dropdown.get()
        self.save_path_entry.delete(0, "end")
        if game == "No Games Found":
            self.file_info.configure(text="No file selected.")
            self.file_tree.delete(*self.file_tree.get_children())
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

    def open_selected_save_folder(self):
        """Opens the save folder for the currently selected game in the dropdown."""
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        save_path = self.save_path_entry.get().strip()
        if not save_path:
             save_path = self.save_manager.get_path(game_name)

        if save_path and os.path.exists(save_path):
            try:
                os.startfile(save_path)
            except Exception as e:
                print(f"Failed to open save folder for {game_name} at {save_path}: {e}")
        else:
            print(f"Save path not found or invalid for {game_name}: {save_path}")


    def hide_game(self, game):
        self.scanner.block_game(game.name)
        self._scan_thread()

    def block_save_game(self):
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        self.save_manager.block_game(game_name)
        self.display_games(self.games)

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
            wrap = ctk.CTkFrame(self.games_frame, fg_color=BG_PANEL,
                                corner_radius=10, border_width=1,
                                border_color=BORDER)
            wrap.pack(fill="x", padx=4, pady=60)
            self._label(wrap, "No games found",
                        size=15, weight="bold", color=TEXT_MID).pack(pady=(28, 4))
            self._label(wrap, "Press  ⟳ Scan  to search your Steam and Epic libraries.",
                        size=11, color=TEXT_LOW).pack(pady=(0, 28))
            return

        for game in games:
            self._build_game_card(game)

    def backup_selected_game(self):

        game_name = self.game_dropdown.get()

        if game_name == "No Games Found":

            return

        try:

            backup = self.save_manager.backup_game(
                game_name
            )

            print(
                f"Backup created: {backup}"
            )

        except ValueError as e:
            print(f"Backup failed: {e}")
        except Exception as e:
            print(f"An unexpected error occurred during backup: {e}")

    def lock_selected_game(self):
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        try:
            self.save_manager.lock_saves(game_name)
            print(f"Saves for {game_name} protected (read-only).")
        except Exception as e:
            print(f"Failed to protect saves for {game_name}: {e}")

    def unlock_selected_game(self):
        game_name = self.game_dropdown.get()
        if game_name == "No Games Found":
            return

        try:
            self.save_manager.unlock_saves(game_name)
            print(f"Saves for {game_name} unprotected (read-write).")
        except Exception as e:
            print(f"Failed to unprotect saves for {game_name}: {e}")

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
            return

        item_id = selected_items[0]
        item = self.file_tree.item(item_id)
        values = item["values"]

        if not values:
            self.file_info.configure(text="No file selected.")
            return

        path = values[0]

        if not os.path.isfile(path):
            self.file_info.configure(text=f"Selected: {os.path.basename(path)} (Folder)")
            return

        size = self.format_size(os.path.getsize(path))
        modified = datetime.datetime.fromtimestamp(
            os.path.getmtime(path)
        )

        self.file_info.configure(
            text=(
                f"{os.path.basename(path)}\n"
                f"Size: {size}\n"
                f"Modified: {modified.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        )

    def load_save_tree(self):
        game = self.game_dropdown.get()

        self.file_tree.delete(
            *self.file_tree.get_children()
        )

        if game == "No Games Found":
            self.file_info.configure(text="No game selected for Save Explorer.")
            return

        try:
            data = self.save_manager.get_save_tree(game)

            if not data:
                self.file_info.configure(text="No save files found for this game.")
                return

            for folder_path, files in data:
                parent_full_path = os.path.join(self.save_manager.get_path(game), folder_path)
                
                if folder_path == ".":
                    parent_id = self.file_tree.insert(
                        "",
                        "end",
                        text="📁 (Root Folder)",
                        values=(parent_full_path,)
                    )
                else:
                    parent_id = self.file_tree.insert(
                        "",
                        "end",
                        text=f"📁 {folder_path}",
                        values=(parent_full_path,)
                    )

                for file in files:
                    full_path = os.path.join(
                        self.save_manager.get_path(game),
                        folder_path,
                        file
                    )
                    self.file_tree.insert(
                        parent_id,
                        "end",
                        text=f"📄 {file}",
                        values=(full_path,)
                    )
            self.file_info.configure(text="Select a file or folder above.")

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

    def open_selected_file(self):
        path = self.get_selected_path()
        if not path:
            return
        
        if os.path.isfile(path):
            try:
                os.startfile(path)
            except Exception as e:
                print(f"Failed to open file {path}: {e}")
        else:
            print(f"Path is not a file: {path}")

    def open_selected_folder(self):
        path = self.get_selected_path()
        if not path:
            return
        
        if os.path.isdir(path):
            folder_to_open = path
        else:
            folder_to_open = os.path.dirname(path)

        if os.path.exists(folder_to_open):
            try:
                os.startfile(folder_to_open)
            except Exception as e:
                print(f"Failed to open folder {folder_to_open}: {e}")
        else:
            print(f"Folder not found: {folder_to_open}")

    def delete_selected_file(self):
        path = self.get_selected_path()
        if not path:
            return

        if not os.path.exists(path):
            print(f"File or folder does not exist: {path}")
            self.load_save_tree()
            return

        try:
            if os.path.isfile(path):
                os.remove(path)
                print(f"Deleted file: {path}")
            elif os.path.isdir(path):
                shutil.rmtree(path)
                print(f"Deleted folder: {path}")
            
            self.load_save_tree()
            self.file_info.configure(text="No file selected.")
        except Exception as e:
            print(f"Failed to delete {path}: {e}")