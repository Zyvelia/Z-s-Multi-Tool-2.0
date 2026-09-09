"""
Builtin agent actions — the first set of things AI Chat can actually do.

Keep handlers off the Tk thread. Import Game Server Manager via
importlib — that package folder has spaces in the name.
"""

from __future__ import annotations

import importlib

from core.services.agent_registry import get_registry, register_action

_GSM_API = None


def _gsm():
    global _GSM_API
    if _GSM_API is None:
        _GSM_API = importlib.import_module(
            "modules.Gaming.Game Server Manager.agent_api"
        )
    return _GSM_API

_REGISTERED = False


def ensure_registered(plugin_manager=None) -> None:
    global _REGISTERED
    registry = get_registry()
    if plugin_manager is not None:
        registry.plugin_manager = plugin_manager
    if _REGISTERED:
        return
    _REGISTERED = True
    _register_app_tools()
    _register_server_tools()
    _register_hub_tools()
    _register_youtube_tools()
    _register_notes_tools()
    _register_message_tools()
    _register_clipboard_tools()
    _register_system_tools()
    _register_build_tools()
    _register_media_tools()
    _register_console_tools()


def _obj(**properties) -> dict:
    props = {}
    required = []
    for key, spec in properties.items():
        spec = dict(spec)
        if spec.pop("_required", False):
            required.append(key)
        props[key] = spec
    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


def _register_app_tools() -> None:
    register_action(
        "list_modules",
        "List catalog tools in this app (name, category, description).",
        _list_modules,
    )
    register_action(
        "list_agent_actions",
        "List actions this agent can run right now.",
        _list_agent_actions,
    )


def _list_modules(_args: dict) -> dict:
    pm = get_registry().plugin_manager
    if pm is None:
        return {"ok": False, "error": "Plugin catalog is not available in this session."}
    tools = []
    for tool in pm.get_tools():
        tools.append({
            "name": tool.get("name", ""),
            "category": tool.get("category", ""),
            "desc": tool.get("desc", ""),
        })
    return {"count": len(tools), "modules": tools}


def _list_agent_actions(_args: dict) -> dict:
    actions = []
    for action in get_registry().list_actions():
        actions.append({
            "name": action.name,
            "description": action.description,
            "risk": action.risk,
        })
    return {"count": len(actions), "actions": actions}


def _register_server_tools() -> None:
    query = {
        "query": {
            "type": "string",
            "description": "Server name, id, or game type substring (e.g. Palworld).",
            "_required": True,
        }
    }
    register_action(
        "list_game_servers",
        "List saved dedicated servers (name, game, folder, running).",
        _list_game_servers,
    )
    register_action(
        "game_server_status",
        "Status for one saved game server: running, players, folder.",
        _game_server_status,
        _obj(**query),
    )
    register_action(
        "start_game_server",
        "Start a saved dedicated server by name or id.",
        _start_game_server,
        _obj(**query),
        risk="write",
    )
    register_action(
        "stop_game_server",
        "Gracefully stop a running dedicated server by name or id.",
        _stop_game_server,
        _obj(**query),
        risk="write",
    )
    register_action(
        "backup_game_server",
        "Zip the server folder into its _backups directory (skips existing backups).",
        _backup_game_server,
        _obj(**query),
        risk="write",
    )
    register_action(
        "wait_until_game_server_ready",
        "Wait until a running server logs ready or its TCP port accepts connections. "
        "Does not start the server — call start_game_server first.",
        _wait_until_ready,
        _obj(
            query={
                "type": "string",
                "description": "Server name, id, or game type substring.",
                "_required": True,
            },
            timeout_seconds={
                "type": "number",
                "description": "How long to wait (default 180, max 600).",
            },
        ),
    )


def _list_game_servers(_args: dict) -> dict:
    return {"servers": _gsm().load_servers_safe()}


def _game_server_status(args: dict) -> dict:
    srv, err = _gsm().find_server(args.get("query", ""))
    if err:
        return {"ok": False, "error": err}
    return _gsm().status_payload(srv)


