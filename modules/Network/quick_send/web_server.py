# modules/quick_send/web_server.py
#
# LocalSend-style file transfer, but scoped to your own Tailscale mesh
# instead of local-network mDNS discovery — same trust model as every
# other module here (Tailscale membership = the access boundary).
#
# Two directions, both through this one server:
#   - Phone -> PC ("Send to PC"): phone POSTs a file, it lands in your
#     Inbox folder (default ~/Downloads/Quick Send Inbox).
#   - PC -> Phone ("Get from PC"): phone browses/downloads whatever's
#     in your Outbox folder (default ~/Desktop/Quick Send Shared) — you
#     drop files there from the desktop and your phone can pull them.
#
# No third-party deps: multipart/form-data is parsed by hand below
# since the stdlib's http.server doesn't include a parser and this
# project avoids extra pip dependencies where stdlib will do.

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote

from . import storage


# ---------------------------------------------------------------------
# Minimal multipart/form-data parser — just enough for file inputs.
# Reads the whole body into memory; fine for the phone-to-PC file sizes
# this is realistically used for (docs, photos, the odd zip). If you
# routinely send multi-GB files, this would want to stream to disk
# instead of buffering — not implemented here.
# ---------------------------------------------------------------------

def _parse_multipart(body: bytes, boundary: bytes):
    parts = body.split(b"--" + boundary)
    files = []
    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n")
        headers = header_blob.decode("utf-8", errors="ignore")
        if "filename=" not in headers:
            continue  # a plain form field, not a file — skip
        filename = None
        for piece in headers.split(";"):
            piece = piece.strip()
            if piece.startswith("filename="):
                filename = piece.split("=", 1)[1].strip('"')
        if not filename:
            continue
        filename = unquote(filename)
        files.append((os.path.basename(filename), content))
    return files


