"""SteamCMD dedicated server adapters — Rust, ARK, CS2, 7DTD, Factorio, etc."""

from __future__ import annotations

import json
import platform
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..core.game_telnet import GameTelnetClient, GameTelnetError
from ..core.source_rcon import SourceRconClient, SourceRconError
from .base import ConfigField
from .games import SteamDedicatedAdapter, _exe

FILE_CONFIG_GAME_TYPES = frozenset({
    "factorio",
    "seven_days_to_die",
    "vrising",
    "enshrouded",
    "dayz",
    "sons_of_the_forest",
    "the_forest",
    "core_keeper",
    "space_engineers",
    "scum",
    "conan_exiles",
    "necesse",
    "raft",
    "icarus",
    "barotrauma",
    "unturned",
    "empyrion",
    "avorion",
    "squad",
    "hell_let_loose",
    "post_scriptum",
    "abiotic_factor",
    "sunkenland",
    "aska",
    "dst",
    "insurgency_sandstorm",
    "mordhau",
    "starbound",
    "bannerlord",
    "smalland",
    "humanitz",
    "once_human",
    "holdfast",
    "rust",
    "ark_evolved",
    "ark_ascended",
    "gmod",
    "l4d2",
})


def _truthy(val: str) -> bool:
    return str(val).lower() in ("true", "1", "yes")


def _rcon_client(config: dict, *, port_key: str = "rcon_port", password_key: str = "rcon_password") -> SourceRconClient | None:
    if not _truthy(str(config.get("rcon_enabled", ""))):
        return None
    password = str(config.get(password_key, "")).strip()
    if not password:
        return None
    try:
        port = int(str(config.get(port_key, "27015") or "27015"))
    except ValueError:
        port = 27015
    return SourceRconClient("127.0.0.1", port, password)


def _telnet_client(config: dict) -> GameTelnetClient | None:
    if not _truthy(str(config.get("telnet_enabled", "true"))):
        return None
    password = str(config.get("telnet_password", "")).strip()
    if not password:
        return None
    try:
        port = int(str(config.get("telnet_port", "8081") or "8081"))
    except ValueError:
        port = 8081
    return GameTelnetClient("127.0.0.1", port, password)


def _read_json_mapped(path: Path, mapping: dict[str, str], *, nested: dict[str, str] | None = None) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for ui_key, json_key in mapping.items():
        if nested and ui_key in nested:
            parent = data.get(nested[ui_key], {})
            if isinstance(parent, dict) and json_key in parent:
                val = parent[json_key]
            else:
                continue
        elif json_key in data:
            val = data[json_key]
        else:
            continue
        if isinstance(val, bool):
            val = "true" if val else "false"
        out[ui_key] = str(val)
    return out


def _write_json_mapped(path: Path, updates: dict[str, str], mapping: dict[str, str], *, nested: dict[str, str] | None = None) -> None:
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    for ui_key, val in updates.items():
        json_key = mapping.get(ui_key)
        if not json_key:
            continue
        if nested and ui_key in nested:
            parent_key = nested[ui_key]
            block = data.setdefault(parent_key, {})
            if not isinstance(block, dict):
                block = {}
                data[parent_key] = block
            if ui_key.endswith("_enabled"):
                block[json_key] = _truthy(val)
            elif ui_key.endswith("_port") or ui_key in ("max_players", "port", "query_port", "slot_count", "max_users"):
                try:
                    block[json_key] = int(val)
                except ValueError:
                    block[json_key] = val
            else:
                block[json_key] = val
        elif ui_key.endswith("_enabled"):
            data[json_key] = _truthy(val)
        elif ui_key in ("max_players", "port", "query_port", "slot_count", "max_users"):
            try:
                data[json_key] = int(val)
            except ValueError:
                data[json_key] = val
        else:
            data[json_key] = val
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


_FACTORIO_MAP = {
    "server_name": "name",
    "server_description": "description",
    "max_players": "max_players",
    "server_password": "game_password",
}
_FACTORIO_NESTED = {
    "rcon_enabled": "rcon",
    "rcon_port": "rcon",
    "rcon_password": "rcon",
}
_FACTORIO_NESTED_KEYS = {
    "rcon_enabled": "enabled",
    "rcon_port": "port",
    "rcon_password": "password",
}

_7DTD_PROPS = {
    "server_name": "ServerName",
    "port": "ServerPort",
    "max_players": "ServerMaxPlayerCount",
    "telnet_enabled": "TelnetEnabled",
    "telnet_port": "TelnetPort",
    "telnet_password": "TelnetPassword",
}

_VRISING_MAP = {
    "server_name": "Name",
    "password": "Password",
    "port": "Port",
    "query_port": "QueryPort",
    "max_users": "MaxConnectedUsers",
    "rcon_enabled": "RconEnabled",
    "rcon_port": "RconPort",
    "rcon_password": "RconPassword",
}

_ENSHROUDED_MAP = {
    "server_name": "name",
    "password": "password",
    "port": "gamePort",
    "query_port": "queryPort",
    "slot_count": "slotCount",
}

_DAYZ_CFG_KEYS = {
    "server_name": "hostname",
    "server_password": "password",
    "admin_password": "passwordAdmin",
    "max_players": "maxPlayers",
}

_SOTF_MAP = {
    "server_name": "ServerName",
    "password": "Password",
    "port": "GamePort",
    "query_port": "QueryPort",
    "max_players": "MaxPlayers",
}


def factorio_settings_path(server_dir: Path) -> Path:
    return server_dir / "server-settings.json"


def read_factorio_settings(server_dir: Path) -> dict[str, str]:
    path = factorio_settings_path(server_dir)
    flat = _read_json_mapped(path, _FACTORIO_MAP)
    nested = _read_json_mapped(
        path,
        _FACTORIO_NESTED_KEYS,
        nested={k: "rcon" for k in _FACTORIO_NESTED_KEYS},
    )
    flat.update(nested)
    return flat


def write_factorio_settings(server_dir: Path, updates: dict[str, str]) -> None:
    path = factorio_settings_path(server_dir)
    flat_updates = {k: v for k, v in updates.items() if k in _FACTORIO_MAP}
    nested_updates = {k: v for k, v in updates.items() if k in _FACTORIO_NESTED_KEYS}
    if flat_updates:
        _write_json_mapped(path, flat_updates, _FACTORIO_MAP)
    if nested_updates:
        _write_json_mapped(
            path,
            nested_updates,
            _FACTORIO_NESTED_KEYS,
            nested={k: "rcon" for k in _FACTORIO_NESTED_KEYS},
        )


def serverconfig_path(server_dir: Path) -> Path:
    return server_dir / "serverconfig.xml"


def read_7dtd_config(server_dir: Path) -> dict[str, str]:
    path = serverconfig_path(server_dir)
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}
    inv = {v: k for k, v in _7DTD_PROPS.items()}
    out: dict[str, str] = {}
    for prop in root.findall("property"):
        name = prop.get("name", "")
        val = prop.get("value", "")
        ui_key = inv.get(name)
        if not ui_key:
            continue
        if ui_key == "telnet_enabled":
            val = "true" if val.lower() in ("true", "1", "yes") else "false"
        out[ui_key] = val
    return out


def write_7dtd_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = serverconfig_path(server_dir)
    if path.exists():
        root = ET.parse(path).getroot()
    else:
        root = ET.Element("ServerSettings")
    by_name = {p.get("name"): p for p in root.findall("property")}
    for ui_key, val in updates.items():
        prop_name = _7DTD_PROPS.get(ui_key)
        if not prop_name:
            continue
        if ui_key == "telnet_enabled":
            val = "true" if _truthy(val) else "false"
        if prop_name in by_name:
            by_name[prop_name].set("value", str(val))
        else:
            ET.SubElement(root, "property", name=prop_name, value=str(val))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def vrising_settings_path(server_dir: Path) -> Path:
    return server_dir / "save-data" / "Settings" / "ServerHostSettings.json"


def read_vrising_settings(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(vrising_settings_path(server_dir), _VRISING_MAP)


def write_vrising_settings(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(vrising_settings_path(server_dir), updates, _VRISING_MAP)


def enshrouded_config_path(server_dir: Path) -> Path:
    return server_dir / "enshrouded_server.json"


def read_enshrouded_config(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(enshrouded_config_path(server_dir), _ENSHROUDED_MAP)


def write_enshrouded_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(enshrouded_config_path(server_dir), updates, _ENSHROUDED_MAP)


def dayz_cfg_path(server_dir: Path) -> Path:
    return server_dir / "serverDZ.cfg"


def read_dayz_cfg(server_dir: Path) -> dict[str, str]:
    path = dayz_cfg_path(server_dir)
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    inv = {v: k for k, v in _DAYZ_CFG_KEYS.items()}
    out: dict[str, str] = {}
    for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"\s*;', text):
        ui_key = inv.get(m.group(1))
        if ui_key:
            out[ui_key] = m.group(2)
    for m in re.finditer(r"(\w+)\s*=\s*(\d+)\s*;", text):
        ui_key = inv.get(m.group(1))
        if ui_key:
            out[ui_key] = m.group(2)
    return out


def write_dayz_cfg(server_dir: Path, updates: dict[str, str]) -> None:
    path = dayz_cfg_path(server_dir)
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = (
            'hostname = "DayZ Server";\n'
            'password = "";\n'
            'passwordAdmin = "";\n'
            "maxPlayers = 60;\n"
            "verifySignatures = 2;\n"
            "forceSameBuild = 1;\n"
            'instanceId = 1;\n\n'
            "class Missions {\n"
            "    class DayZ {\n"
            '        template="dayzOffline.chernarusplus";\n'
            "    };\n"
            "};\n"
        )
    for ui_key, val in updates.items():
        cfg_key = _DAYZ_CFG_KEYS.get(ui_key)
        if not cfg_key:
            continue
        if cfg_key in ("maxPlayers",):
            pattern = rf"({re.escape(cfg_key)}\s*=\s*)\d+(\s*;)"
            repl = rf'\g<1>{val}\2'
        else:
            escaped = str(val).replace('"', '\\"')
            pattern = rf'({re.escape(cfg_key)}\s*=\s*)"[^"]*"(\s*;)'
            repl = rf'\g<1>"{escaped}"\2'
        if re.search(pattern, text):
            text = re.sub(pattern, repl, text, count=1)
        elif cfg_key in ("maxPlayers",):
            text = text.rstrip() + f"\n{cfg_key} = {val};\n"
        else:
            text = text.rstrip() + f'\n{cfg_key} = "{val}";\n'
    path.write_text(text, encoding="utf-8")


def sotf_config_path(server_dir: Path) -> Path:
    for name in ("dedicatedserver.cfg", "DedicatedServerConfig.json"):
        path = server_dir / name
        if path.exists():
            return path
    return server_dir / "dedicatedserver.cfg"


def read_sotf_config(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(sotf_config_path(server_dir), _SOTF_MAP)


def write_sotf_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(sotf_config_path(server_dir), updates, _SOTF_MAP)


def _ue_config_subdir() -> str:
    return "WindowsServer" if platform.system() == "Windows" else "LinuxServer"


_FOREST_LINE_MAP = {
    "server_name": "serverName",
    "port": "serverPort",
    "max_players": "serverPlayers",
    "password": "serverPassword",
}

_CORE_KEEPER_MAP = {
    "max_players": "maxNumberPlayersConnected",
    "port": "gamePort",
    "password": "password",
    "world_seed": "worldSeed",
}

_SE_XML_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
}

_CONAN_INI_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "server_password": "ServerPassword",
    "admin_password": "AdminPassword",
}

_SCUM_INI_MAP = {
    "server_name": "scum.ServerName",
    "max_players": "scum.MaxPlayers",
    "server_password": "scum.ServerPassword",
}

_NECESSE_MAP = {
    "max_players": "maxPlayers",
    "port": "port",
    "password": "password",
    "world_name": "world",
}

_RAFT_INI_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "port": "Port",
    "password": "Password",
}

_ICARUS_MAP = {
    "server_name": "SessionName",
    "max_players": "MaxPlayerCount",
    "password": "Password",
    "port": "Port",
}

_BAROTRAUMA_ATTR_MAP = {
    "server_name": "servername",
    "port": "port",
    "max_players": "maxplayers",
    "password": "password",
}

_UNTURNED_MAP = {
    "server_name": "Name",
    "password": "Password",
    "max_players": "MaxPlayers",
    "port": "Port",
}

_EMPYRION_YAML_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "port": "Port",
    "scenario": "Scenario",
}

