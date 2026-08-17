# modules/notification_mirror/web_server.py
#
# Same shape as modules/notes/web_server.py and modules/quick_send/web_server.py:
# a small dependency-free stdlib HTTP server, bound to 127.0.0.1 only, reached
# by the phone exclusively through `tailscale serve`'s HTTPS proxy — see
# core/services/tailscale_service.py. No extra encryption layer here because
# Tailscale already provides it end-to-end.
#
# Real-time delivery uses Server-Sent Events (GET /api/stream) rather than a
# WebSocket: SSE is one-way (server -> phone), which is all the "mirror a
# notification the instant it happens" requirement actually needs, and it
# works entirely over a normal HTTP response body via BaseHTTPRequestHandler
# — no new dependency on either side. The phone -> PC direction (dismiss,
# settings changes) is just ordinary POST requests on this same server,
# which is the same request/response pattern every other module already uses.
#
# MVP SCOPE (per the phased plan): global enable/off, per-app mirroring,
# real-time delivery, and offline queueing/replay are implemented here.
# Notification actions and phone -> PC dismiss-sync are intentionally left
# as follow-ups — see README_NOTIFICATION_MIRROR.md.

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from . import storage
from .listener import NotificationListener, ListenerStatus

# How many recent events to keep in memory so a phone that reconnects
# after a short drop (per spec: "queue notifications appropriately if the
# phone temporarily disconnects") can catch up via ?since=. This is a
# ring buffer, not persistent storage — it's gone on PC restart, same as
# every other in-memory queue in this codebase (e.g. vault sessions).
BACKLOG_SIZE = 100


class _Broker:
    """
    Fans out listener events to every connected SSE client, and keeps a
    small replay backlog for reconnects. One instance per web server
    (i.e. per app run) — not persisted.
    """

    def __init__(self):
        self._subscribers = []  # list of queue.Queue, one per open /api/stream
        self._lock = threading.Lock()
        self._backlog = []  # list of (seq, event_dict)
        self._seq = 0

    def publish(self, event: dict):
        with self._lock:
            self._seq += 1
            event = {**event, "seq": self._seq}
            self._backlog.append((self._seq, event))
            if len(self._backlog) > BACKLOG_SIZE:
                self._backlog = self._backlog[-BACKLOG_SIZE:]
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow/stuck client — drop rather than block the broker

    def subscribe(self, since: int = 0):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.append(q)
            backlog = [e for (seq, e) in self._backlog if seq > since]
        for e in backlog:
            try:
                q.put_nowait(e)
            except queue.Full:
                break
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def subscriber_count(self):
        with self._lock:
            return len(self._subscribers)


class NotificationWebServer:

    def __init__(self, settings: dict = None):
        self._httpd = None
        self._thread = None
        self._port = None
        self.broker = _Broker()
        self.settings = settings or storage.get_settings()
        self.listener = NotificationListener(
            on_event=self._on_listener_event,
            on_status_change=self._on_listener_status,
            on_log=lambda msg: None,
        )
        self._recent_log = []

    # =====================================================
    # LISTENER CALLBACKS
    # =====================================================

    def _on_listener_event(self, kind, payload):
        if kind == "added":
            entry = {
                "type": "notification",
                "id": payload["id"],
                "app_name": payload["app_name"],
                "app_id": payload.get("app_id"),
                "title": self._apply_privacy(payload["app_name"], payload["title"], is_title=True),
                "body": self._apply_privacy(payload["app_name"], payload["body"], is_title=False),
                "timestamp": payload.get("timestamp") or int(time.time() * 1000),
                "has_actions": bool(payload.get("actions")),
                "updated": payload.get("updated", False),
            }
            storage.append_history(entry)
            self.broker.publish(entry)
        elif kind == "removed":
            entry = {"type": "dismissed", "id": payload["id"]}
            self.broker.publish(entry)

    def _on_listener_status(self, status):
        self.broker.publish({"type": "status", "listener_status": status})

    def _apply_privacy(self, app_name, text, is_title):
        settings = storage.get_settings()
        mode = settings.get("privacy_mode", "hide_sensitive")
        forced_sensitive = app_name in settings.get("sensitive_apps", [])

        if mode == "app_only":
            return "" if not is_title else ""  # title itself also withheld under app_only
        if mode == "hide_sensitive" and forced_sensitive:
            return "New notification"
        if mode == "full" and not forced_sensitive:
            return text
        if mode == "full" and forced_sensitive:
            # Even in "full" mode, apps explicitly marked sensitive stay
            # masked — this list exists specifically so auth codes / bank
            # apps can't be pulled into a broader "show everything" choice
            # by accident.
            return "New notification" if not is_title else text
        return text  # hide_sensitive, not a forced-sensitive app

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def is_running(self):
        return self._httpd is not None

    def start(self, port: int):
        if self.is_running():
            return True, None
        try:
            handler = _make_handler(self)
            self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
            self._port = port
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()

            settings = storage.get_settings()
            if settings.get("enabled"):
                self.listener.start()

            return True, None
        except OSError as e:
            self._httpd = None
            return False, str(e)

    def stop(self):
        self.listener.stop()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._httpd = None
        self._thread = None