def _start_game_server(args: dict) -> dict:
    srv, err = _gsm().find_server(args.get("query", ""))
    if err:
        return {"ok": False, "error": err}
    return _gsm().start_server(srv)


def _stop_game_server(args: dict) -> dict:
    srv, err = _gsm().find_server(args.get("query", ""))
    if err:
        return {"ok": False, "error": err}
    return _gsm().stop_server(srv)


def _backup_game_server(args: dict) -> dict:
    srv, err = _gsm().find_server(args.get("query", ""))
    if err:
        return {"ok": False, "error": err}
    return _gsm().backup_server(srv)


def _wait_until_ready(args: dict) -> dict:
    srv, err = _gsm().find_server(args.get("query", ""))
    if err:
        return {"ok": False, "error": err}
    return _gsm().wait_until_ready(srv, args.get("timeout_seconds") or 180)


def _hub():
    return importlib.import_module("modules.Network.remote_hub.agent_api")


def _yt():
    return importlib.import_module("modules.Media.YouTube Downloader.agent_api")


def _register_hub_tools() -> None:
    register_action(
        "hub_status",
        "Remote Hub / Tailscale status: installed, hostname, hub URL, which apps are live.",
        lambda _args: _hub().status(),
    )
    register_action(
        "hub_go_live",
        "Bring Remote Hub live: start loopback apps and Tailscale serve so your phone can reach them.",
        lambda _args: _hub().go_live(),
        risk="write",
    )
    register_action(
        "hub_go_offline",
        "Take Remote Hub offline (stops Tailscale serve; local servers stay running).",
        lambda _args: _hub().go_offline(),
        risk="write",
    )


def _register_youtube_tools() -> None:
    register_action(
        "queue_youtube_download",
        "Queue a YouTube URL to download as mp3 or mp4 using the app's downloader settings.",
        _queue_youtube,
        _obj(
            url={"type": "string", "description": "YouTube video or playlist URL.", "_required": True},
            format={"type": "string", "description": "mp3 or mp4 (default from settings)."},
            type={"type": "string", "description": "video or playlist."},
        ),
        risk="write",
    )
    register_action(
        "youtube_download_status",
        "Check one download job by id, or list recent jobs.",
        _youtube_status,
        _obj(job_id={"type": "string", "description": "Job id from queue_youtube_download. Omit to list recent jobs."}),
    )
    register_action(
        "wait_for_youtube_download",
        "Wait until a queued YouTube download finishes or errors.",
        _wait_youtube,
        _obj(
            job_id={"type": "string", "description": "Job id from queue_youtube_download.", "_required": True},
            timeout_seconds={"type": "number", "description": "How long to wait (default 300, max 900)."},
        ),
    )


def _queue_youtube(args: dict) -> dict:
    return _yt().queue_download(
        args.get("url", ""),
        fmt=str(args.get("format") or ""),
        dl_type=str(args.get("type") or ""),
    )


def _youtube_status(args: dict) -> dict:
    return _yt().job_status(str(args.get("job_id") or ""))


def _wait_youtube(args: dict) -> dict:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return {"ok": False, "error": "job_id is required."}
    return _yt().wait_for_job(job_id, args.get("timeout_seconds") or 300)


def _register_notes_tools() -> None:
    register_action(
        "list_notes",
        "List note titles and ids.",
        _list_notes,
    )
    register_action(
        "search_notes",
        "Search notes by title, body, or link text.",
        _search_notes,
        _obj(query={"type": "string", "description": "Search text.", "_required": True}),
    )
    register_action(
        "create_note",
        "Create a new note.",
        _create_note,
        _obj(
            title={"type": "string", "description": "Note title.", "_required": True},
            body={"type": "string", "description": "Note body."},
        ),
        risk="write",
    )


