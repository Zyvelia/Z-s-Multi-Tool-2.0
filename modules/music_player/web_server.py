# music_player/web_server.py
#
# A small, dependency-free HTTP server (stdlib only) that lets your phone
# browse + stream your music library, meant to be reached via
# `tailscale serve` (see core.services.tailscale_service) — NOT exposed on
# the LAN or the open internet. Modeled directly on
# core/services/vault_web_server.py.
#
# Security model:
#   - Binds to 127.0.0.1 ONLY. It is never reachable except through the
#     Tailscale HTTPS proxy running on the same machine, which only
#     accepts connections from other devices on your own tailnet.
#   - There's no separate login here (unlike the vault) — being on your
#     tailnet already means it's one of your own signed-in devices, and
#     a music library is not sensitive the way passwords are.
#
# Playback model:
#   - The phone is its own player. It streams audio straight from your
#     PC's library over HTTP (with Range support, so seeking works) into
#     a normal <audio> element. It does NOT remote-control the desktop
#     app's pygame playback — the two are independent listening sessions
#     that both read from the same SQLite-indexed library.

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from . import db as musicdb

# Browser-friendly overrides — Python's mimetypes module either doesn't
# know these or guesses something a browser <audio> tag won't accept.
_MIME_OVERRIDES = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".aifc": "audio/aiff",
    ".wave": "audio/wav",
    ".mp4": "audio/mp4",
    ".m4b": "audio/mp4",
    ".m4p": "audio/mp4",
    ".m4r": "audio/mp4",
    ".mka": "audio/x-matroska",
    ".webm": "audio/webm",
    ".3gp": "audio/3gpp",
    ".3g2": "audio/3gpp2",
    ".spx": "audio/ogg",
    ".amr": "audio/amr",
    # Playlist files — only relevant if one is ever served/downloaded
    # directly through the remote web UI, not for <audio> playback.
    ".m3u": "audio/x-mpegurl",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".pls": "audio/x-scpls",
    ".xspf": "application/xspf+xml",
}

CHUNK_SIZE = 64 * 1024


def _guess_mime(path):
    ext = os.path.splitext(path)[1].lower()
    return _MIME_OVERRIDES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def _song_json(row):
    return {
        "id": row["id"],
        "title": row.get("title") or os.path.basename(row.get("path", "")),
        "artist": row.get("artist") or "",
        "album": row.get("album") or "",
        "duration": row.get("duration") or 0,
    }


