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
# Also hosts the channel watcher (channel_watcher.py): add a channel or
# playlist link once ("Watch" tab, /api/channels), and new uploads get
# queued through the same job pipeline automatically, on a background
# thread, whether or not the phone/extension server is even turned on.
# Everything already downloaded — this session or a past one — is
# browsable straight off disk via library.py ("Library" tab, /api/library),
# since the in-memory job list resets on every app restart.
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
#     POST /api/download, POST /api/channels, POST /api/channels/<id>/check
#     and DELETE /api/channels/<id>; GET endpoints (status/job list,
#     channel list, library) stay open since they're read-only. Setting a
#     code also applies to the browser extension's requests, since they
#     hit the same endpoint.
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
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from core import paths
from core.services import device_trust

from . import library, metadata_tag
from .channel_watcher import ChannelWatcher

SETTINGS_FILE = paths.migrate_legacy_file(
    paths.data_path("yt_downloader", "downloader_settings.json"),
    "modules", "yt_downloader", "downloader_settings.json",
)

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

_JOB_FILE_RE = re.compile(r"^/api/jobs/([^/]+)/download/(\d+)$")
_CHANNEL_ID_RE = re.compile(r"^/api/channels/([^/]+)$")
_CHANNEL_CHECK_RE = re.compile(r"^/api/channels/([^/]+)/check$")


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code, X-Device-Id, X-Device-Ts, X-Device-Sig")
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

    def _serve_job_file(self, srv, job_id, index):
        path = srv.get_job_file_path(job_id, index)
        if path is None:
            self._send_json(404, {"ok": False, "error": "file not found — job incomplete, index out of range, or the file has since moved"})
            return
        self._serve_file(path)

    def _serve_library_file(self, srv, rel_path):
        path = library.resolve_library_file(srv.get_output_dir(), rel_path)
        if path is None:
            self._send_json(404, {"ok": False, "error": "file not found"})
            return
        self._serve_file(path)

    def _serve_file(self, path):
        file_size = os.path.getsize(path)
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        range_header = self.headers.get("Range")

        start, end = 0, file_size - 1
        status = 200
        if range_header and range_header.startswith("bytes="):
            # Supports the single-range case (bytes=START-END or
            # bytes=START-), which covers Safari/iOS's download and
            # scrub-preview requests — same pattern as the music server's
            # streaming endpoint.
            try:
                range_spec = range_header.split("=", 1)[1]
                start_str, _, end_str = range_spec.partition("-")
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                end = min(end, file_size - 1)
                status = 206
            except (ValueError, IndexError):
                start, end = 0, file_size - 1
                status = 200

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{os.path.basename(path)}"',
        )
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self._cors_headers()
        self.end_headers()

        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk_size = 256 * 1024
                while remaining > 0:
                    chunk = f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client cancelled/disconnected mid-transfer — not an error

    def do_GET(self):
        if not device_trust.allow_handler(self):
            return
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
        elif _JOB_FILE_RE.match(path):
            m = _JOB_FILE_RE.match(path)
            self._serve_job_file(srv, m.group(1), int(m.group(2)))
        elif path == "/api/channels":
            self._send_json(200, {"ok": True, "channels": srv.channel_watcher.list_channels()})
        elif path == "/api/library":
            self._send_json(200, {"ok": True, "files": library.scan_library(srv.get_output_dir())})
        elif path == "/api/library/file":
            qs = parse_qs(urlsplit(self.path).query)
            rel_path = (qs.get("path") or [""])[0]
            self._serve_library_file(srv, rel_path)
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
        if not device_trust.allow_handler(self):
            return
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
        elif path == "/api/channels":
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
            result = srv.channel_watcher.add_channel(
                url,
                name=body.get("name") or "",
                interval_minutes=body.get("interval_minutes"),
                fmt=(body.get("format") or srv.default_format),
                dl_type=(body.get("type") or srv.default_type),
                quality=str(body.get("quality") or srv.default_quality),
            )
            self._send_json(200 if result.get("ok") else 400, result)
        elif _CHANNEL_CHECK_RE.match(path):
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return
            m = _CHANNEL_CHECK_RE.match(path)
            result = srv.channel_watcher.check_now(m.group(1))
            self._send_json(200 if result.get("ok") else 404, result)
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_DELETE(self):
        if not device_trust.allow_handler(self):
            return
        path = urlsplit(self.path).path
        srv = self._srv()

        if _CHANNEL_ID_RE.match(path):
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return
            m = _CHANNEL_ID_RE.match(path)
            result = srv.channel_watcher.remove_channel(m.group(1))
            self._send_json(200 if result.get("ok") else 404, result)
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

        # Watches channel/playlist URLs and auto-queues new uploads through
        # queue_download below. Runs on its own thread regardless of
        # whether the remote (phone/extension) HTTP server is started.
        self.channel_watcher = ChannelWatcher(queue_fn=self._watched_queue, get_output_dir=self.get_output_dir)
        self.channel_watcher.start()

    def _watched_queue(self, url, fmt, dl_type, quality, subdir):
        self.queue_download(url, fmt, dl_type, quality, subdir=subdir)

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

    def shutdown_watcher(self):
        """Stops the channel-watching thread. Not called by stop() above —
        that only tears down the remote HTTP server, and watching should
        keep working even when remote access is off."""
        self.channel_watcher.stop()

    def get_output_dir(self):
        try:
            return self._get_output_dir() or ""
        except Exception:
            return ""

    # ---- jobs --------------------------------------------------------

    def list_jobs(self):
        with self._jobs_lock:
            return [self._public_job(self._jobs[jid]) for jid in self._job_order]

    def get_job(self, job_id):
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            return self._public_job(job) if job else None

    @staticmethod
    def _public_job(job):
        # Strip local filesystem paths before this goes out over the API —
        # the phone only needs a name/size to show and an index to request
        # via GET /api/jobs/<id>/download/<index>.
        j = dict(job)
        if j.get("files"):
            j["files"] = [
                {"name": f["name"], "size": f["size"], "video_id": f.get("video_id")}
                for f in j["files"]
            ]
        return j

    def get_job_file_path(self, job_id, index):
        """Returns the absolute on-disk path for a completed job's file at
        `index`, or None if the job/index is invalid or the file's gone
        (e.g. moved/deleted since the download finished)."""
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None or job.get("status") != "done":
                return None
            files = job.get("files") or []
            if index < 0 or index >= len(files):
                return None
            path = files[index]["path"]
        return path if os.path.isfile(path) else None

    def queue_download(self, url, fmt, dl_type, quality, subdir=""):
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "url": url,
            "format": fmt,
            "type": dl_type,
            "quality": quality,
            "subdir": subdir or "",   # e.g. "Watched - SomeChannel" for auto-queued jobs
            "status": "queued",   # queued -> downloading -> done | error
            "percent": 0.0,
            "message": "Queued…",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
        with self._jobs_lock:
            self._jobs[job_id] = job
            self._job_order.append(job_id)
            while len(self._job_order) > MAX_JOBS_KEPT:
                old_id = self._job_order.pop(0)
                self._jobs.pop(old_id, None)
        self._notify(job)
        self._update_job(job_id, status="starting", message="Starting download…")
        worker = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"yt-dlp-{job_id}",
        )
        worker.start()
        return self.get_job(job_id) or job

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
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            url, fmt, dl_type, quality = job["url"], job["format"], job["type"], job["quality"]
            subdir = job.get("subdir") or ""

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

        if youtube_dl is None:
            self._update_job(job_id, status="error",
                             message="yt-dlp is not installed. Run: python -m pip install -U yt-dlp")
            return
        if not output_dir:
            self._update_job(job_id, status="error", message="No output folder configured.")
            return
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            self._update_job(job_id, status="error", message=f"Cannot create output folder: {e}")
            return

        self._update_job(
            job_id,
            status="downloading",
            started_at=time.time(),
            message="Connecting to YouTube…",
        )

        result_files = []  # [{"path": ..., "id": ...}, ...]

        def postprocessor_hook(d):
            # Fires after each postprocessor (audio extraction, video
            # merge, etc.) finishes — d['info_dict']['filepath'] is the
            # actual final file on disk, which differs from the initial
            # download filename for mp3 (extension changes) and for
            # merged mp4s. Accumulates one entry per file, so a playlist
            # job ends up with every track/video it produced.
            if d.get("status") == "finished":
                info = d.get("info_dict") or {}
                fp = info.get("filepath") or info.get("_filename")
                if fp and fp not in {r["path"] for r in result_files}:
                    result_files.append({"path": fp, "id": info.get("id")})

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

        dest_dir = os.path.join(output_dir, subdir) if subdir else output_dir
        if dl_type == "playlist":
            outtmpl = os.path.join(dest_dir, "%(playlist)s", "%(title)s.%(ext)s")
        else:
            outtmpl = os.path.join(dest_dir, "%(title)s.%(ext)s")

        # Let the installed yt-dlp choose YouTube player clients. Hard-coding
        # old clients (android/ios/tv/mweb) can break when YouTube changes its
        # challenge or PO-token requirements.
        class _JobLogger:
            last = ""
            def debug(self, msg):
                pass
            def info(self, msg):
                if msg and not str(msg).startswith("[download]"):
                    self.last = str(msg)
            def warning(self, msg):
                self.last = str(msg)
            def error(self, msg):
                self.last = str(msg)

        job_logger = _JobLogger()
        opts = {
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": False,
            "logger": job_logger,
            "verbose": True,
            "noplaylist": dl_type != "playlist",
            "windowsfilenames": True,
            "retries": 10,
            "fragment_retries": 10,
            "ignoreerrors": dl_type == "playlist",
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
        }
        # YouTube currently requires a JavaScript runtime for its challenge
        # solving. Prefer Deno, then Node, and pass the *actual executable
        # path* to yt-dlp's Python API. PATH lookup can differ between a
        # desktop app and a terminal on Windows.
        def _runtime_path(name, candidates=()):
            found = shutil.which(name)
            if found and os.path.isfile(found):
                return os.path.abspath(found)
            for candidate in candidates:
                if candidate and os.path.isfile(candidate):
                    return os.path.abspath(candidate)
            return None

        deno = _runtime_path(
            "deno",
            (
                os.path.expandvars(r"%USERPROFILE%\.deno\bin\deno.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\deno\deno.exe"),
            ),
        )
        node = _runtime_path(
            "node",
            (
                os.path.expandvars(r"%ProgramFiles%\nodejs\node.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\nodejs\node.exe"),
            ),
        )
        if deno:
            opts["js_runtimes"] = {"deno": {"path": deno}}
        elif node:
            opts["js_runtimes"] = {"node": {"path": node}}
        else:
            self._update_job(
                job_id,
                status="error",
                message=(
                    "YouTube needs a JavaScript runtime. Install Deno 2.3+ "
                    "(recommended) or Node.js 22+, then restart Z's Multi Tool."
                ),
            )
            return

        # yt-dlp can fetch the matching EJS challenge-solver scripts when the
        # Python package was installed without yt-dlp-ejs.
        opts["remote_components"] = {"ejs:github"}
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir

        # Frozen/PyInstaller builds can have a different DLL/PATH environment
        # from `python main.py`. Give yt-dlp a stable PATH for FFmpeg/JS
        # runtimes without mutating the parent process environment.
        child_path_parts = []
        if ffmpeg_dir and os.path.isdir(ffmpeg_dir):
            child_path_parts.append(os.path.abspath(ffmpeg_dir))
        if deno:
            child_path_parts.append(os.path.dirname(deno))
        if node:
            child_path_parts.append(os.path.dirname(node))
        current_path = os.environ.get("PATH", "")
        if child_path_parts:
            opts["paths"] = {"home": output_dir}
            # yt-dlp's Python API accepts the environment through its
            # subprocess configuration; keep this local to the download.
            opts["postprocessor_args"] = opts.get("postprocessor_args", {})
        ffmpeg_available = bool(ffmpeg_dir) or bool(shutil.which("ffmpeg"))
        if not ffmpeg_available:
            self._update_job(job_id, status="error",
                             message="FFmpeg is required for MP3 extraction and MP4 merging. Install FFmpeg and put it on PATH.")
            return
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

        # YouTube is currently returning HTTP 403 for some of the normal
        # web/SABR GoogleVideo URLs when a PO token is not available.  A JS
        # runtime fixes the player challenge, but it does NOT automatically
        # provide the GVS PO token.  Keep the normal/default attempt first,
        # then retry with clients/formats that currently do not require a GVS
        # PO token.  This makes the downloader usable without forcing every
        # user to manually copy a token.
        try:
            attempts = []
    
            normal = dict(opts)
            attempts.append(normal)
    
            # web_embedded does not require a GVS PO token, but only works for
            # videos that allow embedding.
            embedded = dict(opts)
            embedded["extractor_args"] = {"youtube": {"player_client": ["web_embedded"]}}
            attempts.append(embedded)
    
            # android_vr is another no-PO-token client for ordinary videos.
            android_vr = dict(opts)
            android_vr["extractor_args"] = {"youtube": {"player_client": ["android_vr"]}}
            attempts.append(android_vr)
    
            # web_safari can expose HLS formats that do not require a GVS PO
            # token. Prefer an HLS format on this final fallback.
            hls = dict(opts)
            hls["extractor_args"] = {"youtube": {"player_client": ["web_safari"]}}
            if fmt == "mp3":
                hls["format"] = "bestaudio[protocol^=m3u8]/bestaudio/best"
            else:
                hls["format"] = "best[protocol^=m3u8]/best"
            attempts.append(hls)
    
            ret = 1
            last_error = None
            for attempt_no, attempt_opts in enumerate(attempts, 1):
                try:
                    self._update_job(
                        job_id,
                        message=(
                            "Downloading…" if attempt_no == 1
                            else f"Retrying YouTube with fallback {attempt_no - 1}…"
                        ),
                    )
                    with youtube_dl.YoutubeDL(attempt_opts) as ydl:
                        ret = ydl.download([url])
                    if not ret:
                        break
                except youtube_dl.utils.DownloadError as e:
                    last_error = e
                    if "403" not in str(e):
                        raise
                    # Try the next client/format only for the specific HTTP 403
                    # failure that this fallback chain is intended to handle.
                    continue
    
            if ret and last_error is not None:
                raise last_error
    
            if ret:
                self._update_job(
                    job_id,
                    status="error",
                    message="Finished with errors — see the app's download log.",
                )
            else:
                files = []
                for r in result_files:
                    p = r["path"]
                    if not os.path.isfile(p):
                        continue
                    if r.get("id"):
                        metadata_tag.embed_video_id(p, r["id"])
                    files.append({
                        "name": os.path.basename(p),
                        "path": p,
                        "size": os.path.getsize(p),
                        "video_id": r.get("id"),
                    })
                self._update_job(
                    job_id,
                    status="done",
                    percent=1.0,
                    finished_at=time.time(),
                    message="Download complete",
                    files=files,
                )
        except Exception as e:
            detail = str(e).strip() or "Unknown yt-dlp error."
            logger_detail = getattr(job_logger, "last", "")
            if logger_detail and logger_detail not in detail:
                detail = f"{detail} — {logger_detail}"
            # Keep the UI readable while still exposing the useful cause.
            detail = " ".join(detail.split())
            if len(detail) > 900:
                detail = detail[:897] + "..."
            self._update_job(job_id, status="error", finished_at=time.time(), message=detail)


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
  .tabs { display:flex; gap:8px; margin-bottom:16px; }
  .tabs button {
    flex:1; width:auto; padding:10px; font-size:14px; font-weight:600;
    background:var(--card); color:var(--muted);
  }
  .tabs button.active { background:var(--accent); color:#0b0d10; }
  .iconbtn {
    width:auto; padding:8px 12px; font-size:13px; background:var(--card);
    color:var(--text); border:1px solid #252d3d; font-weight:600;
  }
  .iconbtn.danger { color:var(--danger); }
  .card-row { display:flex; align-items:center; justify-content:space-between; gap:10px; }
  .card .name { font-weight:600; font-size:14px; word-break:break-all; }
  .card .sub { color:var(--muted); font-size:12px; margin-top:2px; }
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

let currentView = 'download';

function render() {
  app.innerHTML = `
    <h1>&#9195;&#65039; YouTube Downloader</h1>
    <div class="tabs">
      <button id="tabDownload">Download</button>
      <button id="tabChannels">Watch</button>
      <button id="tabLibrary">Library</button>
    </div>
    <div id="view"></div>
    <div class="muted">Reachable only from devices on your Tailscale network.</div>
  `;
  document.getElementById('tabDownload').onclick = () => switchView('download');
  document.getElementById('tabChannels').onclick = () => switchView('channels');
  document.getElementById('tabLibrary').onclick = () => switchView('library');
  switchView('download');
}

function switchView(view) {
  currentView = view;
  document.getElementById('tabDownload').className = view === 'download' ? 'active' : '';
  document.getElementById('tabChannels').className = view === 'channels' ? 'active' : '';
  document.getElementById('tabLibrary').className = view === 'library' ? 'active' : '';
  if (view === 'download') renderDownloadView();
  else if (view === 'channels') renderChannelsView();
  else renderLibraryView();
}

function renderDownloadView() {
  document.getElementById('view').innerHTML = `
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
  if (currentView !== 'download') return;
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

// ---- Watch a channel ----------------------------------------------

function renderChannelsView() {
  document.getElementById('view').innerHTML = `
    <div class="panel">
      <input id="chUrl" type="url" placeholder="Channel or playlist link">
      <input id="chName" type="text" placeholder="Name (optional)">
      <div class="row2">
        <select id="chType"><option value="video">Video</option><option value="playlist">Playlist</option></select>
        <select id="chFormat"><option value="mp4">mp4</option><option value="mp3">mp3</option></select>
      </div>
      <select id="chInterval">
        <option value="30">Check every 30 min</option>
        <option value="60" selected>Check every hour</option>
        <option value="180">Check every 3 hours</option>
        <option value="720">Check every 12 hours</option>
        <option value="1440">Check once a day</option>
      </select>
      <div id="chErr" class="error" style="display:none;"></div>
      <button id="chAddBtn">Watch Channel</button>
    </div>
    <div id="channels"></div>
  `;
  document.getElementById('chAddBtn').onclick = addChannel;
  refreshChannels();
}

async function addChannel() {
  const url = document.getElementById('chUrl').value.trim();
  const errEl = document.getElementById('chErr');
  errEl.style.display = 'none';
  if (!url) return;
  if (NEEDS_CODE && !accessCode) {
    const entered = prompt('Access code required:');
    if (!entered) return;
    accessCode = entered.trim();
    sessionStorage.setItem('yt_access_code', accessCode);
  }
  const body = {
    url,
    name: document.getElementById('chName').value.trim(),
    type: document.getElementById('chType').value,
    format: document.getElementById('chFormat').value,
    interval_minutes: parseInt(document.getElementById('chInterval').value, 10),
  };
  const r = await api('/api/channels', { method: 'POST', body: JSON.stringify(body) });
  if (!r.ok) {
    errEl.textContent = r.data.error || 'Failed to watch channel.';
    errEl.style.display = 'block';
    return;
  }
  document.getElementById('chUrl').value = '';
  document.getElementById('chName').value = '';
  refreshChannels();
}

async function checkChannelNow(id) {
  await api(`/api/channels/${id}/check`, { method: 'POST' });
  setTimeout(refreshChannels, 1500);
}

async function removeChannel(id) {
  await api(`/api/channels/${id}`, { method: 'DELETE' });
  refreshChannels();
}

function timeAgo(ts) {
  if (!ts) return 'never checked';
  const mins = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  if (mins < 1) return 'checked just now';
  if (mins < 60) return `checked ${mins}m ago`;
  return `checked ${Math.round(mins / 60)}h ago`;
}

async function refreshChannels() {
  if (currentView !== 'channels') return;
  const r = await api('/api/channels');
  const el = document.getElementById('channels');
  if (!el) return;
  const channels = r.data.channels || [];
  if (channels.length === 0) {
    el.innerHTML = '<div class="muted">Not watching any channels yet.</div>';
    return;
  }
  el.innerHTML = channels.map(c => `
    <div class="card">
      <div class="card-row">
        <div>
          <div class="name">${escapeHtml(c.name)}</div>
          <div class="sub">${timeAgo(c.last_checked)} &middot; ${c.downloaded_count} seen &middot; every ${c.interval_minutes}m</div>
          ${c.last_error ? `<div class="sub status-error">${escapeHtml(c.last_error)}</div>` : ''}
        </div>
      </div>
      <div class="row2" style="margin-top:10px;">
        <button class="iconbtn" onclick="checkChannelNow('${c.id}')">Check now</button>
        <button class="iconbtn danger" onclick="removeChannel('${c.id}')">Remove</button>
      </div>
    </div>
  `).join('');
}

// ---- Library ---------------------------------------------------------

function fmtSize(bytes) {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function renderLibraryView() {
  document.getElementById('view').innerHTML = `<div id="library"><div class="muted">Loading…</div></div>`;
  refreshLibrary();
}

async function refreshLibrary() {
  if (currentView !== 'library') return;
  const r = await api('/api/library');
  const el = document.getElementById('library');
  if (!el) return;
  const files = r.data.files || [];
  if (files.length === 0) {
    el.innerHTML = '<div class="muted">Nothing downloaded yet.</div>';
    return;
  }
  el.innerHTML = files.map(f => `
    <div class="card">
      <div class="name">${escapeHtml(f.name)}</div>
      <div class="sub">${escapeHtml(f.folder || 'Downloads')} &middot; ${fmtSize(f.size)}</div>
      <div class="row2" style="margin-top:10px;">
        <a class="iconbtn" style="text-decoration:none; text-align:center;" href="/api/library/file?path=${encodeURIComponent(f.rel_path)}">Open / Download</a>
        ${f.video_url ? `<a class="iconbtn" style="text-decoration:none; text-align:center;" href="${f.video_url}" target="_blank" rel="noopener">View on YouTube</a>` : ''}
      </div>
    </div>
  `).join('');
}

render();
setInterval(() => { refreshJobs(); refreshChannels(); }, 3000);
</script>
</body>
</html>
""".replace("__NEEDS_CODE__", "true" if needs_code else "false")
