"""Loopback HTTP for the phone: list / start / stop / console for GSM."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from core.services import device_trust

from . import agent_api

LOOPBACK_PORT = 8771


class _Handler(BaseHTTPRequestHandler):
    server_version = "GsmWeb/1.0"

    def log_message(self, *_args):
        return

    def _srv(self):
        return self.server.owner

    def _cors(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code, X-Device-Id, X-Device-Ts, X-Device-Sig")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def _code_ok(self) -> bool:
        required = (self._srv().access_code or "").strip()
        if not required:
            return True
        sent = (self.headers.get("X-Access-Code") or "").strip()
        return sent == required

    def _find(self, body: dict) -> tuple[dict | None, str | None]:
        sid = (body.get("id") or body.get("server") or "").strip()
        if not sid:
            return None, "missing 'id'"
        return agent_api.find_server(sid)

    def do_GET(self):
        if not device_trust.allow_handler(self):
            return
        path = urlsplit(self.path).path
        if path == "/api/status":
            rows = agent_api.load_servers_safe()
            return self._json(200, {
                "ok": True,
                "server_count": len(rows),
                "running": sum(1 for r in rows if r.get("running")),
            })
        if path == "/api/servers":
            return self._json(200, {"ok": True, "servers": agent_api.load_servers_safe()})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not device_trust.allow_handler(self):
            return
        if not self._code_ok():
            return self._json(401, {"ok": False, "error": "wrong or missing access code"})
        path = urlsplit(self.path).path
        body = self._body()
        if body is None:
            return self._json(400, {"ok": False, "error": "invalid JSON body"})

        if path == "/api/start":
            srv, err = self._find(body)
            if err or not srv:
                return self._json(404, {"ok": False, "error": err or "unknown server"})
            return self._json(200, agent_api.start_server(srv))

        if path == "/api/stop":
            srv, err = self._find(body)
            if err or not srv:
                return self._json(404, {"ok": False, "error": err or "unknown server"})
            return self._json(200, agent_api.stop_server(srv))

        if path == "/api/console":
            srv, err = self._find(body)
            if err or not srv:
                return self._json(404, {"ok": False, "error": err or "unknown server"})
            return self._json(200, agent_api.send_console(srv, body.get("command") or ""))

        return self._json(404, {"ok": False, "error": "not found"})


class GsmWebServer:
    def __init__(self):
        self.access_code = ""
        self.port = None
        self._httpd = None
        self._thread = None

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self, port: int = LOOPBACK_PORT):
        if self.is_running():
            return True, "already running"
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
        except OSError as e:
            return False, f"couldn't bind to 127.0.0.1:{port} — {e}"
        httpd.owner = self
        httpd.daemon_threads = True
        self._httpd = httpd
        self.port = int(port)
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
