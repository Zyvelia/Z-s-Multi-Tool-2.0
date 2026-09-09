"""Loopback HTTP for pairing a phone. Revoke stays on the desktop UI."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from core.services import device_trust as trust


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeviceTrust/1.0"

    def log_message(self, *_args):
        return

    def _cors(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-Id, X-Device-Ts, X-Device-Sig")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, status: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/status":
            return self._json(200, {
                "ok": True,
                "required": trust.is_required(),
                "devices": trust.list_devices(),
            })
        return self._json(404, {"ok": False})

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self._body()
        if path == "/api/pair":
            ok, secret_or_err, device_id = trust.pair(
                body.get("code") or "",
                body.get("device_id") or "",
                body.get("label") or "",
            )
            if not ok:
                return self._json(400, {"ok": False, "error": secret_or_err})
            return self._json(200, {"ok": True, "secret": secret_or_err, "device_id": device_id})
        return self._json(404, {"ok": False})


class DeviceTrustWebServer:
    def __init__(self):
        self.port = None
        self._httpd = None

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self, port: int = trust.LOOPBACK_PORT):
        if self.is_running():
            return True, "already"
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
        except OSError as e:
            return False, str(e)
        httpd.daemon_threads = True
        self._httpd = httpd
        self.port = int(port)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return True, f"127.0.0.1:{port}"

    def stop(self):
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        self._httpd = None
