# modules/notes/web_server.py
#
# A small, dependency-free HTTP server (stdlib only) that lets you read,
# add, edit, pin, and delete notes from your phone over Tailscale — same
# pattern as Music Player and YouTube Downloader. Modeled directly on
# modules/yt_downloader/web_server.py.
#
# Security model:
#   - Binds to 127.0.0.1 ONLY. Reachable only via `tailscale serve`'s
#     HTTPS proxy (tailnet devices only) — see core/services/tailscale_service.py.
#   - No auth by default, matching Music Player — Tailscale membership is
#     the trust boundary. Notes aren't treated as sensitive as vault
#     passwords; if that's wrong for you, the same access-code gate used
#     in yt_downloader/web_server.py can be ported over here.
#
# Threading model:
#   - Talks directly to modules/notes/storage.py, which is itself just
#     atomic JSON read/write — safe to call from this server's thread
#     independent of whether the desktop Notes page is open.

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from . import storage


class _Handler(BaseHTTPRequestHandler):

    server_version = "NotesWeb/1.0"

    def log_message(self, fmt, *args):
        pass  # silence default stderr request logging

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _cors_headers(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        parts = urlsplit(self.path)
        path = parts.path
        qs = parse_qs(parts.query)

        if path in ("/", "/index.html"):
            self._send_html(200, _PAGE_SHELL)
        elif path == "/api/notes":
            query = (qs.get("q") or [""])[0]
            notes = storage.search_notes(query) if query else storage.get_notes()
            self._send_json(200, {"notes": notes})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parts = urlsplit(self.path)
        segs = [s for s in parts.path.split("/") if s]
        # /api/notes                -> create
        # /api/notes/<id>/update    -> update
        # /api/notes/<id>/delete    -> delete
        # /api/notes/<id>/pin       -> toggle pin
        body = self._read_json_body()

        if segs == ["api", "notes"]:
            note = storage.create_note(
                title=body.get("title", ""),
                body=body.get("body", ""),
                links=body.get("links"),
            )
            self._send_json(200, {"ok": True, "note": note})
            return

        if len(segs) == 3 and segs[0] == "api" and segs[1] == "notes":
            note_id, action = segs[2], None
        elif len(segs) == 4 and segs[0] == "api" and segs[1] == "notes":
            note_id, action = segs[2], segs[3]
        else:
            self._send_json(404, {"error": "not found"})
            return

        if len(segs) == 4:
            if action == "update":
                note = storage.update_note(
                    note_id,
                    title=body.get("title"),
                    body=body.get("body"),
                    links=body.get("links"),
                )
                if note is None:
                    self._send_json(404, {"error": "note not found"})
                else:
                    self._send_json(200, {"ok": True, "note": note})
            elif action == "delete":
                storage.delete_note(note_id)
                self._send_json(200, {"ok": True})
            elif action == "pin":
                note = storage.toggle_pin(note_id)
                if note is None:
                    self._send_json(404, {"error": "note not found"})
                else:
                    self._send_json(200, {"ok": True, "note": note})
            else:
                self._send_json(404, {"error": "not found"})
        else:
            self._send_json(404, {"error": "not found"})


class NotesWebServer:
    """Loopback HTTP server exposing Notes to your phone. Independent of
    any open UI page — safe to auto-start, same shape as YTWebServer."""

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


_PAGE_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Notes</title>
<style>
  :root {
    --bg:#0f1115; --panel:#151922; --card:#1b2030; --accent:#4ea1ff;
    --text:#e8ecf1; --muted:#8a93a6; --danger:#e5484d;
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    padding-bottom: 90px;
  }
  header {
    position:sticky; top:0; background:var(--panel); z-index:5;
    padding:14px 16px; border-bottom:1px solid #232838;
    display:flex; gap:10px; align-items:center;
  }
  header h1 { font-size:17px; margin:0; flex:1; }
  input[type=text], textarea {
    width:100%; background:var(--card); border:1px solid #2a3145; border-radius:8px;
    color:var(--text); padding:10px 12px; font-size:14px; font-family:inherit;
  }
  textarea { min-height:120px; resize:vertical; }
  .search { flex:1; }
  .wrap { max-width:640px; margin:0 auto; padding:12px 16px; }
  .note {
    background:var(--card); border-radius:12px; padding:14px 16px; margin-bottom:10px;
    border:1px solid #232838; cursor:pointer;
  }
  .note .title { font-weight:600; font-size:15px; display:flex; align-items:center; gap:6px; }
  .note .body-preview { color:var(--muted); font-size:13px; margin-top:4px;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
  .pin { color:var(--accent); }
  .fab {
    position:fixed; right:20px; bottom:24px; width:54px; height:54px; border-radius:50%;
    background:var(--accent); color:#0b0d10; font-size:26px; border:none;
    display:flex; align-items:center; justify-content:center; box-shadow:0 4px 14px rgba(0,0,0,.4);
  }
  .overlay {
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:20;
    align-items:flex-end; justify-content:center;
  }
  .overlay.show { display:flex; }
  .sheet {
    background:var(--panel); width:100%; max-width:640px; border-radius:16px 16px 0 0;
    padding:18px 16px 24px; max-height:88vh; overflow-y:auto;
  }
  .row { display:flex; gap:8px; margin-top:10px; }
  .row button {
    flex:1; padding:11px; border-radius:8px; border:none; font-size:14px; font-weight:600;
  }
  .btn-save { background:var(--accent); color:#0b0d10; }
  .btn-delete { background:#3a1f22; color:var(--danger); }
  .btn-cancel { background:var(--card); color:var(--text); }
  .muted-msg { color:var(--muted); text-align:center; padding:40px 0; }
</style>
</head>
<body>
<header>
  <h1>📝 Notes</h1>
</header>
<div class="wrap">
  <input type="text" class="search" id="search" placeholder="Search notes...">
  <div id="list" style="margin-top:14px;"></div>
</div>

<button class="fab" id="addBtn">+</button>

<div class="overlay" id="overlay">
  <div class="sheet">
    <input type="text" id="editTitle" placeholder="Title">
    <textarea id="editBody" placeholder="Write something..." style="margin-top:10px;"></textarea>
    <div class="row">
      <button class="btn-cancel" id="cancelBtn">Cancel</button>
      <button class="btn-delete" id="deleteBtn" style="display:none;">Delete</button>
      <button class="btn-save" id="saveBtn">Save</button>
    </div>
  </div>
</div>

<script>
const list = document.getElementById('list');
const search = document.getElementById('search');
const overlay = document.getElementById('overlay');
const editTitle = document.getElementById('editTitle');
const editBody = document.getElementById('editBody');
const saveBtn = document.getElementById('saveBtn');
const deleteBtn = document.getElementById('deleteBtn');
const cancelBtn = document.getElementById('cancelBtn');
const addBtn = document.getElementById('addBtn');

let notes = [];
let editingId = null;

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadNotes(q) {
  const res = await fetch('/api/notes' + (q ? '?q=' + encodeURIComponent(q) : ''));
  const data = await res.json();
  notes = data.notes;
  render();
}

function render() {
  if (notes.length === 0) {
    list.innerHTML = '<div class="muted-msg">No notes yet.</div>';
    return;
  }
  list.innerHTML = notes.map(n => `
    <div class="note" data-id="${n.id}">
      <div class="title">${n.pinned ? '<span class="pin">📌</span>' : ''}${escapeHtml(n.title)}</div>
      <div class="body-preview">${escapeHtml(n.body)}</div>
    </div>
  `).join('');
  list.querySelectorAll('.note').forEach(el => {
    el.addEventListener('click', () => openEditor(el.getAttribute('data-id')));
  });
}

let debounceTimer = null;
search.oninput = () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => loadNotes(search.value), 300);
};

function openEditor(id) {
  editingId = id;
  if (id) {
    const n = notes.find(n => n.id === id);
    editTitle.value = n.title;
    editBody.value = n.body;
    deleteBtn.style.display = 'block';
  } else {
    editTitle.value = '';
    editBody.value = '';
    deleteBtn.style.display = 'none';
  }
  overlay.classList.add('show');
}

function closeEditor() {
  overlay.classList.remove('show');
  editingId = null;
}

addBtn.onclick = () => openEditor(null);
cancelBtn.onclick = closeEditor;

saveBtn.onclick = async () => {
  const title = editTitle.value.trim() || 'Untitled';
  const body = editBody.value;
  if (editingId) {
    await fetch(`/api/notes/${editingId}/update`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, body}),
    });
  } else {
    await fetch('/api/notes', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, body}),
    });
  }
  closeEditor();
  loadNotes(search.value);
};

deleteBtn.onclick = async () => {
  if (!editingId) return;
  await fetch(`/api/notes/${editingId}/delete`, {method: 'POST'});
  closeEditor();
  loadNotes(search.value);
};

loadNotes('');
</script>
</body>
</html>
"""
