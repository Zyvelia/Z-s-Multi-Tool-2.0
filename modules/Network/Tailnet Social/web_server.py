"""Local HTTP for tailnet friends: queue, soundboard, limited GSM console."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import storage

LOOPBACK_PORT = 8770


def _html() -> bytes:
    return b"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Night with Zyvelia</title>
<style>
body{font-family:system-ui;background:#0d1117;color:#c9d1d9;margin:0;padding:16px}
input,button{font:inherit;padding:8px;border-radius:8px;border:1px solid #30363d;background:#161b22;color:#fff}
button{background:#238636;border:0;margin:4px 4px 4px 0}
.card{background:#161b22;padding:12px;border-radius:12px;margin:12px 0}
li{margin:6px 0}
</style></head><body>
<h1>Night page</h1>
<p>Paste the invite key this PC issued you.</p>
<input id=k placeholder="invite key" style="width:100%">
<div class=card>
<h2>Jukebox queue</h2>
<input id=t placeholder="Track or URL">
<button onclick="add()">Add</button>
<button onclick="loadq()">Refresh</button>
<ul id=q></ul>
</div>
<div class=card>
<h2>Soundboard</h2>
<input id=s placeholder="clip name">
<button onclick="snd()">Play</button>
</div>
<div class=card>
<h2>Server console (if your key allows)</h2>
<input id=srv placeholder="server name">
<input id=cmd placeholder="say hello">
<button onclick="con()">Send</button>
<pre id=out></pre>
</div>
<script>
const K=()=>document.getElementById('k').value.trim();
async function add(){await fetch('/api/queue?key='+encodeURIComponent(K()),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:document.getElementById('t').value})});loadq();}
async function loadq(){const r=await fetch('/api/queue?key='+encodeURIComponent(K()));const j=await r.json();document.getElementById('q').innerHTML=(j.queue||[]).map(i=>'<li>'+i.title+'</li>').join('')||'<li>(empty)</li>';}
async function snd(){await fetch('/api/sound?key='+encodeURIComponent(K()),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({name:document.getElementById('s').value})});}
async function con(){const r=await fetch('/api/console?key='+encodeURIComponent(K()),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({server:document.getElementById('srv').value,command:document.getElementById('cmd').value})});document.getElementById('out').textContent=await r.text();}
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _key(self):
        q = parse_qs(urlparse(self.path).query)
        return (q.get("key") or [""])[0]

    def _cors(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, code: int, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
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
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = _html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        invite = storage.check_invite(self._key())
        if not invite:
            return self._json(401, {"ok": False, "error": "Need a valid invite key."})
        if path == "/api/queue":
            return self._json(200, {"ok": True, "queue": storage.queue_list()})
        if path == "/api/sounds":
            return self._json(200, {"ok": True, "sounds": _list_sounds()})
        return self._json(404, {"ok": False})

    def do_POST(self):
        invite = storage.check_invite(self._key())
        if not invite:
            return self._json(401, {"ok": False, "error": "Need a valid invite key."})
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/queue":
            title = (body.get("title") or "").strip()
            if not title:
                return self._json(400, {"ok": False, "error": "title required"})
            item = storage.queue_add(title, by=invite.get("label") or "")
            return self._json(200, {"ok": True, "item": item})
        if path == "/api/sound":
            return self._json(200, _play_sound(body.get("name") or ""))
        if path == "/api/console":
            if not invite.get("console"):
                return self._json(403, {"ok": False, "error": "This key cannot use the console."})
            return self._json(200, _console(body.get("server") or "", body.get("command") or ""))
        return self._json(404, {"ok": False})


def _list_sounds() -> list[str]:
    import os
    from importlib import import_module

    try:
        ws = import_module("modules.Media.soundboard.web_server")
        server = ws.SoundboardWebServer()
        names = []
        for path in server.list_sounds():
            names.append(os.path.splitext(os.path.basename(path))[0])
        return names
    except Exception:
        return []


def _play_sound(name: str) -> dict:
    import os
    from importlib import import_module

    name = (name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "name required"}
    try:
        ws = import_module("modules.Media.soundboard.web_server")
        server = ws.SoundboardWebServer()
        matches = []
        for path in server.list_sounds():
            base = os.path.splitext(os.path.basename(path))[0].lower()
            if name == base or name in base:
                matches.append(path)
        if not matches:
            return {"ok": False, "error": "No clip matches that name. Set a Soundboard folder first."}
        ok, err = server.play(matches[0])
        if not ok:
            return {"ok": False, "error": err or "play failed"}
        return {"ok": True, "played": os.path.basename(matches[0])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _console(server: str, command: str) -> dict:
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "command required"}
    try:
        from importlib import import_module
        api = import_module("modules.Gaming.Game Server Manager.agent_api")
        runtime = import_module("modules.Gaming.Game Server Manager.runtime")
        srv, err = api.find_server(server)
        if err or not srv:
            return {"ok": False, "error": err or "unknown server"}
        proc = runtime.get_process(srv["id"])
        if not proc.running:
            return {"ok": False, "error": "Server is not running."}
        if not proc.send(command):
            return {"ok": False, "error": "Could not write to the console."}
        return {"ok": True, "sent": command, "name": srv.get("name")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_server: ThreadingHTTPServer | None = None


def is_running() -> bool:
    return _server is not None


def start(port: int = LOOPBACK_PORT) -> tuple[bool, str]:
    global _server
    if _server is not None:
        return True, "already"
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
    except OSError as e:
        return False, str(e)
    import threading
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _server = httpd
    return True, f"127.0.0.1:{port}"


def stop() -> None:
    global _server
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:
            pass
        _server = None


class SocialWebServer:
    def is_running(self):
        return is_running()

    def start(self, port):
        return start(port)

    def stop(self):
        stop()
