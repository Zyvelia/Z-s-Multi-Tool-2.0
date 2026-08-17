# modules/gaming_hub/web_server.py
#
# A small, dependency-free HTTP server (stdlib only) that lets your
# phone see your scanned game library and launch a game on this PC —
# reached from your phone over Tailscale, same idea as Music Player,
# Security Vault, and YouTube Downloader. Modeled directly on
# modules/yt_downloader/web_server.py.
#
# Security model:
#   - Binds to 127.0.0.1 ONLY. Reachable from the LAN/internet only via
#     `tailscale serve`'s HTTPS proxy (tailnet devices only) — see
#     core/services/tailscale_service.py.
#   - No auth by default, matching Music Player / YouTube Downloader:
#     launching a game isn't sensitive the way vault passwords are, and
#     Tailscale membership is already the trust boundary. Set an access
#     code in the Gaming Hub settings if you want an extra step before
#     your phone (or anyone else on your tailnet) can launch anything —
#     it gates POST /api/launch only; GET /api/games stays open.
#   - Only ever launches an exe_path that's already present in the
#     scanned game cache — nothing arbitrary can be launched from a
#     phone request.
#
# Data source:
#   - Reads modules/gaming_hub/games_cache.json via GameScanner.load_cache()
#     — the same cache the desktop UI shows instantly on open. This
#     server doesn't trigger scans on its own; POST /api/rescan asks the
#     desktop's scanner to run again (useful if you installed a new game
#     since the last scan) and refreshes the cache used by /api/games.
#
# Game IDs:
#   - Games have no stable id in the Game dataclass, so this server
#     derives one from a hash of exe_path — stable across restarts as
#     long as the install path doesn't change, which is exactly the
#     condition under which launching it still makes sense anyway.

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .game_scanner import GameScanner
from .launcher import GameLauncher


def _game_id(exe_path: str) -> str:
    return hashlib.sha1((exe_path or "").encode("utf-8")).hexdigest()[:12]


class _Handler(BaseHTTPRequestHandler):

    server_version = "GamingHubWeb/1.0"

    def log_message(self, fmt, *args):
        pass  # silence default stderr request logging

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _srv(self):
        return self.server.owner  # GamingHubWebServer instance

    def _cors_headers(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code")
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
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _code_ok(self, srv):
        required = (srv.access_code or "").strip()
        if not required:
            return True
        sent = (self.headers.get("X-Access-Code") or "").strip()
        return sent == required

    # -------------------------------------------------
    # routing
    # -------------------------------------------------

    def do_GET(self):
        path = urlsplit(self.path).path
        srv = self._srv()

        if path == "/api/status":
            self._send_json(200, {
                "ok": True,
                "game_count": len(srv.list_games()),
                "scanning": srv.is_scanning(),
            })
        elif path == "/api/games":
            games = [
                {
                    "id": _game_id(g.exe_path),
                    "name": g.name,
                    "launcher": g.launcher,
                }
                for g in srv.list_games()
                if g.exe_path
            ]
            games.sort(key=lambda g: g["name"].lower())
            self._send_json(200, {"ok": True, "games": games})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        srv = self._srv()

        if path == "/api/launch":
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return

            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return

            game_id = (body.get("id") or "").strip()
            if not game_id:
                self._send_json(400, {"ok": False, "error": "missing 'id'"})
                return

            game = next(
                (g for g in srv.list_games() if _game_id(g.exe_path) == game_id),
                None,
            )
            if game is None:
                self._send_json(404, {"ok": False, "error": "unknown game id"})
                return

            try:
                srv.launcher.launch(game)
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)})
                return

            self._send_json(200, {"ok": True, "launched": game.name})

        elif path == "/api/rescan":
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return
            srv.rescan_async()
            self._send_json(200, {"ok": True, "scanning": True})

        else:
            self._send_json(404, {"ok": False, "error": "not found"})


class GamingHubWebServer:
    """Loopback HTTP server exposing the cached game library + a launch
    trigger. Independent of any open UI page — safe to auto-start."""

    def __init__(self):
        self.scanner = GameScanner()
        self.launcher = GameLauncher()
        self.access_code = ""  # optional — see _code_ok() above; blank = no gate

        self.port = None
        self._httpd = None
        self._thread = None

        self._games = self.scanner.load_cache()
        self._games_lock = threading.Lock()
        self._scanning = False

    # ---- lifecycle -------------------------------------------------

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self, port: int):
        if self.is_running():
            return True, "already running"
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        except OSError as e:
            return False, f"couldn't bind to 127.0.0.1:{port} — {e}"
        httpd.owner = self
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

    # ---- data --------------------------------------------------------

    def list_games(self):
        with self._games_lock:
            return list(self._games)

    def is_scanning(self):
        return self._scanning

    def refresh_from_cache(self):
        """Call this from the desktop UI after a scan finishes so the
        web server picks up new results without needing a restart."""
        with self._games_lock:
            self._games = self.scanner.load_cache()

    def rescan_async(self):
        if self._scanning:
            return

        def _worker():
            self._scanning = True
            try:
                games = self.scanner.scan()
                self.scanner.save_cache(games)
                with self._games_lock:
                    self._games = games
            except Exception as e:
                print(f"[GamingHubWebServer] Rescan failed: {e}")
            finally:
                self._scanning = False

        threading.Thread(target=_worker, daemon=True).start()