def _make_handler(server_obj: NotificationWebServer):

    class Handler(BaseHTTPRequestHandler):

        server_version = "NotificationMirrorWeb/1.0"

        def log_message(self, fmt, *args):
            pass

        def _cors_headers(self):
            origin = self.headers.get("Origin")
            self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Vary", "Origin")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def _json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except Exception:
                return {}

        # -------------------------------------------------
        # GET
        # -------------------------------------------------

        def do_GET(self):
            parsed = urlsplit(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/api/status":
                self._json(200, {
                    "running": True,
                    "enabled": storage.get_settings().get("enabled", False),
                    "listener_status": server_obj.listener.status,
                    "subscribers": server_obj.broker.subscriber_count(),
                })
                return

            if path == "/api/settings":
                self._json(200, storage.get_settings())
                return

            if path == "/api/history":
                self._json(200, {"items": storage.get_history()})
                return

            if path == "/api/stream":
                self._handle_stream(qs)
                return

            self._json(404, {"error": "not found"})

        def _handle_stream(self, qs):
            since = int(qs.get("since", ["0"])[0] or 0)
            sub_queue = server_obj.broker.subscribe(since=since)

            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                while True:
                    try:
                        event = sub_queue.get(timeout=15)
                        line = f"id: {event.get('seq', 0)}\ndata: {json.dumps(event)}\n\n"
                        self.wfile.write(line.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        # Heartbeat comment line — keeps the Tailscale HTTPS
                        # proxy / phone's HTTP client from timing the
                        # connection out during quiet periods.
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # phone closed the connection / went offline — normal
            finally:
                server_obj.broker.unsubscribe(sub_queue)

        # -------------------------------------------------
        # POST / DELETE
        # -------------------------------------------------

        def do_POST(self):
            path = urlsplit(self.path).path
            body = self._read_json_body()

            if path == "/api/settings":
                settings = storage.get_settings()
                # Shallow-merge top level, but keep "apps" merge explicit so
                # a partial {"apps": {"Spotify": true}} payload from the
                # phone doesn't wipe out every other app's saved choice.
                incoming_apps = body.pop("apps", None)
                settings.update(body)
                if incoming_apps:
                    settings["apps"] = {**settings["apps"], **incoming_apps}
                storage.save_settings(settings)
                self._json(200, settings)
                return

            if path == "/api/enable":
                enabled = bool(body.get("enabled", False))
                settings = storage.get_settings()
                settings["enabled"] = enabled
                storage.save_settings(settings)
                if enabled:
                    if server_obj.listener.status in (ListenerStatus.STOPPED, ListenerStatus.ERROR):
                        # First-ever enable on this run needs an access
                        # grant obtained on the UI thread — ui.py's toggle
                        # handler calls listener.request_access() itself
                        # before flipping this on, so by the time this
                        # endpoint is hit (phone-initiated enable) access
                        # should already be resolved one way or the other.
                        server_obj.listener.start()
                else:
                    server_obj.listener.stop()
                self._json(200, {"enabled": enabled, "listener_status": server_obj.listener.status})
                return

            if path == "/api/dismiss":
                # Best-effort only: WinRT's UserNotificationListener can
                # remove a notification from Windows' own Action Center
                # view, but there is no general WinRT API to tell an
                # arbitrary third-party app (Discord, Chrome, etc.) that
                # its notification was dismissed from your phone — so this
                # clears the PC-side Action Center entry, which is the
                # closest real equivalent, and is documented as a
                # limitation rather than presented as full two-way sync.
                notif_id = body.get("id")
                ok = False
                if notif_id is not None and server_obj.listener._listener is not None:
                    try:
                        server_obj.listener._listener.remove_notification(notif_id)
                        ok = True
                    except Exception:
                        ok = False
                self._json(200, {"ok": ok})
                return

            self._json(404, {"error": "not found"})

        def do_DELETE(self):
            path = urlsplit(self.path).path
            if path == "/api/history":
                storage.clear_history()
                self._json(200, {"ok": True})
                return
            self._json(404, {"error": "not found"})

    return Handler
