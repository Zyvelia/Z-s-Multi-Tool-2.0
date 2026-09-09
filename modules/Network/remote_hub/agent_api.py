"""GUI-free Remote Hub actions for the in-app agent."""

from __future__ import annotations

from core.services.agent_registry import get_registry

from .controller import HubController


def _page_manager():
    plugins = get_registry().plugin_manager
    app = getattr(plugins, "app", None) if plugins is not None else None
    return getattr(app, "page_manager", None)


def _controller() -> HubController:
    manager = _page_manager()
    if manager is None:
        raise RuntimeError("Remote Hub needs the running app (page manager).")
    return HubController(manager)


def status() -> dict:
    controller = _controller()
    ts, live = controller.get_status_sync()
    hostname = ts.get("hostname") or ""
    return {
        "installed": bool(ts.get("installed")),
        "running": bool(ts.get("running")),
        "hostname": hostname,
        "hub_url": f"https://{hostname}/" if hostname and ts.get("running") else "",
        "live_apps": live,
    }


def go_live() -> dict:
    controller = _controller()
    fatal, errors = controller.go_live_sync()
    if fatal:
        return {"ok": False, "error": fatal}
    info = status()
    info["ok"] = True
    info["warnings"] = errors or []
    return info


def go_offline() -> dict:
    controller = _controller()
    controller.go_offline_sync()
    return {"ok": True, "offline": True}
