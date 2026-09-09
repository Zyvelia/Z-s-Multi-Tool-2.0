# modules/Productivity/Messaging/web_server.py
#
# HTTP + WebSocket server for the Messaging module — a relay between
# your phone and your parent's phone, both talking to this one Windows
# PC over Tailscale. Same stdlib-server shape as Notes/YT/Music
# (ThreadingHTTPServer + BaseHTTPRequestHandler), with WebSocket support
# added via the small `simple-websocket` library rather than hand-rolled
# framing.
#
# `simple_websocket.Server` normally expects a WSGI environ carrying a
# 'werkzeug.socket'/'gunicorn.socket'/etc. key to pull the raw socket
# from. BaseHTTPRequestHandler is neither, so the handshake below builds
# a synthetic environ from the already-parsed request headers and stuffs
# the real connection in under the 'werkzeug.socket' key — that's the
# officially-recognized extraction point, just fed by hand instead of by
# an actual WSGI server. Verified end-to-end (handshake + message
# exchange) before writing this.
#
# Model: every message is persisted first, then broadcast to every
# currently-connected socket, sender included — the mobile client
# already shows its own send optimistically and dedupes by "id", so a
# broadcast echo is harmless and keeps this side simple (no per-socket
# "don't echo to sender" bookkeeping, and every connected device — same
# person on two phones, or the other party — gets the same message).
#
# Security model matches Notes: binds 127.0.0.1 only, reachable via
# `tailscale serve`'s HTTPS proxy (which passes WebSocket upgrades
# through fine), no auth beyond tailnet membership.

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from simple_websocket import Server as WSServer, ConnectionClosed

from core.services import device_trust

from . import storage

_clients = set()
_clients_lock = threading.Lock()

# Local (in-process) listeners — lets the desktop UI (MessagingPage) hear
# about new messages the same way a connected phone does, without opening
# a websocket to itself. Registered/unregistered by the UI page as it's
# shown/torn down; the server itself doesn't care whether anyone's
# listening, same "independent of any open UI page" model as the phone
# side. Callbacks run on whatever thread received the message (a WS
# client thread, or the same thread that called append_message locally),
# so callers touching Tkinter widgets must hop back via `widget.after(0, ...)`.
_local_listeners = set()
_local_listeners_lock = threading.Lock()


def add_local_listener(callback):
    with _local_listeners_lock:
        _local_listeners.add(callback)


def remove_local_listener(callback):
    with _local_listeners_lock:
        _local_listeners.discard(callback)


def _notify_local(payload: dict):
    with _local_listeners_lock:
        listeners = list(_local_listeners)
    for cb in listeners:
        try:
            cb(payload)
        except Exception:
            pass


def _broadcast(payload: dict):
    body = json.dumps(payload)
    with _clients_lock:
        dead = []
        for ws in _clients:
            try:
                ws.send(body)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)
    _notify_local(payload)


def send_from_desktop(sender_id: str, text: str) -> dict:
    """
    Entry point for the desktop UI itself sending a message — same
    persist-then-broadcast path as an HTTP POST or a WS frame from the
    phone, just invoked directly in-process instead of over a socket.
    Does NOT call _notify_local's own listeners back at the caller
    synchronously with something distinguishable as "mine"; the UI page
    already renders its own send optimistically (matching the phone's
    id-based dedupe convention), and this broadcast reaching connected
    phones is the point.
    """
    message = storage.append_message(sender_id, text)
    _broadcast(message)
    return message


class _Handler(BaseHTTPRequestHandler):

    server_version = "MessagingWeb/1.0"

    def log_message(self, fmt, *args):
        pass  # silence default stderr request logging

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _cors_headers(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-Id, X-Device-Ts, X-Device-Sig")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # -------------------------------------------------
    # routing
    # -------------------------------------------------

    def do_GET(self):
        if not device_trust.allow_handler(self):
            return
        parts = urlsplit(self.path)
        path = parts.path
        qs = parse_qs(parts.query)

        if path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_ws()
            return

        if path == "/api/messages":
            since = float((qs.get("since") or ["0"])[0] or 0)
            self._send_json(200, {"messages": storage.get_messages_since(since)})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not device_trust.allow_handler(self):
            return
        parts = urlsplit(self.path)
        if parts.path == "/api/messages":
            body = self._read_json_body()
            sender_id = body.get("sender_id", "")
            text = body.get("text", "")
            if not text:
                self._send_json(400, {"error": "text required"})
                return
            message = storage.append_message(sender_id, text, body.get("id"))
            _broadcast(message)
            self._send_json(200, {"ok": True, "message": message})
            return
        self._send_json(404, {"error": "not found"})

    # -------------------------------------------------
    # websocket
    # -------------------------------------------------

    def _handle_ws(self):
        environ = {"REQUEST_METHOD": "GET"}
        for key, value in self.headers.items():
            environ["HTTP_" + key.upper().replace("-", "_")] = value
        environ["werkzeug.socket"] = self.connection

        try:
            ws = WSServer(environ, receive_bytes=4096)
        except Exception:
            return

        with _clients_lock:
            _clients.add(ws)
        try:
            while True:
                data = ws.receive(timeout=None)
                if data is None:
                    continue
                try:
                    parsed = json.loads(data)
                except Exception:
                    continue
                sender_id = parsed.get("sender_id", "")
                text = parsed.get("text", "")
                if not text:
                    continue
                message = storage.append_message(sender_id, text, parsed.get("id"))
                _broadcast(message)
        except ConnectionClosed:
            pass
        finally:
            with _clients_lock:
                _clients.discard(ws)


class MessagingWebServer:
    """Loopback HTTP+WS server exposing Messaging to both phones.
    Independent of any open UI page — same shape as NotesWebServer."""

    def __init__(self):
        self.port = None
        self._httpd = None
        self._thread = None

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self, port: int):
        if self.is_running():
            return True, "already running"
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        except OSError as e:
            return False, f"couldn't bind to 127.0.0.1:{port} — {e}"
        httpd.daemon_threads = True
        self._httpd = httpd
        self.port = port
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return True, f"listening on 127.0.0.1:{port}"

    def stop(self):
        if not self.is_running():
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        self._httpd = None
        self.port = None


# Module-level singleton + lazy-start helper. There's no central "app boot"
# file in this checkout to confirm where module web servers normally get
# started (Notes/Vault/etc. presumably do this from wherever
# manager.register()'d modules are brought up, or from a Settings/Remote-hub
# page — neither is in this zip). Until that's wired in, MessagingPage below
# calls ensure_started() itself the first time the tab is opened, and never
# stops it on teardown, so the relay stays up (and keeps serving the phone)
# even after the user navigates away — matching the "independent of any
# open UI page" model this module is documented to want. If there IS a
# central place other modules' servers get started/stopped from, wire
# ensure_started()/server.stop() in there instead and this fallback becomes
# a no-op (is_running() short-circuits it).
server = MessagingWebServer()


def ensure_started(port: int = 8452):
    if not server.is_running():
        return server.start(port)
    return True, "already running"
