"""Gaming Hub module settings — preferences + remote access (⚙ gear menu)."""

import json

import customtkinter as ctk
from tkinter import filedialog

from .game_scanner import GameScanner
from .save_manager import SaveManager
from core import paths
from core import theme
from core.remote_access_panel import RemoteAccessPanel
from core.services.tailscale_service import APP_HTTPS_PORTS


HUB_SETTINGS_FILE = paths.data_path("gaming_hub", "hub_settings.json")


def load_hub_settings():
    detected = GameScanner.detect_drives()
    defaults = {
        "auto_scan": False,
        "auto_backup": False,
        "scan_drives": detected,
    }
    try:
        with open(HUB_SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        saved = {}

    merged = {**defaults, **saved}

    known = set(merged.get("scan_drives") or [])
    for drive in detected:
        if drive not in known and drive not in (saved.get("_seen_drives") or []):
            merged["scan_drives"].append(drive)

    merged["_seen_drives"] = detected
    return merged


def save_hub_settings(hub_settings):
    try:
        with open(HUB_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(hub_settings, f, indent=4)
    except Exception as e:
        print(f"[GamingHub] Failed saving settings: {e}")


class GamingHubSettingsPanel(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self.save_manager = SaveManager()
        self.hub_settings = load_hub_settings()
        self.drive_checkboxes = {}

        self._build_preferences(self)
        self._build_remote_access(self)

    def _label(self, parent, text, size=13, weight="normal", color=theme.MUTED, **kw):
        return ctk.CTkLabel(
            parent, text=text, text_color=color,
            font=(theme.FONT_FAMILY, size, weight), **kw
        )

    def _section(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(14, 4))
        ctk.CTkLabel(
            row, text=text.upper(),
            text_color=theme.FAINT, font=(theme.FONT_FAMILY, 9, "bold")
        ).pack(side="left")
        ctk.CTkFrame(row, height=1, fg_color=theme.BORDER).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    def _btn(self, parent, text, command=None, width=120, **kw):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.ACCENT_GLOW, hover_color="#1a3a5c", text_color=theme.ACCENT,
            border_width=1, border_color=theme.ACCENT,
            corner_radius=6, font=(theme.FONT_FAMILY, 12, "bold"), **kw
        )

    def _ghost_btn(self, parent, text, command=None, width=120, **kw):
        return ctk.CTkButton(
            parent, text=text, command=command, width=width,
            fg_color=theme.PANEL_2, hover_color=theme.BORDER,
            text_color=theme.MUTED, border_width=0,
            corner_radius=6, font=(theme.FONT_FAMILY, 12), **kw
        )

    def _build_preferences(self, parent):
        panel = ctk.CTkFrame(
            parent, fg_color=theme.PANEL,
            corner_radius=10, border_width=1, border_color=theme.BORDER,
        )
        panel.pack(fill="x", pady=(0, 12))

        self._label(panel, "Preferences", size=16, weight="bold", color=theme.TEXT).pack(
            anchor="w", padx=16, pady=(16, 2))
        self._label(panel, "Configure scan behavior and save backups.",
                    size=11, color=theme.FAINT).pack(anchor="w", padx=16)

        self._section(panel, "General")

        for attr, title, sub in [
            ("auto_scan", "Scan on startup",
             "Find installed games automatically when the app opens"),
            ("auto_backup", "Auto-backup saves",
             "Backup save files automatically when they change"),
        ]:
            row = ctk.CTkFrame(panel, fg_color=theme.PANEL_2,
                               corner_radius=8, border_width=1,
                               border_color=theme.BORDER)
            row.pack(fill="x", padx=16, pady=4)

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True, padx=14, pady=10)

            self._label(text_col, title, size=13, weight="bold", color=theme.TEXT).pack(anchor="w")
            self._label(text_col, sub, size=11, color=theme.FAINT).pack(anchor="w")

            cb = ctk.CTkCheckBox(
                row, text="",
                fg_color=theme.ACCENT_GLOW, hover_color="#1a3a5c",
                checkmark_color=theme.ACCENT, border_color=theme.BORDER,
                width=24,
                command=lambda a=attr: self._on_toggle_setting(a),
            )
            cb.pack(side="right", padx=16)
            setattr(self, attr, cb)

            if self.hub_settings.get(attr):
                cb.select()

        self._section(panel, "Drives to Scan")
        self._label(
            panel,
            "Steam and GOG can be installed on any drive, so this filters "
            "scanning for both of them. Epic, Ubisoft Connect, and "
            "EA/Origin track installs centrally and are always scanned "
            "regardless of which drives are checked here.",
            size=11, color=theme.FAINT, wraplength=640, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 6))

        drives = GameScanner.detect_drives()
        selected = set(self.hub_settings.get("scan_drives") or drives)

        drives_row = ctk.CTkFrame(panel, fg_color="transparent")
        drives_row.pack(fill="x", padx=16, pady=(0, 4))

        for drive in drives:
            chip = ctk.CTkFrame(drives_row, fg_color=theme.PANEL_2,
                                 corner_radius=8, border_width=1,
                                 border_color=theme.BORDER)
            chip.pack(side="left", padx=(0, 8), pady=4)

            cb = ctk.CTkCheckBox(
                chip, text=drive,
                fg_color=theme.ACCENT_GLOW, hover_color="#1a3a5c",
                checkmark_color=theme.ACCENT, border_color=theme.BORDER,
                font=(theme.FONT_FAMILY, 12, "bold"), text_color=theme.TEXT,
                width=24,
                command=lambda d=drive: self._on_toggle_drive(d),
            )
            cb.pack(padx=10, pady=8)

            if drive in selected:
                cb.select()

            self.drive_checkboxes[drive] = cb

        if not drives:
            self._label(panel, "No drives detected.",
                        size=11, color=theme.FAINT).pack(anchor="w", padx=16)

        self._section(panel, "Backup Output Folder")
        self._label(
            panel,
            "Where game save backups are written. Leave blank to use "
            "the default app data folder.",
            size=11, color=theme.FAINT, wraplength=640, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 6))

        backup_row = ctk.CTkFrame(panel, fg_color="transparent")
        backup_row.pack(fill="x", padx=16, pady=(0, 14))

        self.backup_folder_entry = ctk.CTkEntry(
            backup_row,
            placeholder_text="Default app data folder",
            fg_color=theme.PANEL_2, border_color=theme.BORDER,
            text_color=theme.TEXT, placeholder_text_color=theme.FAINT,
            font=(theme.FONT_FAMILY, 12),
        )
        self.backup_folder_entry.pack(side="left", fill="x", expand=True)
        current = self.save_manager.settings.get("backup_folder", "")
        if current:
            self.backup_folder_entry.insert(0, current)

        self._ghost_btn(
            backup_row, "Browse", command=self.browse_backup_folder, width=80
        ).pack(side="left", padx=(6, 0))

        self._btn(
            panel, "Save Backup Folder",
            command=self.save_backup_folder_setting,
        ).pack(fill="x", padx=16, pady=(0, 16))

    def _build_remote_access(self, parent):
        self._section(parent, "Remote access")

        web_server = getattr(self.manager, "gaming_hub_web_server", None)
        if web_server is None:
            from .web_server import GamingHubWebServer
            web_server = GamingHubWebServer()
            self.manager.gaming_hub_web_server = web_server

        RemoteAccessPanel(
            parent,
            manager=self.manager,
            app_key="games",
            web_server=web_server,
            port=APP_HTTPS_PORTS["games"],
        ).pack(fill="x", pady=(0, 8))

    def browse_backup_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.backup_folder_entry.delete(0, "end")
            self.backup_folder_entry.insert(0, folder)

    def save_backup_folder_setting(self):
        folder = self.backup_folder_entry.get().strip()
        self.save_manager.set_backup_folder(folder)

    def _on_toggle_setting(self, attr):
        cb = getattr(self, attr)
        self.hub_settings[attr] = bool(cb.get())
        save_hub_settings(self.hub_settings)

    def _on_toggle_drive(self, drive):
        cb = self.drive_checkboxes[drive]
        drives = set(self.hub_settings.get("scan_drives") or [])
        if cb.get():
            drives.add(drive)
        else:
            drives.discard(drive)
        self.hub_settings["scan_drives"] = sorted(drives)
        save_hub_settings(self.hub_settings)