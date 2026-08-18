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
from .adapters import get_adapter, game_choices
from .adapters.install import (
    create_minecraft_bedrock_install_worker,
    create_minecraft_java_install_worker,
    create_steamcmd_install_worker,
    find_steamcmd,
)
from .core.console_buffer import ConsoleBuffer
from .core.events import DownloadEvent, ServerEvent
from .core.process import ServerProcess
from .core.settings import load_servers, save_servers
from .style import theme as t
from .style import card_style, hint_style, selected_card_style, stat_pill_style
from .style import STATUS_RUNNING, STATUS_STARTING, STATUS_STOPPED

POLL_MS = 80
MAX_CONSOLE_LINES = 2000
IP_MASK = "•" * 13

_LOG_TAG_COLORS = {
    "manager": "#7fa8d9",
    "command": "#c9a6e8",
    "log_error": "#ff6b6b",
    "log_warn": "#e8b339",
    "log_join": "#5fb85a",
    "log_leave": "#e8834f",
}


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _new_server_id() -> str:
    return uuid.uuid4().hex[:12]


class AddServerWizard(ctk.CTkToplevel):
    def __init__(self, master, on_created):
        super().__init__(master)
        self.title("Add Game Server")
        self.geometry("540x480")
        self.resizable(False, False)
        self.configure(fg_color=t.BG)
        self.on_created = on_created
        self.transient(master.winfo_toplevel())
        self.grab_set()

        self.game_type = ctk.StringVar(value="minecraft_java")
        self.name_var = ctk.StringVar(value="My Server")
        self.folder_var = ctk.StringVar(
            value=str(Path.home() / "Documents" / "Game Servers" / "My Server")
        )

        self.grid_columnconfigure(0, weight=1)

        hero = ctk.CTkFrame(self, fg_color=t.ACCENT_DIM, corner_radius=t.RADIUS_SM)
        hero.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 12))
        ctk.CTkLabel(hero, text="🖥️  Add Game Server", font=t.font(18, "bold"),
                     text_color=t.TEXT).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(hero, text="Pick a game type, name your server, and choose a folder.",
                     font=t.font(11), text_color=t.MUTED).pack(anchor="w", padx=16, pady=(0, 14))

        body = ctk.CTkFrame(self, **card_style(t.PANEL))
        body.grid(row=1, column=0, sticky="ew", padx=20)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="Game", font=t.font(12, "bold"), text_color=t.MUTED
                     ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        choices = [f"{icon}  {name}" for _, name, icon in game_choices()]
        self._game_map = {f"{icon}  {name}": gt for gt, name, icon in game_choices()}
        self.game_menu = ctk.CTkOptionMenu(
            body, values=choices or ["Custom"], width=400,
            fg_color=t.PANEL_2, button_color=t.ACCENT, button_hover_color=t.ACCENT_HOVER,
            command=self._on_game_pick,
        )
        self.game_menu.set(choices[0] if choices else "Custom")
        self.game_menu.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        ctk.CTkLabel(body, text="Server name", font=t.font(12, "bold"), text_color=t.MUTED
                     ).grid(row=2, column=0, sticky="w", padx=16)
        ctk.CTkEntry(body, textvariable=self.name_var, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).grid(
            row=3, column=0, sticky="ew", padx=16, pady=(4, 12))

        ctk.CTkLabel(body, text="Server folder", font=t.font(12, "bold"), text_color=t.MUTED
                     ).grid(row=4, column=0, sticky="w", padx=16)
        folder_row = ctk.CTkFrame(body, fg_color="transparent")
        folder_row.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 12))
        folder_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(folder_row, textvariable=self.folder_var, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(folder_row, text="Browse…", width=90, **t.secondary_button_style(),
                      command=self._browse).grid(row=0, column=1, padx=(8, 0))

        self.hint_label = ctk.CTkLabel(body, text="", font=t.font(11), text_color=t.MUTED,
                                       wraplength=460, justify="left")
        self.hint_label.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 14))
        self._update_hint()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="e", padx=20, pady=(16, 20))
        ctk.CTkButton(btn_row, text="Cancel", width=90, **t.secondary_button_style(),
                      command=self.destroy).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Add Server", **t.primary_button_style(),
                      command=self._create).pack(side="left")

    def _on_game_pick(self, label: str) -> None:
        self.game_type.set(self._game_map.get(label, "custom"))
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
        if chosen:
            self.folder_var.set(chosen)

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
        adapter = get_adapter(gt)
        config: dict = {}
        if gt == "minecraft_java":
            config = {"min_mb": 1024, "max_mb": 2048, "java_path": "java"}
        elif gt == "minecraft_bedrock":
            config = {"bedrock_channel": "stable"}
        elif gt == "steamcmd":
            config = {"steam_app_id": "2394010", "executable": "PalServer.exe", "port": "8211"}
        elif gt == "custom":
            config = {"executable": "server.exe", "port": "25565", "stop_command": "stop"}
        else:
            config = {"port": str(adapter.default_port()) if adapter else "25565"}

        server = {
            "id": _new_server_id(),
            "name": name,
            "game_type": gt,
            "server_dir": folder,
            "config": config,
        }
        self.on_created(server)
        self.destroy()


