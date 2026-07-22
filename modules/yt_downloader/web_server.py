# modules/yt_downloader/web_server.py
#
# A small, dependency-free HTTP server (stdlib only) that lets the "Zs
# Multi Tool Companion" browser extension hand off a YouTube URL to this
# app's downloader — click a button on a YouTube tab, the video shows up
# downloading here, without any copy/paste. Also serves a mobile-friendly
# page (GET /) so you can paste a link and queue a download from your
# phone over Tailscale, same idea as Music Player and Security Vault —
# see remote_access_tab.py. Modeled directly on
# modules/music_player/web_server.py and core/services/vault_web_server.py.
#
# Security model:
#   - Binds to 127.0.0.1 ONLY. Reachable from the LAN/internet only via
#     `tailscale serve`'s HTTPS proxy (tailnet devices only) — see
#     core/services/tailscale_service.py — or from other local processes
#     on this same PC (the browser extension).
#   - No auth by default, matching the Music Player server: nothing
#     served here is sensitive the way vault passwords are, and Tailscale
#     membership is already the trust boundary. If you want an extra
#     step before your phone (or anyone else on your tailnet) can queue
#     a download, set an access code in the Settings tab — this gates
#     POST /api/download only; GET endpoints (status/job list) stay open
#     since they're read-only. Setting a code also applies to the browser
#     extension's requests, since they hit the same endpoint.
#   - Downloads only ever land in the folder configured on this page —
#     nothing can choose an arbitrary path.
#
# Threading model:
#   - Runs independently of the Tkinter UI thread. Each queued job runs
#     yt-dlp on its own background thread, so the extension gets an
#     immediate response and multiple downloads can be queued without
#     blocking each other or the app.
#   - Job state lives in an in-memory dict, polled by GET /api/jobs — the
#     desktop UI (if the YouTube Downloader page is open) can show the
#     same jobs, but the server works fine even if that page was never
#     opened.

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

try:
    import yt_dlp as youtube_dl
except ImportError:
    try:
        import youtube_dl
    except ImportError:
        youtube_dl = None

MAX_JOBS_KEPT = 25

_YOUTUBE_HOST_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE
)


def is_youtube_url(url: str) -> bool:
    return bool(url) and bool(_YOUTUBE_HOST_RE.match(url.strip()))


class _Handler(BaseHTTPRequestHandler):

    server_version = "YTDownloaderWeb/1.0"

    def log_message(self, fmt, *args):
        pass  # silence default stderr request logging

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------

    def _srv(self):
        return self.server.owner  # YTWebServer instance

    def _cors_headers(self):
        # Loopback-only, so a permissive CORS policy doesn't expose
        # anything beyond what any other local process could already
        # reach. Needed for the extension's background service worker
        # to fetch() this API from an extension:// origin.
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

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    # -------------------------------------------------
    # routing
    # -------------------------------------------------

    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _code_ok(self, srv):
        required = (srv.access_code or "").strip()
        if not required:
            return True
        sent = (self.headers.get("X-Access-Code") or "").strip()
        return sent == required

    def do_GET(self):
        path = urlsplit(self.path).path
        srv = self._srv()

        if path in ("/", "/index.html"):
            self._send_html(200, _mobile_page(bool((srv.access_code or "").strip())))
        elif path == "/api/status":
            self._send_json(200, {
                "ok": True,
                "ready": youtube_dl is not None,
                "output_dir": srv.get_output_dir(),
                "default_format": srv.default_format,
                "default_type": srv.default_type,
            })
        elif path == "/api/jobs":
            self._send_json(200, {"ok": True, "jobs": srv.list_jobs()})
        elif path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):]
            job = srv.get_job(job_id)
            if job is None:
                self._send_json(404, {"ok": False, "error": "unknown job id"})
            else:
                self._send_json(200, {"ok": True, "job": job})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        srv = self._srv()

        if path == "/api/download":
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return

            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return

            url = (body.get("url") or "").strip()
            if not url:
                self._send_json(400, {"ok": False, "error": "missing 'url'"})
                return
            if not is_youtube_url(url):
                self._send_json(400, {"ok": False, "error": "not a youtube.com / youtu.be URL"})
                return
            if youtube_dl is None:
                self._send_json(503, {"ok": False, "error": "yt-dlp is not installed on this machine"})
                return

            fmt = body.get("format") or srv.default_format
            dl_type = body.get("type") or srv.default_type
            quality = str(body.get("quality") or srv.default_quality)
            if fmt not in ("mp3", "mp4"):
                fmt = srv.default_format
            if dl_type not in ("video", "playlist"):
                dl_type = srv.default_type

            job = srv.queue_download(url=url, fmt=fmt, dl_type=dl_type, quality=quality)
            self._send_json(200, {"ok": True, "job": job})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})