_AVORION_GAME_MAP = {
    "server_name": "name",
    "max_players": "maxPlayers",
    "description": "description",
}

_OWI_CFG_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "port": "Port",
    "server_password": "ServerPassword",
}

_ABIOTIC_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "port": "Port",
    "password": "Password",
}

_SUNKENLAND_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "port": "GamePort",
    "password": "Password",
}

_ASKA_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "port": "Port",
    "password": "Password",
}

_DST_INI_FIELDS = {
    "max_players": ("GAMEPLAY", "max_players"),
    "cluster_password": ("NETWORK", "cluster_password"),
    "cluster_description": ("NETWORK", "cluster_description"),
}

_STARBOUND_MAP = {
    "server_name": "gameName",
    "max_players": "maxPlayers",
    "port": "gamePort",
    "password": "password",
}

_BANNERLORD_LINE_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxNumberOfPlayers",
    "password": "GamePassword",
    "admin_password": "AdminPassword",
    "map": "MapName",
}

_SOURCE_CVAR_MAP = {
    "server_name": "hostname",
    "max_players": "maxplayers",
    "password": "sv_password",
    "rcon_password": "rcon_password",
}

_RUST_CFG_MAP = {
    "server_name": "server.hostname",
    "max_players": "server.maxplayers",
    "world_size": "server.worldsize",
    "seed": "server.seed",
    "rcon_port": "rcon.port",
    "rcon_password": "rcon.password",
}

_ARK_SESSION_MAP = {
    "session_name": "SessionName",
    "port": "Port",
    "query_port": "QueryPort",
}

_ARK_SERVER_MAP = {
    "max_players": "MaxPlayers",
    "server_password": "ServerPassword",
    "admin_password": "ServerAdminPassword",
}


def _read_line_kv_config(path: Path, line_map: dict[str, str]) -> dict[str, str]:
    if not path.exists():
        return {}
    inv = {v: k for k, v in line_map.items()}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        ui_key = inv.get(parts[0])
        if ui_key:
            out[ui_key] = parts[1].strip().strip('"')
    return out