class _Handler(BaseHTTPRequestHandler):

    server_version = "MusicWeb/1.0"

    # Silence default stderr request logging — noisy for a background service.
    def log_message(self, fmt, *args):
        pass

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _lib(self):
        return self.server.library

    def _engine(self):
        ws = getattr(self.server, "web_server", None)
        return getattr(ws, "engine", None) if ws else None

    def _cors_headers(self):
        # Loopback-only (127.0.0.1), so a permissive CORS policy doesn't
        # expose anything beyond what any other local process could already
        # reach. Needed for the browser extension's popup/background page
        # to fetch() this API.
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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

    def _send_html(self, status, html):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # -------------------------------------------------
    # routing
    # -------------------------------------------------

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        qs = parse_qs(parts.query)

        if path in ("/", "/index.html"):
            self._send_html(200, _PAGE_SHELL)
        elif path == "/api/status":
            self._send_json(200, {"ok": True, "count": self._lib().count()})
        elif path == "/api/now-playing":
            self._handle_now_playing()
        elif path == "/api/songs":
            self._handle_songs(qs)
        elif path.startswith("/api/stream/"):
            self._handle_stream(path[len("/api/stream/"):], send_body=True)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parts = urlsplit(self.path)
        if parts.path == "/api/control":
            self._handle_control()
        else:
            self._send_json(404, {"error": "not found"})

    def do_HEAD(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path.startswith("/api/stream/"):
            self._handle_stream(path[len("/api/stream/"):], send_body=False)
        else:
            self.send_response(404)
            self.end_headers()

    # -------------------------------------------------
    # handlers
    # -------------------------------------------------

    def _handle_now_playing(self):
        engine = self._engine()
        if engine is None:
            self._send_json(200, {"attached": False})
            return

        try:
            from .player import State
        except Exception:
            State = None

        meta = engine.get_current_meta()
        song = None
        if meta:
            song = _song_json(meta)
        elif getattr(engine, "playlist", None) and 0 <= engine.index < len(engine.playlist):
            import os as _os
            path = engine.playlist[engine.index]
            song = {"id": None, "title": _os.path.basename(path or "?"), "artist": "", "album": "", "duration": 0}

        state = engine.get_state() if State else None
        self._send_json(200, {
            "attached": True,
            "song": song,
            "is_playing": engine.is_playing(),
            "state": state,
            "position": engine.get_time(),
            "duration": engine.get_length(),
            "volume": getattr(engine, "volume", 0.5),
            "shuffle": getattr(engine, "shuffle", False),
            "repeat_mode": getattr(engine, "repeat_mode", "off"),
            "has_prev": engine.index > 0 if getattr(engine, "playlist", None) else False,
            "has_next": bool(getattr(engine, "playlist", None)) and engine.index + 1 < len(engine.playlist),
        })

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _handle_control(self):
        engine = self._engine()
        if engine is None:
            self._send_json(409, {"error": "no active playback engine — open the Music Player page in the desktop app first"})
            return

        body = self._read_json_body()
        action = body.get("action")

        if action == "play":
            if engine.index < 0 and getattr(engine, "playlist", None):
                engine.play_at(0)
            else:
                engine.play()
        elif action == "pause":
            engine.pause()
        elif action == "next":
            engine.next()
        elif action == "prev":
            engine.prev()
        elif action == "set_volume":
            engine.set_volume(body.get("value", 0.5))
        elif action == "toggle_shuffle":
            engine.shuffle = not engine.shuffle
        elif action == "cycle_repeat":
            modes = ["off", "all", "one"]
            engine.repeat_mode = modes[(modes.index(engine.repeat_mode) + 1) % len(modes)]
        elif action == "play_song":
            song_id = body.get("song_id")
            try:
                song_id = int(song_id)
            except (TypeError, ValueError):
                self._send_json(400, {"error": "song_id required"})
                return
            lib = self._lib()
            ids = lib.search_ids("")
            try:
                start_index = list(ids).index(song_id)
            except ValueError:
                start_index = 0
                ids = [song_id]
            engine.load_ids(lib, ids, start_index=start_index)
            engine.play()
        else:
            self._send_json(400, {"error": f"unknown action: {action}"})
            return

        self._handle_now_playing()

    def _handle_songs(self, qs):
        query = (qs.get("q") or [""])[0]
        try:
            offset = max(0, int((qs.get("offset") or ["0"])[0]))
        except ValueError:
            offset = 0
        try:
            limit = max(1, min(500, int((qs.get("limit") or ["100"])[0])))
        except ValueError:
            limit = 100

        lib = self._lib()
        ids = lib.search_ids(query)
        total = len(ids)
        page_ids = list(ids[offset:offset + limit])
        metas = lib.get_songs(page_ids)
        songs = [_song_json(metas[i]) for i in page_ids if i in metas]

        self._send_json(200, {
            "songs": songs,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total,
        })

    def _handle_stream(self, song_id_str, send_body):
        try:
            song_id = int(song_id_str)
        except ValueError:
            self._send_json(400, {"error": "bad song id"})
            return

        path = self._lib().get_path(song_id)
        if not path or not os.path.exists(path):
            self._send_json(404, {"error": "file not found"})
            return

        try:
            file_size = os.path.getsize(path)
        except OSError:
            self._send_json(404, {"error": "file not found"})
            return

        content_type = _guess_mime(path)
        range_header = self.headers.get("Range")

        start, end = 0, file_size - 1
        status = 200
        if range_header and range_header.startswith("bytes="):
            status = 206
            spec = range_header[len("bytes="):].split("-", 1)
            try:
                if spec[0]:
                    start = int(spec[0])
                if len(spec) > 1 and spec[1]:
                    end = int(spec[1])
            except ValueError:
                start, end = 0, file_size - 1
            start = max(0, min(start, file_size - 1))
            end = max(start, min(end, file_size - 1))

        length = end - start + 1

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        if not send_body:
            return

        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Phone closed the connection early (seek/skip) — not an error.
            return


class MusicWebServer:
    """
    Owns the background HTTP server thread. `library` is a db.Library —
    if not provided, a new one is opened against the same on-disk index
    the desktop app uses (Library's SQLite connections are per-thread,
    so sharing or independently opening the same db file is both fine).

    `engine` is the live PygameMusicEngine driving the desktop app's own
    speakers (manager.music_engine). It's optional — if not supplied,
    /api/now-playing and /api/control just report "no engine attached"
    instead of failing outright — but it's what lets the browser
    extension's remote-control buttons (play/pause/skip/volume) actually
    control the desktop app's playback, as opposed to the independent
    phone-streaming session served by /api/songs + /api/stream.
    """

    def __init__(self, library=None, engine=None):
        self.library = library or musicdb.Library()
        self.engine = engine
        self._httpd = None
        self._thread = None
        self.port = None

    def is_running(self):
        return self._httpd is not None

    def start(self, port):
        if self.is_running():
            return True, f"Already running on port {self.port}."
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        except OSError as e:
            return False, f"Couldn't bind to port {port}: {e}"

        httpd.library = self.library
        # Store a reference to this wrapper (not just the engine) so that
        # reassigning self.engine later (e.g. MusicPage re-fetching the
        # live engine off `manager`) is picked up by in-flight requests
        # without needing to restart the server.
        httpd.web_server = self
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        self._httpd = httpd
        self._thread = thread
        self.port = port
        return True, f"Serving on 127.0.0.1:{port} (local only)."

    def stop(self):
        if not self._httpd:
            return True, "Already stopped."
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None
        self.port = None
        return True, "Stopped."


# =====================================================
# MOBILE PAGE (single file, no build step, no external requests)
# =====================================================

_PAGE_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0f111a">
<title>Music</title>
<style>
  :root {
    --bg:#0f111a; --panel:#151826; --card:#1a1e2e; --card-hover:#222738;
    --accent:#e0a458; --accent-dim:#8a6a3f; --accent-wash:rgba(224,164,88,.13);
    --text:#eef0f4; --muted:#7b8296; --faint:#4c5266; --divider:#242938; --danger:#e2735f;
    --mono: ui-monospace, "SF Mono", "Roboto Mono", Menlo, Consolas, monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html, body { height:100%; }
  body {
    margin:0; background:var(--bg); color:var(--text); font-family:var(--sans);
    overscroll-behavior-y:none;
  }
  .wrap { max-width:600px; margin:0 auto; padding:0 14px 190px; }

  header {
    position:sticky; top:0; z-index:5; background:rgba(15,17,26,.86);
    backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
    padding:calc(env(safe-area-inset-top) + 14px) 14px 12px;
    border-bottom:1px solid var(--divider);
  }
  .brand { display:flex; align-items:center; gap:9px; margin-bottom:12px; }
  .brand svg { flex-shrink:0; }
  .brand h1 { font-size:17px; font-weight:600; margin:0; letter-spacing:.2px; }
  .brand .tag { color:var(--faint); font-size:11px; font-family:var(--mono); margin-left:auto; text-transform:uppercase; letter-spacing:.06em; }

  .searchbar { position:relative; }
  .searchbar svg { position:absolute; left:12px; top:50%; transform:translateY(-50%); color:var(--faint); pointer-events:none; }
  input[type=search] {
    width:100%; padding:12px 36px 12px 38px; border-radius:10px; border:1px solid var(--divider);
    background:var(--card); color:var(--text); font-size:16px; font-family:var(--sans);
    outline:none; transition:border-color .15s;
  }
  input[type=search]:focus { border-color:var(--accent-dim); }
  input[type=search]::-webkit-search-cancel-button { display:none; }
  .clearbtn {
    position:absolute; right:8px; top:50%; transform:translateY(-50%);
    width:22px; height:22px; border:none; border-radius:50%; background:var(--card-hover);
    color:var(--muted); font-size:13px; line-height:1; display:none;
  }
  .count { color:var(--faint); font-size:12px; font-family:var(--mono); margin:9px 2px 4px; }

  .list { margin-top:2px; }
  .row {
    display:flex; align-items:center; gap:12px; padding:11px 4px;
    border-bottom:1px solid var(--divider); cursor:pointer;
  }
  .row:active { background:var(--card-hover); }
  .row.active .idx { color:var(--accent); }
  .row.active .title { color:var(--accent); }
  .idx {
    flex-shrink:0; width:28px; font-family:var(--mono); font-size:12.5px; color:var(--faint);
    text-align:right;
  }
  .row .meta { flex:1; min-width:0; }
  .row .title { font-weight:500; font-size:15px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .row .artist { color:var(--muted); font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:1px; }
  .row .dur { flex-shrink:0; font-family:var(--mono); font-size:12px; color:var(--faint); }
  .row .playbtn {
    flex-shrink:0; width:30px; height:30px; border-radius:50%; border:none;
    background:transparent; color:var(--muted); font-size:12px; display:flex; align-items:center; justify-content:center;
  }
  .row.active .playbtn { color:var(--accent); }

  .loadmore {
    width:100%; padding:13px; border-radius:10px; border:1px solid var(--divider);
    background:transparent; color:var(--muted); font-weight:500; font-size:13px; margin:14px 0 4px;
  }
  .skeleton { padding:11px 4px; display:flex; gap:12px; align-items:center; border-bottom:1px solid var(--divider); }
  .skeleton .bar { height:11px; border-radius:4px; background:var(--card); animation:pulse 1.3s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{opacity:.5} 50%{opacity:1} }
  .muted-msg { color:var(--faint); font-size:13px; text-align:center; padding:40px 0; }
  .error { color:var(--danger); font-size:13px; text-align:center; padding:16px 10px; }

  .player {
    position:fixed; left:0; right:0; bottom:0; background:var(--panel);
    border-top:1px solid var(--divider); padding:12px 16px calc(env(safe-area-inset-bottom) + 12px);
    transform:translateY(110%); transition:transform .25s ease;
  }
  .player.show { transform:translateY(0); }
  .player .now { display:flex; align-items:center; gap:11px; margin-bottom:10px; }
  .disc { flex-shrink:0; animation:spin 3.2s linear infinite; animation-play-state:paused; }
  .disc.spin { animation-play-state:running; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .now .meta { min-width:0; flex:1; }
  .now .title { font-weight:600; font-size:14.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .now .artist { color:var(--muted); font-size:12.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:1px; }

  .seekrow { display:flex; align-items:center; gap:9px; margin-bottom:2px; }
  .seekrow .t { font-family:var(--mono); font-size:11px; color:var(--faint); width:34px; flex-shrink:0; }
  .seekrow .t.end { text-align:right; }
  input[type=range] {
    -webkit-appearance:none; appearance:none; flex:1; height:16px; background:transparent; margin:0;
  }
  input[type=range]::-webkit-slider-runnable-track { height:3px; border-radius:2px; background:var(--divider); }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance:none; width:13px; height:13px; border-radius:50%; background:var(--accent);
    margin-top:-5px; box-shadow:0 0 0 3px rgba(224,164,88,.18);
  }
  input[type=range]::-moz-range-track { height:3px; border-radius:2px; background:var(--divider); }
  input[type=range]::-moz-range-thumb { width:13px; height:13px; border:none; border-radius:50%; background:var(--accent); }

  .transport { display:flex; align-items:center; justify-content:center; gap:26px; margin-top:8px; }
  .transport button { background:none; border:none; color:var(--text); padding:6px; display:flex; }
  .transport button.play {
    width:46px; height:46px; border-radius:50%; background:var(--accent); color:#171308;
    display:flex; align-items:center; justify-content:center;
  }
  .transport button.play svg { margin-left:2px; }
  .transport button:disabled { opacity:.3; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="#e0a458" stroke-width="1.6"/><circle cx="12" cy="12" r="3.2" stroke="#e0a458" stroke-width="1.6"/><circle cx="12" cy="12" r="1" fill="#e0a458"/></svg>
    <h1>Library</h1>
    <span class="tag">tailnet stream</span>
  </div>
  <div class="searchbar">
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/><path d="M21 21l-4.3-4.3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
    <input type="search" id="search" placeholder="Search title, artist, album…" autocomplete="off" autocorrect="off" spellcheck="false">
    <button class="clearbtn" id="clearBtn" aria-label="Clear search">✕</button>
  </div>
  <div class="count" id="count"></div>
</header>

<div class="wrap"><div class="list" id="app"></div></div>

<div class="player" id="player">
  <div class="now">
    <svg class="disc" id="disc" width="34" height="34" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10.5" fill="#20263a" stroke="#2c3348" stroke-width="1"/>
      <circle cx="12" cy="12" r="7.2" fill="none" stroke="#333c56" stroke-width=".8"/>
      <circle cx="12" cy="12" r="3" fill="#e0a458"/>
      <circle cx="14.6" cy="7.9" r=".9" fill="#333c56"/>
    </svg>
    <div class="meta">
      <div class="title" id="npTitle"></div>
      <div class="artist" id="npArtist"></div>
    </div>
  </div>
  <div class="seekrow">
    <span class="t" id="curT">0:00</span>
    <input type="range" id="seek" min="0" max="100" value="0" step="1">
    <span class="t end" id="durT">0:00</span>
  </div>
  <div class="transport">
    <button id="prevBtn" aria-label="Previous">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zM20 6L10 12l10 6z"/></svg>
    </button>
    <button id="playBtn" class="play" aria-label="Play">
      <svg id="playIcon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
    </button>
    <button id="nextBtn" aria-label="Next">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M16 6h2v12h-2zM4 6l10 6-10 6z"/></svg>
    </button>
  </div>
</div>

<audio id="audio" preload="metadata"></audio>

<script>
const app = document.getElementById('app');
const countEl = document.getElementById('count');
const playerBar = document.getElementById('player');
const audio = document.getElementById('audio');
const disc = document.getElementById('disc');
const npTitle = document.getElementById('npTitle');
const npArtist = document.getElementById('npArtist');
const playBtn = document.getElementById('playBtn');
const playIcon = document.getElementById('playIcon');
const seek = document.getElementById('seek');
const curT = document.getElementById('curT');
const durT = document.getElementById('durT');
const searchInput = document.getElementById('search');
const clearBtn = document.getElementById('clearBtn');

const ICON_PLAY = '<path d="M8 5v14l11-7z"/>';
const ICON_PAUSE = '<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>';

let queue = [];
let currentIndex = -1;
let query = '';
let offset = 0;
const LIMIT = 100;
let total = 0;
let seeking = false;

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error('request failed (' + res.status + ')');
  return await res.json();
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtTime(sec) {
  if (!sec || !isFinite(sec) || sec < 0) return '0:00';
  sec = Math.floor(sec);
  const m = Math.floor(sec / 60), s = sec % 60;
  return m + ':' + String(s).padStart(2, '0');
}

function renderSkeleton() {
  app.innerHTML = Array.from({length: 6}).map(() => `
    <div class="skeleton">
      <div class="bar" style="width:24px;height:12px;"></div>
      <div style="flex:1;">
        <div class="bar" style="width:60%;margin-bottom:6px;"></div>
        <div class="bar" style="width:35%;height:9px;"></div>
      </div>
    </div>`).join('');
}

async function loadSongs(reset) {
  if (reset) { offset = 0; queue = []; renderSkeleton(); }
  const data = await api(`/api/songs?q=${encodeURIComponent(query)}&offset=${offset}&limit=${LIMIT}`);
  total = data.total;
  queue = queue.concat(data.songs);
  offset += data.songs.length;
  render(data.has_more);
}

function render(hasMore) {
  countEl.textContent = total ? `${total.toLocaleString()} song${total === 1 ? '' : 's'}` : '';
  clearBtn.style.display = query ? 'block' : 'none';

  if (queue.length === 0) {
    app.innerHTML = `<div class="muted-msg">No songs found.</div>`;
    return;
  }

  let html = queue.map((s, i) => `
    <div class="row ${i === currentIndex ? 'active' : ''}" data-i="${i}">
      <div class="idx">${String(i + 1).padStart(3, '0')}</div>
      <div class="meta">
        <div class="title">${escapeHtml(s.title)}</div>
        <div class="artist">${escapeHtml(s.artist)}</div>
      </div>
      <div class="dur">${s.duration ? fmtTime(s.duration) : ''}</div>
      <button class="playbtn" data-i="${i}" aria-label="Play ${escapeHtml(s.title)}">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </button>
    </div>
  `).join('');
  if (hasMore) html += `<button class="loadmore" id="loadMoreBtn">Load more</button>`;

  app.innerHTML = html;

  app.querySelectorAll('.row, .playbtn').forEach(el => {
    el.addEventListener('click', (e) => {
      const i = parseInt(e.currentTarget.getAttribute('data-i'), 10);
      playIndex(i);
    });
  });

  const loadMoreBtn = document.getElementById('loadMoreBtn');
  if (loadMoreBtn) loadMoreBtn.onclick = () => loadSongs(false);
}

let debounceTimer = null;
function debounce(fn, ms) {
  return (...args) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fn(...args), ms);
  };
}

searchInput.oninput = debounce(() => { query = searchInput.value; loadSongs(true); }, 350);
clearBtn.onclick = () => { searchInput.value = ''; query = ''; clearBtn.style.display = 'none'; loadSongs(true); searchInput.focus(); };

function playIndex(i) {
  if (i < 0 || i >= queue.length) return;
  currentIndex = i;
  const song = queue[i];
  audio.src = `/api/stream/${song.id}`;
  audio.play().catch(() => {});
  playerBar.classList.add('show');
  npTitle.textContent = song.title;
  npArtist.textContent = song.artist;
  highlightActive();
  updateMediaSession(song);
}

function highlightActive() {
  document.querySelectorAll('.row').forEach(el => {
    const i = parseInt(el.getAttribute('data-i'), 10);
    el.classList.toggle('active', i === currentIndex);
  });
}

function updateMediaSession(song) {
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: song.title || '', artist: song.artist || '', album: song.album || '',
    });
    navigator.mediaSession.setActionHandler('previoustrack', prevTrack);
    navigator.mediaSession.setActionHandler('nexttrack', nextTrack);
    navigator.mediaSession.setActionHandler('play', () => audio.play());
    navigator.mediaSession.setActionHandler('pause', () => audio.pause());
  }
}