class GameServerManagerModule(ctk.CTkFrame):
    """Universal game server manager."""

    def __init__(self, master, manager=None, **kwargs):
        super().__init__(master, fg_color=t.BG, **kwargs)
        self.manager = manager

        self.servers: list[dict] = load_servers()
        self._processes: dict[str, ServerProcess] = {}
        self._selected_id: str | None = self.servers[0]["id"] if self.servers else None
        self._restart_flags: dict[str, bool] = {}
        self._download_worker = None
        self._download_meta: dict = {}
        self._console_lines = 0
        self._autoscroll = ctk.BooleanVar(value=True)
        self._ip_visible = ctk.BooleanVar(value=False)
        self._tailscale_ip = ""
        self._tailscale_hostname = ""
        self._tailscale_error = ""
        self._config_vars: dict[str, ctk.Variable] = {}
        self._player_rows: dict[str, ctk.CTkFrame] = {}
        self._list_rows: dict[str, ctk.CTkFrame] = {}
        self._console_buffers: dict[str, ConsoleBuffer] = {}

        # Minecraft install state (Config tab)
        self._mc_versions: list[mc.MCVersion] = []
        self._mc_selected_version: mc.MCVersion | None = None
        self._show_snapshots = ctk.BooleanVar(value=False)
        self._eula_var = ctk.BooleanVar(value=False)

        self._build_layout()
        self._refresh_server_list()
        if self._selected_id:
            self._select_server(self._selected_id)
        self._refresh_tailscale_ip_async()
        self.after(POLL_MS, self._poll_all)

    # ------------------------------------------------------------------ layout

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 8))
        header.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkFrame(header, fg_color=t.ACCENT_DIM, corner_radius=t.RADIUS_SM, width=44, height=44)
        badge.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 12))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text="🖥️", font=t.font(20), text_color=t.TEXT).place(relx=0.5, rely=0.5, anchor="center")

        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(title_col, text="Game Server Manager", font=t.font(22, "bold"),
                     text_color=t.TEXT).pack(anchor="w")
        ctk.CTkLabel(
            title_col,
            text="Minecraft · Valheim · Palworld · Satisfactory · Terraria · Project Zomboid · SteamCMD · Custom",
            font=t.font(11), text_color=t.MUTED,
        ).pack(anchor="w", pady=(2, 0))

        self.stats_row = ctk.CTkFrame(header, fg_color="transparent")
        self.stats_row.grid(row=0, column=2, rowspan=2, sticky="e")
        self.stat_running = ctk.CTkLabel(self.stats_row, text="0 running", font=t.font(11, "bold"),
                                         text_color=t.SUCCESS, **stat_pill_style(), width=90)
        self.stat_running.pack(side="left", padx=(0, 8))
        self.stat_players = ctk.CTkLabel(self.stats_row, text="0 players", font=t.font(11, "bold"),
                                         text_color=t.TEXT, **stat_pill_style(), width=90)
        self.stat_players.pack(side="left")

        # ---- left: server list ----
        left = ctk.CTkFrame(self, fg_color=t.PANEL, corner_radius=t.RADIUS_SM, width=280)
        left.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
        left.grid_propagate(False)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        list_header = ctk.CTkFrame(left, fg_color="transparent")
        list_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ctk.CTkLabel(list_header, text="Servers", font=t.font(14, "bold"), text_color=t.TEXT
                     ).pack(side="left")
        ctk.CTkButton(list_header, text="+ Add", width=60, height=28, **t.primary_button_style(),
                      command=self._open_add_wizard).pack(side="right")

        self.server_list_frame = ctk.CTkScrollableFrame(left, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        self.server_list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.server_list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(left, text="Remove Selected", **t.danger_button_style(),
                      command=self._remove_selected).grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        # ---- right: dashboard ----
        self.dashboard = ctk.CTkFrame(self, fg_color=t.PANEL, corner_radius=t.RADIUS_SM)
        self.dashboard.grid(row=1, column=1, sticky="nsew", padx=(0, 16), pady=(0, 16))
        self.dashboard.grid_columnconfigure(0, weight=1)
        self.dashboard.grid_rowconfigure(2, weight=1)

        self.dash_header = ctk.CTkLabel(self.dashboard, text="Select a server", font=t.font(16, "bold"),
                                        text_color=t.TEXT, anchor="w")
        self.dash_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))

        self.control_row = ctk.CTkFrame(self.dashboard, fg_color="transparent")
        self.control_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.start_btn = ctk.CTkButton(self.control_row, text="▶ Start", **t.primary_button_style(),
                                       command=self._start_server)
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ctk.CTkButton(self.control_row, text="Stop", state="disabled",
                                      **t.secondary_button_style(), command=self._stop_server)
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.restart_btn = ctk.CTkButton(self.control_row, text="⟳ Restart", state="disabled",
                                         **t.secondary_button_style(), command=self._restart_server)
        self.restart_btn.pack(side="left", padx=(0, 6))
        self.kill_btn = ctk.CTkButton(self.control_row, text="Kill", state="disabled",
                                      **t.danger_button_style(), command=self._confirm_kill)
        self.kill_btn.pack(side="left")
        self.state_pill = ctk.CTkLabel(self.control_row, text="● Stopped", font=t.font(12, "bold"),
                                       text_color=t.MUTED, fg_color=t.PANEL_2,
                                       corner_radius=t.RADIUS_SM, width=100, height=26)
        self.state_pill.pack(side="right")

        self.tabview = ctk.CTkTabview(
            self.dashboard, fg_color=t.PANEL_2,
            segmented_button_fg_color=t.PANEL,
            segmented_button_selected_color=t.ACCENT,
            segmented_button_selected_hover_color=t.ACCENT_HOVER,
            text_color=t.TEXT,
        )
        self.tabview.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        for tab in ("Overview", "Console", "Players", "Files", "Mods", "Backups", "Config", "Logs"):
            self.tabview.add(tab)

        self._build_overview_tab(self.tabview.tab("Overview"))
        self._build_console_tab(self.tabview.tab("Console"))
        self._build_players_tab(self.tabview.tab("Players"))
        self._build_files_tab(self.tabview.tab("Files"))
        self._build_mods_tab(self.tabview.tab("Mods"))
        self._build_backups_tab(self.tabview.tab("Backups"))
        self._build_config_tab(self.tabview.tab("Config"))
        self._build_logs_tab(self.tabview.tab("Logs"))

        self.empty_label = ctk.CTkLabel(
            self.dashboard,
            text="No servers yet — click + Add to create one.",
            font=t.font(13), text_color=t.MUTED,
        )

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
        return str(cfg.get("port") or adapter.default_port())

    # ------------------------------------------------------------------ server list

    def _persist(self) -> None:
        save_servers(self.servers)

    def _console_buffer(self, server_id: str | None = None) -> ConsoleBuffer:
        sid = server_id or self._selected_id
        if not sid:
            return ConsoleBuffer()
        if sid not in self._console_buffers:
            self._console_buffers[sid] = ConsoleBuffer(max_lines=MAX_CONSOLE_LINES)
        return self._console_buffers[sid]

    def _render_console(self, server_id: str | None = None) -> None:
        sid = server_id or self._selected_id
        buf = self._console_buffer(sid)
        self.console_box.configure(state="normal")
        self.console_box.delete("1.0", "end")
        for line in buf.lines():
            if line.tag:
                self.console_box.insert("end", line.text + "\n", line.tag)
            else:
                self.console_box.insert("end", line.text + "\n")
        self._console_lines = len(buf)
        if self._autoscroll.get():
            self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def _update_header_stats(self) -> None:
        running = sum(1 for s in self.servers if self._process(s["id"]).running)
        players = sum(len(self._process(s["id"]).players) for s in self.servers)
        self.stat_running.configure(
            text=f"{running} running",
            text_color=t.SUCCESS if running else t.MUTED,
        )
        self.stat_players.configure(text=f"{players} players")

    def _refresh_server_list(self) -> None:
        for row in self._list_rows.values():
            row.destroy()
        self._list_rows.clear()
        self._update_header_stats()

        if not self.servers:
            self.empty_label.grid(row=0, column=0, rowspan=3, sticky="nsew")
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
            if running:
                status_color = STATUS_RUNNING
            elif self._restart_flags.get(srv["id"]):
                status_color = STATUS_STARTING
            else:
                status_color = STATUS_STOPPED
            icon = adapter.icon if adapter else "🎮"
            game_name = adapter.display_name if adapter else srv["game_type"]
            n_players = len(proc.players) if running else 0
            selected = srv["id"] == self._selected_id
            style = selected_card_style() if selected else {
                "fg_color": "transparent",
                "corner_radius": t.RADIUS_SM,
                "border_width": 1,
                "border_color": t.BORDER,
            }

            row = ctk.CTkFrame(self.server_list_frame, **style)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            row.grid_columnconfigure(2, weight=1)

            accent = ctk.CTkFrame(row, fg_color=status_color if selected else status_color,
                                  width=4, corner_radius=2)
            accent.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 8), pady=6)

            ctk.CTkLabel(row, text=icon, font=t.font(16), width=28).grid(
                row=0, column=1, rowspan=2, padx=(0, 6), pady=8)
            ctk.CTkLabel(row, text=srv["name"], font=t.font(12, "bold"),
                         text_color=t.TEXT, anchor="w").grid(row=0, column=2, sticky="w", pady=(8, 0))
            meta = f"{game_name}  ·  {n_players} online" if running else game_name
            ctk.CTkLabel(row, text=meta, font=t.font(10),
                         text_color=t.MUTED, anchor="w").grid(row=1, column=2, sticky="w", pady=(0, 8))

            def _bind_click(widget, sid=srv["id"]):
                widget.bind("<Button-1>", lambda _e, s=sid: self._select_server(s))
                widget.bind("<Enter>", lambda _e, r=row: r.configure(border_color=t.ACCENT) if not selected else None)
                widget.bind("<Leave>", lambda _e, r=row, sel=selected: r.configure(
                    border_color=selected_card_style()["border_color"] if sel else t.BORDER,
                ))

            for child in row.winfo_children():
                _bind_click(child)
            _bind_click(row)

            self._list_rows[srv["id"]] = row

    def _select_server(self, server_id: str) -> None:
        self._selected_id = server_id
        self._refresh_server_list()
        self._render_console(server_id)
        self._refresh_dashboard()

    def _open_add_wizard(self) -> None:
        AddServerWizard(self, self._on_server_added)

    def _on_server_added(self, server: dict) -> None:
        self.servers.append(server)
        self._persist()
        self._selected_id = server["id"]
        self._refresh_server_list()
        self._refresh_dashboard()

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
        self._console_buffers.pop(srv["id"], None)
        self._persist()
        self._selected_id = self.servers[0]["id"] if self.servers else None
        self._refresh_server_list()
        self._refresh_dashboard()

    # ------------------------------------------------------------------ overview

    def _build_overview_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        self.overview_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.overview_scroll.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        self.overview_scroll.grid_columnconfigure(0, weight=1)

        self._build_address_panel(self.overview_scroll)

        self.overview_info = ctk.CTkFrame(self.overview_scroll, fg_color="transparent")
        self.overview_info.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.overview_info.grid_columnconfigure((0, 1, 2), weight=1)

        self.overview_details = ctk.CTkFrame(self.overview_scroll, **card_style(t.PANEL))
        self.overview_details.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.overview_details.grid_columnconfigure(1, weight=1)
        self.uptime_label = ctk.CTkLabel(self.overview_scroll, text="", font=t.font(12), text_color=t.MUTED)
        self.uptime_label.grid(row=2, column=0, sticky="w", pady=(8, 0))

    def _build_address_panel(self, parent) -> None:
        panel = ctk.CTkFrame(parent, **t.panel_style())
        panel.grid(row=0, column=0, sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        ctk.CTkLabel(header, text="Server Address (Tailscale)", font=t.font(12, "bold"),
                     text_color=t.TEXT).pack(side="left")
        addr_row = ctk.CTkFrame(panel, fg_color="transparent")
        addr_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 8))
        addr_row.grid_columnconfigure(0, weight=1)
        self.address_label = ctk.CTkLabel(addr_row, text="Checking…", font=t.mono(13),
                                          text_color=t.TEXT, anchor="w")
        self.address_label.grid(row=0, column=0, sticky="ew")
        self.address_eye_btn = ctk.CTkButton(addr_row, text="👁", width=30, height=26,
                                             **t.secondary_button_style(), command=self._toggle_ip_visibility)
        self.address_eye_btn.grid(row=0, column=1, padx=(6, 0))
        self.address_copy_btn = ctk.CTkButton(addr_row, text="📋", width=30, height=26,
                                              **t.secondary_button_style(), command=self._copy_address)
        self.address_copy_btn.grid(row=0, column=2, padx=(6, 0))
        ctk.CTkButton(addr_row, text="↻", width=30, height=26, **t.secondary_button_style(),
                      command=self._refresh_tailscale_ip_async).grid(row=0, column=3, padx=(6, 0))
        self.address_hostname_label = ctk.CTkLabel(panel, text="", font=t.font(10),
                                                     text_color=t.MUTED, anchor="w")
        self.address_hostname_label.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))

    def _refresh_overview(self) -> None:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return

        for child in self.overview_info.winfo_children():
            child.destroy()
        for child in self.overview_details.winfo_children():
            child.destroy()

        proc = self._process(srv["id"])
        port = self._port()
        installed = adapter.is_installed(self._server_dir(srv))
        stats = [
            ("Status", "Running" if proc.running else "Stopped", t.SUCCESS if proc.running else t.MUTED),
            ("Port", port, t.TEXT),
            ("Protocol", adapter.port_protocol(), t.TEXT),
            ("Players", str(len(proc.players)), t.SUCCESS if proc.players else t.MUTED),
            ("Install", "Ready" if installed else "Missing", t.SUCCESS if installed else t.ACCENT),
        ]
        for i, (label, value, color) in enumerate(stats):
            card = ctk.CTkFrame(self.overview_info, **card_style(t.PANEL))
            card.grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="nsew")
            ctk.CTkLabel(card, text=label, font=t.font(10), text_color=t.MUTED).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(card, text=value, font=t.font(14, "bold"), text_color=color).pack(anchor="w", padx=10, pady=(0, 10))

        rows = adapter.overview_rows(self._server_dir(srv), srv.get("config", {}))
        for i, (label, value) in enumerate(rows):
            ctk.CTkLabel(self.overview_details, text=label, font=t.font(11), text_color=t.MUTED
                         ).grid(row=i, column=0, sticky="w", padx=12, pady=4)
            ctk.CTkLabel(self.overview_details, text=value, font=t.font(11), text_color=t.TEXT,
                         anchor="w", wraplength=420).grid(row=i, column=1, sticky="w", padx=(0, 12), pady=4)

        self._update_address_display()

    # ------------------------------------------------------------------ console

    def _build_console_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="nsew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_rowconfigure(0, weight=1)

        self.console_box = ctk.CTkTextbox(
            top, fg_color=t.PANEL, text_color=t.TEXT, font=t.mono(11),
            wrap="none", corner_radius=t.RADIUS_SM, state="disabled",
        )
        self.console_box.grid(row=0, column=0, sticky="nsew")
        for tag, color in _LOG_TAG_COLORS.items():
            self.console_box.tag_config(tag, foreground=color)

        ctk.CTkCheckBox(top, text="Auto-scroll", variable=self._autoscroll,
                        fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER, text_color=t.MUTED,
                        font=t.font(11)).grid(row=1, column=0, sticky="e", pady=(6, 0))

        cmd_row = ctk.CTkFrame(parent, fg_color="transparent")
        cmd_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        cmd_row.grid_columnconfigure(0, weight=1)
        self.command_entry = ctk.CTkEntry(
            cmd_row, placeholder_text="Type a server command…",
            fg_color=t.PANEL, border_color=t.BORDER, text_color=t.TEXT,
        )
        self.command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.command_entry.bind("<Return>", lambda _e: self._send_command())
        ctk.CTkButton(cmd_row, text="Send", width=80, **t.secondary_button_style(),
                      command=self._send_command).grid(row=0, column=1)

        self.quick_cmd_row = ctk.CTkFrame(parent, fg_color="transparent")
        self.quick_cmd_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ctk.CTkButton(self.quick_cmd_row, text="Clear", width=80, height=26,
                      **t.secondary_button_style(), command=self._clear_console).pack(side="right")

    def _rebuild_quick_commands(self) -> None:
        for child in self.quick_cmd_row.winfo_children():
            child.destroy()
        adapter = self._current_adapter()
        if adapter:
            for label, cmd in adapter.quick_commands():
                ctk.CTkButton(self.quick_cmd_row, text=label, width=90, height=26,
                              **t.secondary_button_style(),
                              command=lambda c=cmd: self._send_raw_command(c)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self.quick_cmd_row, text="Clear", width=80, height=26,
                      **t.secondary_button_style(), command=self._clear_console).pack(side="right")

    # ------------------------------------------------------------------ players

    def _build_players_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        self.players_header = ctk.CTkLabel(parent, text="Players Online", font=t.font(14, "bold"),
                                           text_color=t.TEXT, anchor="w")
        self.players_header.grid(row=0, column=0, sticky="w", pady=(4, 8))
        self.players_frame = ctk.CTkScrollableFrame(parent, fg_color=t.PANEL_2, corner_radius=t.RADIUS_SM)
        self.players_frame.grid(row=1, column=0, sticky="nsew")
        self.players_frame.grid_columnconfigure(0, weight=1)
        self.no_players_label = ctk.CTkLabel(self.players_frame, text="No players online.",
                                             text_color=t.MUTED, font=t.font(12))
        self.no_players_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

    # ------------------------------------------------------------------ files

    def _build_files_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(bar, text="Refresh", width=80, **t.secondary_button_style(),
                      command=self._refresh_files).pack(side="left")
        ctk.CTkButton(bar, text="Open in Explorer", width=120, **t.secondary_button_style(),
                      command=self._open_server_folder).pack(side="left", padx=(8, 0))
        self.files_box = ctk.CTkTextbox(parent, fg_color=t.PANEL_2, font=t.mono(11),
                                        text_color=t.TEXT, state="disabled")
        self.files_box.grid(row=1, column=0, sticky="nsew")

    def _refresh_files(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        root = self._server_dir(srv)
        lines = []
        if root.exists():
            for p in sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                prefix = "📁 " if p.is_dir() else "📄 "
                try:
                    size = p.stat().st_size if p.is_file() else 0
                    extra = f"  ({_human_size(size)})" if p.is_file() else ""
                except OSError:
                    extra = ""
                lines.append(f"{prefix}{p.name}{extra}")
        else:
            lines.append("(folder does not exist yet)")
        self.files_box.configure(state="normal")
        self.files_box.delete("1.0", "end")
        self.files_box.insert("1.0", "\n".join(lines))
        self.files_box.configure(state="disabled")

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
        parent.grid_rowconfigure(1, weight=1)
        self.mods_hint = ctk.CTkLabel(parent, text="", font=t.font(12), text_color=t.MUTED, anchor="w")
        self.mods_hint.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew")
        ctk.CTkButton(bar, text="Refresh", width=80, **t.secondary_button_style(),
                      command=self._refresh_mods).pack(side="left")
        ctk.CTkButton(bar, text="Open mods folder", width=130, **t.secondary_button_style(),
                      command=self._open_mods_folder).pack(side="left", padx=(8, 0))
        self.mods_box = ctk.CTkTextbox(parent, fg_color=t.PANEL_2, font=t.mono(11),
                                       text_color=t.TEXT, state="disabled")
        self.mods_box.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        parent.grid_rowconfigure(2, weight=1)

    def _refresh_mods(self) -> None:
        adapter = self._current_adapter()
        srv = self._current_server()
        if not adapter or not srv:
            return
        if not adapter.supports_mods():
            self.mods_hint.configure(text="This game type does not expose a mods folder through the adapter.")
            self.mods_box.configure(state="normal")
            self.mods_box.delete("1.0", "end")
            self.mods_box.configure(state="disabled")
            return
        mods_dir = adapter.mods_directory(self._server_dir(srv))
        if mods_dir is None:
            mods_dir = self._server_dir(srv) / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        self.mods_hint.configure(text=f"Mods folder: {mods_dir}")
        files = sorted(mods_dir.glob("*"))
        lines = [f.name for f in files if f.is_file()] or ["(empty)"]
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
        parent.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(parent, text="Zip the entire server folder for a quick backup.",
                     font=t.font(12), text_color=t.MUTED, anchor="w").grid(row=0, column=0, sticky="w", pady=(4, 8))
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(bar, text="Create Backup", **t.primary_button_style(),
                      command=self._create_backup).pack(side="left")
        ctk.CTkButton(bar, text="Refresh List", width=100, **t.secondary_button_style(),
                      command=self._refresh_backups).pack(side="left", padx=(8, 0))
        self.backups_box = ctk.CTkTextbox(parent, fg_color=t.PANEL_2, font=t.mono(11),
                                          text_color=t.TEXT, state="disabled")
        self.backups_box.grid(row=2, column=0, sticky="nsew")

    def _backups_dir(self) -> Path:
        srv = self._current_server()
        if not srv:
            return Path(".")
        return self._server_dir(srv) / "_backups"

    def _create_backup(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        root = self._server_dir(srv)
        if not root.exists():
            messagebox.showwarning("Backup", "Server folder does not exist.")
            return
        dest_dir = self._backups_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = dest_dir / f"{srv['name'].replace(' ', '_')}_{stamp}.zip"

        def work():
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in root.rglob("*"):
                        if "_backups" in p.parts or not p.is_file():
                            continue
                        zf.write(p, p.relative_to(root))
                msg = f"Backup saved: {zip_path.name}"
            except OSError as e:
                msg = f"Backup failed: {e}"
            self.after(0, lambda: self._backup_done(msg))

        threading.Thread(target=work, daemon=True).start()

    def _backup_done(self, msg: str) -> None:
        self._append_console_line(f"[Manager] {msg}")
        self._refresh_backups()

    def _refresh_backups(self) -> None:
        dest = self._backups_dir()
        lines = []
        if dest.exists():
            for p in sorted(dest.glob("*.zip"), reverse=True):
                try:
                    lines.append(f"{p.name}  ({_human_size(p.stat().st_size)})")
                except OSError:
                    lines.append(p.name)
        if not lines:
            lines = ["(no backups yet)"]
        self.backups_box.configure(state="normal")
        self.backups_box.delete("1.0", "end")
        self.backups_box.insert("1.0", "\n".join(lines))
        self.backups_box.configure(state="disabled")

    # ------------------------------------------------------------------ config

    def _build_config_tab(self, parent) -> None:
        parent.grid_columnconfigure(0, weight=1)
        self.config_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.config_scroll.grid(row=0, column=0, sticky="nsew")
        parent.grid_rowconfigure(0, weight=1)
        self.config_scroll.grid_columnconfigure(0, weight=1)

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

        # minecraft install panel (shown for MC types)
        self.mc_install_panel = ctk.CTkFrame(self.config_scroll, **t.panel_style())
        self.mc_install_panel.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.mc_install_panel.grid_columnconfigure(0, weight=1)
        self._build_mc_install_panel(self.mc_install_panel)

        self.config_fields_panel = ctk.CTkFrame(self.config_scroll, fg_color="transparent")
        self.config_fields_panel.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.config_fields_panel.grid_columnconfigure(0, weight=1)

        self.steam_install_panel = ctk.CTkFrame(self.config_scroll, **card_style(t.PANEL))
        self.steam_install_panel.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.steam_install_panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.steam_install_panel, text="SteamCMD Install", font=t.font(13, "bold"),
                     text_color=t.TEXT).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))
        self.steamcmd_status_label = ctk.CTkLabel(
            self.steam_install_panel, text="", font=t.font(11), text_color=t.MUTED, anchor="w",
        )
        self.steamcmd_status_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 6))
        self.steam_install_btn = ctk.CTkButton(
            self.steam_install_panel, text="Install / Update via SteamCMD",
            **t.primary_button_style(), command=self._start_steam_install,
        )
        self.steam_install_btn.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 10))
        self.steam_download_progress = ctk.CTkProgressBar(self.steam_install_panel, progress_color=t.ACCENT)
        self.steam_download_progress.set(0)
        self.steam_download_progress.grid(row=2, column=1, sticky="ew", padx=(12, 12), pady=(0, 10))

        self.config_status = ctk.CTkLabel(self.config_scroll, text="", font=t.font(12),
                                          text_color=t.MUTED, anchor="w", wraplength=600, justify="left")
        self.config_status.grid(row=4, column=0, sticky="ew", pady=(0, 8))

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

        mem_row = ctk.CTkFrame(parent, fg_color="transparent")
        mem_row.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        self.min_mb = ctk.IntVar(value=1024)
        self.max_mb = ctk.IntVar(value=2048)
        self.java_path = ctk.StringVar(value="java")
        ctk.CTkLabel(mem_row, text="Min MB", text_color=t.MUTED, font=t.font(11)).pack(side="left")
        ctk.CTkEntry(mem_row, textvariable=self.min_mb, width=70, fg_color=t.PANEL_2,
                     border_color=t.BORDER, text_color=t.TEXT).pack(side="left", padx=(4, 12))
        ctk.CTkLabel(mem_row, text="Max MB", text_color=t.MUTED, font=t.font(11)).pack(side="left")
        ctk.CTkEntry(mem_row, textvariable=self.max_mb, width=70, fg_color=t.PANEL_2,
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

    def _refresh_config_tab(self) -> None:
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return

        self.config_folder_label.configure(text=str(self._server_dir(srv)))

        gt = srv["game_type"]
        is_java = gt == "minecraft_java"
        is_bedrock = gt == "minecraft_bedrock"
        if is_java or is_bedrock:
            self.mc_install_panel.grid()
            self.mc_java_row.grid() if is_java else self.mc_java_row.grid_remove()
            self.mc_version_row.grid() if is_java else self.mc_version_row.grid_remove()
            self.mc_bedrock_row.grid() if is_bedrock else self.mc_bedrock_row.grid_remove()
            cfg = srv.setdefault("config", {})
            self.min_mb.set(int(cfg.get("min_mb", 1024)))
            self.max_mb.set(int(cfg.get("max_mb", 2048)))
            self.java_path.set(cfg.get("java_path", "java"))
            channel = cfg.get("bedrock_channel", "stable")
            self.bedrock_channel_menu.set("Preview" if channel == "preview" else "Stable")
            if is_java:
                self._check_java_async()
        else:
            self.mc_install_panel.grid_remove()

        if adapter.supports_steam_install():
            self.steam_install_panel.grid()
            steam_path, steam_err = find_steamcmd()
            if steam_path:
                self.steamcmd_status_label.configure(
                    text=f"SteamCMD: {steam_path}",
                    text_color=t.SUCCESS,
                )
            else:
                self.steamcmd_status_label.configure(text=steam_err, text_color=t.DANGER)
        else:
            self.steam_install_panel.grid_remove()

        for child in self.config_fields_panel.winfo_children():
            child.destroy()
        self._config_vars.clear()

        stored = srv.get("config", {})
        props = adapter.read_config(self._server_dir(srv)) if adapter.game_type.startswith("minecraft") else {}
        sections = adapter.config_sections(self._server_dir(srv))
        row_idx = 0

        for section in sections:
            sec_frame = ctk.CTkFrame(self.config_fields_panel, **card_style(t.PANEL))
            sec_frame.grid(row=row_idx, column=0, sticky="ew", pady=(0, 10))
            sec_frame.grid_columnconfigure(1, weight=1)
            row_idx += 1

            ctk.CTkLabel(sec_frame, text=section.title, font=t.font(13, "bold"),
                         text_color=t.TEXT).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 2))
            if section.hint:
                ctk.CTkLabel(sec_frame, text=section.hint, **hint_style()).grid(
                    row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6))

            field_start = 2 if section.hint else 1
            for fi, field in enumerate(section.fields):
                r = field_start + fi
                ctk.CTkLabel(sec_frame, text=field.label, text_color=t.MUTED, font=t.font(11)
                             ).grid(row=r, column=0, sticky="w", padx=(12, 4), pady=4)
                if adapter.game_type.startswith("minecraft"):
                    initial = props.get(field.key, field.default)
                else:
                    initial = stored.get(field.key, field.default)

                if field.kind == "menu":
                    var = ctk.StringVar(value=initial)
                    ctk.CTkOptionMenu(sec_frame, values=field.choices, variable=var, width=field.width,
                                      fg_color=t.PANEL_2, button_color=t.ACCENT,
                                      button_hover_color=t.ACCENT_HOVER).grid(
                        row=r, column=1, sticky="w", padx=(0, 12), pady=4)
                elif field.kind == "checkbox":
                    var = ctk.BooleanVar(value=str(initial).lower() == "true")
                    ctk.CTkCheckBox(sec_frame, text="", variable=var,
                                    fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER).grid(
                        row=r, column=1, sticky="w", padx=(0, 12), pady=4)
                elif field.kind == "password":
                    var = ctk.StringVar(value=str(initial))
                    entry = ctk.CTkEntry(sec_frame, textvariable=var, width=field.width, show="•",
                                         fg_color=t.PANEL_2, border_color=t.BORDER, text_color=t.TEXT)
                    entry.grid(row=r, column=1, sticky="w", padx=(0, 12), pady=4)
                else:
                    var = ctk.StringVar(value=str(initial))
                    ctk.CTkEntry(sec_frame, textvariable=var, width=field.width,
                                 fg_color=t.PANEL_2, border_color=t.BORDER, text_color=t.TEXT).grid(
                        row=r, column=1, sticky="w", padx=(0, 12), pady=4)
                self._config_vars[field.key] = var
                if field.hint:
                    ctk.CTkLabel(sec_frame, text=field.hint, font=t.font(10), text_color=t.MUTED).grid(
                        row=r, column=1, sticky="w", padx=(0, 12), pady=(0, 2))

        save_row = ctk.CTkFrame(self.config_fields_panel, fg_color="transparent")
        save_row.grid(row=row_idx, column=0, sticky="ew", pady=(4, 0))
        ctk.CTkButton(save_row, text="Save Config", **t.primary_button_style(),
                      command=self._save_config).pack(side="left")

        ok, msg = adapter.readiness_message(self._server_dir(srv))
        self.config_status.configure(
            text=f"{'✅' if ok else '⚠️'} {msg}",
            text_color=t.SUCCESS if ok else t.ACCENT,
        )

    def _browse_server_folder(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        chosen = filedialog.askdirectory(title="Server folder")
        if chosen:
            srv["server_dir"] = chosen
            self._persist()
            self._refresh_config_tab()
            self._refresh_overview()

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
        else:
            cfg = srv.setdefault("config", {})
            cfg.update(updates)
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
        self.config_status.configure(text="Loading version list from Mojang…")

        def work():
            versions, error = mc.list_versions()
            self.after(0, lambda: self._finish_load_mc_versions(versions, error))
        threading.Thread(target=work, daemon=True).start()

    def _finish_load_mc_versions(self, versions: list[mc.MCVersion], error: str) -> None:
        if error:
            self.config_status.configure(text=error)
            return
        self._mc_versions = versions
        self.config_status.configure(text=f"Loaded {len(versions)} versions.")
        self._populate_mc_version_menu()

    def _populate_mc_version_menu(self) -> None:
        show = self._show_snapshots.get()
        filtered = [v for v in self._mc_versions if show or v.type == "release"]
        ids = [v.id for v in filtered] or ["(load versions first)"]
        self.version_menu.configure(values=ids)
        self.version_menu.set(ids[0])
        self._on_mc_version_selected(ids[0])

    def _on_mc_version_selected(self, version_id: str) -> None:
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
        self.download_btn.configure(state="disabled")
        self.download_progress.set(0)

        if srv["game_type"] == "minecraft_bedrock":
            preview = srv.get("config", {}).get("bedrock_channel", "stable") == "preview"
            worker = create_minecraft_bedrock_install_worker(dest, preview=preview)
            self._download_meta = {"game": "bedrock"}
        else:
            if self._mc_selected_version is None:
                self.config_status.configure(text="Load and pick a version first.")
                self.download_btn.configure(state="normal")
                return
            worker = create_minecraft_java_install_worker(dest, self._mc_selected_version)
            self._download_meta = {"game": "java", "version": self._mc_selected_version.id}

        worker.start()
        self._download_worker = worker
        self._poll_download()

    def _start_steam_install(self) -> None:
        if self._download_worker is not None and self._download_worker.is_alive():
            return
        srv = self._current_server()
        adapter = self._current_adapter()
        if not srv or not adapter:
            return
        app_id = adapter.steam_app_id(srv.get("config", {}))
        if not app_id.isdigit():
            self.config_status.configure(text="Enter a valid Steam App ID in the config sections first.")
            return
        self.steam_install_btn.configure(state="disabled")
        self.steam_download_progress.set(0)
        self.config_status.configure(text=f"Starting SteamCMD install for App ID {app_id}…")
        worker = create_steamcmd_install_worker(self._server_dir(srv), app_id)
        worker.start()
        self._download_worker = worker
        self._download_meta = {"game": "steamcmd", "app_id": app_id}
        self._poll_download(use_steam_bar=True)

    def _poll_download(self, use_steam_bar: bool = False) -> None:
        worker = self._download_worker
        if worker is None:
            return
        try:
            while True:
                event: DownloadEvent = worker.events.get_nowait()
                self._handle_download_event(event, worker, use_steam_bar=use_steam_bar)
        except Exception:
            pass
        if worker.is_alive():
            self.after(POLL_MS, lambda: self._poll_download(use_steam_bar=use_steam_bar))

    def _handle_download_event(self, event: DownloadEvent, worker, use_steam_bar: bool = False) -> None:
        progress = self.steam_download_progress if use_steam_bar else self.download_progress
        done_btn = self.steam_install_btn if use_steam_bar else self.download_btn
        if event.kind == "progress":
            if event.total:
                progress.set(max(0.01, event.downloaded / max(event.total, 1)))
                if event.message:
                    self.config_status.configure(text=event.message)
                else:
                    self.config_status.configure(
                        text=f"Downloading… {_human_size(event.downloaded)} / {_human_size(event.total)}")
            elif event.message:
                self.config_status.configure(text=event.message)
            else:
                self.config_status.configure(text=f"Downloading… {_human_size(event.downloaded)}")
        elif event.kind == "done":
            srv = self._current_server()
            dest = self._server_dir(srv) if srv else Path(".")
            game = self._download_meta.get("game")
            version = ""
            if game == "bedrock":
                mc.write_bedrock_eula_ack(dest)
                version = getattr(worker, "version", "")
            elif game == "java":
                mc.write_eula(dest)
                version = self._download_meta.get("version", "")
            if srv and version:
                srv.setdefault("config", {})["installed_version"] = version
                self._persist()
            progress.set(1)
            done_btn.configure(state="normal")
            suffix = " EULA recorded." if game in ("java", "bedrock") else ""
            self.config_status.configure(text=f"{event.message}{suffix}")
            self._download_worker = None
            self._refresh_config_tab()
            self._refresh_overview()
        elif event.kind == "error":
            done_btn.configure(state="normal")
            self.config_status.configure(text=event.message)
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
        if not srv:
            return
        root = self._server_dir(srv)
        candidates = [
            root / "logs" / "latest.log",
            root / "log.txt",
            root / "server.log",
        ]
        content = ""
        for path in candidates:
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    content = text[-50000:]
                    content = f"--- {path.name} ---\n{content}"
                    break
                except OSError:
                    continue
        if not content:
            content = "(no log file found — common names: logs/latest.log, log.txt, server.log)"
        self.logs_box.configure(state="normal")
        self.logs_box.delete("1.0", "end")
        self.logs_box.insert("1.0", content)
        self.logs_box.configure(state="disabled")

    # ------------------------------------------------------------------ dashboard refresh

    def _refresh_dashboard(self) -> None:
        srv = self._current_server()
        if not srv:
            return
        adapter = get_adapter(srv["game_type"])
        icon = adapter.icon if adapter else "🎮"
        self.dash_header.configure(text=f"{icon}  {srv['name']}")
        self._refresh_overview()
        self._refresh_config_tab()
        self._rebuild_quick_commands()
        self._rebuild_players(self._process(srv["id"]))
        self._refresh_files()
        self._refresh_mods()
        self._refresh_backups()
        self._refresh_logs()
        self._sync_controls()

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
        self.address_copy_btn.configure(state="normal")
        port = self._port()
        full = f"{self._tailscale_ip}:{port}"
        proto = f" · {adapter.port_protocol()}" if adapter and adapter.port_protocol() != "TCP" else ""
        if self._ip_visible.get():
            self.address_label.configure(text=full, text_color=t.SUCCESS)
            self.address_eye_btn.configure(text="🙈")
            host = f"MagicDNS: {self._tailscale_hostname}" if self._tailscale_hostname else ""
            self.address_hostname_label.configure(text=host + proto)
        else:
            self.address_label.configure(text=f"{IP_MASK}:{port}", text_color=t.TEXT)
            self.address_eye_btn.configure(text="👁")
            self.address_hostname_label.configure(text=proto.strip(" ·"))

    def _toggle_ip_visibility(self) -> None:
        self._ip_visible.set(not self._ip_visible.get())
        self._update_address_display()

    def _copy_address(self) -> None:
        if self._tailscale_ip:
            self.clipboard_clear()
            self.clipboard_append(f"{self._tailscale_ip}:{self._port()}")

    # ------------------------------------------------------------------ start/stop

    def _set_state_pill(self, text: str, color: str) -> None:
        self.state_pill.configure(text=f"● {text}", text_color=color)

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
        config = self._build_start_config(srv, adapter)
        error = proc.start(self._server_dir(srv), config, adapter)
        if error:
            self._append_console_line(f"[Manager] {error}")
            return
        self._sync_controls()
        self._set_state_pill("Starting", t.ACCENT)
        self._append_console_line(f"[Manager] Starting {adapter.display_name}…")

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
        self._send_raw_command(text)
        self.command_entry.delete(0, "end")

    def _send_raw_command(self, text: str) -> None:
        srv = self._current_server()
        if not srv:
            return
        if self._process(srv["id"]).send(text):
            self._append_console_line(f"> {text}")
        else:
            self._append_console_line("[Manager] Server isn't running.")

    # ------------------------------------------------------------------ console helpers

    def _log_tag_rules(self) -> list[tuple[re.Pattern[str], str]]:
        adapter = self._current_adapter()
        if adapter:
            return [(r.pattern, r.tag) for r in adapter.log_tag_rules()]
        return []

    def _line_tag(self, line: str) -> str | None:
        if line.startswith("[Manager]"):
            return "manager"
        if line.startswith(">"):
            return "command"
        for pattern, tag in self._log_tag_rules():
            if pattern.search(line):
                return tag
        return None

    def _append_console_line(self, line: str, server_id: str | None = None) -> None:
        sid = server_id or self._selected_id
        tag = self._line_tag(line) if sid == self._selected_id or server_id else self._line_tag_for_server(line, sid)
        if sid:
            buf = self._console_buffer(sid)
            buf.append(line, tag)
        if sid != self._selected_id:
            return
        self.console_box.configure(state="normal")
        if tag:
            self.console_box.insert("end", line + "\n", tag)
        else:
            self.console_box.insert("end", line + "\n")
        self._console_lines += 1
        if self._console_lines > MAX_CONSOLE_LINES:
            self.console_box.delete("1.0", "2.0")
            self._console_lines -= 1
        if self._autoscroll.get():
            self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def _line_tag_for_server(self, line: str, server_id: str) -> str | None:
        srv = next((s for s in self.servers if s["id"] == server_id), None)
        if not srv:
            return None
        adapter = get_adapter(srv["game_type"])
        if line.startswith("[Manager]"):
            return "manager"
        if line.startswith(">"):
            return "command"
        if adapter:
            for rule in adapter.log_tag_rules():
                if rule.pattern.search(line):
                    return rule.tag
        return None

    def _clear_console(self) -> None:
        if self._selected_id:
            self._console_buffer(self._selected_id).clear()
        self.console_box.configure(state="normal")
        self.console_box.delete("1.0", "end")
        self._console_lines = 0
        self.console_box.configure(state="disabled")

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

        if self._selected_id:
            proc = self._process(self._selected_id)
            if proc.running and proc.started_at:
                elapsed = int(time.time() - proc.started_at)
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                self.uptime_label.configure(
                    text=f"Uptime {h:02d}:{m:02d}:{s:02d} · {len(proc.players)} online")
            else:
                self.uptime_label.configure(text="")

        self._refresh_server_list()
        self.after(POLL_MS, self._poll_all)

    def _handle_server_event(self, server_id: str, event: ServerEvent) -> None:
        proc = self._process(server_id)

        if event.kind == "log":
            self._append_console_line(event.message, server_id=server_id)
        elif event.kind == "player_join":
            proc.players.add(event.player)
        elif event.kind == "player_leave":
            proc.players.discard(event.player)

        if server_id != self._selected_id:
            return

        if event.kind == "ready":
            self._set_state_pill("Running", t.SUCCESS)
        elif event.kind == "player_join":
            adapter = self._current_adapter()
            actions = adapter.player_actions() if adapter else [("Kick", "kick")]
            self._add_player_row(event.player, actions)
        elif event.kind == "player_leave":
            self._remove_player_row(event.player)
        elif event.kind == "stopped":
            self._append_console_line(f"[Manager] Server exited (code {event.exit_code}).", server_id=server_id)
            for name in list(self._player_rows):
                self._remove_player_row(name)
            if self._restart_flags.pop(server_id, False):
                self._set_state_pill("Restarting", t.ACCENT)
                self.after(500, self._start_server)
            else:
                self._set_state_pill("Stopped", t.MUTED)
            self._sync_controls()


# Backward-compatible alias for plugin registration
MinecraftServerManagerModule = GameServerManagerModule