def _list_notes(_args: dict) -> dict:
    from modules.Productivity.Notes import storage
    notes = []
    for note in storage.get_notes()[:40]:
        notes.append({
            "id": note.get("id"),
            "title": note.get("title"),
            "pinned": bool(note.get("pinned")),
            "updated_at": note.get("updated_at"),
        })
    return {"count": len(notes), "notes": notes}


def _search_notes(args: dict) -> dict:
    from modules.Productivity.Notes import storage
    hits = []
    for note in storage.search_notes(str(args.get("query", "")))[:20]:
        body = (note.get("body") or "")[:240]
        hits.append({
            "id": note.get("id"),
            "title": note.get("title"),
            "snippet": body,
        })
    return {"count": len(hits), "notes": hits}


def _create_note(args: dict) -> dict:
    from modules.Productivity.Notes import storage
    title = str(args.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "Title is required."}
    note = storage.create_note(title=title, body=str(args.get("body") or ""))
    return {"id": note["id"], "title": note["title"]}


def _register_message_tools() -> None:
    register_action(
        "send_message",
        "Send a chat message from this PC to paired phones (Messages module).",
        _send_message,
        _obj(text={"type": "string", "description": "Message text.", "_required": True}),
        risk="write",
    )
    register_action(
        "recent_messages",
        "Read recent Messages-module chat lines.",
        _recent_messages,
    )


def _send_message(args: dict) -> dict:
    from modules.Productivity.Messaging import storage
    text = str(args.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Message text is required."}
    message = storage.append_message("desktop", text)
    return {"id": message["id"], "sent_at": message["sent_at"]}


def _recent_messages(_args: dict) -> dict:
    from modules.Productivity.Messaging import storage
    rows = storage.get_messages_since(0)[-20:]
    return {
        "count": len(rows),
        "messages": [
            {
                "sender_id": m.get("sender_id"),
                "text": m.get("text"),
                "sent_at": m.get("sent_at"),
            }
            for m in rows
        ],
    }


def _register_clipboard_tools() -> None:
    register_action(
        "read_clipboard",
        "Read the current clipboard text on this PC.",
        _read_clipboard,
    )


def _read_clipboard(_args: dict) -> dict:
    try:
        import pyperclip
        text = pyperclip.paste() or ""
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Clipboard unavailable: {e}"}
    return {"text": text[:4000], "truncated": len(text) > 4000}


def _register_system_tools() -> None:
    register_action(
        "system_stats",
        "Current CPU, RAM, disk, and top processes on this PC.",
        _system_stats,
    )


def _system_stats(_args: dict) -> dict:
    import psutil
    vm = psutil.virtual_memory()
    disk = None
    try:
        disk = psutil.disk_usage("C:\\")
    except Exception:
        pass
    procs = []
    for proc in sorted(
        psutil.process_iter(["name", "cpu_percent", "memory_info"]),
        key=lambda p: getattr(p.info.get("memory_info"), "rss", 0) or 0,
        reverse=True,
    )[:8]:
        info = proc.info
        mem = info.get("memory_info")
        procs.append({
            "name": info.get("name"),
            "rss_mb": round((mem.rss / (1024 * 1024)), 1) if mem else 0,
        })
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": vm.percent,
        "ram_used_gb": round(vm.used / (1024 ** 3), 2),
        "ram_total_gb": round(vm.total / (1024 ** 3), 2),
        "disk_c_percent": disk.percent if disk else None,
        "top_processes": procs,
    }


def _register_build_tools() -> None:
    register_action(
        "build_project",
        "Generate a multi-file project on this PC (same as /build). Writes under AI_Projects. Does not run the code.",
        _build_project,
        _obj(prompt={"type": "string", "description": "What to build.", "_required": True}),
        risk="write",
    )
    register_action(
        "open_last_build",
        "Open the last /build project folder in File Explorer on this PC.",
        _open_last_build,
        risk="write",
    )