class YTWebServer:
    """Loopback HTTP server that queues yt-dlp downloads for the browser
    extension. Independent of any open UI page — safe to auto-start."""

    def __init__(self, get_output_dir, get_cookie_file=None, get_ffmpeg_dir=None,
                 default_format="mp4", default_type="video", default_quality="192"):
        # Callables so settings changed later in the UI (output folder,
        # cookie file) are picked up on the next download, not frozen at
        # server-start time.
        self._get_output_dir = get_output_dir
        self._get_cookie_file = get_cookie_file or (lambda: "")
        self._get_ffmpeg_dir = get_ffmpeg_dir or (lambda: None)

        self.default_format = default_format
        self.default_type = default_type
        self.default_quality = default_quality
        self.access_code = ""   # optional — see _code_ok() above; blank = no gate

        self.port = None
        self._httpd = None
        self._thread = None

        self._jobs = {}          # id -> job dict
        self._job_order = []     # insertion order, oldest first
        self._jobs_lock = threading.Lock()

        # Populated by the UI page (if open) so jobs also show up there.
        self.on_job_update = None  # callback(job_dict)

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

    def get_output_dir(self):
        try:
            return self._get_output_dir() or ""
        except Exception:
            return ""

    # ---- jobs --------------------------------------------------------

    def list_jobs(self):
        with self._jobs_lock:
            return [self._jobs[jid] for jid in self._job_order]

    def get_job(self, job_id):
        with self._jobs_lock:
            return self._jobs.get(job_id)

    def queue_download(self, url, fmt, dl_type, quality):
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "url": url,
            "format": fmt,
            "type": dl_type,
            "quality": quality,
            "status": "queued",   # queued -> downloading -> done | error
            "percent": 0.0,
            "message": "Queued…",
            "created_at": time.time(),
        }
        with self._jobs_lock:
            self._jobs[job_id] = job
            self._job_order.append(job_id)
            while len(self._job_order) > MAX_JOBS_KEPT:
                old_id = self._job_order.pop(0)
                self._jobs.pop(old_id, None)
        self._notify(job)

        threading.Thread(target=self._run_job, args=(job_id,), daemon=True).start()
        return job

    def _notify(self, job):
        if self.on_job_update:
            try:
                self.on_job_update(dict(job))
            except Exception:
                pass

    def _update_job(self, job_id, **patch):
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(patch)
            job_copy = dict(job)
        self._notify(job_copy)

    def _run_job(self, job_id):
        import os

        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            url, fmt, dl_type, quality = job["url"], job["format"], job["type"], job["quality"]

        output_dir = self.get_output_dir()
        cookie = ""
        try:
            cookie = self._get_cookie_file() or ""
        except Exception:
            pass
        ffmpeg_dir = None
        try:
            ffmpeg_dir = self._get_ffmpeg_dir()
        except Exception:
            pass

        if not output_dir or not os.path.isdir(output_dir):
            self._update_job(job_id, status="error", message="No valid output folder configured — "
                                                               "open YouTube Downloader in the app and set one.")
            return

        self._update_job(job_id, status="downloading", message="Starting…")

        def progress_hook(d):
            if d.get("status") == "downloading":
                pct_str = (d.get("_percent_str") or "").replace("\x1b[0K", "").strip()
                try:
                    pct = float(pct_str.replace("%", "")) / 100
                except Exception:
                    pct = self._jobs.get(job_id, {}).get("percent", 0.0)
                speed = (d.get("_speed_str") or "").replace("\x1b[0K", "").strip()
                eta = (d.get("_eta_str") or "").replace("\x1b[0K", "").strip()
                self._update_job(job_id, percent=pct, message=f"{pct_str}  {speed}  ETA {eta}".strip())
            elif d.get("status") == "finished":
                self._update_job(job_id, percent=1.0, message="Post-processing…")

        if dl_type == "playlist":
            outtmpl = os.path.join(output_dir, "%(playlist)s", "%(title)s.%(ext)s")
        else:
            outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

        if cookie:
            player_clients = ["web", "mweb", "tv"]
        else:
            player_clients = ["default", "android", "ios"]

        opts = {
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": dl_type != "playlist",
            "windowsfilenames": True,
            "retries": 10,
            "fragment_retries": 10,
            "ignoreerrors": dl_type == "playlist",
            "progress_hooks": [progress_hook],
            "extractor_args": {"youtube": {"player_client": player_clients}},
        }
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir
        if cookie and os.path.exists(cookie):
            opts["cookiefile"] = os.path.abspath(cookie)

        if fmt == "mp3":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }]
        else:
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mp4"

        try:
            try:
                with youtube_dl.YoutubeDL(opts) as ydl:
                    ret = ydl.download([url])
            except youtube_dl.utils.DownloadError as e:
                if "403" in str(e) and opts.get("format") != "18/best":
                    fallback_opts = dict(opts)
                    fallback_opts["format"] = "18/best"
                    with youtube_dl.YoutubeDL(fallback_opts) as ydl:
                        ret = ydl.download([url])
                else:
                    raise

            if ret:
                self._update_job(job_id, status="error", message="Finished with errors — see the app's download log.")
            else:
                self._update_job(job_id, status="done", percent=1.0, message="Done")
        except Exception as e:
            self._update_job(job_id, status="error", message=str(e))


