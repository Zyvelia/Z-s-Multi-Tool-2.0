"""Palworld dedicated server adapter."""

from __future__ import annotations

import platform
import re
from pathlib import Path

from ..core.events import ServerEvent
from ..core.palworld_rcon import PalworldRconClient, PalworldRconError
from .base import ConfigField, LogTagRule
from .games import SteamDedicatedAdapter

# UI / stored config key -> PalWorldSettings.ini OptionSettings key
_SETTING_MAP: dict[str, str] = {
    "server_name": "ServerName",
    "server_description": "ServerDescription",
    "server_password": "ServerPassword",
    "admin_password": "AdminPassword",
    "port": "PublicPort",
    "max_players": "ServerPlayerMaxNum",
    "rcon_enabled": "RCONEnabled",
    "rcon_port": "RCONPort",
    "show_join_messages": "bIsShowJoinLeftMessage",
    "difficulty": "Difficulty",
}

_BOOL_KEYS = {"RCONEnabled", "bIsShowJoinLeftMessage", "RESTAPIEnabled", "bIsPvP", "bUseAuth"}
_STRING_KEYS = {
    "ServerName", "ServerDescription", "ServerPassword", "AdminPassword",
    "PublicIP", "Region", "BanListURL",
}
_DIFFICULTIES = ["Default", "Easy", "Normal", "Hard"]

_READY_RE = re.compile(
    r"(Dedicated Server|Server has started|LogWorld: Bringing World|Running Palworld dedicated server)",
    re.I,
)
_JOIN_RE = re.compile(r"(?:joined|logged in|Join succeeded)[:\s]+([^\]'\"]+)", re.I)
_LEAVE_RE = re.compile(r"(?:left|logged out|Disconnect)[:\s]+([^\]'\"]+)", re.I)


def _config_subdir() -> str:
    return "WindowsServer" if platform.system() == "Windows" else "LinuxServer"


def palworld_rcon_ready(config: dict) -> bool:
    if str(config.get("rcon_enabled", "")).lower() not in ("true", "1", "yes"):
        return False
    return bool(str(config.get("admin_password", "")).strip())


def palworld_rcon_client(config: dict) -> PalworldRconClient | None:
    if not palworld_rcon_ready(config):
        return None
    try:
        port = int(str(config.get("rcon_port", "25575") or "25575"))
    except ValueError:
        port = 25575
    password = str(config.get("admin_password", "")).strip()
    return PalworldRconClient("127.0.0.1", port, password)


def _normalize_palworld_command(command: str) -> str:
    stripped = command.strip()
    if stripped.startswith("/"):
        return stripped[1:]
    return stripped


def settings_dir(server_dir: Path) -> Path:
    return server_dir / "Pal" / "Saved" / "Config" / _config_subdir()


def settings_path(server_dir: Path) -> Path:
    return settings_dir(server_dir) / "PalWorldSettings.ini"


def default_template_path(server_dir: Path) -> Path:
    return server_dir / "DefaultPalWorldSettings.ini"


def resolve_server_executable(server_dir: Path) -> Path:
    """Return the DS binary that supports piped stdout (not the PalServer.exe launcher)."""
    if platform.system() == "Windows":
        win64 = server_dir / "Pal" / "Binaries" / "Win64"
        for name in (
            "PalServer-Win64-Shipping-Cmd.exe",
            "PalServer-Win64-Test-Cmd.exe",
        ):
            path = win64 / name
            if path.is_file():
                return path
        matches = sorted(win64.glob("PalServer-*-Cmd.exe"))
        if matches:
            return matches[0]
        return server_dir / "PalServer.exe"
    linux_bin = server_dir / "Pal" / "Binaries" / "Linux"
    for name in ("PalServer-Linux-Shipping", "PalServer-Linux-Shipping-Cmd"):
        path = linux_bin / name
        if path.is_file():
            return path
    matches = sorted(linux_bin.glob("PalServer-Linux-Shipping*"))
    if matches:
        return matches[0]
    return server_dir / "PalServer.sh"


def _extract_option_line(text: str) -> str | None:
    for raw in text.splitlines():
        line = raw.strip().lstrip(";").strip()
        if line.startswith("OptionSettings="):
            return line
    return None


def _parse_option_values(option_line: str) -> dict[str, str]:
    inner = option_line
    if inner.startswith("OptionSettings="):
        inner = inner[len("OptionSettings="):]
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]

    values: dict[str, str] = {}
    for part in _split_option_parts(inner):
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        values[key] = val
    return values