def _write_line_kv_config(path: Path, updates: dict[str, str], line_map: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    line_to_ui = {v: k for k, v in line_map.items()}
    pending = {k: v for k, v in updates.items() if k in line_map}
    new_lines: list[str] = []
    touched: set[str] = set()
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(raw)
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2 and parts[0] in line_to_ui:
            ui_key = line_to_ui[parts[0]]
            if ui_key in pending:
                new_lines.append(f"{parts[0]} {pending[ui_key]}")
                touched.add(ui_key)
                continue
        new_lines.append(raw)
    for ui_key, val in pending.items():
        if ui_key not in touched:
            new_lines.append(f"{line_map[ui_key]} {val}")
    if not lines and pending:
        new_lines = ["# DedicatedServer.cfg"] + new_lines
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _read_ini_values(path: Path, ini_to_ui: dict[str, str]) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        ui = ini_to_ui.get(key.strip())
        if ui:
            out[ui] = val.strip().strip('"')
    return out


def _write_ini_values(path: Path, updates: dict[str, str], ui_to_ini: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    pending = {k: v for k, v in updates.items() if k in ui_to_ini}
    new_lines: list[str] = []
    touched: set[str] = set()
    has_section = any(l.strip().startswith("[") for l in lines)
    for raw in lines:
        stripped = raw.strip()
        if "=" in stripped and not stripped.startswith("[") and not stripped.startswith(";"):
            key = stripped.split("=", 1)[0].strip()
            ui_key = next((u for u, i in ui_to_ini.items() if i == key), None)
            if ui_key and ui_key in pending:
                new_lines.append(f"{key}={pending[ui_key]}")
                touched.add(ui_key)
                continue
        new_lines.append(raw)
    for ui_key, val in pending.items():
        if ui_key not in touched:
            if not has_section:
                new_lines.append("[ServerSettings]")
                has_section = True
            new_lines.append(f"{ui_to_ini[ui_key]}={val}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def forest_config_path(server_dir: Path) -> Path:
    return server_dir / "DedicatedServer.cfg"


def read_forest_config(server_dir: Path) -> dict[str, str]:
    return _read_line_kv_config(forest_config_path(server_dir), _FOREST_LINE_MAP)


def write_forest_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_line_kv_config(forest_config_path(server_dir), updates, _FOREST_LINE_MAP)


def core_keeper_config_path(server_dir: Path) -> Path:
    return server_dir / "gamesettings.json"


def read_core_keeper_config(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(core_keeper_config_path(server_dir), _CORE_KEEPER_MAP)


def write_core_keeper_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(core_keeper_config_path(server_dir), updates, _CORE_KEEPER_MAP)


def space_engineers_config_path(server_dir: Path) -> Path:
    return server_dir / "SpaceEngineers-Dedicated.cfg"


def read_space_engineers_config(server_dir: Path) -> dict[str, str]:
    path = space_engineers_config_path(server_dir)
    if not path.exists():
        return {}
    try:
        ss = ET.parse(path).getroot().find(".//SessionSettings")
    except ET.ParseError:
        return {}
    if ss is None:
        return {}
    inv = {v: k for k, v in _SE_XML_MAP.items()}
    out: dict[str, str] = {}
    for child in ss:
        ui = inv.get(child.tag)
        if ui is not None and child.text is not None:
            out[ui] = child.text
    return out


def write_space_engineers_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = space_engineers_config_path(server_dir)
    if path.exists():
        tree = ET.parse(path)
        root = tree.getroot()
    else:
        root = ET.Element("MyObjectBuilder_DedicatedServerConfiguration")
        tree = ET.ElementTree(root)
    ss = root.find(".//SessionSettings")
    if ss is None:
        ss = ET.SubElement(root, "SessionSettings")
    for ui_key, val in updates.items():
        tag = _SE_XML_MAP.get(ui_key)
        if not tag:
            continue
        el = ss.find(tag)
        if el is None:
            el = ET.SubElement(ss, tag)
        el.text = str(val)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def conan_settings_path(server_dir: Path) -> Path:
    return server_dir / "ConanSandbox" / "Saved" / "Config" / _ue_config_subdir() / "ServerSettings.ini"


def read_conan_settings(server_dir: Path) -> dict[str, str]:
    return _read_ini_values(conan_settings_path(server_dir), _CONAN_INI_MAP)


def write_conan_settings(server_dir: Path, updates: dict[str, str]) -> None:
    _write_ini_values(conan_settings_path(server_dir), updates, _CONAN_INI_MAP)


def scum_settings_path(server_dir: Path) -> Path:
    return server_dir / "SCUM" / "Saved" / "Config" / _ue_config_subdir() / "ServerSettings.ini"


def read_scum_settings(server_dir: Path) -> dict[str, str]:
    return _read_ini_values(scum_settings_path(server_dir), _SCUM_INI_MAP)


def write_scum_settings(server_dir: Path, updates: dict[str, str]) -> None:
    path = scum_settings_path(server_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    pending = {k: v for k, v in updates.items() if k in _SCUM_INI_MAP}
    new_lines: list[str] = []
    touched: set[str] = set()
    for raw in lines:
        stripped = raw.strip()
        if "=" in stripped and not stripped.startswith("[") and not stripped.startswith(";"):
            key = stripped.split("=", 1)[0].strip()
            ui_key = next((u for u, i in _SCUM_INI_MAP.items() if i == key), None)
            if ui_key and ui_key in pending:
                new_lines.append(f"{key}={pending[ui_key]}")
                touched.add(ui_key)
                continue
        new_lines.append(raw)
    for ui_key, val in pending.items():
        if ui_key not in touched:
            if not any("SCUMAdditionalServerSettings" in l for l in new_lines):
                new_lines.append("[/Script/SCUM.SCUMAdditionalServerSettings]")
            new_lines.append(f"{_SCUM_INI_MAP[ui_key]}={val}")
    if not lines and pending:
        new_lines = ["[/Script/SCUM.SCUMAdditionalServerSettings]"] + [
            f"{_SCUM_INI_MAP[k]}={v}" for k, v in pending.items()
        ]
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def necesse_settings_path(server_dir: Path) -> Path:
    for name in ("Settings/serverSettings.json", "serverSettings.json"):
        path = server_dir / name
        if path.exists():
            return path
    return server_dir / "Settings" / "serverSettings.json"


def read_necesses_config(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(necesses_settings_path(server_dir), _NECESSE_MAP)


def write_necesses_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(necesses_settings_path(server_dir), updates, _NECESSE_MAP)


def raft_config_path(server_dir: Path) -> Path:
    for name in ("server.cfg", "Server.cfg"):
        path = server_dir / name
        if path.exists():
            return path
    return server_dir / "server.cfg"


def read_raft_config(server_dir: Path) -> dict[str, str]:
    return _read_ini_values(raft_config_path(server_dir), _RAFT_INI_MAP)


def write_raft_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_ini_values(raft_config_path(server_dir), updates, _RAFT_INI_MAP)


def icarus_settings_path(server_dir: Path) -> Path:
    for name in ("DedicatedServerSettings.json", "IcarusServerSettings.json"):
        path = server_dir / name
        if path.exists():
            return path
    return server_dir / "DedicatedServerSettings.json"


def read_icarus_config(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(icarus_settings_path(server_dir), _ICARUS_MAP)


def write_icarus_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(icarus_settings_path(server_dir), updates, _ICARUS_MAP)


def barotrauma_settings_path(server_dir: Path) -> Path:
    for name in ("ServerSettings.xml", "serversettings.xml"):
        path = server_dir / name
        if path.exists():
            return path
    return server_dir / "ServerSettings.xml"


def read_barotrauma_config(server_dir: Path) -> dict[str, str]:
    path = barotrauma_settings_path(server_dir)
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}
    inv = {v: k for k, v in _BAROTRAUMA_ATTR_MAP.items()}
    out: dict[str, str] = {}
    for attr, val in root.attrib.items():
        ui = inv.get(attr.lower())
        if ui:
            out[ui] = val
    return out


def write_barotrauma_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = barotrauma_settings_path(server_dir)
    if path.exists():
        root = ET.parse(path).getroot()
    else:
        root = ET.Element("serversettings")
    for ui_key, val in updates.items():
        attr = _BAROTRAUMA_ATTR_MAP.get(ui_key)
        if attr:
            root.set(attr, str(val))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def unturned_config_path(server_dir: Path, server_folder: str) -> Path:
    name = (server_folder or "Default").strip()
    return server_dir / "Servers" / name / "Server" / "Config.json"


def resolve_unturned_config_path(server_dir: Path, server_folder: str = "") -> Path:
    if server_folder.strip():
        path = unturned_config_path(server_dir, server_folder)
        if path.exists():
            return path
    matches = sorted(server_dir.glob("Servers/*/Server/Config.json"))
    if matches:
        return matches[0]
    return unturned_config_path(server_dir, server_folder or "Default")


def read_unturned_config(server_dir: Path, server_folder: str = "") -> dict[str, str]:
    path = resolve_unturned_config_path(server_dir, server_folder)
    out = _read_json_mapped(path, _UNTURNED_MAP)
    if path.is_file():
        try:
            idx = path.parts.index("Servers")
            out["server_folder"] = path.parts[idx + 1]
        except (ValueError, IndexError):
            pass
    return out


def write_unturned_config(server_dir: Path, updates: dict[str, str]) -> None:
    folder = str(updates.get("server_folder", "Default")).strip() or "Default"
    cfg = {k: v for k, v in updates.items() if k in _UNTURNED_MAP}
    path = unturned_config_path(server_dir, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_mapped(path, cfg, _UNTURNED_MAP)


def empyrion_config_path(server_dir: Path) -> Path:
    for name in ("dedicated.yaml", "Dedicated.yaml", "dedicated.yml"):
        path = server_dir / name
        if path.is_file():
            return path
    return server_dir / "dedicated.yaml"


def read_empyrion_config(server_dir: Path) -> dict[str, str]:
    path = empyrion_config_path(server_dir)
    if not path.is_file():
        return {}
    inv = {v: k for k, v in _EMPYRION_YAML_MAP.items()}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for yaml_key, ui_key in inv.items():
            prefix = f"{yaml_key}:"
            if stripped.startswith(prefix):
                out[ui_key] = stripped[len(prefix):].strip().strip('"').strip("'")
                break
    return out


def write_empyrion_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = empyrion_config_path(server_dir)
    pending = {k: v for k, v in updates.items() if k in _EMPYRION_YAML_MAP}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    inv = _EMPYRION_YAML_MAP
    new_lines: list[str] = []
    touched: set[str] = set()
    for raw in lines:
        stripped = raw.strip()
        matched = False
        for ui_key, yaml_key in inv.items():
            if ui_key in pending and stripped.startswith(f"{yaml_key}:"):
                indent = raw[: len(raw) - len(raw.lstrip())]
                new_lines.append(f"{indent}{yaml_key}: {pending[ui_key]}")
                touched.add(ui_key)
                matched = True
                break
        if not matched:
            new_lines.append(raw)
    if not lines and pending:
        new_lines = ["ServerConfig:"]
        for ui_key, val in pending.items():
            new_lines.append(f"  {inv[ui_key]}: {val}")
    else:
        for ui_key, val in pending.items():
            if ui_key not in touched:
                if not any(l.strip() == "ServerConfig:" for l in new_lines):
                    new_lines.insert(0, "ServerConfig:")
                new_lines.append(f"  {inv[ui_key]}: {val}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _read_ini_section(path: Path, section: str, key_map: dict[str, str]) -> dict[str, str]:
    if not path.is_file():
        return {}
    inv = {v: k for k, v in key_map.items()}
    out: dict[str, str] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            continue
        if current != section or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        ui = inv.get(key.strip())
        if ui:
            out[ui] = val.strip().strip('"')
    return out


def _write_ini_section(path: Path, section: str, updates: dict[str, str], key_map: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    pending = {k: v for k, v in updates.items() if k in key_map}
    new_lines: list[str] = []
    current: str | None = None
    touched: set[str] = set()
    section_header = f"[{section}]"
    has_section = any(l.strip() == section_header for l in lines)

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            new_lines.append(raw)
            continue
        if current == section and "=" in stripped and not stripped.startswith(";"):
            key = stripped.split("=", 1)[0].strip()
            ui = next((u for u, i in key_map.items() if i == key), None)
            if ui and ui in pending:
                new_lines.append(f"{key}={pending[ui]}")
                touched.add(ui)
                continue
        new_lines.append(raw)

    missing = {k: v for k, v in pending.items() if k not in touched}
    if missing:
        if not has_section:
            new_lines.append(section_header)
        else:
            insert_at = len(new_lines)
            for i, raw in enumerate(new_lines):
                if raw.strip() == section_header:
                    insert_at = i + 1
                    while insert_at < len(new_lines):
                        s = new_lines[insert_at].strip()
                        if s.startswith("[") and s.endswith("]"):
                            break
                        if "=" in s and not s.startswith(";"):
                            insert_at += 1
                            continue
                        break
                    break
            for ui_key, val in missing.items():
                new_lines.insert(insert_at, f"{key_map[ui_key]}={val}")
                insert_at += 1
            missing = {}

        if missing:
            new_lines.extend(f"{key_map[k]}={v}" for k, v in missing.items())

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def avorion_server_ini_path(server_dir: Path) -> Path:
    for rel in ("server.ini", "galaxy/server.ini", "Avorion/server.ini"):
        path = server_dir / rel
        if path.is_file():
            return path
    return server_dir / "server.ini"


def read_avorion_config(server_dir: Path) -> dict[str, str]:
    return _read_ini_section(avorion_server_ini_path(server_dir), "Game", _AVORION_GAME_MAP)


def write_avorion_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_ini_section(avorion_server_ini_path(server_dir), "Game", updates, _AVORION_GAME_MAP)


def resolve_owi_server_cfg(server_dir: Path, game_folder: str) -> Path:
    sub = _ue_config_subdir()
    candidates = [
        server_dir / game_folder / "ServerConfig" / "Server.cfg",
        server_dir / game_folder / "Saved" / "Config" / sub / "Server.cfg",
        server_dir / "ServerConfig" / "Server.cfg",
        server_dir / "Server.cfg",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def read_owi_server_cfg(server_dir: Path, game_folder: str) -> dict[str, str]:
    return _read_ini_values(resolve_owi_server_cfg(server_dir, game_folder), _OWI_CFG_MAP)


def write_owi_server_cfg(server_dir: Path, game_folder: str, updates: dict[str, str]) -> None:
    path = resolve_owi_server_cfg(server_dir, game_folder)
    if not path.is_file():
        path = server_dir / game_folder / "ServerConfig" / "Server.cfg"
    _write_ini_values(path, updates, _OWI_CFG_MAP)


def _resolve_survival_json(server_dir: Path, *names: str) -> Path:
    for name in names:
        path = server_dir / name
        if path.is_file():
            return path
    return server_dir / names[0]


def read_abiotic_config(server_dir: Path) -> dict[str, str]:
    path = _resolve_survival_json(server_dir, "ServerConfig.json", "DedicatedServerConfig.json")
    return _read_json_mapped(path, _ABIOTIC_MAP)


def write_abiotic_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = _resolve_survival_json(server_dir, "ServerConfig.json", "DedicatedServerConfig.json")
    _write_json_mapped(path, updates, _ABIOTIC_MAP)


def read_sunkenland_config(server_dir: Path) -> dict[str, str]:
    path = _resolve_survival_json(server_dir, "DedicatedServerConfig.json", "ServerConfig.json")
    return _read_json_mapped(path, _SUNKENLAND_MAP)


def write_sunkenland_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = _resolve_survival_json(server_dir, "DedicatedServerConfig.json", "ServerConfig.json")
    _write_json_mapped(path, updates, _SUNKENLAND_MAP)


def read_aska_config(server_dir: Path) -> dict[str, str]:
    path = _resolve_survival_json(server_dir, "ServerConfig.json", "DedicatedServerSettings.json")
    return _read_json_mapped(path, _ASKA_MAP)


def write_aska_config(server_dir: Path, updates: dict[str, str]) -> None:
    path = _resolve_survival_json(server_dir, "ServerConfig.json", "DedicatedServerSettings.json")
    _write_json_mapped(path, updates, _ASKA_MAP)


def _survival_json_config(server_dir: Path, *names: str) -> dict[str, str]:
    return _read_json_mapped(_resolve_survival_json(server_dir, *names), _ASKA_MAP)


def _survival_json_write(server_dir: Path, updates: dict[str, str], *names: str) -> None:
    _write_json_mapped(_resolve_survival_json(server_dir, *names), updates, _ASKA_MAP)


def read_owi_server_cfg_folders(server_dir: Path, *game_folders: str) -> dict[str, str]:
    for folder in game_folders:
        data = read_owi_server_cfg(server_dir, folder)
        if data:
            return data
    return read_owi_server_cfg(server_dir, game_folders[0]) if game_folders else {}


def write_owi_server_cfg_folders(server_dir: Path, game_folders: tuple[str, ...], updates: dict[str, str]) -> None:
    for folder in game_folders:
        path = resolve_owi_server_cfg(server_dir, folder)
        if path.is_file():
            write_owi_server_cfg(server_dir, folder, updates)
            return
    write_owi_server_cfg(server_dir, game_folders[0], updates)


def starbound_config_path(server_dir: Path) -> Path:
    for rel in ("storage/starbound_server.config", "starbound_server.config"):
        path = server_dir / rel
        if path.is_file():
            return path
    return server_dir / "storage" / "starbound_server.config"


def read_starbound_config(server_dir: Path) -> dict[str, str]:
    return _read_json_mapped(starbound_config_path(server_dir), _STARBOUND_MAP)


def write_starbound_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_json_mapped(starbound_config_path(server_dir), updates, _STARBOUND_MAP)


def bannerlord_config_path(server_dir: Path) -> Path:
    for name in ("_config.txt", "config.txt", "CustomServerConfig.txt"):
        path = server_dir / name
        if path.is_file():
            return path
    return server_dir / "_config.txt"


def read_bannerlord_config(server_dir: Path) -> dict[str, str]:
    return _read_line_kv_config(bannerlord_config_path(server_dir), _BANNERLORD_LINE_MAP)


def write_bannerlord_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_line_kv_config(bannerlord_config_path(server_dir), updates, _BANNERLORD_LINE_MAP)


_MORDHAU_INI_SECTION = "/Script/Mordhau.MordhauGameSession"
_MORDHAU_MAP = {
    "server_name": "ServerName",
    "max_players": "MaxPlayers",
    "password": "ServerPassword",
}

_HOLDFAST_MAP = {
    "server_name": "server_name",
    "max_players": "max_players",
    "port": "server_port",
    "password": "server_password",
}


def mordhau_game_ini_path(server_dir: Path) -> Path:
    sub = _ue_config_subdir()
    return server_dir / "Mordhau" / "Saved" / "Config" / sub / "Game.ini"


def read_mordhau_config(server_dir: Path) -> dict[str, str]:
    return _read_ini_section(mordhau_game_ini_path(server_dir), _MORDHAU_INI_SECTION, _MORDHAU_MAP)


def write_mordhau_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_ini_section(mordhau_game_ini_path(server_dir), _MORDHAU_INI_SECTION, updates, _MORDHAU_MAP)


def holdfast_config_path(server_dir: Path) -> Path:
    for rel in ("configs/serverconfig_default.txt", "serverconfig_default.txt", "serverconfig_default.cfg"):
        path = server_dir / rel
        if path.is_file():
            return path
    return server_dir / "configs" / "serverconfig_default.txt"


def read_holdfast_config(server_dir: Path) -> dict[str, str]:
    return _read_line_kv_config(holdfast_config_path(server_dir), _HOLDFAST_MAP)


def write_holdfast_config(server_dir: Path, updates: dict[str, str]) -> None:
    _write_line_kv_config(holdfast_config_path(server_dir), updates, _HOLDFAST_MAP)


def _read_source_cvar_config(path: Path, cvar_map: dict[str, str]) -> dict[str, str]:
    if not path.is_file():
        return {}
    inv = {v: k for k, v in cvar_map.items()}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        ui_key = inv.get(parts[0])
        if ui_key:
            out[ui_key] = parts[1].strip().strip('"')
    return out


def _write_source_cvar_config(path: Path, updates: dict[str, str], cvar_map: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    cvar_to_ui = {v: k for k, v in cvar_map.items()}
    pending = {k: v for k, v in updates.items() if k in cvar_map}
    new_lines: list[str] = []
    touched: set[str] = set()

    def _format_cvar(cvar: str, val: str) -> str:
        if cvar == "maxplayers":
            return f"{cvar} {val}"
        return f'{cvar} "{val}"'

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            new_lines.append(raw)
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2 and parts[0] in cvar_to_ui:
            ui_key = cvar_to_ui[parts[0]]
            if ui_key in pending:
                new_lines.append(_format_cvar(parts[0], pending[ui_key]))
                touched.add(ui_key)
                continue
        new_lines.append(raw)
    for ui_key, val in pending.items():
        if ui_key not in touched:
            new_lines.append(_format_cvar(cvar_map[ui_key], str(val)))
    if not lines and pending:
        new_lines = ["// Game Server Manager — server.cfg"] + new_lines
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def resolve_source_cfg_path(server_dir: Path, game_folder: str) -> Path:
    for rel in (f"{game_folder}/cfg/server.cfg", "cfg/server.cfg"):
        path = server_dir / rel
        if path.is_file():
            return path
    return server_dir / game_folder / "cfg" / "server.cfg"


def read_source_config(server_dir: Path, game_folder: str) -> dict[str, str]:
    return _read_source_cvar_config(resolve_source_cfg_path(server_dir, game_folder), _SOURCE_CVAR_MAP)


def write_source_config(server_dir: Path, game_folder: str, updates: dict[str, str]) -> None:
    _write_source_cvar_config(resolve_source_cfg_path(server_dir, game_folder), updates, _SOURCE_CVAR_MAP)


def resolve_rust_identity(server_dir: Path, preferred: str = "rust_server_1") -> str:
    preferred = (preferred or "rust_server_1").strip() or "rust_server_1"
    if (server_dir / "server" / preferred / "cfg" / "server.cfg").is_file():
        return preferred
    server_root = server_dir / "server"
    if server_root.is_dir():
        for child in sorted(server_root.iterdir()):
            if child.is_dir() and (child / "cfg" / "server.cfg").is_file():
                return child.name
    return preferred


def rust_server_cfg_path(server_dir: Path, identity: str) -> Path:
    ident = resolve_rust_identity(server_dir, identity)
    return server_dir / "server" / ident / "cfg" / "server.cfg"


def read_rust_config(server_dir: Path, identity: str = "rust_server_1") -> dict[str, str]:
    out = _read_line_kv_config(rust_server_cfg_path(server_dir, identity), _RUST_CFG_MAP)
    ident = resolve_rust_identity(server_dir, identity)
    if ident:
        out["server_identity"] = ident
    return out


def write_rust_config(server_dir: Path, identity: str, updates: dict[str, str]) -> None:
    ident = resolve_rust_identity(server_dir, identity)
    cfg_updates = {k: v for k, v in updates.items() if k in _RUST_CFG_MAP}
    _write_line_kv_config(rust_server_cfg_path(server_dir, ident), cfg_updates, _RUST_CFG_MAP)


def ark_game_user_settings_path(server_dir: Path, content_folder: str = "ShooterGame") -> Path:
    sub = _ue_config_subdir()
    return server_dir / content_folder / "Saved" / "Config" / sub / "GameUserSettings.ini"


def read_ark_config(server_dir: Path, content_folder: str = "ShooterGame") -> dict[str, str]:
    path = ark_game_user_settings_path(server_dir, content_folder)
    out = _read_ini_section(path, "SessionSettings", _ARK_SESSION_MAP)
    out.update(_read_ini_section(path, "ServerSettings", _ARK_SERVER_MAP))
    return out


def write_ark_config(server_dir: Path, content_folder: str, updates: dict[str, str]) -> None:
    path = ark_game_user_settings_path(server_dir, content_folder)
    session_updates = {k: v for k, v in updates.items() if k in _ARK_SESSION_MAP}
    server_updates = {k: v for k, v in updates.items() if k in _ARK_SERVER_MAP}
    if session_updates:
        _write_ini_section(path, "SessionSettings", session_updates, _ARK_SESSION_MAP)
    if server_updates:
        _write_ini_section(path, "ServerSettings", server_updates, _ARK_SERVER_MAP)


def dst_cluster_ini_path(cluster_name: str) -> Path:
    name = (cluster_name or "MyDediCluster").strip()
    return Path.home() / "Documents" / "Klei" / "DoNotStarveTogether" / name / "cluster.ini"


def read_dst_cluster_config(cluster_name: str) -> dict[str, str]:
    path = dst_cluster_ini_path(cluster_name)
    out: dict[str, str] = {}
    for ui_key, (section, ini_key) in _DST_INI_FIELDS.items():
        section_map = {ui_key: ini_key}
        out.update(_read_ini_section(path, section, section_map))
    return out


def write_dst_cluster_config(cluster_name: str, updates: dict[str, str]) -> None:
    path = dst_cluster_ini_path(cluster_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    by_section: dict[str, dict[str, str]] = {}
    for ui_key, val in updates.items():
        field = _DST_INI_FIELDS.get(ui_key)
        if not field:
            continue
        section, ini_key = field
        by_section.setdefault(section, {})[ui_key] = val
    for section, section_updates in by_section.items():
        section_map = {ui: _DST_INI_FIELDS[ui][1] for ui in section_updates}
        _write_ini_section(path, section, section_updates, section_map)


def _build_ark_style_start(
    server_dir: Path,
    config: dict,
    *,
    executable_win: str,
    executable_linux: str,
    default_map: str,
    default_session: str,
    default_port: str,
    default_query: str,
    default_max: str,
) -> tuple[list[str], dict]:
    root = server_dir.resolve()
    exe = find_steam_server_binary(server_dir, executable_win, executable_linux) or root / executable_win
    map_name = str(config.get("map", default_map))
    session = str(config.get("session_name", default_session))
    port = str(config.get("port", default_port))
    query = str(config.get("query_port", default_query))
    max_p = str(config.get("max_players", default_max))
    opts = f"?listen?SessionName={session}?Port={port}?QueryPort={query}?MaxPlayers={max_p}"
    password = str(config.get("server_password", "")).strip()
    if password:
        opts += f"?ServerPassword={password}"
    admin = str(config.get("admin_password", "")).strip()
    if admin:
        opts += f"?ServerAdminPassword={admin}"
    extra = str(config.get("extra_args", "")).strip()
    if extra:
        opts += extra if extra.startswith("?") else f"?{extra}"
    return [_relative_or_absolute_arg(exe, root), map_name + opts], {"cwd": str(root)}


def _apply_mapped_config(server_dir: Path, config: dict, keys: set[str], writer) -> None:
    updates = {k: str(v) for k, v in config.items() if k in keys}
    if updates:
        writer(server_dir, updates)


class _FileConfigMixin:
    """Shared read/write/apply helpers for adapters that sync game config files."""

    _config_keys: set[str] = set()

    def read_config(self, server_dir: Path) -> dict[str, str]:
        return self._read_file_config(server_dir)

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        self._write_file_config(server_dir, updates)

    def apply_config(self, server_dir: Path, config: dict) -> None:
        _apply_mapped_config(server_dir, config, self._config_keys, self._write_file_config)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        raise NotImplementedError

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        raise NotImplementedError


class _RconConsoleMixin:
    def execute_remote_command(
        self, command: str, config: dict, server_dir: Path
    ) -> tuple[bool, str] | None:
        client = _rcon_client(config)
        if client is None:
            return False, "Enable RCON and set a password in Config to use console commands."
        cmd = command.strip()
        if cmd.startswith("/"):
            cmd = cmd[1:]
        try:
            result = client.execute(cmd)
            text = result.strip()
            return True, text if text else f"> {cmd} (ok)"
        except (SourceRconError, OSError) as e:
            return False, f"RCON failed: {e}"

    def prefers_remote_console(self, config: dict) -> bool:
        return _rcon_client(config) is not None

    def graceful_stop_remote(self, config: dict, server_dir: Path) -> tuple[bool, str] | None:
        client = _rcon_client(config)
        if client is None:
            return None
        try:
            client.execute("/quit")
            return True, "Quit sent via RCON."
        except (SourceRconError, OSError) as e:
            return False, f"RCON shutdown failed: {e}"


class _TelnetConsoleMixin:
    def execute_remote_command(
        self, command: str, config: dict, server_dir: Path
    ) -> tuple[bool, str] | None:
        client = _telnet_client(config)
        if client is None:
            return False, "Enable telnet and set a telnet password in Config to use console commands."
        try:
            result = client.execute(command)
            text = result.strip()
            return True, text if text else f"> {command.strip()} (ok)"
        except (GameTelnetError, OSError) as e:
            return False, f"Telnet failed: {e}"

    def prefers_remote_console(self, config: dict) -> bool:
        return _telnet_client(config) is not None

    def graceful_stop_remote(self, config: dict, server_dir: Path) -> tuple[bool, str] | None:
        client = _telnet_client(config)
        if client is None:
            return None
        try:
            client.execute("shutdown")
            return True, "Shutdown sent via telnet."
        except (GameTelnetError, OSError) as e:
            return False, f"Telnet shutdown failed: {e}"


def find_steam_server_binary(server_dir: Path, *names: str) -> Path | None:
    """Search server_dir (and one level of subfolders) for any of the given filenames."""
    if not server_dir.is_dir() or not names:
        return None

    search_dirs: list[Path] = [server_dir]
    seen: set[str] = {str(server_dir.resolve()).lower()}

    def add_dir(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen and path.is_dir():
            seen.add(key)
            search_dirs.append(path)

    for sub in sorted(server_dir.iterdir()):
        if sub.is_dir():
            add_dir(sub)

    for folder in search_dirs:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate

    for name in names:
        matches = sorted(server_dir.glob(f"**/{name}"))
        if matches:
            return matches[0]
    return None


def _relative_or_absolute_arg(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path.resolve())


def _steam_install_worker(server_dir: Path, app_id: str, *exe_names: str):
    from .install import create_steamcmd_install_worker

    return create_steamcmd_install_worker(
        server_dir,
        app_id,
        verify=lambda directory: find_steam_server_binary(directory, *exe_names) is not None,
    )


class RustAdapter(_RconConsoleMixin, _FileConfigMixin, SteamDedicatedAdapter):
    game_type = "rust"
    display_name = "Rust"
    icon = "🪓"
    description = "Rust dedicated server (Steam App ID 258550)."
    steam_app_id = "258550"
    executable_win = "RustDedicated.exe"
    executable_linux = "RustDedicated"
    default_stop_command = "quit"
    _config_keys = set(_RUST_CFG_MAP) | {"server_identity", "rcon_enabled"}

    def default_port(self) -> int:
        return 28015

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_rust_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        identity = str(updates.get("server_identity", "rust_server_1")).strip() or "rust_server_1"
        write_rust_config(server_dir, identity, updates)
        if _truthy(str(updates.get("rcon_enabled", ""))):
            rcon_pw = str(updates.get("rcon_password", "")).strip()
            if rcon_pw:
                _write_line_kv_config(
                    rust_server_cfg_path(server_dir, identity),
                    {"rcon_port": str(updates.get("rcon_port", "28016")), "rcon_password": rcon_pw},
                    {"rcon_port": "rcon.port", "rcon_password": "rcon.password"},
                )
                path = rust_server_cfg_path(server_dir, identity)
                text = path.read_text(encoding="utf-8", errors="replace")
                if "rcon.web" not in text:
                    path.write_text(text.rstrip() + "\nrcon.web 0\n", encoding="utf-8")

    def apply_config(self, server_dir: Path, config: dict) -> None:
        identity = str(config.get("server_identity", "rust_server_1")).strip() or "rust_server_1"
        updates = {k: str(v) for k, v in config.items() if k in self._config_keys}
        updates["server_identity"] = identity
        self._write_file_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "My Rust Server", width=180),
            ConfigField("server_identity", "Server identity", "text", "rust_server_1", width=140),
            ConfigField("port", "Port", "text", "28015", width=100),
            ConfigField("max_players", "Max players", "text", "50", width=80),
            ConfigField("world_size", "World size", "text", "3000", width=80),
            ConfigField("seed", "World seed", "text", "12345", width=100),
            ConfigField("rcon_enabled", "Enable RCON", "checkbox", "false"),
            ConfigField("rcon_port", "RCON port", "text", "28016", width=100),
            ConfigField("rcon_password", "RCON password", "text", "", width=120),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        exe_arg = _relative_or_absolute_arg(exe, root)
        identity = str(config.get("server_identity", "rust_server_1")).strip() or "rust_server_1"
        args = [
            exe_arg,
            "-batchmode", "-nographics",
            "+server.port", str(config.get("port", self.default_port())),
            "+server.identity", identity,
            "+server.hostname", str(config.get("server_name", "My Rust Server")),
            "+server.maxplayers", str(config.get("max_players", "50")),
            "+server.worldsize", str(config.get("world_size", "3000")),
            "+server.seed", str(config.get("seed", "12345")),
        ]
        if _truthy(str(config.get("rcon_enabled", ""))):
            rcon_pw = str(config.get("rcon_password", "")).strip()
            if rcon_pw:
                args.extend([
                    "+rcon.web", "0",
                    "+rcon.port", str(config.get("rcon_port", "28016")),
                    "+rcon.password", rcon_pw,
                ])
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("Status", "status"),
            ("Save", "save"),
            ("Say hello", "say Server message"),
            ("Quit", "quit"),
        ]

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to server/<identity>/cfg/server.cfg.",
            "Enable legacy RCON (+rcon.web 0) for Console tab — default port 28016.",
            "Forward UDP 28015 (game) and TCP 28016 (RCON when enabled).",
            "Use Extra args for Oxide/uMod (+oxide.load etc.).",
        ]


class ArkEvolvedAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "ark_evolved"
    display_name = "ARK: Survival Evolved"
    icon = "🦖"
    description = "ARK: Survival Evolved dedicated server (Steam App ID 376030)."
    steam_app_id = "376030"
    executable_win = "ShooterGameServer.exe"
    executable_linux = "ShooterGameServer"
    _content_folder = "ShooterGame"
    _config_keys = set(_ARK_SESSION_MAP) | set(_ARK_SERVER_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_ark_config(server_dir, self._content_folder)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_ark_config(server_dir, self._content_folder, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("map", "Map", "text", "TheIsland", width=120),
            ConfigField("session_name", "Session name", "text", "ARK Server", width=160),
            ConfigField("port", "Port", "text", "7777", width=80),
            ConfigField("query_port", "Query port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "70", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra ? args", "text", "", width=200),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        return _build_ark_style_start(
            server_dir, config,
            executable_win=self.executable_win,
            executable_linux=self.executable_linux,
            default_map="TheIsland",
            default_session="ARK Server",
            default_port="7777",
            default_query="27015",
            default_max="70",
        )

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            f"Settings sync to ShooterGame/Saved/Config/{sub}/GameUserSettings.ini.",
            "Forward UDP 7777, 7778, and TCP 27015 (query).",
        ]


class ArkAscendedAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "ark_ascended"
    display_name = "ARK: Survival Ascended"
    icon = "🦕"
    description = "ARK: Survival Ascended dedicated server (Steam App ID 2430930)."
    steam_app_id = "2430930"
    executable_win = "ArkAscendedServer.exe"
    executable_linux = "ArkAscendedServer"
    _content_folder = "ShooterGame"
    _config_keys = set(_ARK_SESSION_MAP) | set(_ARK_SERVER_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(
            server_dir,
            self.executable_win,
            self.executable_linux,
            "ShooterGameServer.exe",
            "ShooterGameServer",
        )

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(
            server_dir,
            self.steam_app_id_for(config),
            self.executable_win,
            self.executable_linux,
            "ShooterGameServer.exe",
        )

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_ark_config(server_dir, self._content_folder)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_ark_config(server_dir, self._content_folder, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("map", "Map", "text", "TheIsland_WP", width=140),
            ConfigField("session_name", "Session name", "text", "ASA Server", width=160),
            ConfigField("port", "Port", "text", "7777", width=80),
            ConfigField("query_port", "Query port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "70", width=80),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra ? args", "text", "", width=200),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        return _build_ark_style_start(
            server_dir, config,
            executable_win=self.executable_win,
            executable_linux=self.executable_linux,
            default_map="TheIsland_WP",
            default_session="ASA Server",
            default_port="7777",
            default_query="27015",
            default_max="70",
        )

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            f"Settings sync to ShooterGame/Saved/Config/{sub}/GameUserSettings.ini.",
            "Forward UDP 7777–7778 and TCP 27015 (query).",
        ]


class PixarkAdapter(SteamDedicatedAdapter):
    game_type = "pixark"
    display_name = "PixARK"
    icon = "🦖"
    description = "PixARK dedicated server (Steam App ID 824720)."
    steam_app_id = "824720"
    executable_win = "ShooterGameServer.exe"
    executable_linux = "ShooterGameServer"

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("map", "Map", "text", "CubeWorld", width=120),
            ConfigField("session_name", "Session name", "text", "PixARK Server", width=160),
            ConfigField("port", "Port", "text", "7777", width=80),
            ConfigField("query_port", "Query port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "70", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra ? args", "text", "", width=200),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        return _build_ark_style_start(
            server_dir, config,
            executable_win=self.executable_win,
            executable_linux=self.executable_linux,
            default_map="CubeWorld",
            default_session="PixARK Server",
            default_port="7777",
            default_query="27015",
            default_max="70",
        )

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "ARK-style map?listen URL startup — same pattern as ARK Evolved.",
            "Forward UDP 7777–7778 and TCP 27015 (query).",
        ]


class AtlasAdapter(SteamDedicatedAdapter):
    game_type = "atlas"
    display_name = "Atlas"
    icon = "🗺️"
    description = "Atlas dedicated server (Steam App ID 1006030)."
    steam_app_id = "1006030"
    executable_win = "ShooterGameServer.exe"
    executable_linux = "ShooterGameServer"

    def default_port(self) -> int:
        return 5761

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("map", "Map / grid", "text", "Ocean", width=120),
            ConfigField("session_name", "Session name", "text", "Atlas Server", width=160),
            ConfigField("port", "Port", "text", "5761", width=80),
            ConfigField("query_port", "Query port", "text", "27016", width=100),
            ConfigField("max_players", "Max players", "text", "50", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra ? args", "text", "", width=200),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        return _build_ark_style_start(
            server_dir, config,
            executable_win=self.executable_win,
            executable_linux=self.executable_linux,
            default_map="Ocean",
            default_session="Atlas Server",
            default_port="5761",
            default_query="27016",
            default_max="50",
        )

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Atlas uses ARK-style startup URLs — set map/grid for your world layout.",
            "Forward UDP 5761+ and Steam query port (default 27016).",
        ]


class CounterStrike2Adapter(SteamDedicatedAdapter):
    game_type = "cs2"
    display_name = "Counter-Strike 2"
    icon = "🔫"
    description = "Counter-Strike 2 dedicated server (Steam App ID 730)."
    steam_app_id = "730"
    executable_win = "cs2.exe"
    executable_linux = "cs2"

    def default_port(self) -> int:
        return 27015

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(
            server_dir,
            "cs2.exe",
            "cs2",
            "srcds.exe",
            "srcds_run",
        )

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), "cs2.exe", "cs2", "srcds.exe")

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("map", "Start map", "text", "de_dust2", width=120),
            ConfigField("port", "Port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "16", width=80),
            ConfigField("game_type", "Game type", "text", "0", width=80),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        root = server_dir.resolve()
        exe = self._exe(root) or root / "cs2.exe"
        args = [
            _relative_or_absolute_arg(exe, root),
            "-dedicated",
            "+map", str(config.get("map", "de_dust2")),
            "-port", str(config.get("port", self.default_port())),
            "+maxplayers", str(config.get("max_players", "16")),
            "+game_type", str(config.get("game_type", "0")),
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "SteamCMD app 730 — first install can take a while.",
            "Forward UDP/TCP 27015; use +host_workshop_map for workshop maps in Extra args.",
        ]


class _SourceDedicatedAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    """Shared Source-engine srcds adapter (GMod, L4D2, etc.)."""

    _game_folder: str
    _default_map: str
    _exe_names: tuple[str, ...] = ("srcds.exe", "srcds_run")
    _config_keys = set(_SOURCE_CVAR_MAP) | {"map", "port"}

    def default_port(self) -> int:
        return 27015

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, *self._exe_names)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), *self._exe_names)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_source_config(server_dir, self._game_folder)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        cfg_updates = {k: v for k, v in updates.items() if k in _SOURCE_CVAR_MAP}
        write_source_config(server_dir, self._game_folder, cfg_updates)

    def _source_start_args(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        port = str(config.get("port", self.default_port()))
        game_map = str(config.get("map", self._default_map)).strip() or self._default_map
        max_p = str(config.get("max_players", "16"))
        args = [
            _relative_or_absolute_arg(exe, root),
            "-console", "-game", self._game_folder,
            "-port", port,
            "+map", game_map,
            "+maxplayers", max_p,
            "+exec", "server.cfg",
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}


class GmodAdapter(_SourceDedicatedAdapter):
    game_type = "gmod"
    display_name = "Garry's Mod"
    icon = "🔧"
    description = "Garry's Mod dedicated server (Steam App ID 4020)."
    steam_app_id = "4020"
    executable_win = "srcds.exe"
    executable_linux = "srcds_run"
    _game_folder = "garrysmod"
    _default_map = "gm_construct"
    _exe_names = ("srcds.exe", "srcds_run", "gmod.exe")
    _config_keys = set(_SOURCE_CVAR_MAP) | {"map", "port", "gamemode"}

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "GMod Server", width=160),
            ConfigField("map", "Start map", "text", "gm_construct", width=140),
            ConfigField("gamemode", "Gamemode", "text", "sandbox", width=100),
            ConfigField("port", "Port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "16", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("rcon_password", "RCON password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        args, env = self._source_start_args(server_dir, config)
        gamemode = str(config.get("gamemode", "sandbox")).strip()
        if gamemode:
            args.extend(["+gamemode", gamemode])
        return args, env

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to garrysmod/cfg/server.cfg.",
            "Forward UDP/TCP 27015; workshop maps via Extra args (+host_workshop_collection).",
        ]


class L4d2Adapter(_SourceDedicatedAdapter):
    game_type = "l4d2"
    display_name = "Left 4 Dead 2"
    icon = "🧟"
    description = "Left 4 Dead 2 dedicated server (Steam App ID 222860)."
    steam_app_id = "222860"
    executable_win = "srcds.exe"
    executable_linux = "srcds_run"
    _game_folder = "left4dead2"
    _default_map = "c1m1_hotel"

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "L4D2 Server", width=160),
            ConfigField("map", "Start map", "text", "c1m1_hotel", width=140),
            ConfigField("port", "Port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("rcon_password", "RCON password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        return self._source_start_args(server_dir, config)

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to left4dead2/cfg/server.cfg.",
            "Forward UDP/TCP 27015; campaign rotation via Extra args or cfg.",
        ]


class SevenDaysToDieAdapter(_TelnetConsoleMixin, _FileConfigMixin, SteamDedicatedAdapter):
    game_type = "seven_days_to_die"
    display_name = "7 Days to Die"
    icon = "🧱"
    description = "7 Days to Die dedicated server (Steam App ID 294420)."
    steam_app_id = "294420"
    executable_win = "7DaysToDieServer.exe"
    executable_linux = "7DaysToDieServer.x86_64"
    _config_keys = set(_7DTD_PROPS)

    def default_port(self) -> int:
        return 26900

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_7dtd_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_7dtd_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "7DTD Server", width=160),
            ConfigField("port", "Port", "text", "26900", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("telnet_enabled", "Enable telnet", "checkbox", "true"),
            ConfigField("telnet_port", "Telnet port", "text", "8081", width=100),
            ConfigField("telnet_password", "Telnet password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [
            _relative_or_absolute_arg(exe, root),
            "-configfile=serverconfig.xml",
            "-dedicated",
            "-logfile", "7dtd.log",
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("List players", "listplayers"),
            ("Save world", "saveworld"),
            ("Shutdown", "shutdown"),
            ('Say "Hello"', 'say "Hello"'),
        ]

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to serverconfig.xml — set telnet password for Console tab commands.",
            "Forward UDP 26900–26902 and TCP telnet port (default 8081) if used remotely.",
        ]


class FactorioAdapter(_RconConsoleMixin, _FileConfigMixin, SteamDedicatedAdapter):
    game_type = "factorio"
    display_name = "Factorio"
    icon = "⚙️"
    description = "Factorio headless server (Steam App ID 427520)."
    steam_app_id = "427520"
    executable_win = "factorio.exe"
    executable_linux = "factorio"
    _config_keys = set(_FACTORIO_MAP) | set(_FACTORIO_NESTED_KEYS) | {"save_file"}

    def default_port(self) -> int:
        return 34197

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        win = find_steam_server_binary(server_dir, "factorio.exe", "bin/x64/factorio.exe")
        if win:
            return win
        return find_steam_server_binary(server_dir, "factorio", "bin/x64/factorio")

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), "factorio.exe", "factorio")

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_factorio_settings(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_factorio_settings(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("save_file", "Save file", "text", "save1.zip", width=140),
            ConfigField("port", "Port", "text", "34197", width=100),
            ConfigField("server_name", "Server name", "text", "Factorio Server", width=160),
            ConfigField("server_description", "Description", "text", "", width=200),
            ConfigField("max_players", "Max players", "text", "0", width=80),
            ConfigField("server_password", "Game password", "text", "", width=120),
            ConfigField("rcon_enabled", "Enable RCON", "checkbox", "false"),
            ConfigField("rcon_port", "RCON port", "text", "27015", width=100),
            ConfigField("rcon_password", "RCON password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        ok, msg = super().pre_start_checks(server_dir, config)
        if not ok:
            return ok, msg
        save = server_dir / str(config.get("save_file", "save1.zip"))
        if not save.is_file():
            return False, f"Save file not found: {save.name} — place a .zip save in the server folder."
        if not factorio_settings_path(server_dir).exists():
            self.apply_config(server_dir, config)
            return True, "Created server-settings.json — review Config, then start again."
        return True, "Ready to start."

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / "bin" / "x64" / _exe("factorio.exe", "factorio")
        save = str(config.get("save_file", "save1.zip"))
        args = [
            _relative_or_absolute_arg(exe, root),
            "--start-server", save,
            "--port", str(config.get("port", self.default_port())),
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("/players", "/players"),
            ("/admins", "/admins"),
            ("/ban-list", "/ban-list"),
            ("/save", "/save"),
            ("/shutdown", "/shutdown"),
        ]

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to server-settings.json; enable RCON for Console tab commands.",
            "Place a save .zip in the server folder before first start.",
            "Forward UDP 34197 (and TCP RCON port if enabled).",
        ]


class EnshroudedAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "enshrouded"
    display_name = "Enshrouded"
    icon = "🌫️"
    description = "Enshrouded dedicated server (Steam App ID 2278520)."
    steam_app_id = "2278520"
    executable_win = "enshrouded_server.exe"
    executable_linux = "enshrouded_server"
    _config_keys = set(_ENSHROUDED_MAP)

    def default_port(self) -> int:
        return 15636

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(
            server_dir,
            "enshrouded_server.exe",
            "enshrouded_server",
            "EnshroudedDedicated.exe",
        )

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(
            server_dir,
            self.steam_app_id_for(config),
            "enshrouded_server.exe",
            "enshrouded_server",
            "EnshroudedDedicated.exe",
        )

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_enshrouded_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_enshrouded_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Enshrouded Server", width=160),
            ConfigField("port", "Port", "text", "15636", width=100),
            ConfigField("query_port", "Query port", "text", "15637", width=100),
            ConfigField("slot_count", "Max players", "text", "16", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to enshrouded_server.json in the server folder.",
            "Forward UDP 15636–15637 (and TCP 15637 for query).",
        ]


class VRisingAdapter(_RconConsoleMixin, _FileConfigMixin, SteamDedicatedAdapter):
    game_type = "vrising"
    display_name = "V Rising"
    icon = "🧛"
    description = "V Rising dedicated server (Steam App ID 1829350)."
    steam_app_id = "1829350"
    executable_win = "VRisingServer.exe"
    executable_linux = "VRisingServer"
    _config_keys = set(_VRISING_MAP)

    def default_port(self) -> int:
        return 9876

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_vrising_settings(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_vrising_settings(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "V Rising Server", width=160),
            ConfigField("port", "Game port", "text", "9876", width=100),
            ConfigField("query_port", "Query port", "text", "9877", width=100),
            ConfigField("max_users", "Max players", "text", "40", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("rcon_enabled", "Enable RCON", "checkbox", "false"),
            ConfigField("rcon_port", "RCON port", "text", "25575", width=100),
            ConfigField("rcon_password", "RCON password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root), "-persistentDataPath", str(root / "save-data")]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def graceful_stop_remote(self, config: dict, server_dir: Path) -> tuple[bool, str] | None:
        client = _rcon_client(config)
        if client is None:
            return None
        try:
            client.execute("shutdown,15,Server restarting")
            return True, "Shutdown countdown started via RCON."
        except (SourceRconError, OSError) as e:
            return False, f"RCON shutdown failed: {e}"

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to save-data/Settings/ServerHostSettings.json.",
            "Enable RCON + password in Config for Console tab commands.",
            "Forward UDP 9876–9877 (and TCP RCON port if enabled).",
        ]


class DayZAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "dayz"
    display_name = "DayZ"
    icon = "🌍"
    description = "DayZ dedicated server (Steam App ID 223350)."
    steam_app_id = "223350"
    executable_win = "DayZServer_x64.exe"
    executable_linux = "DayZServer"
    _config_keys = set(_DAYZ_CFG_KEYS) | {"port", "profiles"}

    def default_port(self) -> int:
        return 2302

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_dayz_cfg(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        cfg_updates = {k: v for k, v in updates.items() if k in _DAYZ_CFG_KEYS}
        if cfg_updates:
            write_dayz_cfg(server_dir, cfg_updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "DayZ Server", width=160),
            ConfigField("port", "Port", "text", "2302", width=100),
            ConfigField("max_players", "Max players", "text", "60", width=80),
            ConfigField("server_password", "Join password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("profiles", "Profiles folder", "text", "profiles", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        profiles = str(config.get("profiles", "profiles")).strip() or "profiles"
        args = [
            _relative_or_absolute_arg(exe, root),
            "-config=serverDZ.cfg",
            f"-port={config.get('port', self.default_port())}",
            f"-profiles={profiles}",
            "-dologs", "-adminlog", "-netlog", "-freezecheck",
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to serverDZ.cfg — edit Missions/template for map changes.",
            "Forward UDP 2302–2305 and Steam query ports per Bohemia docs.",
        ]


class SonsOfTheForestAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "sons_of_the_forest"
    display_name = "Sons of the Forest"
    icon = "🪓"
    description = "Sons of the Forest dedicated server (Steam App ID 2465200)."
    steam_app_id = "2465200"
    executable_win = "SonsOfTheForestDedicatedServer.exe"
    executable_linux = "SonsOfTheForestDedicatedServer"
    _config_keys = set(_SOTF_MAP)

    def default_port(self) -> int:
        return 8766

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_sotf_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_sotf_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "SOTF Server", width=160),
            ConfigField("port", "Game port", "text", "8766", width=100),
            ConfigField("query_port", "Query port", "text", "27016", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to dedicatedserver.cfg in the server folder.",
            "Forward UDP 8766 and query port (default 27016).",
        ]


class TheForestAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "the_forest"
    display_name = "The Forest"
    icon = "🌲"
    description = "The Forest dedicated server (Steam App ID 556450)."
    steam_app_id = "556450"
    executable_win = "TheForestDedicatedServer.exe"
    executable_linux = "TheForestDedicatedServer"
    _config_keys = set(_FOREST_LINE_MAP)

    def default_port(self) -> int:
        return 8766

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_forest_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_forest_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "The Forest Server", width=160),
            ConfigField("port", "Port", "text", "8766", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to DedicatedServer.cfg in the server folder.",
            "Forward UDP 8766 and query port 27016.",
        ]


class CoreKeeperAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "core_keeper"
    display_name = "Core Keeper"
    icon = "⛏️"
    description = "Core Keeper dedicated server (Steam App ID 1621690)."
    steam_app_id = "1621690"
    executable_win = "CoreKeeperServer.exe"
    executable_linux = "CoreKeeperServer"
    _config_keys = set(_CORE_KEEPER_MAP)

    def default_port(self) -> int:
        return 27015

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_core_keeper_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_core_keeper_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("port", "Game port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "10", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("world_seed", "World seed", "text", "0", width=100),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to gamesettings.json — world/mode changes need a fresh save.",
            "Forward UDP game port (default 27015).",
        ]


class SpaceEngineersAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "space_engineers"
    display_name = "Space Engineers"
    icon = "🛸"
    description = "Space Engineers dedicated server (Steam App ID 298420)."
    steam_app_id = "298420"
    executable_win = "DedicatedServer64.exe"
    executable_linux = "DedicatedServer64"
    _config_keys = set(_SE_XML_MAP)

    def default_port(self) -> int:
        return 27016

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(
            server_dir,
            self.executable_win,
            self.executable_linux,
            "SpaceEngineersDedicated.exe",
        )

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(
            server_dir,
            self.steam_app_id_for(config),
            self.executable_win,
            self.executable_linux,
            "SpaceEngineersDedicated.exe",
        )

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_space_engineers_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_space_engineers_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Space Engineers Server", width=180),
            ConfigField("max_players", "Max players", "text", "16", width=80),
            ConfigField("port", "Port (display)", "text", "27016", width=100),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Session name/max players sync to SpaceEngineers-Dedicated.cfg in the server folder.",
            "Use Extra args or edit the cfg for mods, autosave, and port overrides.",
            "Forward UDP 27016 (and +1 for Steam).",
        ]


class ScumAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "scum"
    display_name = "SCUM"
    icon = "🏝️"
    description = "SCUM dedicated server (Steam App ID 513710)."
    steam_app_id = "513710"
    executable_win = "SCUMServer.exe"
    executable_linux = "SCUMServer"
    _config_keys = set(_SCUM_INI_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_scum_settings(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_scum_settings(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "SCUM Server", width=160),
            ConfigField("port", "Port (display)", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "64", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root), "-log"]
        port = str(config.get("port", self.default_port()))
        args.append(f"-Port={port}")
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            f"Settings sync to SCUM/Saved/Config/{sub}/ServerSettings.ini.",
            "Forward UDP 7777–7779 and TCP 7777 per official SCUM port list.",
        ]


class EcoAdapter(SteamDedicatedAdapter):
    game_type = "eco"
    display_name = "Eco"
    icon = "🌎"
    description = "Eco dedicated server (Steam App ID 739590)."
    steam_app_id = "739590"
    executable_win = "EcoServer.exe"
    executable_linux = "EcoServer"

    def default_port(self) -> int:
        return 3000

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Eco Server", width=160),
            ConfigField("port", "Port (display)", "text", "3000", width=100),
            ConfigField("max_players", "Max players", "text", "100", width=80),
            ConfigField("server_description", "Description", "text", "", width=200),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        name = str(config.get("server_name", "Eco Server")).replace('"', '\\"')
        desc = str(config.get("server_description", "")).replace('"', '\\"')
        args = [
            _relative_or_absolute_arg(exe, root),
            f'-serverName="{name}"',
            f"-maxUsers={config.get('max_players', '100')}",
        ]
        if desc:
            args.append(f'-description="{desc}"')
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Name and player limit are passed via -serverName / -maxUsers on start.",
            "World and simulation config live under Configs/ — edit after first run.",
            "Forward TCP/UDP 3000 (game) and 3001 (web API).",
        ]


class NecesseAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "necesse"
    display_name = "Necesse"
    icon = "🏰"
    description = "Necesse dedicated server (Steam App ID 1169370)."
    steam_app_id = "1169370"
    executable_win = "NecesseServer.exe"
    executable_linux = "NecesseServer"
    _config_keys = set(_NECESSE_MAP)

    def default_port(self) -> int:
        return 14159

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_necesses_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_necesses_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("world_name", "World name", "text", "world", width=120),
            ConfigField("port", "Port", "text", "14159", width=100),
            ConfigField("max_players", "Max players", "text", "10", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        world = str(config.get("world_name", "world"))
        args = [
            _relative_or_absolute_arg(exe, root),
            "-world", world,
            "-port", str(config.get("port", self.default_port())),
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to Settings/serverSettings.json.",
            "Forward UDP 14159 (and TCP for query if enabled).",
        ]


class RaftAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "raft"
    display_name = "Raft"
    icon = "🛶"
    description = "Raft dedicated server (Steam App ID 1692230)."
    steam_app_id = "1692230"
    executable_win = "RaftDedicatedServer.exe"
    executable_linux = "RaftDedicatedServer"
    _config_keys = set(_RAFT_INI_MAP)

    def default_port(self) -> int:
        return 27015

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_raft_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_raft_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Raft Server", width=160),
            ConfigField("port", "Port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "4", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to server.cfg in the server folder.",
            "Forward UDP 27015.",
        ]


class IcarusAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "icarus"
    display_name = "Icarus"
    icon = "🚀"
    description = "Icarus dedicated server (Steam App ID 2089300)."
    steam_app_id = "2089300"
    executable_win = "IcarusServer.exe"
    executable_linux = "IcarusServer"
    _config_keys = set(_ICARUS_MAP)

    def default_port(self) -> int:
        return 17777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_icarus_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_icarus_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Session name", "text", "Icarus Server", width=160),
            ConfigField("port", "Port (display)", "text", "17777", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root), "-log"]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to DedicatedServerSettings.json.",
            "Forward UDP 17777 (and related ports per official list).",
        ]


class BarotraumaAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "barotrauma"
    display_name = "Barotrauma"
    icon = "🤿"
    description = "Barotrauma dedicated server (Steam App ID 1021770)."
    steam_app_id = "1021770"
    executable_win = "DedicatedServer.exe"
    executable_linux = "DedicatedServer"
    _config_keys = set(_BAROTRAUMA_ATTR_MAP)

    def default_port(self) -> int:
        return 27015

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_barotrauma_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_barotrauma_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Barotrauma Server", width=160),
            ConfigField("port", "Port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "10", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to ServerSettings.xml — edit submarines/missions in the same file.",
            "Forward UDP/TCP 27015.",
        ]


class UnturnedAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "unturned"
    display_name = "Unturned"
    icon = "🚗"
    description = "Unturned dedicated server (Steam App ID 1110390)."
    steam_app_id = "1110390"
    executable_win = "Unturned.exe"
    executable_linux = "Unturned_Headless.x86_64"
    _config_keys = set(_UNTURNED_MAP)

    def default_port(self) -> int:
        return 27015

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(
            server_dir,
            self.executable_win,
            self.executable_linux,
            "Unturned_Headless.x86_64",
        )

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(
            server_dir,
            self.steam_app_id_for(config),
            self.executable_win,
            self.executable_linux,
            "Unturned_Headless.x86_64",
        )

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_unturned_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_unturned_config(server_dir, updates)

    def apply_config(self, server_dir: Path, config: dict) -> None:
        updates = {k: str(v) for k, v in config.items() if k in _UNTURNED_MAP}
        updates["server_folder"] = str(config.get("server_folder", "Default"))
        if updates:
            write_unturned_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_folder", "Server folder", "text", "Default", width=120),
            ConfigField("server_name", "Server name", "text", "Unturned Server", width=160),
            ConfigField("port", "Port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "24", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        folder = str(config.get("server_folder", "Default")).strip() or "Default"
        args = [
            _relative_or_absolute_arg(exe, root),
            "-nographics", "-batchmode",
            f"+InternetServer/{folder}",
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to Servers/<folder>/Server/Config.json.",
            "Server folder must match the +InternetServer/ name used on launch.",
            "Forward UDP 27015 (and 27016 for Steam query).",
        ]


class EmpyrionAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "empyrion"
    display_name = "Empyrion"
    icon = "🪐"
    description = "Empyrion — Galactic Survival dedicated server (Steam App ID 530870)."
    steam_app_id = "530870"
    executable_win = "EmpyrionDedicated.exe"
    executable_linux = "EmpyrionDedicated"
    _config_keys = set(_EMPYRION_YAML_MAP)

    def default_port(self) -> int:
        return 30000

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_empyrion_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_empyrion_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Empyrion Server", width=160),
            ConfigField("port", "Port (display)", "text", "30000", width=100),
            ConfigField("max_players", "Max players", "text", "32", width=80),
            ConfigField("scenario", "Scenario", "text", "Default Multiplayer", width=160),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to dedicated.yaml (ServerConfig section).",
            "Forward UDP 30000–30004 per official Empyrion port list.",
        ]


class AvorionAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "avorion"
    display_name = "Avorion"
    icon = "🌌"
    description = "Avorion dedicated server (Steam App ID 565060)."
    steam_app_id = "565060"
    executable_win = "AvorionServer.exe"
    executable_linux = "AvorionServer"
    _config_keys = set(_AVORION_GAME_MAP)

    def default_port(self) -> int:
        return 27000

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_avorion_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_avorion_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Galaxy name", "text", "Avorion Server", width=160),
            ConfigField("port", "Port (display)", "text", "27000", width=100),
            ConfigField("max_players", "Max players", "text", "20", width=80),
            ConfigField("description", "Description", "text", "", width=200),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Galaxy name/max players sync to server.ini [Game] section.",
            "Forward UDP 27000–27003 (and TCP 27000).",
        ]


class SquadAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "squad"
    display_name = "Squad"
    icon = "🎖️"
    description = "Squad dedicated server (Steam App ID 736220)."
    steam_app_id = "736220"
    executable_win = "SquadGameServer.exe"
    executable_linux = "SquadGameServer"
    _game_folder = "SquadGame"
    _config_keys = set(_OWI_CFG_MAP)

    def default_port(self) -> int:
        return 7787

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_owi_server_cfg(server_dir, self._game_folder)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_owi_server_cfg(server_dir, self._game_folder, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Squad Server", width=160),
            ConfigField("port", "Port", "text", "7787", width=100),
            ConfigField("max_players", "Max players", "text", "100", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        port = str(config.get("port", self.default_port()))
        args = [_relative_or_absolute_arg(exe, root), f"-Port={port}", "-log"]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            f"Settings sync to SquadGame/ServerConfig/Server.cfg (or Saved/Config/{sub}/).",
            "Forward UDP 7787–7789 and TCP 21114 (RCON if enabled).",
        ]


class HellLetLooseAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "hell_let_loose"
    display_name = "Hell Let Loose"
    icon = "💥"
    description = "Hell Let Loose dedicated server (Steam App ID 686810)."
    steam_app_id = "686810"
    executable_win = "HLLServer.exe"
    executable_linux = "HLLServer"
    _game_folder = "HLL"
    _config_keys = set(_OWI_CFG_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_owi_server_cfg(server_dir, self._game_folder)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_owi_server_cfg(server_dir, self._game_folder, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "HLL Server", width=160),
            ConfigField("port", "Port", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "100", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root), f"-Port={config.get('port', '7777')}"]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to HLL/ServerConfig/Server.cfg when present.",
            "Forward UDP 7777–7778 and TCP 27015 (query).",
        ]


class PostScriptumAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "post_scriptum"
    display_name = "Post Scriptum"
    icon = "🪖"
    description = "Post Scriptum dedicated server (Steam App ID 746060)."
    steam_app_id = "746060"
    executable_win = "PostScriptumServer.exe"
    executable_linux = "PostScriptumServer"
    _game_folder = "PostScriptumGame"
    _config_keys = set(_OWI_CFG_MAP)

    def default_port(self) -> int:
        return 7787

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_owi_server_cfg(server_dir, self._game_folder)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_owi_server_cfg(server_dir, self._game_folder, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Post Scriptum Server", width=160),
            ConfigField("port", "Port", "text", "7787", width=100),
            ConfigField("max_players", "Max players", "text", "100", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root), f"-Port={config.get('port', '7787')}", "-log"]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Squad-engine Server.cfg sync under PostScriptumGame/ServerConfig/.",
            "Forward UDP 7787–7789 (same family as Squad).",
        ]


class AbioticFactorAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "abiotic_factor"
    display_name = "Abiotic Factor"
    icon = "🧪"
    description = "Abiotic Factor dedicated server (Steam App ID 2857200)."
    steam_app_id = "2857200"
    executable_win = "AbioticFactorServer.exe"
    executable_linux = "AbioticFactorServer"
    _config_keys = set(_ABIOTIC_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_abiotic_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_abiotic_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Abiotic Factor Server", width=160),
            ConfigField("port", "Port (display)", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "6", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to ServerConfig.json in the server folder.",
            "Forward UDP 7777 per official port list.",
        ]


class SunkenlandAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "sunkenland"
    display_name = "Sunkenland"
    icon = "🌊"
    description = "Sunkenland dedicated server (Steam App ID 2467070)."
    steam_app_id = "2467070"
    executable_win = "SunkenlandDedicated.exe"
    executable_linux = "SunkenlandDedicated"
    _config_keys = set(_SUNKENLAND_MAP)

    def default_port(self) -> int:
        return 27015

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_sunkenland_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_sunkenland_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Sunkenland Server", width=160),
            ConfigField("port", "Game port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to DedicatedServerConfig.json.",
            "Forward UDP 27015 (and query port if listed in config).",
        ]


class AskaAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "aska"
    display_name = "ASKA"
    icon = "⚒️"
    description = "ASKA dedicated server (Steam App ID 2439330)."
    steam_app_id = "2439330"
    executable_win = "ASKAServer.exe"
    executable_linux = "ASKAServer"
    _config_keys = set(_ASKA_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_aska_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_aska_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "ASKA Server", width=160),
            ConfigField("port", "Port (display)", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "4", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to ServerConfig.json in the server folder.",
            "Forward UDP 7777 per official ASKA server docs.",
        ]


class InsurgencySandstormAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "insurgency_sandstorm"
    display_name = "Insurgency: Sandstorm"
    icon = "🎯"
    description = "Insurgency: Sandstorm dedicated server (Steam App ID 581330)."
    steam_app_id = "581330"
    executable_win = "InsurgencyServer.exe"
    executable_linux = "InsurgencyServer"
    _game_folders = ("Insurgency", "InsurgencySandstorm")
    _config_keys = set(_OWI_CFG_MAP) | {"scenario"}

    def default_port(self) -> int:
        return 27102

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_owi_server_cfg_folders(server_dir, *self._game_folders)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_owi_server_cfg_folders(server_dir, self._game_folders, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Sandstorm Server", width=160),
            ConfigField("scenario", "Scenario", "text", "Scenario_Crossing_Checkpoint_Insurgents", width=220),
            ConfigField("port", "Port", "text", "27102", width=100),
            ConfigField("max_players", "Max players", "text", "28", width=80),
            ConfigField("server_password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        scenario = str(config.get("scenario", "Scenario_Crossing_Checkpoint_Insurgents")).strip()
        port = str(config.get("port", self.default_port()))
        args = [_relative_or_absolute_arg(exe, root), scenario, f"-Port={port}", "-log"]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            "Settings sync to Insurgency/ServerConfig/Server.cfg (or Saved/Config/).",
            "Forward UDP 27102 and query port 27131.",
        ]


class MordhauAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "mordhau"
    display_name = "Mordhau"
    icon = "🗡️"
    description = "Mordhau dedicated server (Steam App ID 629800)."
    steam_app_id = "629800"
    executable_win = "MordhauServer-Win64-Shipping.exe"
    executable_linux = "MordhauServer"
    _config_keys = set(_MORDHAU_MAP) | {"map", "port", "query_port"}

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_mordhau_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_mordhau_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Mordhau Server", width=160),
            ConfigField("map", "Map", "text", "FFA_Example", width=140),
            ConfigField("port", "Port", "text", "7777", width=100),
            ConfigField("query_port", "Query port", "text", "27015", width=100),
            ConfigField("max_players", "Max players", "text", "24", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        game_map = str(config.get("map", "FFA_Example")).strip() or "FFA_Example"
        port = str(config.get("port", self.default_port()))
        query = str(config.get("query_port", "27015")).strip() or "27015"
        args = [_relative_or_absolute_arg(exe, root), game_map, f"-Port={port}", f"-QueryPort={query}"]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            f"Settings sync to Mordhau/Saved/Config/{sub}/Game.ini.",
            "Forward UDP 7777 and query port 27015.",
        ]


class StarboundAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "starbound"
    display_name = "Starbound"
    icon = "⭐"
    description = "Starbound dedicated server (Steam App ID 211820)."
    steam_app_id = "211820"
    executable_win = "starbound_server.exe"
    executable_linux = "starbound_server"
    _config_keys = set(_STARBOUND_MAP)

    def default_port(self) -> int:
        return 21025

    def port_protocol(self) -> str:
        return "TCP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_starbound_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_starbound_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Starbound Server", width=160),
            ConfigField("port", "Game port", "text", "21025", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to storage/starbound_server.config.",
            "Forward TCP 21025.",
        ]


class BannerlordAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "bannerlord"
    display_name = "Mount & Blade II: Bannerlord"
    icon = "⚔️"
    description = "Mount & Blade II: Bannerlord dedicated server (Steam App ID 1863440)."
    steam_app_id = "1863440"
    executable_win = "DedicatedCustomServer.Starter.exe"
    executable_linux = "DedicatedCustomServer.Starter"
    _config_keys = set(_BANNERLORD_LINE_MAP)

    def default_port(self) -> int:
        return 7210

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_bannerlord_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_bannerlord_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Bannerlord Server", width=160),
            ConfigField("map", "Map", "text", "Multiplayer_TDM_001", width=160),
            ConfigField("max_players", "Max players", "text", "100", width=80),
            ConfigField("password", "Game password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        cfg_path = bannerlord_config_path(root)
        try:
            cfg_arg = str(cfg_path.relative_to(root))
        except ValueError:
            cfg_arg = str(cfg_path)
        args = [_relative_or_absolute_arg(exe, root), cfg_arg]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to _config.txt in the server folder.",
            "Forward UDP 7210 (default Bannerlord dedicated port).",
        ]


class SmallandAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "smalland"
    display_name = "Smalland"
    icon = "🐜"
    description = "Smalland dedicated server (Steam App ID 2237810)."
    steam_app_id = "2237810"
    executable_win = "SmallandServer.exe"
    executable_linux = "SmallandServer"
    _json_names = ("ServerConfig.json", "DedicatedServerConfig.json")
    _config_keys = set(_ASKA_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return _survival_json_config(server_dir, *self._json_names)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        _survival_json_write(server_dir, updates, *self._json_names)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Smalland Server", width=160),
            ConfigField("port", "Port (display)", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "10", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to ServerConfig.json in the server folder.",
            "Forward UDP 7777 per official Smalland server docs.",
        ]


class HumanitzAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "humanitz"
    display_name = "HumanitZ"
    icon = "🧟"
    description = "HumanitZ dedicated server (Steam App ID 2511920)."
    steam_app_id = "2511920"
    executable_win = "HumanitZServer.exe"
    executable_linux = "HumanitZServer"
    _json_names = ("DedicatedServerConfig.json", "ServerConfig.json")
    _config_keys = set(_ASKA_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return _survival_json_config(server_dir, *self._json_names)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        _survival_json_write(server_dir, updates, *self._json_names)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "HumanitZ Server", width=160),
            ConfigField("port", "Port (display)", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "16", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to DedicatedServerConfig.json in the server folder.",
            "Forward UDP 7777 per official HumanitZ server docs.",
        ]


class OnceHumanAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "once_human"
    display_name = "Once Human"
    icon = "☢️"
    description = "Once Human dedicated server (Steam App ID 3077390)."
    steam_app_id = "3077390"
    executable_win = "OnceHumanServer.exe"
    executable_linux = "OnceHumanServer"
    _json_names = ("DedicatedServerConfig.json", "ServerConfig.json")
    _config_keys = set(_ASKA_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return _survival_json_config(server_dir, *self._json_names)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        _survival_json_write(server_dir, updates, *self._json_names)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Once Human Server", width=160),
            ConfigField("port", "Port (display)", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to DedicatedServerConfig.json in the server folder.",
            "Forward UDP 7777 per official Once Human server docs.",
        ]


class HoldfastAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "holdfast"
    display_name = "Holdfast: Nations At War"
    icon = "🏴"
    description = "Holdfast: Nations At War dedicated server (Steam App ID 732610)."
    steam_app_id = "732610"
    executable_win = "HoldfastDedicatedServer.exe"
    executable_linux = "HoldfastDedicatedServer"
    _config_keys = set(_HOLDFAST_MAP)

    def default_port(self) -> int:
        return 20100

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_holdfast_config(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_holdfast_config(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Holdfast Server", width=160),
            ConfigField("port", "Game port", "text", "20100", width=100),
            ConfigField("max_players", "Max players", "text", "150", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        cfg_path = holdfast_config_path(root)
        try:
            cfg_arg = str(cfg_path.relative_to(root))
        except ValueError:
            cfg_arg = cfg_path.name
        port = str(config.get("port", self.default_port()))
        args = [
            _relative_or_absolute_arg(exe, root),
            "-startserver", "-batchmode", "-nographics",
            "-serverConfigFilePath", cfg_arg,
            "-p", port,
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Settings sync to configs/serverconfig_default.txt.",
            "Forward UDP 20100 and Steam query port 27000.",
        ]


class DontStarveTogetherAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "dst"
    display_name = "Don't Starve Together"
    icon = "🔥"
    description = "Don't Starve Together dedicated server (Steam App ID 343050)."
    steam_app_id = "343050"
    executable_win = "dontstarve_dedicated_server_nullrenderer.exe"
    executable_linux = "dontstarve_dedicated_server_nullrenderer"
    _config_keys = set(_DST_INI_FIELDS) | {"cluster_name"}

    def default_port(self) -> int:
        return 10999

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        klei = Path.home() / "Documents" / "Klei" / "DoNotStarveTogether"
        if klei.is_dir():
            for cluster_dir in sorted(klei.iterdir()):
                if cluster_dir.is_dir() and (cluster_dir / "cluster.ini").is_file():
                    out = read_dst_cluster_config(cluster_dir.name)
                    out["cluster_name"] = cluster_dir.name
                    return out
        return read_dst_cluster_config("MyDediCluster")

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        cluster = str(updates.get("cluster_name", "MyDediCluster")).strip() or "MyDediCluster"
        ini_updates = {k: v for k, v in updates.items() if k in _DST_INI_FIELDS}
        if ini_updates:
            write_dst_cluster_config(cluster, ini_updates)

    def apply_config(self, server_dir: Path, config: dict) -> None:
        cluster = str(config.get("cluster_name", "MyDediCluster")).strip() or "MyDediCluster"
        ini_updates = {k: str(v) for k, v in config.items() if k in _DST_INI_FIELDS}
        if ini_updates:
            write_dst_cluster_config(cluster, ini_updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("cluster_name", "Cluster name", "text", "MyDediCluster", width=140),
            ConfigField("shard", "Shard", "menu", "Master", ["Master", "Caves"], width=100),
            ConfigField("port", "Port (display)", "text", "10999", width=100),
            ConfigField("max_players", "Max players", "text", "6", width=80),
            ConfigField("cluster_password", "Cluster password", "text", "", width=120),
            ConfigField("cluster_description", "Description", "text", "", width=180),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        cluster = str(config.get("cluster_name", "MyDediCluster"))
        shard = str(config.get("shard", "Master"))
        args = [
            _relative_or_absolute_arg(exe, root),
            "-cluster", cluster,
            "-shard", shard,
        ]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        klei = Path.home() / "Documents" / "Klei" / "DoNotStarveTogether"
        return super().setup_panel_hints() + [
            f"Cluster settings sync to {klei}/<cluster>/cluster.ini.",
            "Place cluster_token.txt in the cluster folder (from Klei account).",
            "Caves require a second server entry with shard Caves.",
        ]


class ConanExilesAdapter(_FileConfigMixin, SteamDedicatedAdapter):
    game_type = "conan_exiles"
    display_name = "Conan Exiles"
    icon = "⚔️"
    description = "Conan Exiles dedicated server (Steam App ID 443030)."
    steam_app_id = "443030"
    executable_win = "ConanSandboxServer.exe"
    executable_linux = "ConanSandboxServer"
    _config_keys = set(_CONAN_INI_MAP)

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, self.executable_win, self.executable_linux)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), self.executable_win, self.executable_linux)

    def _read_file_config(self, server_dir: Path) -> dict[str, str]:
        return read_conan_settings(server_dir)

    def _write_file_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        write_conan_settings(server_dir, updates)

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Conan Server", width=160),
            ConfigField("port", "Port", "text", "7777", width=100),
            ConfigField("query_port", "Query port", "text", "27016", width=100),
            ConfigField("max_players", "Max players", "text", "40", width=80),
            ConfigField("server_password", "Join password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        self.apply_config(server_dir, config)
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [
            _relative_or_absolute_arg(exe, root),
            "-log",
            f"-Port={config.get('port', '7777')}",
            f"-QueryPort={config.get('query_port', '27016')}",
            f"-ServerName={config.get('server_name', 'Conan Server')}",
            f"-MaxPlayers={config.get('max_players', '40')}",
        ]
        admin = str(config.get("admin_password", "")).strip()
        if admin:
            args.append(f"-ServerAdminPassword={admin}")
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        sub = _ue_config_subdir()
        return super().setup_panel_hints() + [
            f"Settings sync to ConanSandbox/Saved/Config/{sub}/ServerSettings.ini.",
            "Forward UDP 7777–7778 and TCP 27016.",
        ]


class SoulmaskAdapter(SteamDedicatedAdapter):
    game_type = "soulmask"
    display_name = "Soulmask"
    icon = "🎭"
    description = "Soulmask dedicated server (Steam App ID 3017310)."
    steam_app_id = "3017310"
    executable_win = "WDS.exe"
    executable_linux = "WDS"

    def default_port(self) -> int:
        return 8777

    def port_protocol(self) -> str:
        return "UDP"

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(
            server_dir,
            self.executable_win,
            self.executable_linux,
            "SoulmaskServer.exe",
            "SoulmaskServer.sh",
        )

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(
            server_dir,
            self.steam_app_id_for(config),
            self.executable_win,
            self.executable_linux,
            "SoulmaskServer.exe",
        )

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "Soulmask Server", width=160),
            ConfigField("port", "Port (display)", "text", "8777", width=100),
            ConfigField("max_players", "Max players", "text", "50", width=80),
            ConfigField("password", "Password", "text", "", width=120),
            ConfigField("admin_password", "Admin password", "text", "", width=120),
            ConfigField("extra_args", "Extra args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        name = str(config.get("server_name", "Soulmask Server")).replace('"', '\\"')
        args = [
            _relative_or_absolute_arg(exe, root),
            f'-SteamServerName="{name}"',
            f"-MaxPlayers={config.get('max_players', '50')}",
        ]
        password = str(config.get("password", "")).strip()
        if password:
            args.append(f'-SteamServerPassword="{password.replace(chr(34), "")}"')
        admin = str(config.get("admin_password", "")).strip()
        if admin:
            args.append(f'-AdminPassword="{admin.replace(chr(34), "")}"')
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Name, slots, and passwords are passed via WDS launch flags on start.",
            "Advanced tuning in WS/Saved/Config/ — see official Soulmask server docs.",
            "Forward UDP 8777 (and related ports per official port list).",
        ]


from dataclasses import dataclass


@dataclass(frozen=True)
class SteamGameSpec:
    game_type: str
    display_name: str
    icon: str
    steam_app_id: str
    executable_win: str
    executable_linux: str = ""
    default_port: int = 27015
    port_protocol: str = "UDP"
    exe_alts: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()


class GenericSteamAdapter(SteamDedicatedAdapter):
    """Lightweight adapter for SteamCMD games with standard exe + extra_args startup."""

    def __init__(self, spec: SteamGameSpec):
        self._spec = spec
        self.game_type = spec.game_type
        self.display_name = spec.display_name
        self.icon = spec.icon
        self.description = f"{spec.display_name} dedicated server (Steam App ID {spec.steam_app_id})."
        self.steam_app_id = spec.steam_app_id
        self.executable_win = spec.executable_win
        self.executable_linux = spec.executable_linux or spec.executable_win.replace(".exe", "")
        self.default_stop_command = ""

    def default_port(self) -> int:
        return self._spec.default_port

    def port_protocol(self) -> str:
        return self._spec.port_protocol

    def _exe_names(self) -> tuple[str, ...]:
        names = [self.executable_win, self.executable_linux, *self._spec.exe_alts]
        return tuple(dict.fromkeys(n for n in names if n))

    def _exe(self, server_dir: Path) -> Path | None:
        return find_steam_server_binary(server_dir, *self._exe_names())

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self._exe(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        return _steam_install_worker(server_dir, self.steam_app_id_for(config), *self._exe_names())

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        root = server_dir.resolve()
        exe = self._exe(root) or root / self.executable_name()
        args = [_relative_or_absolute_arg(exe, root)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {"cwd": str(root)}

    def setup_panel_hints(self) -> list[str]:
        hints = list(super().setup_panel_hints()) + list(self._spec.hints)
        return hints


def _g(
    game_type: str,
    display_name: str,
    icon: str,
    app_id: str,
    exe_win: str,
    *,
    exe_linux: str = "",
    port: int = 27015,
    protocol: str = "UDP",
    exe_alts: tuple[str, ...] = (),
    hints: tuple[str, ...] = (),
) -> GenericSteamAdapter:
    return GenericSteamAdapter(
        SteamGameSpec(
            game_type=game_type,
            display_name=display_name,
            icon=icon,
            steam_app_id=app_id,
            executable_win=exe_win,
            executable_linux=exe_linux,
            default_port=port,
            port_protocol=protocol,
            exe_alts=exe_alts,
            hints=hints,
        )
    )


# Extra SteamCMD titles — baseline install/start (polish individually later).
GENERIC_STEAM_ADAPTERS: list[GenericSteamAdapter] = [
    _g("tf2", "Team Fortress 2", "🎩", "232250", "srcds.exe", exe_linux="srcds_run", port=27015),
    _g("killing_floor_2", "Killing Floor 2", "💀", "232130", "KFGame.exe", port=7777, protocol="UDP"),
    _g("staxel", "Staxel", "🌾", "724470", "Staxel.Server.exe", port=38465),
    _g("stationeers", "Stationeers", "🧑‍🚀", "691690", "rocket2stationeers.exe", port=27016),
    _g("miscreated", "Miscreated", "🏚️", "514300", "MiscreatedServer.exe", port=64090, protocol="UDP"),
    _g("hurtworld", "Hurtworld", "🏜️", "405100", "HurtworldDedicated.exe", port=12871, protocol="UDP"),
    _g("life_is_feudal", "Life is Feudal", "🏰", "302520", "yo_cm_server.exe", port=28000, protocol="UDP"),
    _g("foundry", "Foundry", "🏭", "2915550", "FoundryDedicated.exe", port=27015, protocol="UDP"),
    _g("night_of_the_dead", "Night of the Dead", "🌙", "1371580", "NOTDServer.exe", port=7777, protocol="UDP"),
]
