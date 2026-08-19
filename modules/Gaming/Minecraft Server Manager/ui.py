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
import threading
import time
import uuid
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import psutil

from . import backend as mc
from .game_picker import GamePicker
from .adapters import get_adapter, game_choices
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
from .core.settings import (
    align_terraria_server_folder,
    default_server_folder_for,
    load_servers,
    save_servers,
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
    "minecraft_java": {"min_mb": 1024, "max_mb": 2048, "java_path": "java"},
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

    def _on_game_pick_from_picker(self, label: str, game_type: str) -> None:
        self.game_type.set(game_type)
        if not self.import_mode:
            folder, name = default_server_folder_for(game_type)
            self.folder_var.set(folder)
            self.name_var.set(name)
        self._update_hint()

    def _on_game_pick(self, label: str) -> None:
        gt = self._game_map.get(label, "custom")
        self.game_type.set(gt)
        if not self.import_mode:
            folder, name = default_server_folder_for(gt)
            self.folder_var.set(folder)
            self.name_var.set(name)
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
        if name:
            self.name_var.set(name)
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
        self._pending_mc_download = False
        self._show_snapshots = ctk.BooleanVar(value=False)
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
        for tab in ("Overview", "Console", "Players", "Files", "Mods", "Backups", "Config", "Logs"):
            self.tabview.add(tab)
            self.tabview.tab(tab).configure(fg_color=t.PANEL_2)
        self.tabview.configure(command=self._on_tab_changed)

        self._build_overview_tab(self.tabview.tab("Overview"))
        self._build_console_tab(self.tabview.tab("Console"))
        self._build_players_tab(self.tabview.tab("Players"))
        self._build_files_tab(self.tabview.tab("Files"))
        self._build_mods_tab(self.tabview.tab("Mods"))
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

    def _server_dir(self, server: dict | None = None) -> Path:
        srv = server or self._current_server()
        return Path(srv["server_dir"]) if srv else Path(".")

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
        ctk.CTkButton(self.mc_java_row, text="Re-check", width=70, height=24, **t.secondary_button_style(),
                      command=self._check_java_async).pack(side="right")

        self.mc_version_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_version_row.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
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

        self.mc_bedrock_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_bedrock_row.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        self.bedrock_channel_menu = ctk.CTkOptionMenu(
            self.mc_bedrock_row, values=["Stable", "Preview"], width=120,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_bedrock_channel_selected,
        )
        self.bedrock_channel_menu.pack(side="left")

        self.mc_mem_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_mem_row.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        self.min_mb = ctk.IntVar(value=1024)
        self.max_mb = ctk.IntVar(value=2048)
        self.java_path = ctk.StringVar(value="java")
        ctk.CTkLabel(self.mc_mem_row, text="Min MB", text_color=t.MUTED, font=t.font(11)).pack(side="left")
        ctk.CTkEntry(self.mc_mem_row, textvariable=self.min_mb, width=70, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).pack(side="left", padx=(4, 12))
        ctk.CTkLabel(self.mc_mem_row, text="Max MB", text_color=t.MUTED, font=t.font(11)).pack(side="left")
        ctk.CTkEntry(self.mc_mem_row, textvariable=self.max_mb, width=70, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).pack(side="left", padx=(4, 0))

        eula_row = ctk.CTkFrame(parent, fg_color="transparent")
        eula_row.grid(row=5, column=0, sticky="w", padx=12, pady=4)
        ctk.CTkCheckBox(eula_row, text="I agree to Mojang's EULA", variable=self._eula_var,
                        fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.TEXT).pack(side="left")
        link = ctk.CTkLabel(eula_row, text="(view)", font=t.font(11, "bold"), text_color=t.ACCENT, cursor="hand2")
        link.pack(side="left", padx=(6, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open("https://aka.ms/MinecraftEULA"))

        dl_row = ctk.CTkFrame(parent, fg_color="transparent")
        dl_row.grid(row=6, column=0, sticky="ew", padx=12, pady=(4, 10))
        dl_row.grid_columnconfigure(1, weight=1)
        self.download_btn = ctk.CTkButton(dl_row, text="Download & Install", **t.primary_button_style(),
                                          command=self._start_mc_download)
        self.download_btn.grid(row=0, column=0, sticky="w")
        self.download_progress = ctk.CTkProgressBar(dl_row, progress_color=t.ACCENT)
        self.download_progress.set(0)
        self.download_progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))

        self.mc_update_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.mc_update_row.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 10))
        ctk.CTkButton(self.mc_update_row, text="Check for update", width=120, height=26,
                      **t.secondary_button_style(), command=self._check_java_update).pack(side="left")
        ctk.CTkButton(self.mc_update_row, text="Update server.jar", width=120, height=26,
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
            self.mc_version_row.grid() if is_java else self.mc_version_row.grid_remove()
            self.mc_bedrock_row.grid() if is_bedrock else self.mc_bedrock_row.grid_remove()
            self.mc_mem_row.grid() if is_java else self.mc_mem_row.grid_remove()
            self.mc_update_row.grid() if is_java else self.mc_update_row.grid_remove()
            cfg = srv.setdefault("config", {})
            self.min_mb.set(int(cfg.get("min_mb", 1024)))
            self.max_mb.set(int(cfg.get("max_mb", 2048)))
            self.java_path.set(cfg.get("java_path", "java"))
            channel = cfg.get("bedrock_channel", "stable")
            self.bedrock_channel_menu.set("Preview" if channel == "preview" else "Stable")
            if is_java:
                self._check_java_async()
                if self._mc_versions:
                    self._populate_mc_version_menu()
                elif not self._mc_versions_loading:
                    self._load_mc_versions_async()
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
            cfg["min_mb"] = self.min_mb.get()
            cfg["max_mb"] = self.max_mb.get()
            cfg["java_path"] = self.java_path.get()
            self._persist()

        self._append_console_line("[Manager] Config saved.")
        self._refresh_overview()
        self._refresh_config_tab()
        if adapter.game_type == "terraria":
            self._refresh_mods()
        self._update_address_display()

    # ---- minecraft install (preserved from original module) ----

    def _check_java_async(self) -> None:
        self.java_status_label.configure(text="Checking…")

        def work():
            found, version = mc.check_java(self.java_path.get())
            self.after(0, lambda: self.java_status_label.configure(
                text=f"Found — {version}" if found else "Not found — install Java 21+",
                text_color=t.SUCCESS if found else t.DANGER,
            ))
        threading.Thread(target=work, daemon=True).start()

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
        if self._pending_mc_download:
            self._pending_mc_download = False
            if self._eula_var.get():
                self._start_mc_download()

    def _populate_mc_version_menu(self) -> None:
        show = self._show_snapshots.get()
        filtered = [v for v in self._mc_versions if show or v.type == "release"]
        ids = [v.id for v in filtered] or ["(load versions first)"]
        self.version_menu.configure(values=ids)
        self.version_menu.set(ids[0])
        self._on_mc_version_selected(ids[0])

    def _on_mc_version_selected(self, version_id: str) -> None:
        if version_id == "(load versions first)":
            self._mc_selected_version = None
            return
        self._mc_selected_version = next((v for v in self._mc_versions if v.id == version_id), None)

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
            worker = create_minecraft_java_install_worker(dest, self._mc_selected_version)
            self._download_meta = {"game": "java", "version": self._mc_selected_version.id}
            self._append_console_line(
                f"[Manager] Downloading Minecraft {self._mc_selected_version.id} to {dest}…",
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
            if game == "steam":
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
        elif event.kind == "done":
            srv = self._current_server()
            dest = self._server_dir(srv) if srv else Path(".")
            if game == "bedrock":
                mc.write_bedrock_eula_ack(dest)
                mc.ensure_bedrock_server_properties(dest)
                version = getattr(worker, "version", "")
            elif game == "java":
                mc.write_eula(dest)
                version = self._download_meta.get("version", "")
            else:
                version = ""
            if srv and version:
                srv.setdefault("config", {})["installed_version"] = version
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
            cfg.setdefault("min_mb", self.min_mb.get() if hasattr(self, "min_mb") else 1024)
            cfg.setdefault("max_mb", self.max_mb.get() if hasattr(self, "max_mb") else 2048)
            cfg.setdefault("java_path", self.java_path.get() if hasattr(self, "java_path") else "java")
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