class _Handler(BaseHTTPRequestHandler):

    server_version = "QuickSendWeb/1.0"

    def log_message(self, fmt, *args):
        pass

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

    # -------------------------------------------------
    # GET
    # -------------------------------------------------

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path

        if path in ("/", "/index.html"):
            self._send_html(200, _PAGE_SHELL)
            return

        if path == "/api/status":
            cfg = storage.get_config()
            self._send_json(200, {"ok": True, "outbox_count": len(storage.list_outbox_files())})
            return

        if path == "/api/outbox":
            self._send_json(200, {"files": storage.list_outbox_files()})
            return

        if path.startswith("/api/outbox/"):
            self._handle_download(unquote(path[len("/api/outbox/"):]))
            return

        self._send_json(404, {"error": "not found"})

    def _handle_download(self, name):
        cfg = storage.get_config()
        full = os.path.join(cfg["outbox_dir"], os.path.basename(name))
        if not os.path.isfile(full):
            self._send_json(404, {"error": "file not found"})
            return
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(full)}"',
        )
        self._cors_headers()
        self.end_headers()
        with open(full, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

    # -------------------------------------------------
    # POST — upload from phone
    # -------------------------------------------------

    def do_POST(self):
        parts = urlsplit(self.path)
        if parts.path != "/api/send":
            self._send_json(404, {"error": "not found"})
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type or "boundary=" not in content_type:
            self._send_json(400, {"error": "expected multipart/form-data upload"})
            return

        boundary = content_type.split("boundary=", 1)[1].strip().encode()
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            self._send_json(400, {"error": "empty body"})
            return
        if length > 500 * 1024 * 1024:  # 500MB sanity cap
            self._send_json(413, {"error": "file too large (500MB limit)"})
            return

        body = self.rfile.read(length)
        files = _parse_multipart(body, boundary)
        if not files:
            self._send_json(400, {"error": "no files found in upload"})
            return

        cfg = storage.get_config()
        saved = []
        for filename, content in files:
            if not filename:
                continue
            dest = storage.unique_path(cfg["inbox_dir"], filename)
            try:
                with open(dest, "wb") as f:
                    f.write(content)
                storage.log_received(os.path.basename(dest), len(content))
                saved.append(os.path.basename(dest))
            except Exception as e:
                self._send_json(500, {"error": f"failed saving {filename}: {e}"})
                return

        self._send_json(200, {"ok": True, "saved": saved})


class QuickSendWebServer:
    """Loopback HTTP server for phone<->PC file transfer. Same shape as
    NotesWebServer/GamingHubWebServer — safe to auto-start from Remote
    Hub, independent of whether any Quick Send desktop tab is open."""

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
<title>Quick Send</title>
<style>
  :root { --bg:#0f1115; --panel:#151922; --card:#1b2030; --accent:#4ea1ff; --text:#e8ecf1; --muted:#8a93a6; --green:#3ddc84; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  header { position:sticky; top:0; background:var(--panel); padding:14px 16px; border-bottom:1px solid #232838; }
  header h1 { font-size:17px; margin:0; }
  .wrap { max-width:640px; margin:0 auto; padding:16px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin:22px 0 10px; }
  .dropzone {
    border:2px dashed #2a3145; border-radius:14px; padding:32px 16px; text-align:center; color:var(--muted);
  }
  .dropzone.drag { border-color:var(--accent); color:var(--accent); background:rgba(78,161,255,.06); }
  input[type=file] { display:none; }
  .pickbtn { background:var(--accent); color:#0b0d10; border:none; border-radius:8px; padding:10px 18px; font-weight:600; margin-top:10px; }
  .file { background:var(--card); border-radius:10px; padding:12px 14px; margin-bottom:8px; border:1px solid #232838;
    display:flex; align-items:center; justify-content:space-between; gap:10px; }
  .fname { font-size:14px; }
  .fmeta { color:var(--muted); font-size:11px; margin-top:2px; }
  a.dl { color:var(--accent); font-size:13px; font-weight:600; text-decoration:none; }
  .muted-msg { color:var(--muted); text-align:center; padding:20px 0; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--green); color:#0b0d10;
    padding:10px 18px; border-radius:20px; font-size:13px; font-weight:600; opacity:0; transition:opacity .3s; pointer-events:none; }
  .toast.show { opacity:1; }
</style>
</head>
<body>
<header><h1>📤 Quick Send</h1></header>
<div class="wrap">
  <h2>Send to PC</h2>
  <div class="dropzone" id="drop">
    Tap to choose a file, or drag one here
    <div><button class="pickbtn" id="pickBtn">Choose file</button></div>
    <input type="file" id="fileInput" multiple>
  </div>

  <h2>Get from PC</h2>
  <div id="outbox"></div>
</div>
<div class="toast" id="toast"></div>

<script>
const drop = document.getElementById('drop');
const fileInput = document.getElementById('fileInput');
const pickBtn = document.getElementById('pickBtn');
const outbox = document.getElementById('outbox');
const toast = document.getElementById('toast');

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2200);
}

function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1024/1024).toFixed(1) + ' MB';
}
function escapeHtml(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

pickBtn.onclick = () => fileInput.click();
fileInput.onchange = () => sendFiles(fileInput.files);

['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('drag'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('drag'); }));
drop.addEventListener('drop', e => { if (e.dataTransfer.files.length) sendFiles(e.dataTransfer.files); });

async function sendFiles(fileList) {
  const form = new FormData();
  for (const f of fileList) form.append('file', f, f.name);
  showToast('Sending…');
  try {
    const res = await fetch('/api/send', { method: 'POST', body: form });
    const data = await res.json();
    if (data.ok) { showToast('Sent to PC ✓'); }
    else { showToast('Failed: ' + (data.error || 'unknown error')); }
  } catch (e) {
    showToast('Failed: ' + e);
  }
  fileInput.value = '';
}

async function loadOutbox() {
  const res = await fetch('/api/outbox');
  const data = await res.json();
  if (data.files.length === 0) {
    outbox.innerHTML = '<div class="muted-msg">Nothing shared yet — drop a file in your Quick Send Shared folder on the PC.</div>';
    return;
  }
  outbox.innerHTML = data.files.map(f => `
    <div class="file">
      <div><div class="fname">${escapeHtml(f.name)}</div><div class="fmeta">${fmtSize(f.size)}</div></div>
      <a class="dl" href="/api/outbox/${encodeURIComponent(f.name)}" download>Download</a>
    </div>`).join('');
}

loadOutbox();
setInterval(loadOutbox, 5000);
</script>
</body>
</html>
"""
