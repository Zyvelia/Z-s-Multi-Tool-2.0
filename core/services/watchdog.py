"""
Crash watchdog for dedicated servers.

Polls the shared GSM process map. If a server dies without an expected
stop (UI/agent Stop), it logs a notification and can retry start a
limited number of times.
"""

from __future__ import annotations

import importlib
import threading
import time

from core.services import activity_log

_lock = threading.Lock()
_state: dict[str, dict] = {}
_started = False


def tick(settings) -> None:
    if not settings.get("watchdog_enabled"):
        return
    try:
        gsm = importlib.import_module("modules.Gaming.Game Server Manager.agent_api")
        runtime = importlib.import_module("modules.Gaming.Game Server Manager.runtime")
    except Exception:
        return

    max_retries = int(settings.get("watchdog_retries") or 0)
    now = time.time()

    for srv in gsm.load_servers_safe():
        sid = srv.get("id") or ""
        if not sid:
            continue
        running = bool(srv.get("running"))
        with _lock:
            prev = _state.get(sid, {"running": False, "retries": 0, "since": now})
            was_running = bool(prev.get("running"))
            retries = int(prev.get("retries") or 0)

        if running:
            with _lock:
                _state[sid] = {"running": True, "retries": 0, "since": now}
            continue

        if not was_running:
            with _lock:
                _state[sid] = {"running": False, "retries": retries, "since": prev.get("since", now)}
            continue

        expected = runtime.consume_expected_stop(sid)
        name = srv.get("name") or sid
        if expected:
            activity_log.add("notify", f"Stopped {name}", "Clean stop.", "info")
            with _lock:
                _state[sid] = {"running": False, "retries": 0, "since": now}
            continue

        activity_log.add("crash", f"{name} crashed", "Process exited unexpectedly.", "error")
        if retries < max_retries:
            result = gsm.start_server(srv)
            if result.get("ok"):
                activity_log.add(
                    "retry",
                    f"Restarted {name}",
                    f"Retry {retries + 1}/{max_retries}.",
                    "warn",
                )
                with _lock:
                    _state[sid] = {"running": True, "retries": retries + 1, "since": now}
                continue
            activity_log.add(
                "retry",
                f"Restart failed: {name}",
                str(result.get("error") or "unknown"),
                "error",
            )
        else:
            activity_log.add(
                "retry",
                f"Gave up on {name}",
                f"Hit retry limit ({max_retries}).",
                "error",
            )
        with _lock:
            _state[sid] = {"running": False, "retries": retries, "since": now}


def start_polling(app, settings, interval_ms: int = 5000) -> None:
    global _started
    if _started:
        return
    _started = True

    def loop():
        def work():
            try:
                tick(settings)
            except Exception as e:
                print(f"[Watchdog] {e}")
            app.after(interval_ms, loop)

        threading.Thread(target=work, daemon=True).start()

    app.after(interval_ms, loop)
