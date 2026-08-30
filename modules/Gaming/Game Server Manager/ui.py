"""
Game Server Manager — universal UI.

Layout:
  Left  — server list (status, game, name, players)
  Right — selected server dashboard with tabs:
          Overview, Console, Players, Files, Mods, Backups, Config, Logs

Minecraft Java/Bedrock retain their full download/install/EULA flow inside
the Config tab. All other games use adapter-driven setup hints and fields.
"""

from __future__ import annotations

import queue
import re
import shutil
import threading
import subprocess
import time
import uuid
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk
import psutil

from . import backend as mc
from . import dialogs
from .game_picker import GamePicker
from .adapters import get_adapter, game_choices
from .adapters.minecraft_loaders import get_loader_versions, loader_choices, loader_name, detect_minecraft_version, create_install_worker as create_minecraft_loader_install_worker
from .adapters.java_runtimes import discover_java_runtimes, required_java_major, recommended_runtime, compatibility_text
from .adapters.minecraft_modpacks import (
    search_modpacks, get_project_files, get_latest_project_files, get_file, create_curseforge_download_worker, create_modpack_install_worker, create_modpack_loader_repair_worker, infer_profile_loader,
    peek_manifest_minecraft_version, detect_loader, scan_modpack_version_conflicts, quarantine_modpack_conflicts, replace_with_compatible_curseforge_mod, build_missing_mod_entry,
)
from .adapters.minecraft_client import prepare_client, launch_minecraft_direct, open_minecraft_launcher, ModpackDownloadError, estimate_memory_mb, get_last_heap_probe_notes
from .adapters.minecraft_auth import load_auth, sign_in as minecraft_sign_in, logout as minecraft_logout
from .adapters.install import (
    create_minecraft_bedrock_install_worker,
    create_minecraft_java_install_worker,
    create_steamcmd_install_worker,
    find_steamcmd,
)
from .core.console_buffer import ConsoleBuffer
from .core.module_prefs import TERMINAL_SCHEMES, load_prefs, scheme_colors
from .core.events import DownloadEvent, ServerEvent
from .core.process import ServerProcess
from .core.ytdlp import ensure_ytdlp
from .core.settings import (
    align_terraria_server_folder,
    default_server_folder_for,
    load_servers,
    save_servers,
    load_manager_settings,
    save_manager_settings,
)
from core import theme as t
from core.module_shell import find_module_shell
from core.theme import apply_theme_tokens
from . import ui_layout as st
from .icons import server_icon_frame
from .ui_features import GameServerFeaturesMixin

POLL_MS = 80
LIST_POLL_MS = 250
MONITOR_POLL_MS = 2000
MAX_CONSOLE_LINES = 2000
IP_MASK = "•" * 13

_DEFAULT_CONFIGS: dict[str, dict] = {
    "minecraft_java": {"config_version": 2, "loader": "vanilla", "loader_version": "", "minecraft_version": "", "installed_version": "", "verified_version": "", "version_status": "unknown", "version_checked_at": "", "min_mb": 1024, "max_mb": 2048, "java_path": "java", "auto_start": False, "auto_start_confirmed": False},
    "minecraft_bedrock": {"bedrock_channel": "stable"},
    "satisfactory": {
        "port": "7777", "reliable_port": "8888", "server_name": "Satisfactory Server",
        "admin_password": "", "api_token": "", "extra_args": "",
    },
    "valheim": {
        "server_name": "My Valheim Server", "world_name": "Dedicated", "password": "",
        "port": "2456", "public": "Public", "crossplay": "Off",
    },
    "palworld": {
        "server_name": "Palworld Server", "server_description": "", "server_password": "",
        "admin_password": "", "port": "8211", "max_players": "32", "difficulty": "Default",
        "show_join_messages": "true", "rcon_enabled": "false", "rcon_port": "25575",
        "steam_app_id": "2394010",
    },
    "terraria": {
        "server_mode": "Vanilla",
        "world_file": "world.wld", "port": "7777", "max_players": "8",
        "password": "", "motd": "Welcome!", "steam_app_id": "105600",
    },
    "project_zomboid": {
        "server_profile": "servertest",
        "server_name": "PZ Server",
        "admin_password": "",
        "port": "16261",
        "udp_port": "",
        "max_players": "32",
        "public": "Public",
    },
    "rust": {
        "server_name": "My Rust Server", "server_identity": "rust_server_1",
        "port": "28015", "max_players": "50", "world_size": "3000", "seed": "12345",
        "rcon_enabled": "false", "rcon_port": "28016", "rcon_password": "",
    },
    "ark_evolved": {
        "map": "TheIsland", "session_name": "ARK Server", "port": "7777",
        "query_port": "27015", "max_players": "70", "server_password": "", "admin_password": "",
    },
    "ark_ascended": {
        "map": "TheIsland_WP", "session_name": "ASA Server", "port": "7777",
        "query_port": "27015", "max_players": "70", "admin_password": "",
    },
    "cs2": {
        "map": "de_dust2", "port": "27015", "max_players": "16", "game_type": "0",
    },
    "gmod": {
        "server_name": "GMod Server", "map": "gm_construct", "gamemode": "sandbox",
        "port": "27015", "max_players": "16", "password": "", "rcon_password": "",
    },
    "l4d2": {
        "server_name": "L4D2 Server", "map": "c1m1_hotel",
        "port": "27015", "max_players": "8", "password": "", "rcon_password": "",
    },
    "seven_days_to_die": {
        "server_name": "7DTD Server", "port": "26900", "max_players": "8",
        "telnet_enabled": "true", "telnet_port": "8081", "telnet_password": "",
    },
    "factorio": {
        "save_file": "save1.zip", "port": "34197", "server_name": "Factorio Server",
        "server_description": "", "max_players": "0", "server_password": "",
        "rcon_enabled": "false", "rcon_port": "27015", "rcon_password": "",
    },
    "enshrouded": {
        "server_name": "Enshrouded Server", "port": "15636", "query_port": "15637",
        "slot_count": "16", "password": "",
    },
    "vrising": {
        "server_name": "V Rising Server", "port": "9876", "query_port": "9877",
        "max_users": "40", "password": "",
        "rcon_enabled": "false", "rcon_port": "25575", "rcon_password": "",
    },
    "dayz": {
        "server_name": "DayZ Server", "port": "2302", "max_players": "60",
        "server_password": "", "admin_password": "", "profiles": "profiles",
    },
    "sons_of_the_forest": {
        "server_name": "SOTF Server", "port": "8766", "query_port": "27016",
        "max_players": "8", "password": "",
    },
    "the_forest": {
        "server_name": "The Forest Server", "port": "8766", "max_players": "8", "password": "",
    },
    "core_keeper": {
        "port": "27015", "max_players": "10", "password": "", "world_seed": "0",
    },
    "space_engineers": {
        "server_name": "Space Engineers Server", "max_players": "16", "port": "27016",
    },
    "scum": {
        "server_name": "SCUM Server", "port": "7777", "max_players": "64", "server_password": "",
    },
    "eco": {
        "server_name": "Eco Server", "port": "3000", "max_players": "100", "server_description": "",
    },
    "necesse": {
        "world_name": "world", "port": "14159", "max_players": "10", "password": "",
    },
    "raft": {
        "server_name": "Raft Server", "port": "27015", "max_players": "4", "password": "",
    },
    "icarus": {
        "server_name": "Icarus Server", "port": "17777", "max_players": "8", "password": "",
    },
    "barotrauma": {
        "server_name": "Barotrauma Server", "port": "27015", "max_players": "10", "password": "",
    },
    "unturned": {
        "server_folder": "Default", "server_name": "Unturned Server",
        "port": "27015", "max_players": "24", "password": "",
    },
    "empyrion": {
        "server_name": "Empyrion Server", "port": "30000", "max_players": "32",
        "scenario": "Default Multiplayer",
    },
    "pixark": {
        "map": "CubeWorld", "session_name": "PixARK Server", "port": "7777",
        "query_port": "27015", "max_players": "70", "server_password": "", "admin_password": "",
    },
    "atlas": {
        "map": "Ocean", "session_name": "Atlas Server", "port": "5761",
        "query_port": "27016", "max_players": "50", "server_password": "", "admin_password": "",
    },
    "avorion": {
        "server_name": "Avorion Server", "port": "27000", "max_players": "20", "description": "",
    },
    "squad": {
        "server_name": "Squad Server", "port": "7787", "max_players": "100", "server_password": "",
    },
    "hell_let_loose": {
        "server_name": "HLL Server", "port": "7777", "max_players": "100", "server_password": "",
    },
    "post_scriptum": {
        "server_name": "Post Scriptum Server", "port": "7787", "max_players": "100", "server_password": "",
    },
    "abiotic_factor": {
        "server_name": "Abiotic Factor Server", "port": "7777", "max_players": "6", "password": "",
    },
    "sunkenland": {
        "server_name": "Sunkenland Server", "port": "27015", "max_players": "8", "password": "",
    },
    "aska": {
        "server_name": "ASKA Server", "port": "7777", "max_players": "4", "password": "",
    },
    "dst": {
        "cluster_name": "MyDediCluster", "shard": "Master", "port": "10999",
        "max_players": "6", "cluster_password": "", "cluster_description": "",
    },
    "conan_exiles": {
        "server_name": "Conan Server", "port": "7777", "query_port": "27016",
        "max_players": "40", "server_password": "", "admin_password": "",
    },
    "soulmask": {
        "server_name": "Soulmask Server", "port": "8777", "max_players": "50",
        "password": "", "admin_password": "",
    },
    "insurgency_sandstorm": {
        "server_name": "Sandstorm Server", "scenario": "Scenario_Crossing_Checkpoint_Insurgents",
        "port": "27102", "max_players": "28", "server_password": "",
    },
    "mordhau": {
        "server_name": "Mordhau Server", "map": "FFA_Example", "port": "7777",
        "query_port": "27015", "max_players": "24", "password": "",
    },
    "starbound": {
        "server_name": "Starbound Server", "port": "21025", "max_players": "8", "password": "",
    },
    "bannerlord": {
        "server_name": "Bannerlord Server", "map": "Multiplayer_TDM_001",
        "max_players": "100", "password": "", "admin_password": "",
    },
    "smalland": {
        "server_name": "Smalland Server", "port": "7777", "max_players": "10", "password": "",
    },
    "humanitz": {
        "server_name": "HumanitZ Server", "port": "7777", "max_players": "16", "password": "",
    },
    "once_human": {
        "server_name": "Once Human Server", "port": "7777", "max_players": "8", "password": "",
    },
    "holdfast": {
        "server_name": "Holdfast Server", "port": "20100", "max_players": "150", "password": "",
    },
    "steamcmd": {
        "steam_app_id": "2394010", "executable": "PalServer.exe", "port": "8211", "stop_command": "",
    },
    "custom": {"executable": "server.exe", "port": "25565", "stop_command": "stop", "startup_args": ""},
}


def _default_server_config(game_type: str, adapter) -> dict:
    if game_type in _DEFAULT_CONFIGS:
        return dict(_DEFAULT_CONFIGS[game_type])
    port = str(adapter.default_port()) if adapter else "25565"
    return {"port": port}


def _adapter_uses_file_config(adapter) -> bool:
    if adapter.game_type.startswith("minecraft") or adapter.game_type == "palworld":
        return True
    from .adapters.steam_games import FILE_CONFIG_GAME_TYPES
    return adapter.game_type in FILE_CONFIG_GAME_TYPES

_LOG_TAG_COLORS = {
    "manager": "#7fa8d9",
    "command": "#d4a8ff",
    "log_error": "#ff6b6b",
    "log_warn": "#f0c040",
    "log_info": "#7ec8e8",
    "log_debug": "#6b7a8f",
    "log_join": "#6fd97a",
    "log_leave": "#f09868",
    "log_ready": "#98e6a0",
    "log_save": "#c4a8f0",
    "log_admin": "#f0a0c8",
    "log_chat": "#e8eaed",
    "log_rcon": "#a8c8ff",
    "log_install": "#88d9c8",
    "log_default": "#b0b8c8",
}

# First match wins — checked before adapter-specific rules.
_CONSOLE_TAG_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\[Manager\]"), "manager"),
    (re.compile(r"^\[Install\]"), "log_install"),
    (re.compile(r"^>\s"), "command"),
    # Unreal Engine — Satisfactory, Palworld, etc.
    (re.compile(
        r"Engine is initialized|Game Engine Initialized|Server API listening|Starting Game\."
    ), "log_ready"),
    (re.compile(r": Error:"), "log_error"),
    (re.compile(r": Warning:"), "log_warn"),
    (re.compile(r": Display:"), "log_info"),
    (re.compile(r"^Log[A-Za-z0-9]+:"), "log_debug"),
    (re.compile(r"ERROR\]|/ERROR:|\bERROR\]|\bException\b|\bFATAL\b|\bCrash\b"), "log_error"),
    (re.compile(r"WARN\]|/WARN:|\bWARN\]"), "log_warn"),
    (re.compile(r" joined the game|Player connected:"), "log_join"),
    (re.compile(r" left the game|Player disconnected:"), "log_leave"),
    (re.compile(r"Listening on port", re.I), "log_ready"),
    (re.compile(r"\bServer started\b", re.I), "log_ready"),
    (re.compile(r"^Terraria Server v", re.I), "log_info"),
    (re.compile(
        r"^(Resetting game objects|Loading world data|Settling liquids)\s+\d+%", re.I
    ), "log_save"),
    (re.compile(r"Done \(.*\)! For help|Server started\.|CREATING VANILLA WORLD"), "log_ready"),
    (re.compile(r"Saved the game|Saving chunks|save-all|save hold|save resume|Opening level"), "log_save"),
    (re.compile(r"\bop |\bdeop |\bkick |\bban |\bpardon |\ballowlist "), "log_admin"),
    (re.compile(r"RCON|Thread RCON"), "log_rcon"),
    (re.compile(r"/INFO:|INFO\]:|\bINFO\]"), "log_info"),
    (re.compile(r"/DEBUG:|DEBUG\]:|\bDEBUG\]"), "log_debug"),
    (re.compile(r"<\w+>|\[Not Secure\]"), "log_chat"),
]

# Bedrock/Java wrap long messages across lines without repeating the level prefix.
_STRUCTURED_LOG_LINE = re.compile(
    r"^(?:"
    r"\[\d{4}-\d{2}-\d{2}\s"  # Bedrock timestamp
    r"|\[\d{2}:\d{2}:\d{2}\]"  # Java timestamp
    r"|\[\d{4}\.\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2}:\d{3}\]"  # Unreal Engine timestamp
    r"|\[Manager\]"
    r"|\[Install\]"
    r"|>\s"
    r"|Log[A-Za-z0-9]+:"
    r")"
)
_CONTINUATION_TAGS = frozenset({"log_warn", "log_info", "log_error", "log_debug"})


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _new_server_id() -> str:
    return uuid.uuid4().hex[:12]


def _center_toplevel(window: ctk.CTkToplevel, parent: ctk.CTkBaseClass) -> None:
    window.update_idletasks()
    root = parent.winfo_toplevel()
    root.update_idletasks()
    ww = window.winfo_width() or 520
    wh = window.winfo_height() or 500
    rx = root.winfo_rootx()
    ry = root.winfo_rooty()
    rw = root.winfo_width()
    rh = root.winfo_height()
    x = rx + max(0, (rw - ww) // 2)
    y = ry + max(0, (rh - wh) // 2)
    window.geometry(f"+{x}+{y}")


def _apply_owner_theme(owner) -> None:
    shell = find_module_shell(owner)
    if shell is not None and hasattr(shell, "_t"):
        apply_theme_tokens(shell._t)


def _release_stale_grab(widget) -> None:
    """Release only if something still holds a Tk grab (avoids breaking a healthy app)."""
    try:
        current = widget.tk.call("grab", "current")
        if current:
            widget.tk.call("grab", "release", current)
    except Exception:
        pass


class AddServerWizard(ctk.CTkToplevel):
    """Simple add/import dialog."""

    def __init__(self, master, on_created, import_mode: bool = False):
        self._owner = master
        _apply_owner_theme(master)
        super().__init__(master)
        self.configure(fg_color=t.BG)
        self.title("Import Server" if import_mode else "Add Server")
        self.resizable(False, False)
        self.on_created = on_created
        self.import_mode = import_mode
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _e: (self._close(), "break"))

        self.game_type = ctk.StringVar(value="minecraft_java")
        _folder, _name = default_server_folder_for("minecraft_java")
        self.name_var = ctk.StringVar(value=_name)
        self.folder_var = ctk.StringVar(value=_folder)
        # Tracks whether the user has typed their own server name, so later
        # game/folder changes don't silently clobber it with a default.
        self._name_user_edited = False
        self._setting_name_programmatically = False
        self.name_var.trace_add("write", self._on_name_var_write)

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Import Game Server" if import_mode else "Add Game Server",
            font=t.font(18, "bold"),
            text_color=t.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        ctk.CTkLabel(self, text="Game", font=t.font(12, "bold"), text_color=t.MUTED).grid(
            row=1, column=0, sticky="w", padx=20,
        )
        choices = game_choices()
        self._game_map = {f"{icon}  {name}": gt for gt, name, icon in choices}
        self.game_picker = GamePicker(
            self,
            choices,
            on_select=self._on_game_pick_from_picker,
        )
        self.game_picker.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 12))
        if choices:
            self.game_type.set(choices[0][0])

        ctk.CTkLabel(self, text="Server name", font=t.font(12, "bold"), text_color=t.MUTED).grid(
            row=3, column=0, sticky="w", padx=20,
        )
        ctk.CTkEntry(
            self, textvariable=self.name_var, fg_color=t.PANEL_2,
            border_color=t.BORDER, text_color=t.TEXT,
        ).grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 12))

        ctk.CTkLabel(self, text="Server folder", font=t.font(12, "bold"), text_color=t.MUTED).grid(
            row=5, column=0, sticky="w", padx=20,
        )
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.grid(row=6, column=0, sticky="ew", padx=20, pady=(4, 12))
        folder_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            folder_row, textvariable=self.folder_var, fg_color=t.PANEL_2,
            border_color=t.BORDER, text_color=t.TEXT,
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            folder_row, text="Browse…", width=90, **t.secondary_button_style(),
            command=self._browse,
        ).grid(row=0, column=1, padx=(8, 0))

        self.hint_label = ctk.CTkLabel(
            self, text="", font=t.font(11), text_color=t.MUTED,
            wraplength=460, justify="left",
        )
        self.hint_label.grid(row=7, column=0, sticky="ew", padx=20, pady=(0, 12))
        self._update_hint()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=8, column=0, sticky="e", padx=20, pady=(8, 20))
        ctk.CTkButton(
            btn_row, text="Cancel", width=90, **t.secondary_button_style(),
            command=self._close,
        ).pack(side="left", padx=(0, 8))
        self._create_btn = ctk.CTkButton(
            btn_row,
            text="Import" if import_mode else "Add Server",
            **t.primary_button_style(),
            command=self._create,
        )
        self._create_btn.pack(side="left")

        self.update_idletasks()
        _h = max(540, self.winfo_reqheight() + 12)
        self.geometry(f"520x{_h}")
        _center_toplevel(self, master)
        # Native Tk listbox renders above CTk widgets — keep action row clickable.
        for row_widget in (folder_row, self.hint_label, btn_row):
            try:
                row_widget.lift()
            except Exception:
                pass
        self.lift()
        self.game_picker.focus_search()

    def _clear_owner_ref(self) -> None:
        owner = getattr(self, "_owner", None)
        if owner is not None and getattr(owner, "_add_wizard", None) is self:
            owner._add_wizard = None

    def _close(self) -> None:
        self._clear_owner_ref()
        try:
            self.destroy()
        except Exception:
            pass

    def _on_name_var_write(self, *_args) -> None:
        if self._setting_name_programmatically:
            return
        self._name_user_edited = True

    def _set_default_name(self, name: str) -> None:
        self._setting_name_programmatically = True
        try:
            self.name_var.set(name)
        finally:
            self._setting_name_programmatically = False

    def _on_game_pick_from_picker(self, label: str, game_type: str) -> None:
        self.game_type.set(game_type)
        if not self.import_mode:
            folder, name = default_server_folder_for(game_type)
            self.folder_var.set(folder)
            if not self._name_user_edited:
                self._set_default_name(name)
        self._update_hint()

    def _on_game_pick(self, label: str) -> None:
        gt = self._game_map.get(label, "custom")
        self.game_type.set(gt)
        if not self.import_mode:
            folder, name = default_server_folder_for(gt)
            self.folder_var.set(folder)
            if not self._name_user_edited:
                self._set_default_name(name)
        self._update_hint()

    def _update_hint(self) -> None:
        adapter = get_adapter(self.game_type.get())
        if adapter is None:
            self.hint_label.configure(text="")
            return
        hints = adapter.setup_panel_hints()
        self.hint_label.configure(text=" · ".join(hints) if hints else adapter.description)

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(title="Choose server folder")
        if not chosen:
            return
        self.folder_var.set(chosen)
        from . import server_files as sf
        detected = sf.detect_game_type(Path(chosen))
        if detected:
            self.game_type.set(detected)
            self.game_picker.set_game_type(detected)
        name = Path(chosen).name
        if name and not self._name_user_edited:
            self._set_default_name(name)
        self._update_hint()

    def _create(self) -> None:
        name = self.name_var.get().strip()
        folder = self.folder_var.get().strip()
        gt = self.game_type.get()
        if not name:
            messagebox.showwarning("Add Server", "Enter a server name.", parent=self)
            return
        if not folder:
            messagebox.showwarning("Add Server", "Choose a server folder.", parent=self)
            return
        Path(folder).mkdir(parents=True, exist_ok=True)
        adapter = get_adapter(gt)
        config = _default_server_config(gt, adapter)
        if gt == "terraria":
            from .adapters.games import infer_terraria_server_mode

            config["server_mode"] = infer_terraria_server_mode(Path(folder))
            suggested_folder, suggested_name = default_server_folder_for("terraria", config)
            vanilla_folder, _ = default_server_folder_for("terraria", {"server_mode": "Vanilla"})
            try:
                if Path(folder).resolve() == Path(vanilla_folder).resolve():
                    folder = suggested_folder
                    name = suggested_name
            except OSError:
                pass

        server = {
            "id": _new_server_id(),
            "name": name,
            "game_type": gt,
            "server_dir": folder,
            "config": config,
        }
        self.on_created(server)
        self._close()