def _split_option_parts(inner: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '"' and (i == 0 or inner[i - 1] != "\\"):
            in_string = not in_string
            current.append(ch)
        elif not in_string:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts


def _format_ini_value(ini_key: str, value: str) -> str:
    if ini_key in _BOOL_KEYS:
        return "True" if str(value).lower() in ("true", "1", "yes") else "False"
    if ini_key == "Difficulty":
        v = str(value).strip()
        if not v or v.lower() == "default":
            return "None"
        return v
    if ini_key in _STRING_KEYS or ini_key.endswith("Password") or ini_key.endswith("Name"):
        escaped = str(value).replace('"', '\\"')
        return f'"{escaped}"'
    return str(value).strip()


def _set_option_value(option_line: str, ini_key: str, value: str) -> str:
    formatted = _format_ini_value(ini_key, value)
    pattern = rf"({re.escape(ini_key)}=)(\"(?:\\.|[^\"])*\"|[^,\)]+)"
    if re.search(pattern, option_line):
        return re.sub(pattern, rf"\g<1>{formatted}", option_line, count=1)

    if option_line.rstrip().endswith(")"):
        return option_line.rstrip()[:-1] + f",{ini_key}={formatted})"
    return option_line + f",{ini_key}={formatted}"


def ensure_settings_file(server_dir: Path) -> Path:
    """Create PalWorldSettings.ini from the default template if missing."""
    path = settings_path(server_dir)
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    template = default_template_path(server_dir)
    if template.exists():
        option_line = _extract_option_line(template.read_text(encoding="utf-8", errors="replace"))
        if option_line:
            path.write_text(
                "[/Script/Pal.PalGameWorldSettings]\n" + option_line + "\n",
                encoding="utf-8",
            )
            return path

    path.write_text(
        "[/Script/Pal.PalGameWorldSettings]\n"
        "OptionSettings=(Difficulty=None,ServerName=\"Palworld Server\",ServerDescription=\"\","
        "ServerPassword=\"\",AdminPassword=\"\",PublicPort=8211,ServerPlayerMaxNum=32,"
        "RCONEnabled=False,RCONPort=25575,bIsShowJoinLeftMessage=True)\n",
        encoding="utf-8",
    )
    return path


def read_palworld_settings(server_dir: Path) -> dict[str, str]:
    path = settings_path(server_dir)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    option_line = _extract_option_line(text)
    if not option_line:
        return {}
    raw = _parse_option_values(option_line)
    out: dict[str, str] = {}
    for ui_key, ini_key in _SETTING_MAP.items():
        if ini_key not in raw:
            continue
        val = raw[ini_key]
        if ini_key == "Difficulty" and val == "None":
            val = "Default"
        if ini_key in _BOOL_KEYS:
            val = "true" if val.lower() == "true" else "false"
        out[ui_key] = val
    return out


def write_palworld_settings(server_dir: Path, updates: dict[str, str]) -> None:
    path = ensure_settings_file(server_dir)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header = "[/Script/Pal.PalGameWorldSettings]"
    option_line = _extract_option_line("\n".join(lines))
    if not option_line:
        option_line = (
            "OptionSettings=(ServerName=\"Palworld Server\",PublicPort=8211,ServerPlayerMaxNum=32)"
        )

    for ui_key, val in updates.items():
        ini_key = _SETTING_MAP.get(ui_key)
        if ini_key:
            option_line = _set_option_value(option_line, ini_key, val)

    path.write_text(header + "\n" + option_line + "\n", encoding="utf-8")


class PalworldAdapter(SteamDedicatedAdapter):
    game_type = "palworld"
    display_name = "Palworld"
    icon = "🐾"
    description = "Palworld dedicated server (Steam App ID 2394010)."
    steam_app_id = "2394010"
    executable_win = "PalServer.exe"
    executable_linux = "PalServer.sh"

    def default_port(self) -> int:
        return 8211

    def port_protocol(self) -> str:
        return "UDP"

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Palworld Server", width=180),
            ConfigField("server_description", "Description", "text", "", width=220),
            ConfigField("server_password", "Join password", "text", "", width=140),
            ConfigField("admin_password", "Admin password", "text", "", width=140),
            ConfigField("port", "Port", "text", "8211", width=100),
            ConfigField("max_players", "Max players", "text", "32", width=100),
            ConfigField("difficulty", "Difficulty", "menu", "Default", _DIFFICULTIES),
            ConfigField("show_join_messages", "Show join/leave in chat", "checkbox", "true"),
            ConfigField("rcon_enabled", "Enable RCON", "checkbox", "false"),
            ConfigField("rcon_port", "RCON port", "text", "25575", width=100),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
            ConfigField("steam_app_id", "Steam App ID", "text", self.steam_app_id, width=120),
        ]

    def read_config(self, server_dir: Path) -> dict[str, str]:
        return read_palworld_settings(server_dir)

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_palworld_settings(server_dir, updates)

    def apply_config(self, server_dir: Path, config: dict) -> None:
        """Sync stored server config into PalWorldSettings.ini before launch."""
        updates = {k: str(v) for k, v in config.items() if k in _SETTING_MAP}
        if updates:
            write_palworld_settings(server_dir, updates)

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        exe = resolve_server_executable(server_dir)
        args = [str(exe)]
        if platform.system() == "Windows":
            args.extend(["-useperfthreads", "-NoAsyncLoadingThread", "-log", "-stdout"])
        else:
            args.extend(["-log", "-stdout"])
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args.extend(extra.split())
        return args, {}

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        ok, msg = super().pre_start_checks(server_dir, config)
        if not ok:
            return ok, msg
        exe = resolve_server_executable(server_dir)
        if not exe.is_file():
            return False, (
                f"Server binary not found ({exe.name}). "
                "Reinstall via SteamCMD, then start again."
            )
        if exe.name.lower() in ("palserver.exe", "palserver.sh"):
            return False, (
                "Only the PalServer launcher was found. "
                "Run Install via SteamCMD so Pal/Binaries contains the server executable."
            )
        if not settings_path(server_dir).exists():
            ensure_settings_file(server_dir)
            return True, "Created PalWorldSettings.ini — save settings, then start the server."
        return True, "Ready to start."

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if _READY_RE.search(line):
            return ServerEvent(kind="ready", message=line)
        m = _JOIN_RE.search(line)
        if m:
            name = m.group(1).strip().strip("'\"")
            if name and len(name) < 64:
                return ServerEvent(kind="player_join", player=name)
        m = _LEAVE_RE.search(line)
        if m:
            name = m.group(1).strip().strip("'\"")
            if name and len(name) < 64:
                return ServerEvent(kind="player_leave", player=name)
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        rules = super().log_tag_rules()
        rules.extend([
            LogTagRule(re.compile(r"joined|logged in", re.I), "log_join"),
            LogTagRule(re.compile(r"left|logged out|Disconnect", re.I), "log_leave"),
            LogTagRule(re.compile(r"Auto-saved|Save", re.I), "log_save"),
        ])
        return rules

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("Save", "Save"),
            ("Info", "Info"),
            ("ShowPlayers", "ShowPlayers"),
            ('Broadcast "Hello!"', 'Broadcast Hello!'),
            ("Shutdown 60", "Shutdown 60 Server restarting soon"),
            ("DoExit", "DoExit"),
        ]

    def execute_remote_command(
        self, command: str, config: dict, server_dir: Path
    ) -> tuple[bool, str] | None:
        client = palworld_rcon_client(config)
        if client is None:
            return (
                False,
                "Enable RCON and set an Admin password in Config to use console commands.",
            )
        cmd = _normalize_palworld_command(command)
        try:
            result = client.execute(cmd)
            text = result.strip()
            return True, text if text else f"> {cmd} (ok)"
        except (PalworldRconError, OSError) as e:
            return False, f"RCON failed: {e}"

    def prefers_remote_console(self, config: dict) -> bool:
        return True

    def graceful_stop_remote(self, config: dict, server_dir: Path) -> tuple[bool, str] | None:
        client = palworld_rcon_client(config)
        if client is None:
            return None
        try:
            client.execute("Save")
            client.execute('Shutdown 30 "Server stopping"')
            return True, "Save sent — shutdown in 30s via RCON."
        except (PalworldRconError, OSError) as e:
            return False, f"RCON shutdown failed: {e}"

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        ini = settings_path(server_dir)
        rows.append(("Settings file", str(ini) if ini.exists() else "(created on first save/start)"))
        if config.get("admin_password"):
            rows.append(("Admin", "Password set"))
        if str(config.get("rcon_enabled", "")).lower() == "true":
            rows.append(("RCON", f"Port {config.get('rcon_port', '25575')}"))
        return rows

    def setup_panel_hints(self) -> list[str]:
        sub = _config_subdir()
        return super().setup_panel_hints() + [
            f"Settings live in Pal/Saved/Config/{sub}/PalWorldSettings.ini.",
            "Enable RCON + Admin password in Config — console commands and Stop use RCON, not stdin.",
            "Stop the server before saving settings — Palworld rewrites the ini on shutdown.",
            "Forward UDP 8211 (and TCP RCON port if enabled, default 25575).",
            "Pak mods: Pal/Content/Paks/~mods — workshop packages: Mods/Workshop.",
            "Run Save before DoExit; Shutdown gives players a countdown.",
        ]

    def log_file_candidates(self, server_dir: Path) -> list[Path]:
        return [
            server_dir / "Pal" / "Saved" / "Logs" / "PalWorld.log",
            server_dir / "Pal" / "Saved" / "Logs" / "PalServer.log",
            *super().log_file_candidates(server_dir),
        ]

    def supports_mods(self) -> bool:
        return True

    def mods_directory(self, server_dir: Path) -> Path | None:
        return server_dir / "Mods"

    def mods_directories(self, server_dir: Path) -> list[Path]:
        root = server_dir
        return [
            root / "Mods",
            root / "Pal" / "Content" / "Paks" / "~mods",
            root / "Pal" / "Content" / "Paks" / "LogicMods",
            root / "Pal" / "Content" / "Paks" / "~WorkshopMods",
        ]

    def mod_file_extensions(self) -> tuple[str, ...] | None:
        return (".pak", ".ucas", ".utoc")

    def mods_empty_message(self) -> str:
        return (
            "No mod files found.\n"
            "Drop .pak files into Pal/Content/Paks/~mods (or LogicMods), "
            "or add workshop packages under Mods/Workshop."
        )

    def mods_browser_urls(self) -> dict[str, str]:
        return {
            "curseforge": "https://www.curseforge.com/palworld/search?page=1&pageSize=20&sortBy=relevancy",
        }

    def graceful_stop_command(self) -> str:
        return "Shutdown 30 Server stopping"