function prevTrack() { if (currentIndex > 0) playIndex(currentIndex - 1); }
function nextTrack() { if (currentIndex + 1 < queue.length) playIndex(currentIndex + 1); }

audio.addEventListener('ended', nextTrack);
audio.addEventListener('play', () => {
  playIcon.outerHTML = `<svg id="playIcon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">${ICON_PAUSE}</svg>`;
  disc.classList.add('spin');
});
audio.addEventListener('pause', () => {
  const el = document.getElementById('playIcon');
  if (el) el.outerHTML = `<svg id="playIcon" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">${ICON_PLAY}</svg>`;
  disc.classList.remove('spin');
});
audio.addEventListener('loadedmetadata', () => {
  seek.max = Math.floor(audio.duration) || 0;
  durT.textContent = fmtTime(audio.duration);
});
audio.addEventListener('timeupdate', () => {
  if (seeking) return;
  seek.value = Math.floor(audio.currentTime);
  curT.textContent = fmtTime(audio.currentTime);
});

seek.addEventListener('input', () => { seeking = true; curT.textContent = fmtTime(seek.value); });
seek.addEventListener('change', () => { audio.currentTime = Number(seek.value); seeking = false; });

playBtn.onclick = () => { audio.paused ? audio.play() : audio.pause(); };
document.getElementById('prevBtn').onclick = prevTrack;
document.getElementById('nextBtn').onclick = nextTrack;

(async function init() {
  try {
    await loadSongs(true);
  } catch (err) {
    app.innerHTML = `<div class="error">Couldn't load the library: ${escapeHtml(String(err))}</div>`;
  }
})();
</script>
</body>
</html>
"""