class GameServerManagerModule(GameServerFeaturesMixin, ctk.CTkFrame):
    """Universal game server manager."""

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=t.BG, **kwargs)
        self.manager = manager

        self.servers: list[dict] = load_servers()
        self._sync_all_terraria_modes_on_load()
        self._processes: dict[str, ServerProcess] = {}
        self._selected_id: str | None = self.servers[0]["id"] if self.servers else None
        self._restart_flags: dict[str, bool] = {}
        self._download_worker = None
        self._download_meta: dict = {}
        self._console_lines = 0
        self._console_buffer = ConsoleBuffer(MAX_CONSOLE_LINES)
        self._module_prefs = load_prefs()
        self._autoscroll = ctk.BooleanVar(value=True)
        self._ip_visible = ctk.BooleanVar(value=False)
        self._tailscale_ip = ""
        self._tailscale_hostname = ""
        self._tailscale_error = ""
        self._lan_ip = ""
        self._config_vars: dict[str, ctk.Variable] = {}
        self._player_rows: dict[str, ctk.CTkFrame] = {}
        self._list_rows: dict[str, ctk.CTkFrame] = {}
        self._list_row_widgets: dict[str, dict] = {}
        self._list_row_state: dict[str, tuple] = {}
        self._state_pill_state: tuple[str, str] = ("", "")
        self._active_tab = "Overview"
        self._poll_tick = 0
        self._terraria_mixed_warned: set[str] = set()
        self._add_wizard: AddServerWizard | None = None

        # Minecraft install state (Config tab)
        self._mc_versions: list[mc.MCVersion] = []
        self._mc_selected_version: mc.MCVersion | None = None
        self._mc_versions_loading = False
        self._mc_loader_versions: list = []
        self._mc_loader_versions_loading = False
        self._mc_selected_loader_version = ""
        self._java_runtimes = []
        self._java_required_major = 21
        self._java_auto_path = "java"
        self._pending_mc_download = False
        self._show_snapshots = ctk.BooleanVar(value=False)
        self._curseforge_results: list[dict] = []
        self._modpack_minecraft_version = ""
        self._curseforge_settings = load_manager_settings()
        self._eula_var = ctk.BooleanVar(value=False)

        self._init_features()
        self._build_layout()
        self._apply_terminal_scheme()
        self._refresh_server_list()
        if self._selected_id:
            self._refresh_dashboard(full=True)
            self._render_console_from_buffer()
            self.after(200, self._warn_terraria_mixed_folder)
        self._refresh_tailscale_ip_async()
        self.after(POLL_MS, self._poll_all)
        self.after(1500, self._auto_start_servers)
        self.after(50, game_choices)  # warm adapter registry before Add wizard opens
        threading.Thread(target=ensure_ytdlp, daemon=True, name="yt-dlp-bootstrap").start()

    # ------------------------------------------------------------------ layout

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- left: server list ----
        left = ctk.CTkFrame(self, **st.surface_style(), width=272)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        left.grid_propagate(False)
        left.grid_rowconfigure(2, weight=1)
        left.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 10))
        title_row.grid_columnconfigure(2, weight=1)
        ctk.CTkFrame(title_row, **st.accent_strip(), height=40).grid(
            row=0, column=0, rowspan=2, sticky="ns", padx=(0, 10),
        )
        server_icon_frame(title_row, size=36).grid(row=0, column=1, rowspan=2, sticky="nw", padx=(0, 10))
        title_col = ctk.CTkFrame(title_row, fg_color="transparent")
        title_col.grid(row=0, column=2, rowspan=2, sticky="ew")
        title_col.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_col, text="Game Server Manager", font=t.font(15, "bold"),
                     text_color=t.TEXT, anchor="w", justify="left").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_col,
            text="Host Minecraft, Rust, ARK, Factorio, Valheim, Palworld, and more.",
            font=t.font(10), text_color=t.MUTED, anchor="w", justify="left", wraplength=190,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        list_header = ctk.CTkFrame(left, fg_color="transparent")
        list_header.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        ctk.CTkLabel(list_header, text="Your servers", font=t.font(13, "bold"), text_color=t.TEXT
                     ).pack(side="left")
        ctk.CTkButton(list_header, text="Import", width=62, height=30, **t.secondary_button_style(),
                      command=self._open_import_wizard).pack(side="right", padx=(4, 0))
        ctk.CTkButton(list_header, text="+ Add", width=64, height=30, **t.primary_button_style(),
                      command=self._open_add_wizard).pack(side="right")

        self.server_list_frame = ctk.CTkScrollableFrame(left, **st.inset_style())
        self.server_list_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.server_list_frame.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.server_list_frame)

        ctk.CTkButton(left, text="Remove Selected", height=34,
                      **t.danger_button_style(), command=self._remove_selected
                      ).grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))

        # ---- right: dashboard ----
        self.dashboard = ctk.CTkFrame(self, **st.surface_style())
        self.dashboard.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        self.dashboard.grid_columnconfigure(0, weight=1)
        self.dashboard.grid_rowconfigure(3, weight=1)

        dash_top = ctk.CTkFrame(self.dashboard, fg_color="transparent")
        dash_top.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 0))
        dash_top.grid_columnconfigure(0, weight=1)
        self.dash_header = ctk.CTkLabel(dash_top, text="Select a server", font=t.font(18, "bold"),
                                        text_color=t.TEXT, anchor="w", justify="left")
        self.dash_header.grid(row=0, column=0, sticky="w")
        self.state_pill = ctk.CTkLabel(
            dash_top, text="● Stopped", font=t.font(11, "bold"),
            width=110, height=28, anchor="center", **st.status_pill_style(False),
        )
        self.state_pill.grid(row=0, column=1, sticky="e", padx=(8, 0), pady=2)

        self.control_row = ctk.CTkFrame(self.dashboard, **st.card_style(fg=t.PANEL))
        self.control_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(10, 8))
        ctrl_inner = ctk.CTkFrame(self.control_row, fg_color="transparent")
        ctrl_inner.pack(fill="x", padx=10, pady=8)
        self.start_btn = ctk.CTkButton(ctrl_inner, text="▶  Start", width=88, height=32,
                                       **t.primary_button_style(), command=self._start_server)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ctk.CTkButton(ctrl_inner, text="Stop", width=72, height=32, state="disabled",
                                      **t.secondary_button_style(), command=self._stop_server)
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.restart_btn = ctk.CTkButton(ctrl_inner, text="Restart", width=80, height=32, state="disabled",
                                         **t.secondary_button_style(), command=self._restart_server)
        self.restart_btn.pack(side="left", padx=(0, 6))
        self.kill_btn = ctk.CTkButton(ctrl_inner, text="Kill", width=64, height=32, state="disabled",
                                      **t.danger_button_style(), command=self._confirm_kill)
        self.kill_btn.pack(side="left")

        ctk.CTkFrame(self.dashboard, height=1, fg_color=t.BORDER).grid(
            row=2, column=0, sticky="ew", padx=14, pady=(0, 4),
        )

        self.tabview = ctk.CTkTabview(
            self.dashboard, fg_color="transparent",
            segmented_button_fg_color=t.PANEL_HOVER,
            segmented_button_selected_color=t.ACCENT,
            segmented_button_selected_hover_color=t.ACCENT_HOVER,
            segmented_button_unselected_color=t.PANEL,
            segmented_button_unselected_hover_color=t.PANEL_HOVER,
            text_color=t.TEXT,
            corner_radius=t.RADIUS_SM,
        )
        self.tabview.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 14))
        for tab in ("Overview", "Console", "Players", "Files", "Mods", "Modpacks", "Backups", "Config", "Logs"):
            self.tabview.add(tab)
            self.tabview.tab(tab).configure(fg_color=t.PANEL_2)
        self.tabview.configure(command=self._on_tab_changed)

        self._build_overview_tab(self.tabview.tab("Overview"))
        self._build_console_tab(self.tabview.tab("Console"))
        self._build_players_tab(self.tabview.tab("Players"))
        self._build_files_tab(self.tabview.tab("Files"))
        self._build_mods_tab(self.tabview.tab("Mods"))
        self._build_modpacks_tab(self.tabview.tab("Modpacks"))
        self._build_backups_tab(self.tabview.tab("Backups"))
        self._build_config_tab(self.tabview.tab("Config"))
        self._build_logs_tab(self.tabview.tab("Logs"))

        self.empty_label = ctk.CTkFrame(self.dashboard, **st.card_style())
        empty_inner = ctk.CTkFrame(self.empty_label, fg_color="transparent")
        empty_inner.pack(expand=True, pady=48)
        server_icon_frame(empty_inner, size=56, fg_color=t.PANEL_HOVER).pack(pady=(0, 4))
        ctk.CTkLabel(empty_inner, text="No servers yet", font=t.font(16, "bold"),
                     text_color=t.TEXT).pack(pady=(8, 4))
        ctk.CTkLabel(empty_inner, text="Click + Add or Import to get started.",
                     font=t.font(12), text_color=t.MUTED).pack()

    def _current_server(self) -> dict | None:
        if not self._selected_id:
            return None
        return next((s for s in self.servers if s["id"] == self._selected_id), None)

    def _current_adapter(self):
        srv = self._current_server()
        return get_adapter(srv["game_type"]) if srv else None

    def _process(self, server_id: str | None = None) -> ServerProcess:
        sid = server_id or self._selected_id
        if not sid:
            return ServerProcess()
        if sid not in self._processes:
            self._processes[sid] = ServerProcess()
        return self._processes[sid]

    @staticmethod
    def _mem_mb(var: "ctk.StringVar", default: int) -> int:
        """Safely read a memory (MB) StringVar, tolerating an empty/invalid entry."""
        try:
            value = int(str(var.get()).strip())
        except (ValueError, tk.TclError):
            return default
        return value if value > 0 else default

    def _suggest_mc_memory(self) -> None:
        """Sets Min/Max MB from the currently-installed modpack's mod count/
        size, capped to a safe share of system RAM, instead of the person
        having to guess or crank the sliders to "use everything". Writes
        straight into the saved server config too, so the value takes
        effect on the next Play/Launch even if Save Config is never
        clicked separately."""
        srv = self._current_server()
        client_dir = self._server_dir(srv) if srv else None
        if not client_dir or not client_dir.exists():
            messagebox.showinfo("Suggest Memory", "Install or select a modpack first.",
                                 parent=self.winfo_toplevel())
            return
        try:
            min_mb, max_mb = estimate_memory_mb(client_dir)
        except Exception as e:
            messagebox.showerror("Suggest Memory", f"Couldn't estimate memory: {e}",
                                  parent=self.winfo_toplevel())
            return
        self.min_mb.set(str(min_mb))
        self.max_mb.set(str(max_mb))
        cfg = srv.setdefault("config", {})
        cfg["min_mb"] = min_mb
        cfg["max_mb"] = max_mb
        self._persist()

    def _system_ram_mb(self) -> int | None:
        try:
            import psutil
            return int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:
            return None

    def _refresh_mc_mem_system_label(self) -> None:
        total = self._system_ram_mb()
        self.mc_mem_system_label.configure(text=f"System RAM: {total} MB" if total else "")

    def _schedule_mc_mem_autosave(self) -> None:
        """Debounces edits to Min/Max MB so every keystroke doesn't hit disk,
        but changes still land without a separate Save click — same effect
        as CurseForge writing its per-instance memory slider to disk as
        soon as you let go of it."""
        if getattr(self, "_mc_mem_syncing", False):
            return
        job = getattr(self, "_mc_mem_autosave_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._mc_mem_autosave_job = self.after(600, self._commit_mc_mem_autosave)

    def _commit_mc_mem_autosave(self) -> None:
        self._mc_mem_autosave_job = None
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            return
        min_mb = self._mem_mb(self.min_mb, 1024)
        max_mb = self._mem_mb(self.max_mb, 2048)
        # Mirror CurseForge's own slider ceiling: it queries total system RAM
        # and never lets the slider (or the saved value) exceed it, so a
        # mistyped/huge number here can't hand the JVM more memory than the
        # machine actually has.
        total = self._system_ram_mb()
        if total:
            cap = max(1024, total - 1024)
            clamped_max = min(max_mb, cap)
            if clamped_max != max_mb:
                max_mb = clamped_max
                self._mc_mem_syncing = True
                self.max_mb.set(str(max_mb))
                self._mc_mem_syncing = False
            min_mb = min(min_mb, max_mb)
        cfg = srv.setdefault("config", {})
        if cfg.get("min_mb") == min_mb and cfg.get("max_mb") == max_mb:
            return
        cfg["min_mb"] = min_mb
        cfg["max_mb"] = max_mb
        self._persist()

    def _server_dir(self, server: dict | None = None) -> Path:
        srv = server or self._current_server()
        if not srv:
            return Path(".")
        base = Path(srv["server_dir"])
        active = str((srv.get("config", {}) or {}).get("active_modpack_profile") or "")
        if active:
            return base / "modpacks" / self._profile_dir_name(srv, active)
        return base

    def _modpack_profiles(self, srv: dict) -> dict:
        cfg = srv.setdefault("config", {})
        return cfg.setdefault("modpack_profiles", {})

    @staticmethod
    def _sanitize_profile_dir_name(name: str) -> str:
        """Turn a modpack's display name into a filesystem-safe folder name."""
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip(" .")
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned[:60].strip(" .")
        return cleaned or "Modpack"

    def _unique_profile_dir_name(self, srv: dict, name: str) -> str:
        """Pick a sanitized folder name that doesn't collide with an existing
        profile's folder (either already on disk or reserved by another
        profile entry)."""
        base_name = self._sanitize_profile_dir_name(name)
        taken = {
            str(p.get("dir_name") or "") for p in self._modpack_profiles(srv).values()
        }
        modpacks_root = Path(srv["server_dir"]) / "modpacks"
        candidate = base_name
        n = 2
        while candidate in taken or (modpacks_root / candidate).exists():
            candidate = f"{base_name} ({n})"
            n += 1
        return candidate

    def _profile_dir_name(self, srv: dict, profile_id: str) -> str:
        """Resolve a profile's on-disk folder name, falling back to the raw
        profile id for profiles created before folders were named after the
        modpack (keeps existing installs working without moving anything)."""
        profile = self._modpack_profiles(srv).get(profile_id) or {}
        return str(profile.get("dir_name") or profile_id)

    def _new_modpack_profile(self, srv: dict, name: str) -> str:
        profile_id = uuid.uuid4().hex[:10]
        dir_name = self._unique_profile_dir_name(srv, name)
        profiles = self._modpack_profiles(srv)
        profiles[profile_id] = {"name": name, "dir_name": dir_name}
        return profile_id

    def _activate_modpack_profile(self, srv: dict, profile_id: str) -> None:
        cfg = srv.setdefault("config", {})
        cfg["active_modpack_profile"] = profile_id
        profile = self._modpack_profiles(srv).get(profile_id) if profile_id else None
        if profile:
            cfg["modpack_provider"] = profile.get("provider", "curseforge")
            cfg["modpack_name"] = profile.get("name", "")
            cfg["modpack_project_id"] = profile.get("project_id", 0)
            cfg["modpack_file_id"] = profile.get("file_id", 0)
            if profile.get("minecraft_version"):
                cfg["minecraft_version"] = profile["minecraft_version"]
                cfg["installed_version"] = profile.get("installed_version", profile["minecraft_version"])
            if profile.get("loader"):
                cfg["loader"] = profile["loader"]
                cfg["loader_version"] = profile.get("loader_version", "")
            if profile.get("java_path"):
                cfg["java_path"] = profile["java_path"]
                self.java_path.set(profile["java_path"])
        elif not profile_id:
            cfg["modpack_name"] = ""
        self._persist()

    def _remove_modpack_profile(self, srv: dict, profile_id: str) -> None:
        profiles = self._modpack_profiles(srv)
        dir_name = self._profile_dir_name(srv, profile_id)
        profiles.pop(profile_id, None)
        cfg = srv.get("config", {})
        profile_dir = Path(srv["server_dir"]) / "modpacks" / dir_name
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
        if str(cfg.get("active_modpack_profile") or "") == profile_id:
            self._activate_modpack_profile(srv, "")
        else:
            self._persist()

    def _port(self) -> str:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return "25565"
        cfg = srv.get("config", {})
        if adapter.game_type in ("minecraft_java", "minecraft_bedrock"):
            props = adapter.read_config(self._server_dir(srv))
            return props.get("server-port", str(adapter.default_port()))
        if adapter.game_type == "palworld":
            props = adapter.read_config(self._server_dir(srv))
            if props.get("port"):
                return props["port"]
        return str(cfg.get("port") or adapter.default_port())

    # ------------------------------------------------------------------ server list

    def _persist(self) -> None:
        save_servers(self.servers)

    def _rebuild_server_list(self) -> None:
        """Full rebuild — only when servers are added/removed or selection changes."""
        for row in self._list_rows.values():
            row.destroy()
        self._list_rows.clear()
        self._list_row_widgets.clear()
        self._list_row_state.clear()

        if not self.servers:
            self.empty_label.grid(row=0, column=0, rowspan=4, sticky="nsew", padx=14, pady=14)
            self.tabview.grid_remove()
            self.dash_header.grid_remove()
            self.control_row.grid_remove()
            return

        self.empty_label.grid_remove()
        self.tabview.grid()
        self.dash_header.grid()
        self.control_row.grid()

        for i, srv in enumerate(self.servers):
            adapter = get_adapter(srv["game_type"])
            proc = self._process(srv["id"])
            running = proc.running
            status_color = t.SUCCESS if running else t.MUTED
            icon = adapter.icon if adapter else "🎮"
            game_name = adapter.display_name if adapter else srv["game_type"]
            n_players = len(proc.players) if running else 0
            selected = srv["id"] == self._selected_id

            if selected:
                row = ctk.CTkFrame(self.server_list_frame, **st.card_style(fg=t.ACCENT_GLOW))
                row.configure(border_color=t.ACCENT_DIM)
            else:
                row = ctk.CTkFrame(self.server_list_frame, fg_color="transparent", corner_radius=t.RADIUS_SM)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(2, weight=1)

            def _bind_click(widget, sid=srv["id"]) -> None:
                widget.bind("<Button-1>", lambda _e, s=sid: self._select_server(s))

            _bind_click(row)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=7)
            inner.grid_columnconfigure(2, weight=1)

            accent = ctk.CTkFrame(
                inner, width=4, height=40,
                fg_color=t.ACCENT if selected else t.BORDER,
                corner_radius=2,
            )
            accent.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 8))

            status_lbl = ctk.CTkLabel(inner, text="●", font=t.font(11), text_color=status_color, width=14)
            status_lbl.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(0, 8))

            text_col = ctk.CTkFrame(inner, fg_color="transparent")
            text_col.grid(row=0, column=2, rowspan=2, sticky="ew")
            text_col.grid_columnconfigure(0, weight=1)

            name_lbl = ctk.CTkLabel(
                text_col, text=f"{icon} {srv['name']}",
                font=t.font(12, "bold" if selected else "normal"),
                text_color=t.TEXT if selected else t.MUTED,
                anchor="w", justify="left",
            )
            name_lbl.grid(row=0, column=0, sticky="w")
            meta_lbl = ctk.CTkLabel(
                text_col, text=self._server_list_meta_text(game_name, n_players, running),
                font=t.font(10), text_color=t.MUTED, anchor="w", justify="left",
            )
            meta_lbl.grid(row=1, column=0, sticky="w", pady=(1, 0))

            for child in row.winfo_children():
                _bind_click(child)
            for child in inner.winfo_children():
                _bind_click(child)
            for child in text_col.winfo_children():
                _bind_click(child)

            self._list_rows[srv["id"]] = row
            self._list_row_widgets[srv["id"]] = {
                "frame": row,
                "accent": accent,
                "status": status_lbl,
                "meta": meta_lbl,
                "name": name_lbl,
            }

    def _server_list_meta_text(self, game_name: str, n_players: int, running: bool) -> str:
        if running:
            return f"{game_name} · {n_players} online"
        return game_name

    def _update_server_list(self) -> None:
        """Lightweight in-place update for status/player counts — no widget rebuild."""
        if not self.servers:
            return

        current_ids = {s["id"] for s in self.servers}
        if current_ids != set(self._list_row_widgets):
            self._rebuild_server_list()
            return

        for srv in self.servers:
            widgets = self._list_row_widgets.get(srv["id"])
            if widgets is None:
                self._rebuild_server_list()
                return

            adapter = get_adapter(srv["game_type"])
            proc = self._process(srv["id"])
            running = proc.running
            game_name = adapter.display_name if adapter else srv["game_type"]
            n_players = len(proc.players) if running else 0

            status_color = t.SUCCESS if running else t.MUTED
            meta_text = self._server_list_meta_text(game_name, n_players, running)
            state_key = (status_color, meta_text)
            if self._list_row_state.get(srv["id"]) == state_key:
                continue
            self._list_row_state[srv["id"]] = state_key
            widgets["status"].configure(text_color=status_color)
            widgets["meta"].configure(text=meta_text)

    def _refresh_server_list(self) -> None:
        """Alias for full rebuild (add/remove/select)."""
        self._rebuild_server_list()

    def _select_server(self, server_id: str) -> None:
        if server_id == self._selected_id:
            return
        prev_id = self._selected_id
        self._selected_id = server_id
        self._apply_selection_style(prev_id)
        self._apply_selection_style(server_id)
        self._render_console_from_buffer()
        self._on_server_context_changed()

    def _apply_selection_style(self, server_id: str | None) -> None:
        if not server_id:
            return
        widgets = self._list_row_widgets.get(server_id)
        if not widgets or "name" not in widgets:
            return
        selected = server_id == self._selected_id
        widgets["name"].configure(
            font=t.font(12, "bold" if selected else "normal"),
            text_color=t.TEXT if selected else t.MUTED,
        )
        if "frame" in widgets:
            frame = widgets["frame"]
            if selected:
                frame.configure(fg_color=t.ACCENT_GLOW, border_width=1, border_color=t.ACCENT_DIM)
            else:
                frame.configure(fg_color="transparent", border_width=0)
        if "accent" in widgets:
            widgets["accent"].configure(fg_color=t.ACCENT if selected else t.BORDER)

    def _on_tab_changed(self, tab_name: str | None = None) -> None:
        if tab_name is None:
            tab_name = self.tabview.get()
        self._active_tab = tab_name
        self._refresh_active_tab()

    def _refresh_active_tab(self) -> None:
        self._sync_active_tab()
        tab = self._active_tab
        if tab == "Overview":
            self._refresh_overview()
        elif tab == "Console":
            self._rebuild_quick_commands()
        elif tab == "Players":
            self._refresh_rcon_panel()
            srv = self._current_server()
            if srv and not self._palworld_rcon_ready():
                self._rebuild_players(self._process(srv["id"]))
            self._refresh_access_list()
        elif tab == "Files":
            self._files_subpath = "."
            self._refresh_files_listing()
        elif tab == "Mods":
            self._refresh_mods()
        elif tab == "Modpacks":
            self._refresh_modpacks_tab()
        elif tab == "Backups":
            self._refresh_backups()
        elif tab == "Config":
            self._refresh_config_tab()
        elif tab == "Logs":
            self._refresh_logs()

    def _transition_dashboard_refresh(self) -> None:
        self._refresh_dashboard(full=False)

    def _open_add_wizard(self, import_mode: bool = False) -> None:
        if self._add_wizard is not None:
            try:
                if self._add_wizard.winfo_exists():
                    self._add_wizard.lift()
                    self._add_wizard.focus_force()
                    return
            except Exception:
                pass
            self._add_wizard = None

        _release_stale_grab(self)
        self._add_wizard = AddServerWizard(self, self._on_server_added, import_mode=import_mode)

    def _on_server_added(self, server: dict) -> None:
        self._add_wizard = None
        self.servers.append(server)
        self._persist()
        self._selected_id = server["id"]
        self._refresh_server_list()
        self._on_server_context_changed()

    def _remove_selected(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        proc = self._process(srv["id"])
        if proc.running:
            messagebox.showwarning("Remove Server", "Stop the server before removing it.")
            return
        if not messagebox.askyesno("Remove Server", f"Remove '{srv['name']}' from the list?"):
            return
        self.servers = [s for s in self.servers if s["id"] != srv["id"]]
        self._processes.pop(srv["id"], None)
        self._console_buffer.remove_server(srv["id"])
        self._persist()
        self._selected_id = self.servers[0]["id"] if self.servers else None
        self._refresh_server_list()
        if self._selected_id:
            self._render_console_from_buffer()
        self._refresh_dashboard()

    # ------------------------------------------------------------------ overview

    def _build_overview_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        self.overview_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.overview_scroll.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        self.overview_scroll.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.overview_scroll)

        self._build_address_panel(self.overview_scroll)

        monitor = ctk.CTkFrame(self.overview_scroll, **st.card_style())
        monitor.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(monitor, text="📊  Monitoring", font=t.font(12, "bold"),
                     text_color=t.TEXT).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))
        self.monitor_cpu_label = ctk.CTkLabel(monitor, text="CPU: —", font=t.font(11), text_color=t.MUTED)
        self.monitor_cpu_label.grid(row=1, column=0, sticky="w", padx=12, pady=2)
        self.monitor_mem_label = ctk.CTkLabel(monitor, text="RAM: —", font=t.font(11), text_color=t.MUTED)
        self.monitor_mem_label.grid(row=1, column=1, sticky="w", padx=12, pady=2)
        self.monitor_size_label = ctk.CTkLabel(monitor, text="Folder: —", font=t.font(11), text_color=t.MUTED)
        self.monitor_size_label.grid(row=2, column=0, sticky="w", padx=12, pady=(2, 8))
        self.monitor_disk_label = ctk.CTkLabel(monitor, text="Disk free: —", font=t.font(11), text_color=t.MUTED)
        self.monitor_disk_label.grid(row=2, column=1, sticky="w", padx=12, pady=(2, 8))

        options = ctk.CTkFrame(self.overview_scroll, **st.card_style())
        options.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.auto_start_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            options, text="Auto-start when app opens", variable=self.auto_start_var,
            command=self._toggle_auto_start, fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER,
            text_color=t.TEXT, font=t.font(11),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=10)

        self.overview_info = ctk.CTkFrame(self.overview_scroll, **st.card_style())
        self.overview_info.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.overview_info.grid_columnconfigure(1, weight=1)
        self.uptime_label = ctk.CTkLabel(self.overview_scroll, text="", font=t.font(12), text_color=t.MUTED)
        self.uptime_label.grid(row=4, column=0, sticky="w", pady=(8, 0))

    def _build_address_panel(self, parent) -> None:
        panel = ctk.CTkFrame(parent, **st.card_style())
        panel.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        panel.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        ctk.CTkLabel(header, text="🌐  Server addresses", font=t.font(12, "bold"),
                     text_color=t.TEXT).pack(side="left")
        self.address_eye_btn = ctk.CTkButton(header, text="👁", width=30, height=26,
                                             **t.secondary_button_style(), command=self._toggle_ip_visibility)
        self.address_eye_btn.pack(side="right")
        ctk.CTkLabel(panel, text="Tailscale", font=t.font(10),
                     text_color=t.MUTED).grid(row=1, column=0, sticky="w", padx=10, pady=(6, 0))
        addr_row = ctk.CTkFrame(panel, fg_color="transparent")
        addr_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 4))
        addr_row.grid_columnconfigure(0, weight=1)
        self.address_label = ctk.CTkLabel(addr_row, text="Checking…", font=t.mono(13),
                                          text_color=t.TEXT, anchor="w")
        self.address_label.grid(row=0, column=0, sticky="ew")
        self.address_copy_btn = ctk.CTkButton(addr_row, text="📋", width=30, height=26,
                                              **t.secondary_button_style(), command=self._copy_address)
        self.address_copy_btn.grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(addr_row, text="↻", width=30, height=26, **t.secondary_button_style(),
                      command=self._refresh_tailscale_ip_async).grid(row=0, column=2, padx=(6, 0))
        self.address_hostname_label = ctk.CTkLabel(panel, text="", font=t.font(10),
                                                     text_color=t.MUTED, anchor="w")
        self.address_hostname_label.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))

        ctk.CTkLabel(panel, text="LAN", font=t.font(10),
                     text_color=t.MUTED).grid(row=4, column=0, sticky="w", padx=10, pady=(4, 0))
        lan_row = ctk.CTkFrame(panel, fg_color="transparent")
        lan_row.grid(row=5, column=0, sticky="ew", padx=10, pady=(2, 10))
        lan_row.grid_columnconfigure(0, weight=1)
        self.lan_label = ctk.CTkLabel(lan_row, text="—", font=t.mono(12), text_color=t.TEXT, anchor="w")
        self.lan_label.grid(row=0, column=0, sticky="ew")
        self.lan_copy_btn = ctk.CTkButton(lan_row, text="📋", width=30, height=26,
                                          **t.secondary_button_style(), command=self._copy_lan_address)
        self.lan_copy_btn.grid(row=0, column=1, padx=(6, 0))

    def _refresh_overview(self) -> None:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return

        for child in self.overview_info.winfo_children():
            child.destroy()

        rows = adapter.overview_rows(
            self._server_dir(srv),
            srv.get("config", {}),
            running=self._process(srv["id"]).running,
        )
        for i, (label, value) in enumerate(rows):
            ctk.CTkLabel(self.overview_info, text=label, font=t.font(11), text_color=t.MUTED
                         ).grid(row=i, column=0, sticky="w", padx=12, pady=4)
            ctk.CTkLabel(self.overview_info, text=value, font=t.font(11), text_color=t.TEXT,
                         anchor="w", wraplength=420).grid(row=i, column=1, sticky="w", padx=(0, 12), pady=4)

        self._update_address_display()
        self._update_lan_display()
        cfg = srv.get("config", {})
        self.auto_start_var.set(bool(cfg.get("auto_start")))
        self._update_monitoring()

    # ------------------------------------------------------------------ console

    def _build_console_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(toolbar, text="Console output", font=t.font(11, "bold"),
                     text_color=t.MUTED).pack(side="left")
        scheme_labels = [k.replace("_", " ").title() for k in TERMINAL_SCHEMES]
        self.terminal_scheme_menu = ctk.CTkOptionMenu(
            toolbar, values=scheme_labels, width=120, height=26,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_terminal_scheme_changed,
        )
        cur = self._module_prefs.get("terminal_scheme", "default").replace("_", " ").title()
        if cur in scheme_labels:
            self.terminal_scheme_menu.set(cur)
        self.terminal_scheme_menu.pack(side="right", padx=(8, 0))
        ctk.CTkCheckBox(
            toolbar, text="Auto-scroll", variable=self._autoscroll,
            fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.MUTED,
            font=t.font(11),
        ).pack(side="right")

        search_row = ctk.CTkFrame(parent, fg_color="transparent")
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        search_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(search_row, text="Search", font=t.font(10), text_color=t.MUTED).grid(row=0, column=0, sticky="w")
        search_entry = ctk.CTkEntry(
            search_row, textvariable=self._console_search, placeholder_text="Filter console lines…",
            fg_color=t.PANEL, border_color=t.BORDER, text_color=t.TEXT, height=28,
        )
        search_entry.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._console_search.trace_add("write", self._on_console_search_changed)

        console_wrap = ctk.CTkFrame(parent, **st.inset_style())
        console_wrap.grid(row=2, column=0, sticky="nsew")
        console_wrap.grid_columnconfigure(0, weight=1)
        console_wrap.grid_rowconfigure(0, weight=1)

        self.console_box = ctk.CTkTextbox(
            console_wrap, fg_color=t.PANEL_2, text_color=_LOG_TAG_COLORS["log_default"],
            font=t.mono(11), wrap="none", corner_radius=t.RADIUS_SM, state="disabled",
        )
        self.console_box.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self._configure_console_tags()

        cmd_panel = ctk.CTkFrame(parent, **st.card_style())
        cmd_panel.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        cmd_panel.grid_columnconfigure(0, weight=1)

        cmd_row = ctk.CTkFrame(cmd_panel, fg_color="transparent")
        cmd_row.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        cmd_row.grid_columnconfigure(0, weight=1)
        self.command_entry = ctk.CTkEntry(
            cmd_row, placeholder_text="Type a server command…",
            fg_color=t.PANEL, border_color=t.BORDER, text_color=t.TEXT, height=30,
        )
        self.command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.command_entry.bind("<Return>", lambda _e: self._send_command())
        self.command_entry.bind("<Up>", self._on_command_history_key)
        self.command_entry.bind("<Down>", self._on_command_history_key)
        ctk.CTkButton(cmd_row, text="Send", width=72, height=30, **t.secondary_button_style(),
                      command=self._send_command).grid(row=0, column=1)
        ctk.CTkButton(cmd_row, text="Clear", width=72, height=30, **t.secondary_button_style(),
                      command=self._clear_console).grid(row=0, column=2, padx=(6, 0))

        quick_header = ctk.CTkFrame(cmd_panel, fg_color="transparent")
        quick_header.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        self._quick_cmds_expanded = bool(self._module_prefs.get("quick_commands_expanded"))
        self._quick_cmds_toggle = ctk.CTkButton(
            quick_header,
            text="▸ Quick commands" if not self._quick_cmds_expanded else "▾ Quick commands",
            height=24,
            font=t.font(10),
            fg_color="transparent",
            hover_color=t.PANEL_HOVER,
            text_color=t.MUTED,
            anchor="w",
            command=self._toggle_quick_commands,
        )
        self._quick_cmds_toggle.pack(side="left")

        self.quick_cmd_row = ctk.CTkFrame(cmd_panel, fg_color="transparent")
        for col in range(8):
            self.quick_cmd_row.grid_columnconfigure(col, weight=0)
        if self._quick_cmds_expanded:
            self.quick_cmd_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        else:
            self.quick_cmd_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 4))
            self.quick_cmd_row.grid_remove()

    def _toggle_quick_commands(self) -> None:
        self._quick_cmds_expanded = not self._quick_cmds_expanded
        self._module_prefs["quick_commands_expanded"] = self._quick_cmds_expanded
        from .core.module_prefs import save_prefs
        save_prefs(self._module_prefs)
        if self._quick_cmds_expanded:
            self.quick_cmd_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
            self._quick_cmds_toggle.configure(text="▾ Quick commands")
        else:
            self.quick_cmd_row.grid_remove()
            self._quick_cmds_toggle.configure(text="▸ Quick commands")

    def _rebuild_quick_commands(self) -> None:
        for child in self.quick_cmd_row.winfo_children():
            child.destroy()
        commands = self._all_quick_commands()
        cols = 8
        for i, (label, cmd) in enumerate(commands):
            r, c = divmod(i, cols)
            short = label if len(label) <= 14 else label[:12] + "…"
            btn_style = t.secondary_button_style()
            btn_style.update(font=t.font(10), height=22)
            ctk.CTkButton(
                self.quick_cmd_row, text=short,
                command=lambda c=cmd: self._send_raw_command(c),
                **btn_style,
            ).grid(row=r, column=c, sticky="w", padx=(0, 4), pady=(0, 4))

    # ------------------------------------------------------------------ players

    def _build_players_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)
        self.players_header = ctk.CTkLabel(parent, text="Players Online", font=t.font(14, "bold"),
                                           text_color=t.TEXT, anchor="w")
        self.players_header.grid(row=0, column=0, sticky="w", pady=(4, 8))

        self.rcon_panel = ctk.CTkFrame(parent, **st.card_style())
        self.rcon_panel.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        parent.grid_rowconfigure(1, weight=1)
        self.rcon_panel.grid_columnconfigure(0, weight=1)
        self.rcon_panel.grid_rowconfigure(3, weight=1)
        self.rcon_panel.grid_remove()

        rcon_hdr = ctk.CTkFrame(self.rcon_panel, fg_color="transparent")
        rcon_hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ctk.CTkLabel(rcon_hdr, text="RCON Admin", font=t.font(12, "bold"), text_color=t.TEXT).pack(side="left")
        self._rcon_auto_refresh = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            rcon_hdr, text="Auto-refresh", variable=self._rcon_auto_refresh,
            fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.MUTED, font=t.font(10),
        ).pack(side="right")
        ctk.CTkButton(
            rcon_hdr, text="Refresh", width=72, height=26, **t.secondary_button_style(),
            command=self._refresh_rcon_players_async,
        ).pack(side="right", padx=(0, 8))
        self.rcon_status_label = ctk.CTkLabel(
            rcon_hdr, text="", font=t.font(10), text_color=t.MUTED,
        )
        self.rcon_status_label.pack(side="right", padx=(0, 12))

        rcon_tools = ctk.CTkFrame(self.rcon_panel, fg_color="transparent")
        rcon_tools.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        rcon_tools.grid_columnconfigure(0, weight=1)
        self.rcon_broadcast_entry = ctk.CTkEntry(
            rcon_tools, placeholder_text="Broadcast message…",
            fg_color=t.PANEL, border_color=t.BORDER, text_color=t.TEXT, height=28,
        )
        self.rcon_broadcast_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(rcon_tools, text="Broadcast", width=88, height=28, **t.primary_button_style(),
                      command=self._rcon_broadcast).grid(row=0, column=1)

        cmd_row = ctk.CTkFrame(self.rcon_panel, fg_color="transparent")
        cmd_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        cmd_row.grid_columnconfigure(0, weight=1)
        self.rcon_cmd_entry = ctk.CTkEntry(
            cmd_row, placeholder_text="RCON command (Save, ShowPlayers, Shutdown 60…)",
            fg_color=t.PANEL, border_color=t.BORDER, text_color=t.TEXT, height=28,
        )
        self.rcon_cmd_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.rcon_cmd_entry.bind("<Return>", lambda _e: self._rcon_send_command())
        ctk.CTkButton(cmd_row, text="Send", width=64, height=28, **t.secondary_button_style(),
                      command=self._rcon_send_command).grid(row=0, column=1)

        self.rcon_players_frame = ctk.CTkScrollableFrame(self.rcon_panel, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        self.rcon_players_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.rcon_players_frame.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.rcon_players_frame)
        self.rcon_no_players_label = ctk.CTkLabel(
            self.rcon_players_frame, text="No players online.", text_color=t.MUTED, font=t.font(12),
        )
        self.rcon_no_players_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

        self.players_frame = ctk.CTkScrollableFrame(parent, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        self.players_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        parent.grid_rowconfigure(2, weight=1)
        self.players_frame.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.players_frame)
        self.no_players_label = ctk.CTkLabel(self.players_frame, text="No players online.",
                                             text_color=t.MUTED, font=t.font(12))
        self.no_players_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

        access_panel = ctk.CTkFrame(parent, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        self.access_panel = access_panel
        access_panel.grid(row=3, column=0, sticky="nsew")
        access_panel.grid_columnconfigure(0, weight=1)
        access_panel.grid_rowconfigure(1, weight=1)
        access_header = ctk.CTkFrame(access_panel, fg_color="transparent")
        access_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        ctk.CTkLabel(access_header, text="Whitelist / Allowlist", font=t.font(12, "bold"),
                     text_color=t.TEXT).pack(side="left")
        self.access_add_entry = ctk.CTkEntry(access_header, width=140, placeholder_text="Player name",
                                             fg_color=t.PANEL, border_color=t.BORDER)
        self.access_add_entry.pack(side="right", padx=(6, 0))
        ctk.CTkButton(access_header, text="Add", width=60, height=28, **t.primary_button_style(),
                      command=self._add_access_name).pack(side="right", padx=(6, 0))
        self.access_list_frame = ctk.CTkScrollableFrame(access_panel, fg_color=t.PANEL, height=120)
        self.access_list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.access_list_frame.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.access_list_frame)

    # ------------------------------------------------------------------ files

    def _build_files_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(parent, **st.card_style())
        panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        hdr = ctk.CTkFrame(panel, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        ctk.CTkLabel(hdr, text="📂  Server files", font=t.font(13, "bold"),
                     text_color=t.TEXT).pack(side="left")
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(btn_row, text="Refresh", width=80, height=30, **t.secondary_button_style(),
                      command=self._refresh_files_listing).pack(side="left")
        ctk.CTkButton(btn_row, text="Edit", width=64, height=30, **t.secondary_button_style(),
                      command=self._edit_selected_file).pack(side="left", padx=(6, 0))
        ctk.CTkButton(btn_row, text="Explorer", width=84, height=30, **t.secondary_button_style(),
                      command=self._open_server_folder).pack(side="left", padx=(6, 0))

        self.terraria_world_panel = ctk.CTkFrame(panel, **st.inset_style())
        self.terraria_world_panel.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.terraria_world_panel.grid_columnconfigure(0, weight=1)
        self.terraria_world_panel.grid_remove()
        ctk.CTkLabel(
            self.terraria_world_panel, text="Terraria world", font=t.font(12, "bold"), text_color=t.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self.terraria_world_status = ctk.CTkLabel(
            self.terraria_world_panel, text="", font=t.font(11), text_color=t.MUTED,
            anchor="w", justify="left", wraplength=520,
        )
        self.terraria_world_status.grid(row=1, column=0, sticky="ew", padx=10)
        self.terraria_world_hint = ctk.CTkLabel(
            self.terraria_world_panel,
            text="Import a .wld or copy one into the server folder — any filename works if it's the only world there.",
            font=t.font(10), text_color=t.MUTED, anchor="w", justify="left", wraplength=520,
        )
        self.terraria_world_hint.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 6))
        tw_btn_row = ctk.CTkFrame(self.terraria_world_panel, fg_color="transparent")
        tw_btn_row.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 10))
        ctk.CTkButton(
            tw_btn_row, text="Import world…", width=120, height=28, **t.primary_button_style(),
            command=self._import_terraria_world,
        ).pack(side="left")
        ctk.CTkButton(
            tw_btn_row, text="Open server folder", width=130, height=28, **t.secondary_button_style(),
            command=self._open_server_folder,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            tw_btn_row, text="Open Terraria saves", width=140, height=28, **t.secondary_button_style(),
            command=self._open_terraria_client_worlds,
        ).pack(side="left", padx=(8, 0))

        path_wrap = ctk.CTkFrame(panel, **st.inset_style())
        path_wrap.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.files_path_label = ctk.CTkLabel(
            path_wrap, text="/", font=t.mono(12), text_color=t.MUTED, anchor="w",
        )
        self.files_path_label.pack(fill="x", padx=10, pady=8)

        list_wrap = ctk.CTkFrame(panel, **st.inset_style())
        list_wrap.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        list_wrap.grid_columnconfigure(0, weight=1)
        list_wrap.grid_rowconfigure(0, weight=1)

        self.files_box = ctk.CTkTextbox(
            list_wrap, fg_color=t.PANEL_HOVER, font=t.mono(13), text_color=t.TEXT,
            state="disabled", wrap="none", corner_radius=t.RADIUS_SM,
        )
        self.files_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.files_box.tag_config("folder", foreground=t.ACCENT)
        self.files_box.tag_config("file", foreground=t.TEXT)
        self.files_box.tag_config("world", foreground=t.SUCCESS)
        self.files_box.tag_config("muted", foreground=t.MUTED)
        self.files_box.bind("<Double-Button-1>", self._on_files_double_click)
        self._files_listing: list[str] = []

    def _open_server_folder(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        path = self._server_dir(srv)
        path.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(path))

    # ------------------------------------------------------------------ mods

    def _minecraft_auth_status(self) -> None:
        if not hasattr(self, "minecraft_account_status"):
            return
        account = load_auth()
        if account and account.get("name"):
            self.minecraft_account_status.configure(text=f"Signed in: {account['name']}", text_color=t.SUCCESS)
            self.minecraft_signin_button.configure(text="Refresh Login")
            self.minecraft_signout_button.configure(state="normal")
        else:
            self.minecraft_account_status.configure(text="Not signed in", text_color=t.MUTED)
            self.minecraft_signin_button.configure(text="Sign in with Microsoft")
            self.minecraft_signout_button.configure(state="disabled")

    def _minecraft_sign_in(self) -> None:
        self.minecraft_signin_button.configure(state="disabled", text="Signing in…")
        self.minecraft_account_status.configure(
            text="Checking your official Minecraft Launcher login…", text_color=t.MUTED
        )

        def ask_for_redirect(auth_url: str) -> str | None:
            # Called from the worker thread. Show the dialog on the main
            # thread and block this worker until the user submits/cancels.
            done = threading.Event()
            holder: dict = {}

            def show() -> None:
                dlg = dialogs.MicrosoftSignInDialog(self, auth_url)
                self.wait_window(dlg)
                holder["value"] = dlg.result
                done.set()

            self.after(0, show)
            done.wait()
            return holder.get("value")

        def set_status(msg: str) -> None:
            self.after(0, lambda: self.minecraft_account_status.configure(text=msg, text_color=t.MUTED))

        def worker() -> None:
            try:
                account = minecraft_sign_in(on_code=ask_for_redirect, on_status=set_status)
                self.after(0, lambda: self._minecraft_auth_finished(account, None))
            except Exception as exc:
                self.after(0, lambda exc=exc: self._minecraft_auth_finished(None, exc))

        threading.Thread(target=worker, daemon=True, name="Minecraft-Launcher-Login").start()


    def _minecraft_auth_finished(self, account: dict | None, exc: Exception | None) -> None:
        if exc:
            self.modpack_status.configure(text=f"Minecraft sign-in failed: {exc}", text_color=t.DANGER)
        elif account:
            self.modpack_status.configure(
                text=f"Microsoft account connected: {account.get('name', '')}",
                text_color=t.SUCCESS,
            )
        self._minecraft_auth_status()
        self.minecraft_signin_button.configure(state="normal")

    def _minecraft_sign_out(self) -> None:
        minecraft_logout()
        self._minecraft_auth_status()
        self.modpack_status.configure(text="Minecraft account signed out.", text_color=t.MUTED)

    def _sync_modpack_profiles_from_disk(self, srv: dict) -> None:
        """Register existing modpack folders that are missing from config."""
        if not srv or srv.get("game_type") != "minecraft_java":
            return
        root = Path(srv.get("server_dir", "")) / "modpacks"
        if not root.is_dir():
            return
        profiles = self._modpack_profiles(srv)
        known_dirs = {str(p.get("dir_name") or "") for p in profiles.values()}
        changed = False
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name in known_dirs or folder.name.startswith(".") or folder.name == "__pycache__":
                continue
            name = folder.name
            minecraft_version = ""
            loader = ""
            manifest_path = folder / "manifest.json"
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    name = str(manifest.get("name") or name)
                    minecraft_version = str((manifest.get("minecraft") or {}).get("version") or "")
                    loaders = (manifest.get("minecraft") or {}).get("modLoaders") or []
                    if loaders:
                        lid = str((loaders[0] or {}).get("id") or "").lower()
                        loader = next((x for x in ("neoforge", "forge", "fabric", "quilt") if lid.startswith(x + "-")), "")
                except Exception:
                    pass
            profile_id = uuid.uuid4().hex[:10]
            profiles[profile_id] = {"name": name, "dir_name": folder.name, "provider": "curseforge",
                                    "minecraft_version": minecraft_version, "installed_version": minecraft_version,
                                    "loader": loader}
            known_dirs.add(folder.name)
            changed = True
        if changed:
            self._persist()

    def _refresh_modpacks_tab(self) -> None:
        srv = self._current_server()
        if not hasattr(self, "modpack_status"):
            return
        if not srv:
            self.modpack_status.configure(text="Select a server to manage modpacks.", text_color=t.MUTED)
            return
        if srv.get("game_type") != "minecraft_java":
            self.modpack_status.configure(text="Modpacks are available for Minecraft Java servers only.", text_color=t.MUTED)
            return
        self._sync_modpack_profiles_from_disk(srv)
        cfg = srv.get("config", {})
        if hasattr(self, "modpack_version_menu"):
            self._load_modpack_versions()
        if hasattr(self, "modpack_profile_menu"):
            labels = self._modpack_profile_labels(srv)
            none_label = "No modpack (base server files)"
            values = [none_label] + list(labels.keys())
            self.modpack_profile_menu.configure(values=values)
            active_id = str(cfg.get("active_modpack_profile") or "")
            active_label = next((lbl for lbl, pid in labels.items() if pid == active_id), none_label)
            self.modpack_profile_menu.set(active_label)
        name = cfg.get("modpack_name")
        if name:
            version = cfg.get("installed_version", "")
            loader = cfg.get("loader", "")
            count = len(self._modpack_profiles(srv))
            extra = f"  •  {count} modpack(s) installed" if count > 1 else ""
            self.modpack_status.configure(
                text=f"Loaded: {name}" + (f"  •  Minecraft {version}" if version else "") + (f"  •  {loader_name(loader)}" if loader else "") + extra,
                text_color=t.SUCCESS,
            )
        else:
            self.modpack_status.configure(text="Search CurseForge or import a modpack ZIP.", text_color=t.MUTED)

    def _modpack_profile_labels(self, srv: dict) -> dict[str, str]:
        """Map a distinct display label -> profile_id for the current server."""
        profiles = self._modpack_profiles(srv)
        labels: dict[str, str] = {}
        for pid, profile in profiles.items():
            base = str(profile.get("name") or "Modpack")
            label = base
            if label in labels:
                label = f"{base} ({pid[:6]})"
            labels[label] = pid
        return labels

    def _on_modpack_profile_selected(self, label: str) -> None:
        srv = self._current_server()
        if not srv:
            return
        if self._process(srv["id"]).running:
            messagebox.showwarning("Modpack", "Stop the server before switching modpacks.", parent=self.winfo_toplevel())
            self._refresh_modpacks_tab()
            return
        labels = self._modpack_profile_labels(srv)
        profile_id = labels.get(label, "")
        self._activate_modpack_profile(srv, profile_id)
        self._refresh_modpacks_tab()
        self._refresh_config_tab()
        self._refresh_overview()
        self._refresh_mods()

    def _repair_selected_modpack_loader(self) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            return
        if self._process(srv["id"]).running:
            messagebox.showwarning("Modpack", "Stop the server before repairing its loader.", parent=self.winfo_toplevel())
            return
        label = self.modpack_profile_menu.get()
        profile_id = self._modpack_profile_labels(srv).get(label, "")
        if not profile_id:
            self.modpack_status.configure(text="Select a modpack first.", text_color=t.DANGER)
            return
        profile = self._modpack_profiles(srv).get(profile_id) or {}
        folder = Path(srv["server_dir"]) / "modpacks" / str(profile.get("dir_name") or profile_id)
        if not folder.is_dir():
            self.modpack_status.configure(text="Modpack folder was not found.", text_color=t.DANGER)
            return
        if detect_loader(folder):
            self.modpack_status.configure(text="This modpack already has a server loader.", text_color=t.SUCCESS)
            return
        self.modpack_status.configure(text="Checking mod versions before loader installation…", text_color=t.MUTED)

        def work():
            try:
                conflict_report = scan_modpack_version_conflicts(folder)
                conflicts = conflict_report.get("conflicts", [])
                if conflicts:
                    dominant = conflict_report.get("dominant_version") or "unknown"
                    lines = [
                        "This modpack contains mods targeting a different Minecraft version.",
                        f"\nPrimary detected version: {dominant}",
                        "\nConflicting mods:",
                    ]
                    for item in conflicts[:60]:
                        lines.append(f"• {item['file']}  →  Minecraft {item['version']}")
                    if len(conflicts) > 60:
                        lines.append(f"… and {len(conflicts) - 60} more")
                    lines.append(
                        "\nYes = move ONLY these incompatible JARs into the modpack's "
                        "incompatible-mods folder and continue.\n"
                        "No = leave everything untouched and stop."
                    )
                    text = "\n".join(lines)
                    self.after(0, lambda text=text, conflicts=conflicts, folder=folder, dominant=dominant:
                               self._resolve_modpack_conflicts_before_loader(
                                   text, conflicts, folder, dominant, srv, profile_id, label
                               ))
                    return
                mc_version, loader, loader_version = infer_profile_loader(folder, label)
                if not mc_version or loader == "vanilla" or not loader_version:
                    raise RuntimeError("Could not determine a supported Minecraft loader for this modpack.")
                required = required_java_major(mc_version) if mc_version else None
                self.after(0, lambda: self._start_modpack_loader_repair(
                    srv, profile_id, label, folder, mc_version, loader, loader_version, required
                ))
            except Exception as exc:
                text = str(exc)
                self.after(0, lambda text=text: self.modpack_status.configure(
                    text=f"Loader repair failed: {text}", text_color=t.DANGER
                ))
        threading.Thread(target=work, daemon=True).start()

    def _resolve_modpack_conflicts_before_loader(self, text, conflicts, folder, dominant, srv, profile_id, label) -> None:
        """Try to replace conflicting JARs with CurseForge-compatible versions.

        We preserve every original JAR under .modpack_backup. If CurseForge's
        distribution/API permission blocks a replacement, the original is left
        in place and a MISSING_MODS.txt entry with a manual CurseForge link is
        written. Loader installation is stopped until the user resolves those
        remaining conflicts.
        """
        proceed = messagebox.askyesno(
            "Find Compatible Mod Versions",
            text + "\n\nYes = find and replace each conflicting mod with a compatible CurseForge version.\n"
                  "No = leave everything untouched and stop.",
            parent=self.winfo_toplevel(),
        )
        if not proceed:
            self.modpack_status.configure(
                text=f"Loader installation stopped: {len(conflicts)} conflicting mod(s) detected.",
                text_color=t.DANGER,
            )
            return

        self.modpack_status.configure(text="Finding compatible CurseForge versions…", text_color=t.MUTED)
        try:
            api_key = str(self.curseforge_key_var.get() or "").strip()
        except Exception:
            api_key = ""

        def work():
            replaced = []
            unresolved = []
            links = []
            for item in conflicts:
                src = folder / str(item.get("path") or item.get("file") or "")
                if not src.is_file():
                    continue
                ok, link = replace_with_compatible_curseforge_mod(
                    folder, src, api_key, dominant, infer_profile_loader(folder, label)[1]
                )
                if ok:
                    replaced.append(src.name)
                else:
                    unresolved.append(item)
                    links.append(build_missing_mod_entry(
                        src.name, dominant, infer_profile_loader(folder, label)[1],
                        project_url=link,
                        reason="No automatic replacement was available; the original file was preserved."
                    ))

            if links:
                try:
                    (folder / "MISSING_MODS.txt").write_text(
                        "These mods need manual attention before the server loader can be installed.\n"
                        "The original JARs were NOT deleted. Replace them with the compatible\n"
                        "Minecraft/loader version shown by the CurseForge link below.\n\n"
                        + "\n\n".join(links) + "\n", encoding="utf-8"
                    )
                except Exception:
                    pass

            self.after(0, lambda: self._finish_modpack_conflict_repair(
                folder, srv, profile_id, label, replaced, unresolved, dominant
            ))

        threading.Thread(target=work, daemon=True).start()

    def _finish_modpack_conflict_repair(self, folder, srv, profile_id, label, replaced, unresolved, dominant):
        if unresolved:
            msg = (
                f"Replaced {len(replaced)} compatible mod(s).\n\n"
                f"{len(unresolved)} mod(s) could not be replaced automatically.\n"
                "See MISSING_MODS.txt for the CurseForge links.\n\n"
                "The original JARs were preserved, and the loader was NOT installed."
            )
            messagebox.showwarning("Manual Mod Replacement Required", msg, parent=self.winfo_toplevel())
            self.modpack_status.configure(
                text=f"{len(unresolved)} mod conflict(s) need manual replacement. See MISSING_MODS.txt.",
                text_color=t.DANGER,
            )
            return

        def work():
            try:
                report = scan_modpack_version_conflicts(folder)
                remaining = report.get("conflicts", [])
                if remaining:
                    self.after(0, lambda: self.modpack_status.configure(
                        text=f"{len(remaining)} Minecraft-version conflict(s) remain. See MISSING_MODS.txt.",
                        text_color=t.DANGER,
                    ))
                    return
                mc_version, loader, loader_version = infer_profile_loader(folder, label)
                if not mc_version or loader == "vanilla" or not loader_version:
                    raise RuntimeError("Could not determine a supported Minecraft loader for this modpack.")
                required = required_java_major(mc_version) if mc_version else None
                self.after(0, lambda: self._start_modpack_loader_repair(
                    srv, profile_id, label, folder, mc_version, loader, loader_version, required
                ))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda msg=msg: self.modpack_status.configure(
                    text=f"Loader repair failed: {msg}", text_color=t.DANGER
                ))
        threading.Thread(target=work, daemon=True).start()

    def _start_modpack_loader_repair(self, srv, profile_id, label, folder, mc_version, loader, loader_version, required_java) -> None:
        runtime_match = next((r for r in self._java_runtimes if r.major == required_java), None) if required_java else None
        if required_java and not runtime_match:
            self.modpack_status.configure(
                text=f"Minecraft {mc_version} needs Java {required_java}; installing it…", text_color=t.MUTED
            )
            self._install_required_java_async(
                required_java,
                lambda: self._start_modpack_loader_repair(srv, profile_id, label, folder, mc_version, loader, loader_version, required_java),
            )
            return
        java_path = runtime_match.path if runtime_match else self.java_path.get()
        self.modpack_status.configure(
            text=f"Installing {loader_name(loader)} {loader_version} for Minecraft {mc_version}…", text_color=t.MUTED
        )
        worker = create_modpack_loader_repair_worker(
            folder, label, java_path=java_path,
            min_mb=self._mem_mb(self.min_mb, 1024), max_mb=self._mem_mb(self.max_mb, 2048),
        )
        previous = str(srv.get("config", {}).get("active_modpack_profile") or "")
        self._begin_modpack_worker(
            worker, {"name": label}, None,
            extra_meta={"profile_id": profile_id, "previous_profile_id": previous, "loader_repair": True},
        )

    def _remove_selected_modpack_profile(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        label = self.modpack_profile_menu.get()
        labels = self._modpack_profile_labels(srv)
        profile_id = labels.get(label, "")
        if not profile_id:
            return
        if self._process(srv["id"]).running and str(srv.get("config", {}).get("active_modpack_profile") or "") == profile_id:
            messagebox.showwarning("Modpack", "Stop the server before removing the loaded modpack.", parent=self.winfo_toplevel())
            return
        if not messagebox.askyesno(
            "Remove Modpack", f'Remove "{label}" and delete its files? This cannot be undone.',
            parent=self.winfo_toplevel(),
        ):
            return
        self._remove_modpack_profile(srv, profile_id)
        self._refresh_modpacks_tab()
        self._refresh_config_tab()
        self._refresh_overview()
        self._refresh_mods()

    def _build_modpacks_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(7, weight=1)
        ctk.CTkLabel(parent, text="Minecraft Modpacks", font=t.font(15, "bold"), text_color=t.TEXT).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12, 4)
        )
        self.modpack_status = ctk.CTkLabel(parent, text="", font=t.font(10), text_color=t.MUTED,
                                            anchor="w", justify="left", wraplength=620)
        self.modpack_status.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self._modpack_missing_links: list[str] = []
        self.modpack_copy_links_btn = ctk.CTkButton(
            parent, text="Copy Links", width=110, height=24, font=t.font(10),
            command=self._copy_modpack_missing_links,
        )
        self.modpack_copy_links_btn.grid(row=1, column=1, sticky="e", padx=12, pady=(0, 8))
        self.modpack_copy_links_btn.grid_remove()

        auth_row = ctk.CTkFrame(parent, fg_color="transparent")
        auth_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.minecraft_account_status = ctk.CTkLabel(
            auth_row, text="Not signed in", font=t.font(10), text_color=t.MUTED, anchor="w"
        )
        self.minecraft_account_status.pack(side="left", fill="x", expand=True)
        self.minecraft_signin_button = ctk.CTkButton(
            auth_row, text="Sign in with Microsoft", width=150, height=28,
            **t.secondary_button_style(), command=self._minecraft_sign_in,
        )
        self.minecraft_signin_button.pack(side="right")
        self.minecraft_signout_button = ctk.CTkButton(
            auth_row, text="Sign out", width=70, height=28,
            **t.secondary_button_style(), command=self._minecraft_sign_out,
        )
        self.minecraft_signout_button.pack(side="right", padx=(0, 8))

        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        controls.grid_columnconfigure(0, weight=1)
        self.modpack_search_entry = ctk.CTkEntry(controls, placeholder_text="Search CurseForge modpacks…",
                                                 fg_color=t.PANEL, border_color=t.BORDER)
        self.modpack_search_entry.grid(row=0, column=0, sticky="ew")
        self.modpack_search_entry.bind("<Return>", lambda _e: self._search_curseforge_modpacks())
        ctk.CTkButton(controls, text="Search", width=82, **t.primary_button_style(),
                      command=self._search_curseforge_modpacks).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(controls, text="Import ZIP", width=90, **t.secondary_button_style(),
                      command=self._import_modpack_zip).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkButton(controls, text="Play Modpack", width=105, **t.secondary_button_style(),
                      command=self._launch_installed_modpack).grid(row=0, column=3, padx=(8, 0))

        profile_row = ctk.CTkFrame(parent, fg_color="transparent")
        profile_row.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 8))
        ctk.CTkLabel(profile_row, text="Loaded modpack", font=t.font(10), text_color=t.MUTED).pack(side="left")
        self.modpack_profile_menu = ctk.CTkOptionMenu(
            profile_row, values=["No modpack (base server files)"], width=260,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_modpack_profile_selected,
        )
        self.modpack_profile_menu.pack(side="left", padx=(8, 0))
        ctk.CTkButton(profile_row, text="Repair Loader", width=100, height=26,
                      **t.secondary_button_style(), command=self._repair_selected_modpack_loader).pack(side="left", padx=(8, 0))
        ctk.CTkButton(profile_row, text="Remove", width=80, height=26,
                      **t.secondary_button_style(), command=self._remove_selected_modpack_profile).pack(side="left", padx=(8, 0))

        version_row = ctk.CTkFrame(parent, fg_color="transparent")
        version_row.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 8))
        ctk.CTkLabel(version_row, text="Minecraft version", font=t.font(10), text_color=t.MUTED).pack(side="left")
        self.modpack_version_menu = ctk.CTkOptionMenu(
            version_row, values=["Use server version", "Latest"], width=170,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_modpack_version_selected,
        )
        self.modpack_version_menu.pack(side="left", padx=(8, 0))
        ctk.CTkButton(version_row, text="Load Versions", width=100, height=26,
                      **t.secondary_button_style(), command=self._load_modpack_versions).pack(side="left", padx=(8, 0))

        key_row = ctk.CTkFrame(parent, fg_color="transparent")
        key_row.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 8))
        key_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(key_row, text="CurseForge API key", font=t.font(10), text_color=t.MUTED).grid(row=0, column=0, sticky="w")
        self.curseforge_key_var = ctk.StringVar(value=str(self._curseforge_settings.get("curseforge_api_key", "")))
        self.curseforge_key_entry = ctk.CTkEntry(key_row, textvariable=self.curseforge_key_var, show="•",
                                                 fg_color=t.PANEL, border_color=t.BORDER)
        self.curseforge_key_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ctk.CTkButton(key_row, text="Save Key", width=82, **t.secondary_button_style(),
                      command=self._save_curseforge_key).grid(row=0, column=2)

        self.modpack_results = ctk.CTkScrollableFrame(parent, **st.inset_style())
        self.modpack_results.grid(row=7, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.modpack_results.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.modpack_results,
                     text="Search CurseForge or import a CurseForge .zip / server pack.\n"
                          "Manifest-based packs require an API key to download their mod files.",
                     font=t.font(11), text_color=t.MUTED, justify="left", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=8, pady=12
        )

        self._minecraft_auth_status()

    def _load_modpack_versions(self) -> None:
        if not self._mc_versions:
            self._load_mc_versions_async()
            self.modpack_status.configure(text="Loading Minecraft versions…", text_color=t.MUTED)
            return
        versions = [v.id for v in self._mc_versions if getattr(v, "type", "release") == "release"]
        versions = ["Automatic (latest)", "Use server version"] + versions
        self.modpack_version_menu.configure(values=versions)
        srv = self._current_server()
        current = str((srv or {}).get("config", {}).get("minecraft_version", ""))
        selected = current if current in versions else "Automatic (latest)"
        self.modpack_version_menu.set(selected)
        self._modpack_minecraft_version = current if selected == "Use server version" else ("" if selected == "Automatic (latest)" else selected)

    def _on_modpack_version_selected(self, value: str) -> None:
        srv = self._current_server()
        server_version = str((srv or {}).get("config", {}).get("minecraft_version", ""))
        if value == "Use server version":
            self._modpack_minecraft_version = server_version
        elif value == "Automatic (latest)":
            self._modpack_minecraft_version = ""
        else:
            self._modpack_minecraft_version = value
        if self._modpack_minecraft_version:
            self.modpack_status.configure(text=f"Modpack search/install restricted to Minecraft {self._modpack_minecraft_version}.", text_color=t.MUTED)

    def _minecraft_modpack_available(self) -> bool:
        srv = self._current_server()
        return bool(srv and srv.get("game_type") == "minecraft_java")

    def _save_curseforge_key(self) -> None:
        key = self.curseforge_key_var.get().strip()
        self._curseforge_settings["curseforge_api_key"] = key
        save_manager_settings(self._curseforge_settings)
        self.modpack_status.configure(text="CurseForge API key saved.", text_color=t.SUCCESS)

    def _search_curseforge_modpacks(self) -> None:
        if not self._minecraft_modpack_available():
            self.modpack_status.configure(text="Select a Minecraft Java server first.", text_color=t.DANGER)
            return
        key = self.curseforge_key_var.get().strip()
        if not key:
            self.modpack_status.configure(text="Enter and save a CurseForge API key first.", text_color=t.DANGER)
            return
        query = self.modpack_search_entry.get().strip()
        self.modpack_status.configure(text=f"Searching CurseForge{f" for Minecraft {self._modpack_minecraft_version}" if self._modpack_minecraft_version else ""}…", text_color=t.MUTED)
        for child in self.modpack_results.winfo_children():
            child.destroy()

        def work():
            try:
                results = search_modpacks(key, query)
                self.after(0, lambda: self._show_curseforge_results(results))
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda error_text=error_text: self.modpack_status.configure(
                    text=f"CurseForge search failed: {error_text}", text_color=t.DANGER
                ))
        threading.Thread(target=work, daemon=True).start()

    def _show_curseforge_results(self, results: list[dict]) -> None:
        self._curseforge_results = results
        for child in self.modpack_results.winfo_children():
            child.destroy()
        if not results:
            ctk.CTkLabel(self.modpack_results, text="No modpacks found.", text_color=t.MUTED).grid(row=0, column=0, padx=8, pady=12)
            self.modpack_status.configure(text="No results.", text_color=t.MUTED)
            return
        self.modpack_status.configure(text=f"Found {len(results)} modpacks.", text_color=t.MUTED)
        for row, pack in enumerate(results):
            frame = ctk.CTkFrame(self.modpack_results, **st.card_style())
            frame.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
            frame.grid_columnconfigure(0, weight=1)
            name = str(pack.get("name") or "Unnamed Modpack")
            summary = str(pack.get("summary") or "").replace("\n", " ")
            downloads = pack.get("downloadCount")
            text = name
            if downloads is not None:
                text += f"  •  {int(downloads):,} downloads"
            ctk.CTkLabel(frame, text=text, font=t.font(12, "bold"), text_color=t.TEXT, anchor="w").grid(
                row=0, column=0, sticky="ew", padx=10, pady=(8, 2)
            )
            ctk.CTkLabel(frame, text=summary[:180], font=t.font(10), text_color=t.MUTED,
                         anchor="w", justify="left", wraplength=500).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
            ctk.CTkButton(frame, text="Install Latest", width=105, height=28, **t.primary_button_style(),
                          command=lambda p=pack: self._install_curseforge_project(p)).grid(row=0, column=1, rowspan=2, padx=10)

    def _install_curseforge_project(self, project: dict) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            return
        if not self._eula_var.get():
            self.modpack_status.configure(text="Accept Mojang's EULA in Config before installing a modpack.", text_color=t.DANGER)
            return
        if self._process(srv["id"]).running:
            messagebox.showwarning("Modpack", "Stop the server before installing a modpack.", parent=self.winfo_toplevel())
            return
        key = self.curseforge_key_var.get().strip()
        if not key:
            self.modpack_status.configure(text="Enter a CurseForge API key first.", text_color=t.DANGER)
            return
        project_id = int(project.get("id") or 0)
        if not project_id:
            self.modpack_status.configure(text="CurseForge project has no valid ID.", text_color=t.DANGER)
            return
        self.modpack_status.configure(text=f"Finding latest file for {project.get('name', 'modpack')}…", text_color=t.MUTED)
        def work():
            try:
                # Modpacks determine their own Minecraft version. The
                # selected/server Minecraft version is only a hint for the UI;
                # it must never prevent us from finding the correct modpack
                # release (e.g. SkyFactory 4 is 1.12.2).
                target_version = ""
                files = get_latest_project_files(key, project_id)
                auto_selected = bool(files)

                # If the normal file listing is unavailable, use the project's
                # latestFilesIndexes as a fallback.

                # Some CurseForge API responses expose latestFilesIndexes on
                # the project but return no rows from /files for legacy packs.
                # Use those file IDs as a final fallback, then fetch the full
                # file records. This is especially important for old packs
                # such as SkyFactory 4.
                if not files:
                    indexes = project.get("latestFilesIndexes") or []
                    candidates = []
                    for item in indexes:
                        if not isinstance(item, dict):
                            continue
                        fid = int(item.get("fileId") or 0)
                        if not fid:
                            continue
                        gv = str(item.get("gameVersion") or "")
                        if target_version and gv and gv != target_version:
                            continue
                        candidates.append((fid, gv))
                    if not candidates and target_version:
                        for item in indexes:
                            if not isinstance(item, dict):
                                continue
                            fid = int(item.get("fileId") or 0)
                            if fid:
                                candidates.append((fid, str(item.get("gameVersion") or "")))
                        auto_selected = bool(candidates)
                    for fid, gv in candidates[:25]:
                        try:
                            info = get_file(key, project_id, fid)
                            if isinstance(info, dict):
                                files.append(info)
                        except Exception:
                            continue
                    auto_selected = auto_selected or bool(files)

                if not files:
                    raise RuntimeError(
                        "CurseForge returned no downloadable files for this modpack. "
                        "Check that your API key has access to the project."
                    )

                files.sort(key=lambda f: str(f.get("fileDate") or ""), reverse=True)

                def is_server_pack_file(item: dict) -> bool:
                    if item.get("serverPackFileId") or item.get("isServerPack"):
                        return True
                    name = str(item.get("displayName") or item.get("fileName") or "").lower()
                    return (
                        "server pack" in name
                        or "server files" in name
                        or "_server_" in name
                        or name.endswith("_server.zip")
                    )

                # Prefer a dedicated server-pack file. If the client release
                # points at a separate serverPackFileId, the worker resolves
                # that exact child file after this selection.
                server_pack_files = [item for item in files if is_server_pack_file(item)]
                release_files = [
                    item for item in files
                    if int(item.get("releaseType") or 1) == 1
                ]

                # Prefer a server pack. Among server packs, prefer one that
                # actually declares a Minecraft version, then the newest one.
                candidates = server_pack_files or release_files or files
                candidates = sorted(
                    candidates,
                    key=lambda item: (
                        bool([
                            v for v in (item.get("gameVersions") or [])
                            if re.fullmatch(r"1\.\d+(?:\.\d+)?", str(v))
                        ]),
                        str(item.get("fileDate") or ""),
                    ),
                    reverse=True,
                )
                f = candidates[0]

                if auto_selected:
                    versions = [str(v) for v in (f.get("gameVersions") or [])]
                    mc_versions = [
                        v for v in versions
                        if re.fullmatch(r"1\.\d+(?:\.\d+)?", v)
                    ]
                    if mc_versions:
                        selected_mc = mc_versions[0]
                        self._modpack_minecraft_version = selected_mc
                        self.after(
                            0,
                            lambda v=selected_mc: self.modpack_status.configure(
                                text=f"Automatically selected Minecraft {v} for this modpack.",
                                text_color=t.MUTED,
                            ),
                        )
                # Modpacks determine their own Minecraft version. Pick the Java
                # runtime for that detected version instead of blindly using the
                # Java configured for the server's old/current vanilla version.
                detected_java_major = required_java_major(
                    selected_mc if 'selected_mc' in locals() else
                    (mc_versions[0] if mc_versions else "")
                ) if (('selected_mc' in locals() and selected_mc) or mc_versions) else None

                def launch_modpack_worker(java_path_for_pack=None):
                    previous_profile = str(srv.get("config", {}).get("active_modpack_profile") or "")
                    profile_id = self._new_modpack_profile(srv, str(project.get("name") or "CurseForge Modpack"))
                    self._activate_modpack_profile(srv, profile_id)
                    worker = create_curseforge_download_worker(
                        self._server_dir(srv), key, project_id, int(f["id"]),
                        java_path=java_path_for_pack or self.java_path.get(),
                        min_mb=self._mem_mb(self.min_mb, 1024), max_mb=self._mem_mb(self.max_mb, 2048),
                        project_name=str(project.get("name") or "CurseForge Modpack"),
                    )
                    self.after(0, lambda: self._begin_modpack_worker(
                        worker, project, f,
                        extra_meta={"profile_id": profile_id, "previous_profile_id": previous_profile},
                    ))

                if detected_java_major:
                    runtime_match = next(
                        (r for r in self._java_runtimes if r.major == detected_java_major),
                        None,
                    )
                    if runtime_match:
                        self.java_path.set(runtime_match.path)
                        # Java installed under Program Files (x86) is a 32-bit
                        # JVM. A 2 GB heap cannot be reserved reliably by it.
                        if "program files (x86)" in runtime_match.path.lower():
                            self.min_mb.set(str(min(self._mem_mb(self.min_mb, 1024), 512)))
                            self.max_mb.set(str(min(self._mem_mb(self.max_mb, 2048), 1024)))
                        self._append_console_line(
                            f"[Modpack] Using Java {detected_java_major} for Minecraft {selected_mc}: {runtime_match.path}"
                        )
                        self.after(0, lambda p=runtime_match.path: launch_modpack_worker(p))
                    else:
                        self.after(
                            0,
                            lambda req=detected_java_major: self._install_required_java_async(
                                req,
                                lambda: launch_modpack_worker(
                                    next((r.path for r in self._java_runtimes if r.major == req), self.java_path.get())
                                ),
                            ),
                        )
                else:
                    self.after(0, launch_modpack_worker)
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda error_text=error_text: self.modpack_status.configure(
                    text=f"Modpack lookup failed: {error_text}", text_color=t.DANGER
                ))
        threading.Thread(target=work, daemon=True).start()

    def _set_modpack_missing_links(self, urls: list[str]) -> None:
        self._modpack_missing_links = urls
        if urls:
            self.modpack_copy_links_btn.grid()
        else:
            self.modpack_copy_links_btn.grid_remove()

    def _copy_modpack_missing_links(self) -> None:
        if not self._modpack_missing_links:
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(self._modpack_missing_links))
        self.modpack_copy_links_btn.configure(text="Copied!")
        self.after(1500, lambda: self.modpack_copy_links_btn.configure(text="Copy Links"))

    def _launch_installed_modpack(self) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            self.modpack_status.configure(text="Select a Minecraft Java server first.", text_color=t.DANGER)
            return
        cfg = srv.get("config", {})
        name = str(cfg.get("modpack_name") or "").strip()
        mc_version = str(cfg.get("minecraft_version") or cfg.get("installed_version") or "").strip()
        if not mc_version:
            # Older imports (before the extractor recorded a version for
            # manifest-less server-pack ZIPs) can have this saved blank.
            # Recover it from the files already on disk instead of forcing
            # a full reinstall/redownload.
            server_dir = self._server_dir(srv)
            detected = detect_minecraft_version(server_dir)
            if detected:
                mc_version = detected
                cfg["minecraft_version"] = detected
                cfg["installed_version"] = detected
                self._persist()
        loader = str(cfg.get("loader") or "").lower()
        loader_version = str(cfg.get("loader_version") or "").strip()
        if not name:
            self.modpack_status.configure(text="Install a modpack first.", text_color=t.DANGER)
            return
        if not loader:
            loader = "vanilla"
        supported_loaders = {"forge", "neoforge", "fabric", "quilt", "vanilla"}
        if loader not in supported_loaders:
            self.modpack_status.configure(
                text=f"Client launcher preparation does not yet support {loader or 'unknown'} modpacks.",
                text_color=t.DANGER,
            )
            return
        java_path = str(cfg.get("java_path") or self.java_path.get() or "java")
        server_dir = self._server_dir(srv)
        active_profile = str(cfg.get("active_modpack_profile") or "")
        instance_id = f'{srv.get("id") or "default"}-{active_profile}' if active_profile else str(srv.get("id") or "default")
        prep_label = f"Minecraft {mc_version}" if loader == "vanilla" else f"Minecraft {mc_version} + {loader.title()} {loader_version}"
        self.modpack_status.configure(
            text=f"Preparing {prep_label}…",
            text_color=t.MUTED,
        )
        self._set_modpack_missing_links([])

        def work():
            try:
                client_dir, version_id = prepare_client(
                    server_dir,
                    mc_version,
                    loader,
                    loader_version,
                    java_path,
                    name,
                    instance_id,
                    curseforge_api_key=self.curseforge_key_var.get().strip(),
                    project_id=int(cfg.get("modpack_project_id") or 0),
                    file_id=int(cfg.get("modpack_file_id") or 0),
                )
                self.after(0, lambda: self.modpack_status.configure(
                    text=f"Launching Minecraft {version_id}…", text_color=t.MUTED
                ))
                self.after(0, lambda: self._finish_modpack_launch(client_dir, version_id, java_path, cfg, srv.get("id")))
            except ModpackDownloadError as exc:
                error_text = str(exc)
                links = [url for _name, url in exc.entries if url]
                self.after(0, lambda error_text=error_text: self.modpack_status.configure(
                    text=f"Minecraft client preparation failed: {error_text}", text_color=t.DANGER
                ))
                self.after(0, lambda links=links: self._set_modpack_missing_links(links))
            except Exception as exc:
                error_text = str(exc)
                self.after(0, lambda error_text=error_text: self.modpack_status.configure(
                    text=f"Minecraft client preparation failed: {error_text}", text_color=t.DANGER
                ))

        threading.Thread(target=work, daemon=True).start()

    def _finish_modpack_launch(self, client_dir: Path, version_id: str, java_path: str, cfg: dict, server_id: str | None = None) -> None:
        try:
            min_mb = int(cfg.get("min_mb", 1024) or 1024)
            max_mb = int(cfg.get("max_mb", 4096) or 4096)
            applied_min, applied_max, mc_proc = launch_minecraft_direct(client_dir, version_id, java_path, min_mb, max_mb)
            self.modpack_status.configure(
                text=f"Minecraft {version_id} launched directly. The Minecraft Launcher was not opened.",
                text_color=t.SUCCESS,
            )
            self._append_console_line(
                f"[Modpack] Launched {version_id} directly; game directory: {client_dir}",
                server_id=server_id,
            )
            self._stream_minecraft_client_output(mc_proc, version_id, server_id)
            mismatch_note = ""
            if applied_min != min_mb or applied_max != max_mb:
                probe_notes = get_last_heap_probe_notes()
                if probe_notes:
                    mismatch_note = (
                        f" — Java rejected {max_mb} MB, so it was auto-reduced "
                        f"to what your JVM will actually accept: "
                        + "; ".join(probe_notes)
                    )
                else:
                    mismatch_note = (
                        " — mismatch: either Config → Min/Max MB wasn't saved "
                        "before launching, or Java was detected as 32-bit and "
                        "clamped to 1024 MB max"
                    )
            self._append_console_line(
                f"[Modpack] Heap: -Xms{applied_min}M -Xmx{applied_max}M "
                f"(requested {min_mb}/{max_mb} MB){mismatch_note}",
                server_id=server_id,
            )
        except Exception as exc:
            error_text = str(exc)
            # If the only missing piece is an existing launcher login, give a
            # clear one-time setup message rather than silently opening it.
            self.modpack_status.configure(
                text=f"Could not launch Minecraft directly: {error_text}",
                text_color=t.DANGER,
            )
            self._append_console_line(f"[Modpack] Direct launch failed: {error_text}", server_id=server_id)

    def _stream_minecraft_client_output(self, proc, version_id: str, server_id: str | None) -> None:
        """Read the Minecraft client's piped stdout/stderr in a background
        thread and forward each line into the manager's own console instead
        of leaving it to print to whatever terminal launched the manager."""
        def read_loop():
            try:
                assert proc.stdout is not None
                for raw_line in proc.stdout:
                    line = raw_line.rstrip("\r\n")
                    if not line:
                        continue
                    self.after(0, lambda l=line: self._append_console_line(f"[Minecraft] {l}", server_id=server_id))
            except Exception:
                pass
            finally:
                exit_code = proc.wait()
                self.after(
                    0,
                    lambda: self._append_console_line(
                        f"[Minecraft] {version_id} exited (code {exit_code}).", server_id=server_id
                    ),
                )

        threading.Thread(target=read_loop, daemon=True).start()

    def _import_modpack_zip(self) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            self.modpack_status.configure(text="Select a Minecraft Java server first.", text_color=t.DANGER)
            return
        if not self._eula_var.get():
            self.modpack_status.configure(text="Accept Mojang's EULA in Config before installing a modpack.", text_color=t.DANGER)
            return
        if self._process(srv["id"]).running:
            messagebox.showwarning("Modpack", "Stop the server before importing a modpack.", parent=self.winfo_toplevel())
            return
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title="Select Minecraft Modpack",
                                          filetypes=[("Modpack ZIP", "*.zip"), ("All files", "*.*")])
        if not path:
            return

        def launch(java_path_for_pack: str | None = None) -> None:
            previous_profile = str(srv.get("config", {}).get("active_modpack_profile") or "")
            profile_id = self._new_modpack_profile(srv, Path(path).stem)
            self._activate_modpack_profile(srv, profile_id)
            worker = create_modpack_install_worker(
                self._server_dir(srv), Path(path), self.curseforge_key_var.get().strip(),
                java_path=java_path_for_pack or self.java_path.get(),
                min_mb=self._mem_mb(self.min_mb, 1024), max_mb=self._mem_mb(self.max_mb, 2048),
                project_name=Path(path).stem,
            )
            self._begin_modpack_worker(
                worker, {"name": Path(path).stem}, None,
                extra_meta={"profile_id": profile_id, "previous_profile_id": previous_profile},
            )

        # A ZIP's manifest declares its own Minecraft version, which can be
        # older than whatever Java the server currently has configured
        # (e.g. a 1.16.5 pack needs Java 8, not the Java 17/21 a newer
        # vanilla server on the same profile might be using). The
        # CurseForge search-and-install flow already resolves the right
        # runtime before installing; Import ZIP previously just used
        # self.java_path.get() unconditionally, which could hand a modern
        # JDK to an old Forge installer and cause it to fail.
        mc_version = peek_manifest_minecraft_version(Path(path))
        required_java = required_java_major(mc_version) if mc_version else None
        if not required_java:
            launch()
            return
        runtime_match = next((r for r in self._java_runtimes if r.major == required_java), None)
        if runtime_match:
            self.java_path.set(runtime_match.path)
            if "program files (x86)" in runtime_match.path.lower():
                self.min_mb.set(str(min(self._mem_mb(self.min_mb, 1024), 512)))
                self.max_mb.set(str(min(self._mem_mb(self.max_mb, 2048), 1024)))
            self._append_console_line(
                f"[Modpack] Using Java {required_java} for Minecraft {mc_version}: {runtime_match.path}"
            )
            launch(runtime_match.path)
        else:
            self.modpack_status.configure(
                text=f"Minecraft {mc_version} needs Java {required_java}; installing it…",
                text_color=t.MUTED,
            )
            self._install_required_java_async(
                required_java,
                lambda req=required_java: launch(
                    next((r.path for r in self._java_runtimes if r.major == req), self.java_path.get())
                ),
            )


    def _begin_modpack_worker(self, worker, project: dict, file_info: dict | None, extra_meta: dict | None = None) -> None:
        if self._download_worker is not None and self._download_worker.is_alive():
            self.modpack_status.configure(text="Another installation is already running.", text_color=t.DANGER)
            return
        self._download_worker = worker
        self._download_meta = {
            "game": "modpack",
            "project_id": int(project.get("id") or 0) if isinstance(project, dict) else 0,
            "file_id": int(file_info.get("id") or 0) if file_info else 0,
            "project_name": str(project.get("name") or "Modpack") if isinstance(project, dict) else "Modpack",
        }
        self._download_meta.update(extra_meta or {})
        self.modpack_status.configure(text="Installing modpack…", text_color=t.MUTED)
        self._append_console_line(f"[Modpack] Installing {self._download_meta['project_name']}…")
        worker.start()
        self._poll_download()

    def _build_mods_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        panel = ctk.CTkFrame(parent, **st.card_style())
        panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        hdr = ctk.CTkFrame(panel, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        ctk.CTkLabel(hdr, text="🧩  Mods & plugins", font=t.font(13, "bold"),
                     text_color=t.TEXT).pack(side="left")
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(btn_row, text="Refresh", width=80, height=30, **t.secondary_button_style(),
                      command=self._refresh_mods).pack(side="left")
        ctk.CTkButton(btn_row, text="Open folder", width=96, height=30, **t.secondary_button_style(),
                      command=self._open_mods_folder).pack(side="left", padx=(6, 0))
        self.mods_modrinth_btn = ctk.CTkButton(
            btn_row, text="Modrinth", width=88, height=30, **t.secondary_button_style(),
            command=lambda: self._open_mod_browser("modrinth"),
        )
        self.mods_modrinth_btn.pack(side="left", padx=(6, 0))
        self.mods_curseforge_btn = ctk.CTkButton(
            btn_row, text="CurseForge", width=96, height=30, **t.secondary_button_style(),
            command=lambda: self._open_mod_browser("curseforge"),
        )
        self.mods_curseforge_btn.pack(side="left", padx=(6, 0))

        path_wrap = ctk.CTkFrame(panel, **st.inset_style())
        path_wrap.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.mods_hint = ctk.CTkLabel(
            path_wrap, text="", font=t.mono(12), text_color=t.MUTED, anchor="w", wraplength=560, justify="left",
        )
        self.mods_hint.pack(fill="x", padx=10, pady=8)

        list_wrap = ctk.CTkFrame(panel, **st.inset_style())
        list_wrap.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        list_wrap.grid_columnconfigure(0, weight=1)
        list_wrap.grid_rowconfigure(0, weight=1)

        self.mods_empty_label = ctk.CTkLabel(
            list_wrap, text="No mods installed yet.\nDrop .jar files into the mods folder or browse Modrinth / CurseForge.",
            font=t.font(12), text_color=t.MUTED, justify="center",
        )
        self.mods_box = ctk.CTkTextbox(
            list_wrap, fg_color=t.PANEL_HOVER, font=t.mono(13), text_color=t.TEXT,
            state="disabled", wrap="none", corner_radius=t.RADIUS_SM,
        )
        self.mods_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _collect_mod_files(self, adapter, server_dir: Path) -> list[Path]:
        return adapter.collect_mod_files(server_dir)

    def _refresh_mods(self) -> None:
        adapter = self._current_adapter()
        srv = self._current_server()
        if not adapter or not srv:
            return
        browser_urls = adapter.mods_browser_urls()
        if browser_urls.get("modrinth"):
            self.mods_modrinth_btn.pack(side="left", padx=(6, 0))
        else:
            self.mods_modrinth_btn.pack_forget()
        if browser_urls.get("curseforge"):
            self.mods_curseforge_btn.pack(side="left", padx=(6, 0))
        else:
            self.mods_curseforge_btn.pack_forget()
        if not adapter.supports_mods() and not (
            hasattr(adapter, "supports_mods_for")
            and adapter.supports_mods_for(srv.get("config", {}))
        ):
            hint = f"{adapter.display_name} does not use a mods folder."
            if adapter.game_type == "terraria":
                hint = "Vanilla Terraria has no mods folder. Set Server type to tModLoader in Config."
            self.mods_hint.configure(text=hint)
            self.mods_box.grid_remove()
            self.mods_empty_label.configure(
                text=f"Mods aren't supported for {adapter.display_name} servers.",
            )
            self.mods_empty_label.grid(row=0, column=0, sticky="nsew")
            return
        server_dir = self._server_dir(srv)
        mod_dirs = adapter.mods_directories(server_dir)
        if not mod_dirs:
            primary = adapter.mods_directory(server_dir)
            mod_dirs = [primary] if primary else [server_dir / "mods"]
        self.mods_hint.configure(text="\n".join(str(d) for d in mod_dirs))
        files = self._collect_mod_files(adapter, server_dir)
        if not files:
            self.mods_box.grid_remove()
            self.mods_empty_label.configure(text=adapter.mods_empty_message())
            self.mods_empty_label.grid(row=0, column=0, sticky="nsew")
            return
        self.mods_empty_label.grid_remove()
        self.mods_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        lines = []
        for f in files:
            try:
                rel = f.relative_to(server_dir)
            except ValueError:
                rel = f
            try:
                size = _human_size(f.stat().st_size)
                lines.append(f"📄  {rel}  ({size})")
            except OSError:
                lines.append(f"📄  {rel}")
        self.mods_box.configure(state="normal")
        self.mods_box.delete("1.0", "end")
        self.mods_box.insert("1.0", "\n".join(lines))
        self.mods_box.configure(state="disabled")

    def _open_mods_folder(self) -> None:
        adapter = self._current_adapter()
        srv = self._current_server()
        if not adapter or not srv:
            return
        mods_dir = adapter.mods_directory(self._server_dir(srv)) or (self._server_dir(srv) / "mods")
        mods_dir.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(mods_dir))

    # ------------------------------------------------------------------ backups

    def _build_backups_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(parent, text="Zip the entire server folder. Restore overwrites files in the server folder.",
                     font=t.font(12), text_color=t.MUTED, anchor="w", wraplength=520
                     ).grid(row=0, column=0, sticky="w", pady=(4, 8))
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(bar, text="Create Backup", **t.primary_button_style(),
                      command=self._create_backup).pack(side="left")
        ctk.CTkButton(bar, text="Refresh List", width=100, **t.secondary_button_style(),
                      command=self._refresh_backups).pack(side="left", padx=(8, 0))

        sched = ctk.CTkFrame(parent, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        sched.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.backup_enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(sched, text="Scheduled backups while server is running",
                        variable=self.backup_enabled_var, command=self._toggle_scheduled_backup,
                        fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.TEXT
                        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4))
        ctk.CTkLabel(sched, text="Every (hours)", font=t.font(10), text_color=t.MUTED).grid(row=1, column=0, padx=(10, 4), pady=4)
        self.backup_interval_var = ctk.StringVar(value="6")
        ctk.CTkEntry(sched, textvariable=self.backup_interval_var, width=50).grid(row=1, column=1, sticky="w", pady=4)
        ctk.CTkLabel(sched, text="Keep", font=t.font(10), text_color=t.MUTED).grid(row=1, column=2, padx=(12, 4), pady=4)
        self.backup_keep_var = ctk.StringVar(value="5")
        ctk.CTkEntry(sched, textvariable=self.backup_keep_var, width=50).grid(row=1, column=3, sticky="w", pady=4)
        ctk.CTkButton(sched, text="Save schedule", width=100, **t.secondary_button_style(),
                      command=self._save_backup_settings).grid(row=1, column=4, padx=(12, 10), pady=4)

        self.backups_list_frame = ctk.CTkScrollableFrame(parent, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        self.backups_list_frame.grid(row=3, column=0, sticky="nsew")
        self.backups_list_frame.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.backups_list_frame)

    def _backups_dir(self) -> Path:
        srv = self._current_server()
        if not srv:
            return Path(".")
        return self._server_dir(srv) / "_backups"

    def _create_backup(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        if not self._server_dir(srv).exists():
            messagebox.showwarning("Backup", "Server folder does not exist.")
            return
        self._create_backup_for_server(srv)

    def _backup_done(self, msg: str, server_id: str | None = None) -> None:
        sid = server_id or self._selected_id
        if sid == self._selected_id:
            self._append_console_line(f"[Manager] {msg}")
        if sid == self._selected_id:
            self._refresh_backups()

    def _refresh_backups(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        cfg = srv.get("config", {})
        self.backup_enabled_var.set(bool(cfg.get("backup_enabled")))
        self.backup_interval_var.set(str(cfg.get("backup_interval_hours", 6)))
        self.backup_keep_var.set(str(cfg.get("backup_keep_count", 5)))

        for child in self.backups_list_frame.winfo_children():
            child.destroy()
        dest = self._backups_dir()
        zips = sorted(dest.glob("*.zip"), reverse=True) if dest.exists() else []
        if not zips:
            ctk.CTkLabel(self.backups_list_frame, text="(no backups yet)", text_color=t.MUTED,
                         font=t.font(11)).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return
        for i, p in enumerate(zips):
            row = ctk.CTkFrame(self.backups_list_frame, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=6, pady=3)
            try:
                size = _human_size(p.stat().st_size)
            except OSError:
                size = "?"
            ctk.CTkLabel(row, text=f"{p.name}  ({size})", font=t.mono(10), text_color=t.TEXT
                         ).pack(side="left", padx=(4, 8))
            ctk.CTkButton(row, text="Restore", width=70, height=24, **t.primary_button_style(),
                          command=lambda z=p: self._restore_backup(z)).pack(side="right", padx=(4, 0))
            ctk.CTkButton(row, text="Delete", width=70, height=24, **t.danger_button_style(),
                          command=lambda z=p: self._delete_backup(z)).pack(side="right")

    # ------------------------------------------------------------------ config

    def _build_config_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        self.config_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.config_scroll.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        self.config_scroll.grid_columnconfigure(0, weight=1)
        self._bind_scroll_pause(self.config_scroll)

        # folder row
        folder_row = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        folder_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        folder_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder_row, text="Server Folder", font=t.font(13, "bold"), text_color=t.TEXT
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=10)
        self.config_folder_label = ctk.CTkLabel(folder_row, text="", font=t.mono(11), text_color=t.MUTED, anchor="w")
        self.config_folder_label.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(folder_row, text="Browse…", width=90, **t.secondary_button_style(),
                      command=self._browse_server_folder).grid(row=0, column=2, padx=12)

        self._config_game_map = {f"{icon}  {name}": gt for gt, name, icon in game_choices()}
        self._config_game_rev = {gt: label for label, gt in self._config_game_map.items()}
        self._config_game_picker_ready = False

        game_row = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        game_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        game_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(game_row, text="Game type", font=t.font(13, "bold"), text_color=t.TEXT
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.config_game_picker = GamePicker(
            game_row,
            game_choices(),
            on_select=self._on_config_game_picker_select,
            defer_build=True,
        )
        self.config_game_picker.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))

        # minecraft install panel (shown for MC types)
        self.mc_install_panel = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        self.mc_install_panel.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.mc_install_panel.grid_columnconfigure(0, weight=1)
        self._build_mc_install_panel(self.mc_install_panel)

        self.steam_install_panel = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        self.steam_install_panel.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.steam_install_panel.grid_columnconfigure(0, weight=1)
        self._build_steam_install_panel(self.steam_install_panel)

        self.setup_hints_panel = ctk.CTkFrame(self.config_scroll, **st.card_style())
        self.setup_hints_panel.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.setup_hints_label = ctk.CTkLabel(
            self.setup_hints_panel, text="", font=t.font(11), text_color=t.MUTED,
            anchor="w", wraplength=580, justify="left",
        )
        self.setup_hints_label.pack(fill="x", padx=12, pady=10)

        self.config_fields_panel = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        self.config_fields_panel.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.config_fields_panel.grid_columnconfigure(1, weight=1)

        self.config_status = ctk.CTkLabel(self.config_scroll, text="", font=t.font(12),
                                          text_color=t.MUTED, anchor="w", wraplength=600, justify="left")
        self.config_status.grid(row=6, column=0, sticky="ew", pady=(0, 8))

        self.custom_cmds_panel = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        self.custom_cmds_panel.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(self.custom_cmds_panel, text="Custom quick commands", font=t.font(13, "bold"),
                     text_color=t.TEXT).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))
        add_row = ctk.CTkFrame(self.custom_cmds_panel, fg_color="transparent")
        add_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        ctk.CTkLabel(add_row, text="Label", font=t.font(10), text_color=t.MUTED).pack(side="left")
        self.custom_cmd_label = ctk.CTkEntry(add_row, width=100, fg_color=t.PANEL_2, border_color=t.BORDER)
        self.custom_cmd_label.pack(side="left", padx=(4, 8))
        ctk.CTkLabel(add_row, text="Command", font=t.font(10), text_color=t.MUTED).pack(side="left")
        self.custom_cmd_text = ctk.CTkEntry(add_row, width=180, fg_color=t.PANEL_2, border_color=t.BORDER)
        self.custom_cmd_text.pack(side="left", padx=(4, 8))
        ctk.CTkButton(add_row, text="Add", width=60, **t.primary_button_style(),
                      command=self._add_custom_quick_command).pack(side="left")

    def _build_steam_install_panel(self, parent) -> None:
        ctk.CTkLabel(parent, text="SteamCMD Install", font=t.font(13, "bold"), text_color=t.TEXT
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.steamcmd_status_label = ctk.CTkLabel(
            parent, text="", font=t.font(11), text_color=t.MUTED, anchor="w", wraplength=540, justify="left",
        )
        self.steamcmd_status_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))

        steam_dl_row = ctk.CTkFrame(parent, fg_color="transparent")
        steam_dl_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        steam_dl_row.grid_columnconfigure(1, weight=1)
        self.steam_install_btn = ctk.CTkButton(
            steam_dl_row, text="Install via SteamCMD", **t.primary_button_style(),
            command=self._start_steam_install,
        )
        self.steam_install_btn.grid(row=0, column=0, sticky="w")
        self.steam_download_progress = ctk.CTkProgressBar(steam_dl_row, progress_color=t.ACCENT)
        self.steam_download_progress.set(0)
        self.steam_download_progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

    def _build_mc_install_panel(self, parent) -> None:
        ctk.CTkLabel(parent, text="Minecraft Install", font=t.font(13, "bold"), text_color=t.TEXT
                     ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self.mc_java_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_java_row.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkLabel(self.mc_java_row, text="Java", font=t.font(11), text_color=t.MUTED).pack(side="left")
        self.java_status_label = ctk.CTkLabel(self.mc_java_row, text="Checking…", font=t.font(11), text_color=t.MUTED)
        self.java_status_label.pack(side="left", padx=(8, 0))
        ctk.CTkButton(self.mc_java_row, text="Install Required Java", width=135, height=24, **t.secondary_button_style(),
                      command=self._install_required_java_async).pack(side="right", padx=(6, 0))
        ctk.CTkButton(self.mc_java_row, text="Refresh Java", width=90, height=24, **t.secondary_button_style(),
                      command=self._refresh_java_runtimes_async).pack(side="right")

        self.java_runtime_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.java_runtime_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))
        ctk.CTkLabel(self.java_runtime_row, text="Runtime", font=t.font(11), text_color=t.MUTED).pack(side="left")
        self.java_required_label = ctk.CTkLabel(self.java_runtime_row, text="Required: Java —", font=t.font(10), text_color=t.MUTED)
        self.java_required_label.pack(side="left", padx=(8, 0))
        self.java_runtime_menu = ctk.CTkOptionMenu(
            self.java_runtime_row, values=["Automatic"], width=300,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_java_runtime_selected,
        )
        self.java_runtime_menu.pack(side="left", padx=(8, 0))

        self.mc_loader_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_loader_row.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        ctk.CTkLabel(self.mc_loader_row, text="Loader", font=t.font(11), text_color=t.MUTED).pack(side="left")
        self.loader_menu = ctk.CTkOptionMenu(
            self.mc_loader_row, values=[loader_name(x) for x in loader_choices()], width=140,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_mc_loader_selected,
        )
        self.loader_menu.pack(side="left", padx=(8, 0))
        self.loader_version_menu = ctk.CTkOptionMenu(
            self.mc_loader_row, values=["Vanilla"], width=190,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_mc_loader_version_selected,
        )
        self.loader_version_menu.pack(side="left", padx=(8, 0))

        self.mc_version_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_version_row.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        self.version_menu = ctk.CTkOptionMenu(
            self.mc_version_row, values=["(load versions)"], width=180,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_mc_version_selected,
        )
        self.version_menu.pack(side="left")
        ctk.CTkCheckBox(self.mc_version_row, text="Snapshots", variable=self._show_snapshots,
                        fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.TEXT,
                        command=self._populate_mc_version_menu).pack(side="left", padx=(8, 0))
        ctk.CTkButton(self.mc_version_row, text="Load Versions", width=100, height=26,
                      **t.secondary_button_style(), command=self._load_mc_versions_async).pack(side="left", padx=(8, 0))
        ctk.CTkButton(self.mc_version_row, text="Check Installed", width=110, height=26,
                      **t.secondary_button_style(), command=self._check_installed_mc_version).pack(side="left", padx=(8, 0))
        self.mc_version_status_label = ctk.CTkLabel(self.mc_version_row, text="Installed: —", font=t.font(10), text_color=t.MUTED)
        self.mc_version_status_label.pack(side="left", padx=(10, 0))

        self.mc_bedrock_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_bedrock_row.grid(row=5, column=0, sticky="ew", padx=12, pady=4)
        self.bedrock_channel_menu = ctk.CTkOptionMenu(
            self.mc_bedrock_row, values=["Stable", "Preview"], width=120,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_bedrock_channel_selected,
        )
        self.bedrock_channel_menu.pack(side="left")

        self.mc_mem_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_mem_row.grid(row=6, column=0, sticky="ew", padx=12, pady=4)
        self.min_mb = ctk.StringVar(value="1024")
        self.max_mb = ctk.StringVar(value="2048")
        self.java_path = ctk.StringVar(value="java")
        ctk.CTkLabel(self.mc_mem_row, text="Min MB", text_color=t.MUTED, font=t.font(11)).pack(side="left")
        ctk.CTkEntry(self.mc_mem_row, textvariable=self.min_mb, width=70, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).pack(side="left", padx=(4, 12))
        ctk.CTkLabel(self.mc_mem_row, text="Max MB", text_color=t.MUTED, font=t.font(11)).pack(side="left")
        ctk.CTkEntry(self.mc_mem_row, textvariable=self.max_mb, width=70, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).pack(side="left", padx=(4, 8))
        ctk.CTkButton(self.mc_mem_row, text="Suggest", width=64, height=24, font=t.font(11),
                      fg_color=t.PANEL_2, hover_color=t.ACCENT_HOVER, text_color=t.TEXT,
                      command=self._suggest_mc_memory).pack(side="left")
        self.mc_mem_system_label = ctk.CTkLabel(self.mc_mem_row, text="", text_color=t.MUTED, font=t.font(10))
        self.mc_mem_system_label.pack(side="left", padx=(10, 0))
        self._refresh_mc_mem_system_label()
        # Auto-persist Min/Max MB as the person edits them (like CurseForge's
        # instance slider, which writes to disk as soon as it changes)
        # instead of requiring a separate "Save Config" click to stick.
        self._mc_mem_autosave_job: str | None = None
        self.min_mb.trace_add("write", lambda *_: self._schedule_mc_mem_autosave())
        self.max_mb.trace_add("write", lambda *_: self._schedule_mc_mem_autosave())

        eula_row = ctk.CTkFrame(parent, fg_color="transparent")
        eula_row.grid(row=7, column=0, sticky="w", padx=12, pady=4)
        ctk.CTkCheckBox(eula_row, text="I agree to Mojang's EULA", variable=self._eula_var,
                        fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.TEXT).pack(side="left")
        link = ctk.CTkLabel(eula_row, text="(view)", font=t.font(11, "bold"), text_color=t.ACCENT, cursor="hand2")
        link.pack(side="left", padx=(6, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open("https://aka.ms/MinecraftEULA"))

        dl_row = ctk.CTkFrame(parent, fg_color="transparent")
        dl_row.grid(row=8, column=0, sticky="ew", padx=12, pady=(4, 10))
        dl_row.grid_columnconfigure(1, weight=1)
        self.download_btn = ctk.CTkButton(dl_row, text="Download & Install", **t.primary_button_style(),
                                          command=self._start_mc_download)
        self.download_btn.grid(row=0, column=0, sticky="w")
        self.download_progress = ctk.CTkProgressBar(dl_row, progress_color=t.ACCENT)
        self.download_progress.set(0)
        self.download_progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

        self.mc_update_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_update_row.grid(row=9, column=0, sticky="ew", padx=12, pady=(0, 10))
        ctk.CTkButton(self.mc_update_row, text="Check for update", width=120, height=26,
                      **t.secondary_button_style(), command=self._check_java_update).pack(side="left")
        ctk.CTkButton(self.mc_update_row, text="Update Server", width=120, height=26,
                      **t.primary_button_style(), command=self._apply_java_update).pack(side="left", padx=(8, 0))
        self.update_status_label = ctk.CTkLabel(self.mc_update_row, text="", font=t.font(10), text_color=t.MUTED)
        self.update_status_label.pack(side="left", padx=(12, 0))

    def _on_config_game_picker_select(self, label: str, game_type: str) -> None:
        self._on_config_game_type_changed(label)

    def _on_config_game_type_changed(self, label: str) -> None:
        srv = self._current_server()
        if not srv:
            return
        gt = self._config_game_map.get(label)
        if not gt or gt == srv.get("game_type"):
            return
        proc = self._process(srv["id"])
        if proc.running:
            messagebox.showwarning(
                "Game type",
                "Stop the server before changing its game type.",
                parent=self.winfo_toplevel(),
            )
            self.config_game_picker.set_game_type(srv["game_type"])
            return
        srv["game_type"] = gt
        adapter = get_adapter(gt)
        defaults = _default_server_config(gt, adapter)
        cfg = srv.setdefault("config", {})
        for key, val in defaults.items():
            cfg.setdefault(key, val)
        self._persist()
        self._refresh_server_list()
        self._update_server_list()
        self._on_server_context_changed()

    def _sync_config_tab_panels(self, srv: dict, adapter) -> None:
        gt = srv["game_type"]
        is_java = gt == "minecraft_java"
        is_bedrock = gt == "minecraft_bedrock"
        if is_java or is_bedrock:
            self.mc_install_panel.grid()
            self.mc_java_row.grid() if is_java else self.mc_java_row.grid_remove()
            self.java_runtime_row.grid() if is_java else self.java_runtime_row.grid_remove()
            self.mc_loader_row.grid() if is_java else self.mc_loader_row.grid_remove()
            self.mc_version_row.grid() if is_java else self.mc_version_row.grid_remove()
            self.mc_bedrock_row.grid() if is_bedrock else self.mc_bedrock_row.grid_remove()
            self.mc_mem_row.grid() if is_java else self.mc_mem_row.grid_remove()
            self.mc_update_row.grid() if is_java else self.mc_update_row.grid_remove()
            cfg = srv.setdefault("config", {})
            self._mc_mem_syncing = True
            self.min_mb.set(str(int(cfg.get("min_mb", 1024) or 1024)))
            self.max_mb.set(str(int(cfg.get("max_mb", 2048) or 2048)))
            self._mc_mem_syncing = False
            self.java_path.set(cfg.get("java_path", "java"))
            loader = str(cfg.get("loader", "vanilla"))
            self.loader_menu.set(loader_name(loader))
            self._mc_selected_loader_version = str(cfg.get("loader_version", ""))
            channel = cfg.get("bedrock_channel", "stable")
            self.bedrock_channel_menu.set("Preview" if channel == "preview" else "Stable")
            if is_java:
                self._check_installed_mc_version()
                self._refresh_java_runtimes_async()
                if self._mc_versions:
                    self._populate_mc_version_menu()
                elif not self._mc_versions_loading:
                    self._load_mc_versions_async()
                self._load_mc_loader_versions_async(loader)
        else:
            self.mc_install_panel.grid_remove()

        if gt.startswith("minecraft"):
            self.custom_cmds_panel.grid()
        else:
            self.custom_cmds_panel.grid_remove()

        if adapter.supports_steam_install():
            self.steam_install_panel.grid()
            if gt == "terraria":
                from .adapters.games import terraria_server_mode

                mode = terraria_server_mode(srv.get("config", {}))
                self.steam_install_btn.configure(text="Install Server Files")
                if mode == "tmodloader":
                    self.steamcmd_status_label.configure(
                        text=(
                            "Downloads the official tModLoader release from GitHub "
                            "(same build as Steam).\n"
                            "If you own tModLoader on Steam, files copy from your library first."
                        ),
                        text_color=t.MUTED,
                    )
                else:
                    self.steamcmd_status_label.configure(
                        text=(
                            "Downloads the official Terraria server package from terraria.org.\n"
                            "If you own Terraria on Steam, files copy from your library first."
                        ),
                        text_color=t.MUTED,
                    )
            else:
                self.steam_install_btn.configure(text="Install via SteamCMD")
                steam_path, steam_err = find_steamcmd()
                if steam_path:
                    self.steamcmd_status_label.configure(
                        text=f"SteamCMD found: {steam_path}",
                        text_color=t.SUCCESS,
                    )
                else:
                    self.steamcmd_status_label.configure(text=steam_err, text_color=t.DANGER)
                app_id = adapter.steam_app_id_for(srv.get("config", {}))
                if app_id:
                    self.steamcmd_status_label.configure(
                        text=self.steamcmd_status_label.cget("text") + f"\nApp ID for this server: {app_id}",
                    )
        else:
            self.steam_install_panel.grid_remove()

        if gt == "terraria":
            hints = adapter.setup_panel_hints(srv.get("config", {}))
        else:
            hints = adapter.setup_panel_hints()
        if hints and not gt.startswith("minecraft"):
            self.setup_hints_panel.grid()
            self.setup_hints_label.configure(text="\n".join(f"• {h}" for h in hints))
        else:
            self.setup_hints_panel.grid_remove()

    def _refresh_config_tab(self) -> None:
        if not self._config_game_picker_ready:
            self._config_game_picker_ready = True
            self.config_game_picker.start_build()

        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return

        self.config_folder_label.configure(text=str(self._server_dir(srv)))
        gt_label = self._config_game_rev.get(srv["game_type"])
        if gt_label:
            self.config_game_picker.set_by_label(gt_label)

        self._sync_config_tab_panels(srv, adapter)

        cache_key = self._config_tab_key(srv)
        if self._config_tab_cache_key == cache_key:
            now = time.time()
            if now - self._config_status_ts >= 5.0:
                self._config_status_ts = now
                ok, msg = adapter.readiness_message(self._server_dir(srv), srv.get("config", {}))
                self.config_status.configure(
                    text=f"{'✅' if ok else '⚠️'} {msg}",
                    text_color=t.SUCCESS if ok else t.ACCENT,
                )
            return

        self._config_tab_cache_key = cache_key
        self._config_tab_server_id = srv["id"]
        self._monitor_cache.clear()

        gt = srv["game_type"]

        for child in self.config_fields_panel.winfo_children():
            child.destroy()
        self._config_vars.clear()

        fields = adapter.config_fields(self._server_dir(srv))
        stored = srv.get("config", {})
        if gt == "terraria":
            self._sync_terraria_mode_from_folder(srv)
            stored = srv.get("config", {})
        props = adapter.read_config(self._server_dir(srv)) if _adapter_uses_file_config(adapter) else {}

        for i, field in enumerate(fields):
            ctk.CTkLabel(self.config_fields_panel, text=field.label, text_color=t.MUTED, font=t.font(11)
                         ).grid(row=i, column=0, sticky="w", padx=(12, 4), pady=4)
            if _adapter_uses_file_config(adapter):
                initial = props.get(field.key, stored.get(field.key, field.default))
            else:
                initial = stored.get(field.key, field.default)

            if field.kind == "menu":
                var = ctk.StringVar(value=initial)
                menu_kwargs = {
                    "values": field.choices,
                    "variable": var,
                    "width": field.width,
                    "fg_color": t.PANEL_2,
                    "button_color": t.ACCENT,
                    "button_hover_color": t.ACCENT_HOVER,
                }
                if gt == "terraria" and field.key == "server_mode":
                    menu_kwargs["command"] = self._on_terraria_server_mode_changed
                ctk.CTkOptionMenu(self.config_fields_panel, **menu_kwargs).grid(
                    row=i, column=1, sticky="w", padx=(0, 12), pady=4)
            elif field.kind == "checkbox":
                var = ctk.BooleanVar(value=str(initial).lower() == "true")
                ctk.CTkCheckBox(self.config_fields_panel, text="", variable=var,
                                fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER).grid(
                    row=i, column=1, sticky="w", padx=(0, 12), pady=4)
            else:
                var = ctk.StringVar(value=str(initial))
                ctk.CTkEntry(self.config_fields_panel, textvariable=var, width=field.width,
                             fg_color=t.PANEL_2, border_color=t.BORDER, text_color=t.TEXT).grid(
                    row=i, column=1, sticky="w", padx=(0, 12), pady=4)
            self._config_vars[field.key] = var

        ctk.CTkButton(self.config_fields_panel, text="Save Config", **t.primary_button_style(),
                      command=self._save_config).grid(row=len(fields), column=0, columnspan=2,
                                                      sticky="ew", padx=12, pady=(8, 4))
        if gt == "palworld":
            ctk.CTkButton(
                self.config_fields_panel, text="Edit PalWorldSettings.ini", **t.secondary_button_style(),
                command=self._edit_palworld_settings,
            ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        elif gt == "terraria":
            ctk.CTkButton(
                self.config_fields_panel, text="Import world…", **t.primary_button_style(),
                command=self._import_terraria_world,
            ).grid(row=len(fields) + 1, column=0, sticky="ew", padx=(12, 4), pady=(0, 12))
            ctk.CTkButton(
                self.config_fields_panel, text="Open Terraria saves", **t.secondary_button_style(),
                command=self._open_terraria_client_worlds,
            ).grid(row=len(fields) + 1, column=1, sticky="ew", padx=(4, 12), pady=(0, 12))

        self._refresh_terraria_world_panel()

        ok, msg = adapter.readiness_message(self._server_dir(srv), srv.get("config", {}))
        self._config_status_ts = time.time()
        self.config_status.configure(
            text=f"{'✅' if ok else '⚠️'} {msg}",
            text_color=t.SUCCESS if ok else t.ACCENT,
        )
        self.after_idle(lambda: self._bind_scroll_pause(self.config_scroll))

    def _browse_server_folder(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        chosen = filedialog.askdirectory(title="Server folder")
        if chosen:
            srv["server_dir"] = chosen
            from . import server_files as sf
            detected = sf.detect_game_type(Path(chosen))
            if detected and detected != srv.get("game_type"):
                proc = self._process(srv["id"])
                if proc.running:
                    messagebox.showwarning(
                        "Server folder",
                        "Stop the server before changing the detected game type.",
                        parent=self.winfo_toplevel(),
                    )
                else:
                    srv["game_type"] = detected
                    adapter = get_adapter(detected)
                    defaults = _default_server_config(detected, adapter)
                    cfg = srv.setdefault("config", {})
                    for key, val in defaults.items():
                        cfg.setdefault(key, val)
            if srv.get("game_type") == "terraria":
                self._sync_terraria_mode_from_folder(srv)
                self.after(100, lambda: self._warn_terraria_mixed_folder(srv, force=True))
            self._persist()
            self._refresh_server_list()
            self._update_server_list()
            self._on_server_context_changed()

    def _on_terraria_server_mode_changed(self, value: str) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "terraria":
            return
        cfg = srv.setdefault("config", {})
        if cfg.get("server_mode") == value:
            return
        cfg["server_mode"] = value
        from .core.settings import align_terraria_server_folder

        folder_changed = align_terraria_server_folder(srv)
        self._persist()
        self._append_console_line(f"[Manager] Server type set to {value} (saved).")
        if folder_changed:
            self._append_console_line(
                f"[Manager] Server folder set to {srv.get('name')} ({srv.get('server_dir')}). "
                "Use Install Server Files on Config if this folder is not set up yet.",
            )
        adapter = self._current_adapter()
        if adapter:
            self._invalidate_config_tab()
            self._sync_config_tab_panels(srv, adapter)
            self._refresh_mods()
            self._refresh_overview()
            self._refresh_server_list()

    def _save_config(self) -> None:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return

        updates: dict[str, str] = {}
        for key, var in self._config_vars.items():
            if isinstance(var, ctk.BooleanVar):
                updates[key] = "true" if var.get() else "false"
            else:
                updates[key] = str(var.get())

        if adapter.game_type.startswith("minecraft"):
            adapter.write_config(self._server_dir(srv), updates)
        elif adapter.game_type == "palworld":
            running = self._process(srv["id"]).running
            if not self._confirm_palworld_save(running):
                return
            adapter.write_config(self._server_dir(srv), updates)
            cfg = srv.setdefault("config", {})
            cfg.update(updates)
            self._persist()
        elif _adapter_uses_file_config(adapter):
            adapter.write_config(self._server_dir(srv), updates)
            cfg = srv.setdefault("config", {})
            cfg.update(updates)
            self._persist()
        else:
            cfg = srv.setdefault("config", {})
            cfg.update(updates)
            if adapter.game_type == "terraria" and "world_file" in cfg:
                from .adapters.games import normalize_terraria_world_file

                cfg["world_file"] = normalize_terraria_world_file(cfg["world_file"])
            self._persist()

        if srv["game_type"] == "minecraft_java":
            cfg = srv.setdefault("config", {})
            cfg["min_mb"] = self._mem_mb(self.min_mb, 1024)
            cfg["max_mb"] = self._mem_mb(self.max_mb, 2048)
            cfg["java_path"] = self.java_path.get()
            self._persist()

        self._append_console_line("[Manager] Config saved.")
        self._refresh_overview()
        self._refresh_config_tab()
        if adapter.game_type == "terraria":
            self._refresh_mods()
        self._update_address_display()

    # ---- minecraft install (preserved from original module) ----

    def _refresh_java_runtimes_async(self) -> None:
        self.java_status_label.configure(text="Scanning installed Java runtimes…", text_color=t.MUTED)
        self.java_required_label.configure(text="Required: Java —")
        def work():
            runtimes = discover_java_runtimes()
            self.after(0, lambda: self._finish_java_runtimes(runtimes))
        threading.Thread(target=work, daemon=True).start()

    def _finish_java_runtimes(self, runtimes) -> None:
        self._java_runtimes = runtimes
        srv = self._current_server()
        mc_version = str((srv or {}).get("config", {}).get("minecraft_version", ""))
        required, status = compatibility_text(mc_version, runtimes) if mc_version else (None, "Select a Minecraft version")
        self._java_required_major = required or 21
        self.java_required_label.configure(text=f"Required: Java {required}" if required else "Required: Java —", text_color=t.TEXT)
        self.java_status_label.configure(text=status, text_color=t.SUCCESS if "✓" in status else t.DANGER if "✗" in status else t.MUTED)
        values = ["Automatic"]
        for r in runtimes:
            values.append(f"Java {r.major} — {r.version} — {r.path}")
        self.java_runtime_menu.configure(values=values)
        cfg = (srv or {}).setdefault("config", {}) if srv else {}
        current_path = str(cfg.get("java_path", "java"))
        selected = "Automatic"
        if current_path not in ("", "java", "auto"):
            match = next((r for r in runtimes if Path(r.path).resolve() == Path(current_path).resolve()), None)
            if match:
                selected = next((v for v in values if v.endswith(f"— {match.path}")), values[0])
        elif required:
            match = recommended_runtime(mc_version, runtimes)
            if match:
                self._java_auto_path = match.path
        self.java_runtime_menu.set(selected)
        self._update_java_selection(cfg if srv else None)

    def _on_java_runtime_selected(self, value: str) -> None:
        srv = self._current_server()
        if not srv:
            return
        cfg = srv.setdefault("config", {})
        if value == "Automatic":
            cfg["java_path"] = "java"
            self._update_java_selection(cfg)
        else:
            marker = " — "
            path = value.rsplit(marker, 1)[-1] if marker in value else "java"
            cfg["java_path"] = path
            self.java_path.set(path)
            self._persist()
            self._check_java_async()

    def _update_java_selection(self, cfg: dict | None) -> None:
        srv = self._current_server()
        if not srv:
            return
        mc_version = str(cfg.get("minecraft_version", "")) if cfg else ""
        match = recommended_runtime(mc_version, self._java_runtimes) if mc_version else None
        if match:
            self._java_auto_path = match.path
            self.java_path.set(match.path)
            self.java_status_label.configure(text=f"✓ Java {match.major} installed — {match.version}", text_color=t.SUCCESS)
        else:
            self.java_path.set(str(cfg.get("java_path", "java")) if cfg else "java")
        self._persist()

    def _check_java_async(self) -> None:
        self._refresh_java_runtimes_async()

    def _java_package_id(self, major: int) -> str:
        # Microsoft Build of OpenJDK only publishes 11, 17, 21, 25+ — there
        # is no "Microsoft.OpenJDK.8" package, so requesting it for Java 8
        # (which many legacy/1.16.5-and-earlier Forge modpacks require)
        # silently fails. Eclipse Temurin publishes a proper Java 8 build
        # on WinGet, so use that specifically for major 8 and keep
        # Microsoft's builds for everything newer where they do exist.
        if int(major) == 8:
            return "EclipseAdoptium.Temurin.8.JDK"
        return f"Microsoft.OpenJDK.{int(major)}"

    def _install_required_java_async(self, required: int | None = None, on_done=None) -> None:
        srv = self._current_server()
        if required is None:
            mc_version = str((srv or {}).get("config", {}).get("minecraft_version", ""))
            required = required_java_major(mc_version) if mc_version else None
        if not required:
            self.java_status_label.configure(text="Select a Minecraft version first", text_color=t.MUTED)
            return
        if any(r.major == required for r in self._java_runtimes):
            self._refresh_java_runtimes_async()
            if on_done:
                self.after(100, on_done)
            return

        import shutil as _shutil
        winget = _shutil.which("winget")
        if not winget:
            self.java_status_label.configure(text="✗ WinGet is not installed", text_color=t.DANGER)
            self._append_console_line("[Manager] WinGet is required to automatically install Java. Install App Installer/WinGet from Microsoft, then refresh Java.")
            return

        package_id = self._java_package_id(required)
        self.java_status_label.configure(text=f"Downloading and installing Java {required}…", text_color=t.ACCENT)
        self._append_console_line(f"[Manager] Installing {package_id} (64-bit) automatically…")

        def work():
            try:
                # --architecture x64 pins this to a 64-bit build explicitly —
                # without it WinGet can still resolve to an x86 package on
                # some systems/sources, which is exactly the "32-bit JVM
                # clamps your heap to 1024 MB" problem this is meant to avoid.
                cmd = [winget, "install", "--id", package_id, "--exact", "--architecture", "x64",
                       "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"]
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
                success = proc.returncode == 0
            except Exception as exc:
                output = str(exc)
                success = False
            self.after(0, lambda: self._finish_java_install(required, success, output, on_done))
        threading.Thread(target=work, daemon=True).start()

    def _finish_java_install(self, required: int, success: bool, output: str, on_done=None) -> None:
        if success:
            self._append_console_line(f"[Manager] Java {required} installation command completed. Rescanning installed runtimes…")
            # Give the MSI/WinGet registration a moment to settle before discovery.
            def rescan():
                import time
                time.sleep(2)
                runtimes = discover_java_runtimes()
                self.after(0, lambda: self._finish_java_install_rescan(required, runtimes, on_done))
            threading.Thread(target=rescan, daemon=True).start()
        else:
            self.java_status_label.configure(text=f"✗ Java {required} installation failed", text_color=t.DANGER)
            tail = output[-1200:] if output else "No installer output."
            self._append_console_line(f"[Manager] Java {required} installation failed:\n{tail}")

    def _finish_java_install_rescan(self, required: int, runtimes, on_done=None) -> None:
        self._finish_java_runtimes(runtimes)
        match = next((r for r in runtimes if r.major == required), None)
        if match:
            self.java_status_label.configure(text=f"✓ Java {required} installed — {match.version}", text_color=t.SUCCESS)
            self._append_console_line(f"[Manager] Java {required} detected: {match.path}")
            if on_done:
                self.after(100, on_done)
        else:
            self.java_status_label.configure(text=f"✗ Java {required} was not detected after installation", text_color=t.DANGER)
            self._append_console_line(f"[Manager] Java {required} installation finished, but no Java {required} executable was detected. Click Refresh Java and check the installation.")

    def _load_mc_versions_async(self) -> None:
        if self._mc_versions_loading:
            return
        self._mc_versions_loading = True
        self.config_status.configure(text="Loading version list from Mojang…")

        def work():
            versions, error = mc.list_versions()
            self.after(0, lambda: self._finish_load_mc_versions(versions, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_load_mc_versions(self, versions: list[mc.MCVersion], error: str) -> None:
        self._mc_versions_loading = False
        if error:
            self.config_status.configure(text=error, text_color=t.DANGER)
            self._pending_mc_download = False
            return
        self._mc_versions = versions
        self.config_status.configure(text=f"Loaded {len(versions)} versions.", text_color=t.MUTED)
        self._populate_mc_version_menu()
        if hasattr(self, "modpack_version_menu"):
            self._load_modpack_versions()
        if self._pending_mc_download:
            self._pending_mc_download = False
            if self._eula_var.get():
                self._start_mc_download()

    def _populate_mc_version_menu(self) -> None:
        show = self._show_snapshots.get()
        filtered = [v for v in self._mc_versions if show or v.type == "release"]
        ids = [v.id for v in filtered] or ["(load versions first)"]
        self.version_menu.configure(values=ids)

        # Never overwrite an already-installed/configured version just because
        # Mojang's list was refreshed. This is especially important after a
        # modpack install: SkyFactory 4 is 1.12.2 even though the newest
        # Minecraft release may be much newer.
        srv = self._current_server()
        cfg_version = str((srv or {}).get("config", {}).get("minecraft_version", "")).strip()
        selected = cfg_version if cfg_version in ids else ids[0]
        self.version_menu.set(selected)
        self._mc_selected_version = next(
            (v for v in self._mc_versions if v.id == selected), None
        )

    def _check_installed_mc_version(self) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            return
        cfg = srv.setdefault("config", {})
        detected = detect_minecraft_version(self._server_dir(srv))
        expected = str(cfg.get("minecraft_version") or cfg.get("installed_version") or "").strip()
        from datetime import datetime
        cfg["config_version"] = 2
        cfg["verified_version"] = detected or ""
        cfg["version_checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if not detected:
            cfg["version_status"] = "unknown"
            self.mc_version_status_label.configure(text="Installed: Unknown", text_color=t.MUTED)
            self.config_status.configure(text="Couldn't detect the installed Minecraft version. Start the server once, then check again.", text_color=t.MUTED)
        elif expected and detected != expected:
            cfg["version_status"] = "mismatch"
            self.mc_version_status_label.configure(text=f"Installed: {detected} ⚠ expected {expected}", text_color=t.DANGER)
            self.config_status.configure(text=f"Version mismatch: folder reports Minecraft {detected}, but config expects {expected}.", text_color=t.DANGER)
        else:
            cfg["version_status"] = "match"
            self.mc_version_status_label.configure(text=f"Installed: {detected} ✓", text_color=t.SUCCESS)
            self.config_status.configure(text=f"Minecraft {detected} verified in this server folder.", text_color=t.SUCCESS)
        self._persist()
        self._refresh_overview()

    def _on_mc_version_selected(self, version_id: str) -> None:
        if version_id == "(load versions first)":
            self._mc_selected_version = None
            return
        self._mc_selected_version = next((v for v in self._mc_versions if v.id == version_id), None)
        srv = self._current_server()
        if srv and self._mc_selected_version:
            cfg = srv.setdefault("config", {})
            cfg["minecraft_version"] = self._mc_selected_version.id
            cfg["config_version"] = 2
            if cfg.get("installed_version") and cfg.get("installed_version") != self._mc_selected_version.id:
                cfg["version_status"] = "mismatch"
            self._persist()
            self._refresh_java_runtimes_async()
            self._load_mc_loader_versions_async(srv["config"].get("loader", "vanilla"))

    def _on_mc_loader_selected(self, value: str) -> None:
        srv = self._current_server()
        loader = next((k for k in loader_choices() if loader_name(k) == value), "vanilla")
        if srv:
            cfg = srv.setdefault("config", {})
            cfg["loader"] = loader
            cfg["loader_version"] = ""
            self._persist()
        self._mc_selected_loader_version = ""
        self._load_mc_loader_versions_async(loader)

    def _on_mc_loader_version_selected(self, value: str) -> None:
        if value in {"Vanilla", "(select Minecraft first)", "(loading…)", "(unavailable)", "(none available)"}:
            self._mc_selected_loader_version = ""
            return
        self._mc_selected_loader_version = value.split(" (", 1)[0]
        srv = self._current_server()
        if srv:
            srv.setdefault("config", {})["loader_version"] = self._mc_selected_loader_version
            self._persist()

    def _load_mc_loader_versions_async(self, loader: str | None = None) -> None:
        srv = self._current_server()
        if not srv or srv.get("game_type") != "minecraft_java":
            return
        cfg = srv.setdefault("config", {})
        loader = loader or str(cfg.get("loader", "vanilla"))
        mc_version = str(cfg.get("minecraft_version") or (self._mc_selected_version.id if self._mc_selected_version else ""))
        if loader == "vanilla":
            self._mc_loader_versions = []
            self.loader_version_menu.configure(values=["Vanilla"])
            self.loader_version_menu.set("Vanilla")
            self._mc_selected_loader_version = ""
            return
        if not mc_version:
            self.loader_version_menu.configure(values=["(select Minecraft first)"])
            self.loader_version_menu.set("(select Minecraft first)")
            return
        if self._mc_loader_versions_loading:
            return
        self._mc_loader_versions_loading = True
        self.loader_version_menu.configure(values=["(loading…)"])
        self.loader_version_menu.set("(loading…)")
        def work():
            versions, error = get_loader_versions(loader, mc_version)
            self.after(0, lambda: self._finish_mc_loader_versions(loader, versions, error))
        threading.Thread(target=work, daemon=True).start()

    def _finish_mc_loader_versions(self, loader: str, versions: list, error: str) -> None:
        self._mc_loader_versions_loading = False
        if error:
            self.loader_version_menu.configure(values=["(unavailable)"])
            self.loader_version_menu.set("(unavailable)")
            self.config_status.configure(text=error, text_color=t.DANGER)
            return
        self._mc_loader_versions = versions
        values = [v.label for v in versions] or ["(none available)"]
        self.loader_version_menu.configure(values=values)
        wanted = self._mc_selected_loader_version or ""
        # Preserve the configured loader version when the version list is
        # refreshed. Do not silently replace an installed modpack's Forge
        # version with the newest Forge release for that Minecraft version.
        selected = next((v.label for v in versions if v.id == wanted), values[0])
        self.loader_version_menu.set(selected)
        if versions:
            self._mc_selected_loader_version = next(v.id for v in versions if v.label == selected)
            srv = self._current_server()
            if srv and loader != "vanilla":
                srv.setdefault("config", {})["loader_version"] = self._mc_selected_loader_version
                self._persist()
    def _on_bedrock_channel_selected(self, value: str) -> None:
        srv = self._current_server()
        if srv:
            srv.setdefault("config", {})["bedrock_channel"] = "preview" if value == "Preview" else "stable"
            self._persist()

    def _start_mc_download(self) -> None:
        if self._download_worker is not None and self._download_worker.is_alive():
            return
        if not self._eula_var.get():
            self.config_status.configure(text="Check the EULA agreement box first.")
            return
        srv = self._current_server()
        if not srv:
            return
        dest = self._server_dir(srv)
        dest.mkdir(parents=True, exist_ok=True)
        self.download_btn.configure(state="disabled")
        self.download_progress.set(0.02)

        if srv["game_type"] == "minecraft_bedrock":
            preview = srv.get("config", {}).get("bedrock_channel", "stable") == "preview"
            worker = create_minecraft_bedrock_install_worker(dest, preview=preview)
            self._download_meta = {"game": "bedrock"}
            self._append_console_line(f"[Manager] Downloading Bedrock server to {dest}…")
        else:
            if self._mc_selected_version is None:
                if not self._mc_versions and not self._mc_versions_loading:
                    self.config_status.configure(text="Loading version list…")
                    self._pending_mc_download = True
                    self._load_mc_versions_async()
                    return
                self.config_status.configure(text="Load and pick a version first.")
                self.download_btn.configure(state="normal")
                return
            cfg = srv.setdefault("config", {})
            loader = str(cfg.get("loader", "vanilla"))
            loader_version = str(cfg.get("loader_version", ""))
            if loader != "vanilla" and not loader_version:
                self.config_status.configure(text="Select a loader version first.", text_color=t.DANGER)
                self.download_btn.configure(state="normal")
                return
            cfg["minecraft_version"] = self._mc_selected_version.id
            required_java = required_java_major(self._mc_selected_version.id)
            java_match = recommended_runtime(self._mc_selected_version.id, self._java_runtimes)
            if not java_match:
                self.config_status.configure(
                    text=f"Java {required_java} is required. Installing it automatically…",
                    text_color=t.ACCENT,
                )
                self.download_btn.configure(state="disabled")
                def resume_install():
                    # Re-run the install flow after Java is detected.
                    self._start_mc_download()
                self._install_required_java_async(required_java, resume_install)
                return
            self.java_path.set(java_match.path)
            worker = create_minecraft_loader_install_worker(
                dest, loader, self._mc_selected_version.id, loader_version,
                java_path=self.java_path.get(), min_mb=self._mem_mb(self.min_mb, 1024), max_mb=self._mem_mb(self.max_mb, 2048),
            )
            self._download_meta = {"game": "java", "version": self._mc_selected_version.id, "loader": loader, "loader_version": loader_version}
            self._append_console_line(
                f"[Manager] Installing Minecraft {self._mc_selected_version.id} with {loader_name(loader)} to {dest}…",
            )

        worker.start()
        self._download_worker = worker
        self._poll_download()

    def _start_steam_install(self) -> None:
        if self._download_worker is not None and self._download_worker.is_alive():
            return
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter or not adapter.supports_steam_install():
            return

        app_id = adapter.steam_app_id_for(srv.get("config", {}))
        if "steam_app_id" in self._config_vars:
            app_id = str(self._config_vars["steam_app_id"].get()).strip() or app_id

        dest = self._server_dir(srv)
        custom_worker = adapter.create_install_worker(dest, srv.get("config", {}))
        if custom_worker is None and not app_id:
            self.config_status.configure(text="Set a Steam App ID in Config first.")
            return

        if self._process(srv["id"]).running:
            self.config_status.configure(
                text="Stop the server before installing.",
                text_color=t.DANGER,
            )
            return

        self.steam_install_btn.configure(state="disabled")
        self.steam_download_progress.set(0.02)
        if custom_worker is not None:
            self._append_console_line(f"[Manager] Installing {adapter.display_name} server files to {dest}…")
            worker = custom_worker
        else:
            self._append_console_line(f"[Manager] Installing Steam app {app_id} to {dest}…")
            worker = create_steamcmd_install_worker(
                dest, app_id, verify=lambda d: adapter.is_installed(d),
            )
        worker.start()
        self._download_worker = worker
        self._download_meta = {"game": "steam", "app_id": app_id, "last_status": ""}
        self._poll_download()

    def _drain_download_events(self, worker) -> None:
        while True:
            try:
                event: DownloadEvent = worker.events.get_nowait()
            except queue.Empty:
                break
            self._handle_download_event(event, worker)

    def _poll_download(self) -> None:
        worker = self._download_worker
        if worker is None:
            return
        self._drain_download_events(worker)
        if worker.is_alive():
            self.after(POLL_MS, self._poll_download)
            return
        self._drain_download_events(worker)
        if self._download_worker is worker:
            self._download_worker = None
            game = self._download_meta.get("game", "java")
            btn = self.steam_install_btn if game == "steam" else self.download_btn
            btn.configure(state="normal")
            if game == "modpack":
                self.modpack_status.configure(text="Install finished unexpectedly — check Console for details.", text_color=t.ACCENT)
                return
            self.config_status.configure(
                text="Install finished unexpectedly — check Console for details.",
                text_color=t.ACCENT,
            )

    def _apply_download_progress(self, progress_bar, event: DownloadEvent) -> None:
        if event.total and event.total > 0:
            fraction = min(1.0, max(0.0, event.downloaded / event.total))
            progress_bar.set(fraction)
        elif event.downloaded > 0:
            progress_bar.set(min(0.9, 0.05 + event.downloaded / 50_000_000))
        try:
            progress_bar.update_idletasks()
        except Exception:
            pass

    def _steam_progress_status(self, event: DownloadEvent) -> str:
        if event.message:
            return event.message
        if event.total and event.total > 100:
            return f"Downloading… {_human_size(event.downloaded)} / {_human_size(event.total)}"
        if event.total == 10_000:
            pct = event.downloaded / 100.0
            return f"Installing… {pct:.0f}%"
        if event.total == 100:
            return f"Installing… {event.downloaded:.0f}%"
        if event.downloaded:
            return f"Downloading… {_human_size(event.downloaded)}"
        return "Installing…"

    def _handle_download_event(self, event: DownloadEvent, worker) -> None:
        game = self._download_meta.get("game", "java")
        progress = self.steam_download_progress if game == "steam" else self.download_progress
        btn = self.steam_install_btn if game == "steam" else self.download_btn

        if event.kind == "progress":
            self._apply_download_progress(progress, event)
            status = self._steam_progress_status(event) if game == "steam" else ""
            if game == "modpack":
                if event.message:
                    self.modpack_status.configure(text=event.message, text_color=t.MUTED)
                elif event.total:
                    self.modpack_status.configure(text=f"Installing modpack… {event.downloaded / event.total * 100:.0f}%", text_color=t.MUTED)
            if game == "modpack":
                pass
            elif game == "steam":
                self.config_status.configure(text=status, text_color=t.MUTED)
                last = self._download_meta.get("last_status", "")
                if status and status != last:
                    self._download_meta["last_status"] = status
                    self._append_console_line(f"[Install] {status}")
            elif event.total and event.total > 100:
                self.config_status.configure(
                    text=f"Downloading… {_human_size(event.downloaded)} / {_human_size(event.total)}",
                    text_color=t.MUTED,
                )
            elif event.message:
                self.config_status.configure(text=event.message, text_color=t.MUTED)
                if (
                    not event.total
                    or "Extracting" in event.message
                    or "%" in event.message
                ):
                    self._append_console_line(f"[Install] {event.message}")
            elif event.total and event.total > 0:
                msg = f"Downloading… {_human_size(event.downloaded)} / {_human_size(event.total)}"
                self.config_status.configure(text=msg, text_color=t.MUTED)
            elif event.downloaded:
                self.config_status.configure(
                    text=f"Downloading… {_human_size(event.downloaded)}",
                    text_color=t.MUTED,
                )
        elif event.kind == "error":
            btn.configure(state="normal")
            if game == "modpack":
                self.modpack_status.configure(text=event.message or "Modpack installation failed.", text_color=t.DANGER)
                srv = self._current_server()
                profile_id = str(self._download_meta.get("profile_id") or "")
                if srv and profile_id:
                    previous = str(self._download_meta.get("previous_profile_id") or "")
                    self._remove_modpack_profile(srv, profile_id)
                    if previous:
                        self._activate_modpack_profile(srv, previous)
                    self._refresh_modpacks_tab()
            else:
                self.config_status.configure(text=event.message or "Installation failed.", text_color=t.DANGER)
            self._append_console_line(f"[Install] ERROR: {event.message or 'Installation failed.'}")
        elif event.kind == "done":
            srv = self._current_server()
            dest = self._server_dir(srv) if srv else Path(".")
            if game == "modpack":
                if self._download_meta.get("loader_repair"):
                    if not getattr(worker, "loader", ""):
                        btn.configure(state="normal")
                        self.modpack_status.configure(text=event.message or "Loader repair failed.", text_color=t.DANGER)
                        self._download_worker = None
                        return
                    cfg = srv.setdefault("config", {}) if srv else {}
                    profile_id = str(self._download_meta.get("profile_id") or "")
                    profile = self._modpack_profiles(srv).get(profile_id) if srv and profile_id else None
                    if profile is not None:
                        profile.update({
                            "provider": "curseforge",
                            "name": getattr(worker, "modpack_name", label if 'label' in locals() else profile.get("name", "Modpack")),
                            "minecraft_version": getattr(worker, "minecraft_version", ""),
                            "installed_version": getattr(worker, "minecraft_version", ""),
                            "loader": getattr(worker, "loader", ""),
                            "loader_version": getattr(worker, "loader_version", ""),
                            "java_path": getattr(worker, "java_path", ""),
                        })
                    if profile_id:
                        self._activate_modpack_profile(srv, profile_id)
                    cfg["loader"] = getattr(worker, "loader", "")
                    cfg["loader_version"] = getattr(worker, "loader_version", "")
                    if getattr(worker, "minecraft_version", ""):
                        cfg["minecraft_version"] = worker.minecraft_version
                        cfg["installed_version"] = worker.minecraft_version
                    if getattr(worker, "java_path", ""):
                        cfg["java_path"] = worker.java_path
                        self.java_path.set(worker.java_path)
                    self._persist()
                    btn.configure(state="normal")
                    self.modpack_status.configure(text=event.message or "Loader repaired successfully.", text_color=t.SUCCESS)
                    self._download_worker = None
                    self._refresh_modpacks_tab()
                    self._refresh_config_tab()
                    self._refresh_overview()
                    self._refresh_mods()
                    return
                # A modpack with no detected loader is not a usable install —
                # it previously fell through here silently, leaving whatever
                # stale/default "loader" value (usually "vanilla") the server
                # config already had, while still showing the modpack as
                # successfully "Loaded". Treat a missing loader as a failure
                # instead so this can't happen again.
                if not getattr(worker, "loader", ""):
                    btn.configure(state="normal")
                    self.modpack_status.configure(
                        text="Modpack installed, but no Forge/NeoForge/Fabric/Quilt loader "
                             "was detected — treating this as a failed install.",
                        text_color=t.DANGER,
                    )
                    profile_id = str(self._download_meta.get("profile_id") or "")
                    if srv and profile_id:
                        previous = str(self._download_meta.get("previous_profile_id") or "")
                        self._remove_modpack_profile(srv, profile_id)
                        if previous:
                            self._activate_modpack_profile(srv, previous)
                        self._refresh_modpacks_tab()
                    self._download_worker = None
                    return
                mc.write_eula(dest)
                cfg = srv.setdefault("config", {}) if srv else {}
                cfg["modpack_provider"] = "curseforge"
                cfg["modpack_name"] = getattr(worker, "modpack_name", self._download_meta.get("project_name", "Modpack"))
                cfg["modpack_project_id"] = getattr(worker, "project_id", self._download_meta.get("project_id", 0))
                cfg["modpack_file_id"] = getattr(worker, "file_id", self._download_meta.get("file_id", 0))
                if getattr(worker, "minecraft_version", ""):
                    cfg["minecraft_version"] = worker.minecraft_version
                    cfg["installed_version"] = worker.minecraft_version
                cfg["loader"] = worker.loader
                cfg["loader_version"] = getattr(worker, "loader_version", "")
                # The modpack installer may have selected a different Java
                # runtime from the normal server setting. Persist that exact
                # executable for this server so legacy Forge (1.12.x) is not
                # accidentally launched with Java 17+.
                pack_java = str(getattr(worker, "java_path", "") or "")
                if pack_java:
                    cfg["java_path"] = pack_java
                    self.java_path.set(pack_java)

                # Mirror the resolved fields onto this modpack's own profile
                # record too, so switching to another profile and back
                # restores them (not just the flat cfg fields above).
                profile_id = str(self._download_meta.get("profile_id") or "")
                if srv and profile_id:
                    profile = self._modpack_profiles(srv).setdefault(profile_id, {})
                    profile.update({
                        "provider": cfg.get("modpack_provider", "curseforge"),
                        "name": cfg.get("modpack_name", profile.get("name", "Modpack")),
                        "project_id": cfg.get("modpack_project_id", 0),
                        "file_id": cfg.get("modpack_file_id", 0),
                        "minecraft_version": cfg.get("minecraft_version", ""),
                        "installed_version": cfg.get("installed_version", ""),
                        "loader": cfg.get("loader", ""),
                        "loader_version": cfg.get("loader_version", ""),
                        "java_path": cfg.get("java_path", ""),
                    })
                self._persist()

                # Keep the Config tab's in-memory selections synchronized with
                # the modpack that was just installed. _refresh_config_tab()
                # will now preserve cfg["minecraft_version"] instead of
                # selecting the newest Mojang release.
                if cfg.get("minecraft_version"):
                    self._mc_selected_version = next(
                        (v for v in self._mc_versions if v.id == str(cfg["minecraft_version"])),
                        self._mc_selected_version,
                    )
                self._mc_selected_loader_version = str(cfg.get("loader_version", "") or "")
                progress.set(1)
                self.modpack_status.configure(text=f"{event.message} EULA recorded.", text_color=t.SUCCESS)
                self._append_console_line(f"[Modpack] {event.message}")
                self._download_worker = None
                self._refresh_overview()
                self._refresh_config_tab()
                self._refresh_mods()
                return
            if game == "bedrock":
                mc.write_bedrock_eula_ack(dest)
                mc.ensure_bedrock_server_properties(dest)
                version = getattr(worker, "version", "")
            elif game == "java":
                mc.write_eula(dest)
                version = self._download_meta.get("version", "")
                loader = self._download_meta.get("loader", "vanilla")
                loader_version = self._download_meta.get("loader_version", "")
            else:
                version = ""
            if srv and version:
                cfg = srv.setdefault("config", {})
                cfg["installed_version"] = version
                cfg["config_version"] = 2
                cfg["verified_version"] = version
                cfg["version_status"] = "match" if cfg.get("minecraft_version", version) == version else "mismatch"
                cfg["version_checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                if game == "java":
                    cfg["loader"] = self._download_meta.get("loader", "vanilla")
                    cfg["loader_version"] = self._download_meta.get("loader_version", "")
                self._persist()
            progress.set(1)
            btn.configure(state="normal")
            if game in ("java", "bedrock"):
                msg = f"{event.message} EULA recorded."
                self.config_status.configure(text=msg, text_color=t.SUCCESS)
            else:
                self.config_status.configure(text=event.message, text_color=t.SUCCESS)
            self._append_console_line(f"[Install] {event.message}")
            if game == "steam":
                dest.mkdir(parents=True, exist_ok=True)
                import os
                os.startfile(str(dest))
                if srv and srv.get("game_type") == "terraria":
                    self._sync_terraria_mode_from_folder(srv)
                    self.after(100, lambda: self._warn_terraria_mixed_folder(srv, force=True))
            self._download_worker = None
            from . import server_files as sf
            sf.invalidate_folder_size_cache(dest)
            self._refresh_config_tab()
            self._refresh_overview()
        elif event.kind == "error":
            btn.configure(state="normal")
            self.config_status.configure(text=event.message, text_color=t.DANGER)
            self._append_console_line(f"[Install] ERROR: {event.message}")
            self._download_worker = None

    # ------------------------------------------------------------------ logs

    def _build_logs_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(bar, text="Refresh", width=80, **t.secondary_button_style(),
                      command=self._refresh_logs).pack(side="left")
        self.logs_box = ctk.CTkTextbox(parent, fg_color=t.PANEL_2, font=t.mono(10),
                                       text_color=t.TEXT, state="disabled", wrap="none")
        self.logs_box.grid(row=1, column=0, sticky="nsew")

    def _refresh_logs(self) -> None:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return
        root = self._server_dir(srv)
        candidates = adapter.log_file_candidates(root)
        content = ""
        for path in candidates:
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    content = text[-50000:]
                    content = f"--- {path.relative_to(root)} ---\n{content}"
                    break
                except OSError:
                    continue
        if not content:
            names = ", ".join(str(p.relative_to(root)) for p in candidates[:4])
            content = f"(no log file found — checked: {names})"
        self.logs_box.configure(state="normal")
        self.logs_box.delete("1.0", "end")
        self.logs_box.insert("1.0", content)
        self.logs_box.configure(state="disabled")

    # ------------------------------------------------------------------ dashboard refresh

    def _refresh_dashboard(self, full: bool = True) -> None:
        srv = self._current_server()
        if not srv:
            return
        adapter = get_adapter(srv["game_type"])
        icon = adapter.icon if adapter else "🎮"
        new_title = f"{icon}  {srv['name']}"
        if self.dash_header.cget("text") != new_title:
            self.dash_header.configure(text=new_title)
        self._sync_controls()
        if full:
            self._refresh_overview()
            self._refresh_config_tab()
            self._rebuild_quick_commands()
            self._refresh_rcon_panel()
            self._rebuild_players(self._process(srv["id"]))
            self._refresh_access_list()
            self._refresh_files_listing()
            self._refresh_mods()
            self._refresh_backups()
            self._refresh_logs()
        else:
            self._refresh_active_tab()

    def _sync_controls(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        proc = self._process(srv["id"])
        running = proc.running
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.restart_btn.configure(state="normal" if running else "disabled")
        self.kill_btn.configure(state="normal" if running else "disabled")
        if running:
            self._set_state_pill("Running", t.SUCCESS)
        else:
            self._set_state_pill("Stopped", t.MUTED)

    # ------------------------------------------------------------------ tailscale

    def _refresh_tailscale_ip_async(self) -> None:
        self.address_label.configure(text="Checking…", text_color=t.MUTED)

        def work():
            status = self._tailscale_status()
            self.after(0, lambda: self._finish_tailscale_ip(status))
        threading.Thread(target=work, daemon=True).start()

    def _tailscale_status(self) -> dict:
        service = getattr(getattr(self.manager, "container", None), "tailscale_service", None)
        if service is not None:
            return service.get_status()
        ip, error = mc.get_tailscale_ip_fallback()
        return {
            "installed": bool(ip or error != "Tailscale CLI not found."),
            "running": bool(ip),
            "hostname": "",
            "tailscale_ip": ip,
            "_error": error,
        }

    def _finish_tailscale_ip(self, status: dict) -> None:
        self._tailscale_ip = status.get("tailscale_ip", "")
        self._tailscale_hostname = status.get("hostname", "")
        if not status.get("installed"):
            self._tailscale_error = "Tailscale isn't installed."
        elif not status.get("running"):
            self._tailscale_error = "Not connected to your tailnet."
        elif not self._tailscale_ip:
            self._tailscale_error = status.get("_error") or "No Tailscale IP yet."
        else:
            self._tailscale_error = ""
        self._update_address_display()

    def _update_address_display(self) -> None:
        adapter = self._current_adapter()
        if not self._tailscale_ip:
            self.address_label.configure(text=self._tailscale_error or "Tailscale not available", text_color=t.DANGER)
            self.address_eye_btn.configure(state="disabled")
            self.address_copy_btn.configure(state="disabled")
            self.address_hostname_label.configure(text="")
            return
        self.address_eye_btn.configure(state="normal")
        port = self._port()
        full = f"{self._tailscale_ip}:{port}"
        proto = f" · {adapter.port_protocol()}" if adapter and adapter.port_protocol() != "TCP" else ""
        if self._ip_visible.get():
            self.address_label.configure(text=full, text_color=t.SUCCESS)
            self.address_eye_btn.configure(text="🙈")
            self.address_copy_btn.configure(state="normal")
            host = f"MagicDNS: {self._tailscale_hostname}" if self._tailscale_hostname else ""
            self.address_hostname_label.configure(text=host + proto)
        else:
            self.address_label.configure(text=f"{IP_MASK}:{port}", text_color=t.TEXT)
            self.address_eye_btn.configure(text="👁")
            self.address_copy_btn.configure(state="disabled")
            self.address_hostname_label.configure(text=proto.strip(" ·"))

    def _toggle_ip_visibility(self) -> None:
        self._ip_visible.set(not self._ip_visible.get())
        self._update_address_display()
        self._update_lan_display()

    def _copy_address(self) -> None:
        if self._tailscale_ip and self._ip_visible.get():
            self.clipboard_clear()
            self.clipboard_append(f"{self._tailscale_ip}:{self._port()}")

    # ------------------------------------------------------------------ start/stop

    def _set_state_pill(self, text: str, color: str) -> None:
        key = (text, color)
        if key == self._state_pill_state:
            return
        self._state_pill_state = key
        running = text == "Running"
        active = text in ("Restarting", "Starting")
        self.state_pill.configure(text=f"● {text}", **st.status_pill_style(running, active))

    def _build_start_config(self, srv: dict, adapter) -> dict:
        cfg = dict(srv.get("config", {}))
        if adapter.game_type == "minecraft_java":
            cfg.setdefault("min_mb", self._mem_mb(self.min_mb, 1024) if hasattr(self, "min_mb") else 1024)
            cfg.setdefault("max_mb", self._mem_mb(self.max_mb, 2048) if hasattr(self, "max_mb") else 2048)
            cfg.setdefault("java_path", self.java_path.get() if hasattr(self, "java_path") else "java")
            mc_version = str(cfg.get("minecraft_version", ""))
            if mc_version and str(cfg.get("java_path", "java")) in ("", "java", "auto"):
                match = recommended_runtime(mc_version, self._java_runtimes)
                if match:
                    cfg["java_path"] = match.path
            if mc_version:
                required = required_java_major(mc_version)
                ok = any(r.major == required and Path(r.path).resolve() == Path(str(cfg.get("java_path", "java"))).resolve() for r in self._java_runtimes)
                if not ok and str(cfg.get("java_path", "java")) in ("", "java", "auto"):
                    return cfg
        return cfg

    def _start_server(self) -> None:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return
        proc = self._process(srv["id"])
        if proc.running:
            return
        if srv.get("game_type") == "terraria":
            self._sync_terraria_mode_from_folder(srv)
            self._warn_terraria_mixed_folder(srv, force=True)
        config = self._build_start_config(srv, adapter)
        if adapter.game_type == "minecraft_java":
            mc_version = str(config.get("minecraft_version", ""))
            if mc_version:
                required = required_java_major(mc_version)
                java_path = str(config.get("java_path", "java"))
                ok = False
                selected_major = None
                for runtime in self._java_runtimes:
                    try:
                        same_path = Path(runtime.path).resolve() == Path(java_path).resolve()
                    except OSError:
                        same_path = runtime.path.lower() == java_path.lower()
                    if same_path:
                        selected_major = runtime.major
                        ok = runtime.major == required
                        break
                if not ok:
                    detail = f"Minecraft {mc_version} requires Java {required}."
                    if selected_major is not None:
                        detail += f" Selected Java is {selected_major}."
                    else:
                        detail += " The required Java runtime is not installed/detected."
                    self._append_console_line(f"[Manager] {detail}")
                    if selected_major is None:
                        self._install_required_java_async(required, lambda: self._start_server())
                    else:
                        self._refresh_java_runtimes_async()
                    return
        error = proc.start(self._server_dir(srv), config, adapter)
        if error:
            self._append_console_line(f"[Manager] {error}")
            return
        self._sync_controls()
        self._set_state_pill("Starting", t.ACCENT)
        self._append_console_line(f"[Manager] Starting {adapter.display_name}…")
        self._refresh_overview()

    def _stop_server(self) -> None:
        srv = self._current_server()
        if srv:
            self._process(srv["id"]).stop(graceful=True)

    def _restart_server(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        proc = self._process(srv["id"])
        if not proc.running:
            return
        self._restart_flags[srv["id"]] = True
        self._append_console_line("[Manager] Restarting…")
        self._set_state_pill("Restarting", t.ACCENT)
        proc.stop(graceful=True)

    def _confirm_kill(self) -> None:
        if messagebox.askyesno("Kill Server", "Force-kill skips graceful shutdown. Continue?", icon="warning"):
            srv = self._current_server()
            if srv:
                self._process(srv["id"]).stop(graceful=False)

    def _send_command(self) -> None:
        text = self.command_entry.get().strip()
        if not text:
            return
        self._push_command_history(text)
        self._send_raw_command(text)
        self.command_entry.delete(0, "end")

    def _send_raw_command(self, text: str) -> None:
        srv = self._current_server()
        if not srv:
            return
        proc = self._process(srv["id"])
        if not proc.running:
            self._append_console_line("[Manager] Server isn't running.")
            return

        adapter = self._current_adapter()
        config = srv.get("config", {})
        remote = getattr(adapter, "execute_remote_command", None) if adapter else None
        prefers_remote = (
            remote is not None
            and adapter is not None
            and adapter.prefers_remote_console(config)
        )
        if prefers_remote:
            server_dir = self._server_dir(srv)

            def _worker() -> None:
                try:
                    result = remote(text, config, server_dir)
                except Exception as e:  # noqa: BLE001
                    result = (False, str(e))
                if result is None:
                    self.after(0, lambda: self._send_raw_command_stdin(text, srv, proc))
                    return

                ok, msg = result
                prefix = "" if ok else "[Manager] "
                line = f"{prefix}{msg}" if msg else f"> {text} (ok)"

                def _finish() -> None:
                    self._append_console_line(f"> {text}")
                    if msg:
                        self._append_console_line(line)

                self.after(0, _finish)

            threading.Thread(target=_worker, daemon=True).start()
            return

        self._send_raw_command_stdin(text, srv, proc)

    def _send_raw_command_stdin(self, text: str, srv: dict, proc) -> None:
        if proc.send(text):
            self._append_console_line(f"> {text}")
        elif proc.proc is not None and proc.proc.stdin is None:
            self._append_console_line(
                "[Manager] Couldn't send command — this server wasn't started with console input.",
            )
        else:
            self._append_console_line("[Manager] Couldn't send command to the server.")

    # ------------------------------------------------------------------ console helpers

    def _log_tag_rules(self) -> list[tuple[re.Pattern[str], str]]:
        adapter = self._current_adapter()
        if adapter:
            return [(r.pattern, r.tag) for r in adapter.log_tag_rules()]
        return []

    def _line_tag(self, line: str, previous_tag: str | None = None) -> str:
        for pattern, tag in _CONSOLE_TAG_RULES:
            if pattern.search(line):
                return tag
        for pattern, tag in self._log_tag_rules():
            if pattern.search(line):
                return tag
        if (
            previous_tag in _CONTINUATION_TAGS
            and line.strip()
            and not _STRUCTURED_LOG_LINE.match(line)
        ):
            return previous_tag
        return "log_default"

    def _track_console_tag(self, server_id: str, line: str, tag: str) -> None:
        if not line.strip():
            return
        if tag != "log_default":
            self._console_last_tag[server_id] = tag

    def _append_console_line(self, line: str, server_id: str | None = None) -> None:
        sid = server_id or self._selected_id
        if not sid:
            return
        prev = self._console_last_tag.get(sid)
        tag = self._line_tag(line, prev)
        self._track_console_tag(sid, line, tag)
        self._record_console_line(sid, line, tag)
        if sid != self._selected_id:
            return
        if self._is_scrolling():
            self._console_deferred = True
            return
        query = self._console_search.get().strip().lower()
        if query and query not in line.lower():
            return
        self.console_box.configure(state="normal")
        self.console_box.insert("end", line + "\n", tag)
        self._console_lines += 1
        if self._console_lines > MAX_CONSOLE_LINES:
            self.console_box.delete("1.0", "2.0")
            self._console_lines -= 1
        if self._autoscroll.get():
            self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def _clear_console(self) -> None:
        self._clear_console_for_server()

    # ------------------------------------------------------------------ players

    def _rebuild_players(self, proc: ServerProcess) -> None:
        for row in self._player_rows.values():
            row.destroy()
        self._player_rows.clear()
        if not proc.players:
            self.no_players_label.grid()
        else:
            self.no_players_label.grid_remove()
            adapter = self._current_adapter()
            actions = adapter.player_actions() if adapter else [("Kick", "kick")]
            for name in sorted(proc.players):
                self._add_player_row(name, actions)

    def _add_player_row(self, name: str, actions) -> None:
        if name in self._player_rows:
            return
        self.no_players_label.grid_remove()
        row = ctk.CTkFrame(self.players_frame, fg_color="transparent")
        row.grid(row=len(self._player_rows) + 1, column=0, sticky="ew", padx=8, pady=3)
        ctk.CTkLabel(row, text="●", font=t.font(10), text_color=t.SUCCESS, width=12).pack(side="left")
        ctk.CTkLabel(row, text=name, font=t.font(12), text_color=t.TEXT).pack(side="left", padx=(4, 8))
        proc = self._process()
        joined = proc.player_join_times.get(name)
        if joined:
            elapsed = self._format_session_time(time.time() - joined)
            ctk.CTkLabel(row, text=elapsed, font=t.font(10), text_color=t.MUTED).pack(side="left")
        adapter = self._current_adapter()
        for label, action in actions:
            cmd = adapter.player_command(action, name) if adapter else None
            if cmd:
                ctk.CTkButton(row, text=label, width=50, height=22, **t.secondary_button_style(),
                              command=lambda c=cmd: self._send_raw_command(c)).pack(side="right", padx=(4, 0))
        self._player_rows[name] = row
        self.players_header.configure(text=f"Players Online ({len(self._player_rows)})")

    def _remove_player_row(self, name: str) -> None:
        row = self._player_rows.pop(name, None)
        if row:
            row.destroy()
        if not self._player_rows:
            self.no_players_label.grid()
        self.players_header.configure(text="Players Online" if not self._player_rows
                                      else f"Players Online ({len(self._player_rows)})")

    # ------------------------------------------------------------------ polling

    def _poll_all(self) -> None:
        for srv in self.servers:
            proc = self._process(srv["id"])
            try:
                while True:
                    event: ServerEvent = proc.events.get_nowait()
                    self._handle_server_event(srv["id"], event)
            except Exception:
                pass

        scrolling = self._is_scrolling()
        if self._selected_id and not scrolling:
            if self._active_tab == "Overview":
                proc = self._process(self._selected_id)
                uptime_text = ""
                if proc.running and proc.started_at:
                    elapsed = int(time.time() - proc.started_at)
                    h, rem = divmod(elapsed, 3600)
                    m, s = divmod(rem, 60)
                    uptime_text = f"Uptime {h:02d}:{m:02d}:{s:02d} · {len(proc.players)} online"
                if uptime_text != self._uptime_cache:
                    self._uptime_cache = uptime_text
                    self.uptime_label.configure(text=uptime_text)
                elif not uptime_text and self._uptime_cache:
                    self._uptime_cache = ""
                    self.uptime_label.configure(text="")
                if proc.running and self._poll_tick % max(1, MONITOR_POLL_MS // POLL_MS) == 0:
                    self._update_monitoring()
                elif not proc.running and self._monitor_cache.get("cpu") != "CPU: —":
                    self._update_monitoring()

        if not scrolling and self._console_deferred and self._active_tab == "Console":
            self._console_deferred = False
            self._render_console_from_buffer()

        if (
            not scrolling
            and self._active_tab == "Players"
            and self._palworld_rcon_ready()
            and self._rcon_auto_refresh.get()
            and time.time() - self._rcon_last_poll >= 5.0
        ):
            self._rcon_last_poll = time.time()
            self._refresh_rcon_players_async()

        self._poll_tick += 1
        if not self._is_scrolling() and self._poll_tick % max(1, LIST_POLL_MS // POLL_MS) == 0:
            self._update_server_list()
        if self._poll_tick % 40 == 0:
            self._check_scheduled_backups()
        self.after(POLL_MS, self._poll_all)

    def _handle_server_event(self, server_id: str, event: ServerEvent) -> None:
        if event.kind == "log":
            self._append_console_line(event.message, server_id=server_id)
        elif server_id == self._selected_id:
            if event.kind == "ready":
                self._set_state_pill("Running", t.SUCCESS)
                self._refresh_overview()
            elif event.kind == "player_join":
                adapter = self._current_adapter()
                actions = adapter.player_actions() if adapter else [("Kick", "kick")]
                self._add_player_row(event.player, actions)
            elif event.kind == "player_leave":
                self._remove_player_row(event.player)
            elif event.kind == "stopped":
                self._append_console_line(f"[Manager] Server exited (code {event.exit_code}).", server_id)
                for name in list(self._player_rows):
                    self._remove_player_row(name)
                if self._restart_flags.pop(server_id, False):
                    self._set_state_pill("Restarting", t.ACCENT)
                    self.after(500, self._start_server)
                else:
                    self._set_state_pill("Stopped", t.MUTED)
                self._sync_controls()
                self._refresh_overview()

        proc = self._process(server_id)
        if event.kind == "player_join" and event.player:
            proc.players.add(event.player)
        elif event.kind == "player_leave" and event.player:
            proc.players.discard(event.player)


# Backward-compatible alias for plugin registration
MinecraftServerManagerModule = GameServerManagerModule