def _build_project(args: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt is required"}
    from pathlib import Path

    from . import session as ai_session
    from . import web_server as ai_web
    from .builder import AIProjectBuilder, BuildError

    client = ai_session.live_client()
    if client is None or not client.has_key():
        srv = ai_web.ChatWebServer()
        client, _src, err = srv._client()
        if client is None:
            return {"ok": False, "error": err or "Connect AI Chat first."}
    settings = _read_ai_settings()
    root = settings.get("projects_root") or str(Path(__file__).resolve().parents[2] / "AI_Projects")
    log: list[str] = []
    try:
        path = AIProjectBuilder(client, str(root)).build(prompt, log.append)
    except BuildError as e:
        return {"ok": False, "error": str(e), "log": log[-12:]}
    settings["last_project_dir"] = path
    _write_ai_settings(settings)
    return {"ok": True, "path": path, "log": log[-16:]}


def _open_last_build(_args: dict) -> dict:
    import os
    from pathlib import Path
    data = _read_ai_settings()
    path = str(data.get("last_project_dir") or "")
    if not path or not Path(path).is_dir():
        return {"ok": False, "error": "No last project. Build something first."}
    try:
        os.startfile(path)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": path}


def _read_ai_settings() -> dict:
    from pathlib import Path
    from core import paths
    file = Path(paths.data_path("ai_terminal", "settings.json"))
    try:
        import json
        data = json.loads(file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_ai_settings(data: dict) -> None:
    import json
    from pathlib import Path
    from core import paths
    file = Path(paths.data_path("ai_terminal", "settings.json"))
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _register_media_tools() -> None:
    register_action(
        "list_soundboard_clips",
        "List soundboard clip names on this PC.",
        _list_sounds,
    )
    register_action(
        "play_soundboard",
        "Play a soundboard clip by name on this PC's speakers.",
        _play_sound,
        _obj(name={"type": "string", "description": "Clip name or substring.", "_required": True}),
        risk="write",
    )
    register_action(
        "launch_hub_game",
        "Launch a scanned Gaming Hub game on this PC by name.",
        _launch_hub_game,
        _obj(name={"type": "string", "description": "Game name substring.", "_required": True}),
        risk="write",
    )


def _list_sounds(_args: dict) -> dict:
    ws = importlib.import_module("modules.Media.soundboard.web_server")
    server = ws.SoundboardWebServer()
    names = []
    for path in server.list_sounds():
        import os
        names.append(os.path.splitext(os.path.basename(path))[0])
    return {"sounds": names}


def _play_sound(args: dict) -> dict:
    social = importlib.import_module("modules.Network.Tailnet Social.web_server")
    return social._play_sound(str(args.get("name") or ""))


def _launch_hub_game(args: dict) -> dict:
    name = str(args.get("name") or "").strip().lower()
    if not name:
        return {"ok": False, "error": "name is required"}
    hub = importlib.import_module("modules.Gaming.Gaming Hub.game_scanner")
    launch = importlib.import_module("modules.Gaming.Gaming Hub.launcher")
    games = hub.GameScanner().load_cache()
    matches = [g for g in games if name in (g.name or "").lower()]
    if not matches:
        return {"ok": False, "error": f"No Hub game matching {name!r}."}
    if len(matches) > 1:
        return {"ok": False, "error": "Multiple matches: " + ", ".join(g.name for g in matches[:8])}
    launch.GameLauncher().launch(matches[0])
    return {"ok": True, "launched": matches[0].name}


def _register_console_tools() -> None:
    register_action(
        "send_game_server_console",
        "Send one console line to a running dedicated server (say, save, etc).",
        _send_console,
        _obj(
            query={"type": "string", "description": "Server name or id.", "_required": True},
            command={"type": "string", "description": "Console command.", "_required": True},
        ),
        risk="write",
    )


def _send_console(args: dict) -> dict:
    srv, err = _gsm().find_server(args.get("query", ""))
    if err:
        return {"ok": False, "error": err}
    return _gsm().send_console(srv, str(args.get("command") or ""))
