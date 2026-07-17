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

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        elif path == "/api/songs":
            self._handle_songs(qs)
        elif path.startswith("/api/stream/"):
            self._handle_stream(path[len("/api/stream/"):], send_body=True)
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
    """

    def __init__(self, library=None):
        self.library = library or musicdb.Library()
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
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Music Player</title>
<style>
  :root {
    --bg:#0f1115; --panel:#151922; --card:#1b2030; --accent:#a78bfa;
    --text:#e8ecf1; --muted:#8a93a6; --success:#3ecf8e;
  }
  * { box-sizing: border-box; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-tap-highlight-color: transparent;
  }
  .wrap { max-width:560px; margin:0 auto; padding:16px 14px 160px; }
  h1 { font-size:20px; margin:6px 0 16px; }
  input[type=search] {
    width:100%; padding:13px; border-radius:10px; border:1px solid #252d3d;
    background:var(--card); color:var(--text); font-size:16px; margin-bottom:12px;
  }
  .count { color:var(--muted); font-size:13px; margin:-6px 0 10px; }
  .row {
    display:flex; align-items:center; gap:10px;
    background:var(--card); border-radius:10px; padding:12px 14px; margin-bottom:8px;
  }
  .row.active { outline:2px solid var(--accent); }
  .row .meta { flex:1; min-width:0; }
  .row .title { font-weight:600; font-size:15px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .row .artist { color:var(--muted); font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .row .playbtn {
    flex-shrink:0; width:36px; height:36px; border-radius:50%; border:none;
    background:var(--accent); color:#0b0d10; font-size:14px;
  }
  .loadmore {
    width:100%; padding:12px; border-radius:10px; border:none;
    background:var(--card); color:var(--muted); font-weight:600; margin-top:6px;
  }
  .muted { color:var(--muted); font-size:13px; text-align:center; padding:20px 0; }
  .player {
    position:fixed; left:0; right:0; bottom:0; background:var(--panel);
    border-top:1px solid #252d3d; padding:10px 14px 16px;
  }
  .player .now { font-size:14px; margin-bottom:8px; }
  .player .now .title { font-weight:700; }
  .player .now .artist { color:var(--muted); }
  .transport { display:flex; align-items:center; justify-content:center; gap:18px; margin-bottom:6px; }
  .transport button {
    background:none; border:none; color:var(--text); font-size:24px; padding:6px 10px;
  }
  .transport button.play { font-size:32px; color:var(--accent); }
  audio { width:100%; height:32px; }
  .error { color:#e07a7a; font-size:13px; text-align:center; padding:10px; }
</style>
</head>
<body>
<div class="wrap" id="app"></div>
<div class="player" id="player" style="display:none;">
  <div class="now" id="now"></div>
  <div class="transport">
    <button id="prevBtn">⏮</button>
    <button id="playBtn" class="play">▶</button>
    <button id="nextBtn">⏭</button>
  </div>
  <audio id="audio" preload="metadata"></audio>
</div>
<script>
const app = document.getElementById('app');
const playerBar = document.getElementById('player');
const audio = document.getElementById('audio');
const nowEl = document.getElementById('now');
const playBtn = document.getElementById('playBtn');

let queue = [];       // current search-result song list
let currentIndex = -1;
let query = '';
let offset = 0;
const LIMIT = 100;
let total = 0;

async function api(path) {
  const res = await fetch(path);
  return await res.json();
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtRow(song) {
  return song.artist ? `${song.artist} - ${song.title}` : song.title;
}

async function loadSongs(reset) {
  if (reset) { offset = 0; queue = []; }
  const data = await api(`/api/songs?q=${encodeURIComponent(query)}&offset=${offset}&limit=${LIMIT}`);
  total = data.total;
  queue = queue.concat(data.songs);
  offset += data.songs.length;
  render(data.has_more);
}

function render(hasMore) {
  let html = `<h1>🎵 Music Player</h1>
    <input type="search" id="search" placeholder="Search title / artist / album…" value="${escapeHtml(query)}">
    <div class="count">${total.toLocaleString()} songs</div>`;

  if (queue.length === 0) {
    html += `<div class="muted">No songs found.</div>`;
  } else {
    html += queue.map((s, i) => `
      <div class="row ${i === currentIndex ? 'active' : ''}" data-i="${i}">
        <div class="meta">
          <div class="title">${escapeHtml(s.title)}</div>
          <div class="artist">${escapeHtml(s.artist)}</div>
        </div>
        <button class="playbtn" data-i="${i}">▶</button>
      </div>
    `).join('');
    if (hasMore) html += `<button class="loadmore" id="loadMoreBtn">Load more…</button>`;
  }

  app.innerHTML = html;

  const search = document.getElementById('search');
  search.oninput = debounce(() => { query = search.value; loadSongs(true); }, 350);
  search.focus = search.focus; // no-op, avoid re-focus stealing on rerender

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

function playIndex(i) {
  if (i < 0 || i >= queue.length) return;
  currentIndex = i;
  const song = queue[i];
  audio.src = `/api/stream/${song.id}`;
  audio.play().catch(() => {});
  playerBar.style.display = 'block';
  nowEl.innerHTML = `<div class="title">${escapeHtml(song.title)}</div><div class="artist">${escapeHtml(song.artist)}</div>`;
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
audio.addEventListener('play', () => { playBtn.textContent = '⏸'; });
audio.addEventListener('pause', () => { playBtn.textContent = '▶'; });

playBtn.onclick = () => { audio.paused ? audio.play() : audio.pause(); };
document.getElementById('prevBtn').onclick = prevTrack;
document.getElementById('nextBtn').onclick = nextTrack;

(async function init() {
  try {
    await loadSongs(true);
  } catch (err) {
    app.innerHTML = `<h1>🎵 Music Player</h1><div class="error">Couldn't load the library: ${escapeHtml(String(err))}</div>`;
  }
})();
</script>
</body>
</html>
"""