# =====================================================
# MOBILE PAGE (single file, no build step, no external requests)
# =====================================================

def _mobile_page(needs_code: bool) -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>YouTube Downloader</title>
<style>
  :root {
    --bg:#0f1115; --panel:#151922; --card:#1b2030; --accent:#a78bfa;
    --text:#e8ecf1; --muted:#8a93a6; --danger:#e0555f; --success:#3ecf8e;
  }
  * { box-sizing: border-box; }
  body {
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-tap-highlight-color: transparent;
  }
  .wrap { max-width:520px; margin:0 auto; padding:20px 16px 60px; }
  h1 { font-size:22px; margin:10px 0 20px; }
  .panel { background:var(--panel); border-radius:14px; padding:16px; margin-bottom:14px; }
  input, select {
    width:100%; padding:14px; border-radius:10px; border:1px solid #252d3d;
    background:var(--card); color:var(--text); font-size:16px; margin-bottom:10px;
  }
  .row2 { display:flex; gap:10px; }
  .row2 > * { flex:1; }
  button {
    width:100%; padding:14px; border-radius:10px; border:none;
    background:var(--accent); color:#0b0d10; font-weight:700; font-size:16px;
  }
  .card { background:var(--card); border-radius:12px; padding:14px; margin-bottom:10px; }
  .card .url { font-size:13px; word-break:break-all; color:var(--muted); }
  .card .msg { font-size:14px; margin-top:6px; }
  .bar { height:6px; border-radius:3px; background:#252d3d; margin-top:8px; overflow:hidden; }
  .bar > div { height:100%; background:var(--accent); }
  .status-done { color:var(--success); }
  .status-error { color:var(--danger); }
  .error { color:var(--danger); font-size:14px; margin:-4px 0 10px; }
  .muted { color:var(--muted); font-size:13px; }
</style>
</head>
<body>
<div class="wrap" id="app"></div>
<script>
const NEEDS_CODE = __NEEDS_CODE__;
const app = document.getElementById('app');
let accessCode = NEEDS_CODE ? (sessionStorage.getItem('yt_access_code') || '') : '';

function headers(extra) {
  const h = Object.assign({ 'Content-Type': 'application/json' }, extra || {});
  if (accessCode) h['X-Access-Code'] = accessCode;
  return h;
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign({}, opts || {}, { headers: headers((opts || {}).headers) }));
  let data = {};
  try { data = await res.json(); } catch (e) {}
  return { ok: res.ok, status: res.status, data };
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function render() {
  app.innerHTML = `
    <h1>&#9195;&#65039; YouTube Downloader</h1>
    <div class="panel">
      <input id="url" type="url" placeholder="Paste a YouTube link" autofocus>
      <div class="row2">
        <select id="type"><option value="video">Video</option><option value="playlist">Playlist</option></select>
        <select id="format"><option value="mp4">mp4</option><option value="mp3">mp3</option></select>
      </div>
      <div id="err" class="error" style="display:none;"></div>
      <button id="goBtn">Queue Download</button>
    </div>
    <div id="jobs"></div>
    <div class="muted">Reachable only from devices on your Tailscale network.</div>
  `;
  document.getElementById('goBtn').onclick = submit;
  document.getElementById('url').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  refreshJobs();
}

async function submit() {
  const url = document.getElementById('url').value.trim();
  const errEl = document.getElementById('err');
  errEl.style.display = 'none';
  if (!url) return;

  if (NEEDS_CODE && !accessCode) {
    const entered = prompt('Access code required:');
    if (!entered) return;
    accessCode = entered.trim();
    sessionStorage.setItem('yt_access_code', accessCode);
  }

  const type = document.getElementById('type').value;
  const format = document.getElementById('format').value;
  const r = await api('/api/download', { method: 'POST', body: JSON.stringify({ url, type, format }) });
  if (!r.ok) {
    if (r.status === 401) { accessCode = ''; sessionStorage.removeItem('yt_access_code'); }
    errEl.textContent = r.data.error || 'Failed to queue download.';
    errEl.style.display = 'block';
    return;
  }
  document.getElementById('url').value = '';
  refreshJobs();
}

async function refreshJobs() {
  const r = await api('/api/jobs');
  const el = document.getElementById('jobs');
  if (!el) return;
  const jobs = (r.data.jobs || []).slice().reverse();
  if (jobs.length === 0) {
    el.innerHTML = '<div class="muted">No downloads yet.</div>';
    return;
  }
  el.innerHTML = jobs.map(j => `
    <div class="card">
      <div class="url">${escapeHtml(j.url)}</div>
      <div class="msg ${j.status === 'done' ? 'status-done' : j.status === 'error' ? 'status-error' : ''}">${escapeHtml(j.message || j.status)}</div>
      ${j.status === 'downloading' || j.status === 'queued' ? `<div class="bar"><div style="width:${Math.round((j.percent||0)*100)}%"></div></div>` : ''}
    </div>
  `).join('');
}

render();
setInterval(refreshJobs, 3000);
</script>
</body>
</html>
""".replace("__NEEDS_CODE__", "true" if needs_code else "false")
