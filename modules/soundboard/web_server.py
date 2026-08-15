# modules/soundboard/web_server.py
#
# A small, dependency-free HTTP server (stdlib only) that lets your
# phone see a folder of sound clips and trigger playback on this PC —
# e.g. a Bluetooth speaker/headset paired to the PC, picked as the
# output device below. Reached from your phone over Tailscale, same
# idea as Music Player, Security Vault, YouTube Downloader, and Gaming
# Hub. Modeled directly on modules/yt_downloader/web_server.py.
#
# Unlike the desktop Soundboard page (which loads whatever files you
# drag in for that session), this server works off a *persisted*
# folder path so it has something to serve even if the desktop page
# was never opened this session — see remote_settings.json.
#
# Security model:
#   - Binds to 127.0.0.1 ONLY. Reachable from the LAN/internet only via
#     `tailscale serve`'s HTTPS proxy (tailnet devices only) — see
#     core/services/tailscale_service.py.
#   - No auth by default, matching Music Player / YouTube Downloader.
#     Set an access code in the Soundboard settings if you want an
#     extra step before your phone (or anyone else on your tailnet) can
#     trigger playback — it gates POST /api/play and POST /api/stop
#     only; GET endpoints stay open.
#   - Playback is restricted to files already inside the configured
#     folder — nothing arbitrary can be played from a phone request.

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from core import paths

AUDIO_EXT = (".mp3", ".wav", ".flac", ".ogg", ".m4a")
SETTINGS_FILE = paths.data_path("soundboard", "remote_settings.json")

DEFAULT_SETTINGS = {
    "folder": "",
    "device_indices": [],   # empty = system default output
}


def _sound_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def _load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def _save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)


def _get_output_devices() -> list:
    try:
        import sounddevice as sd
        devs = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                devs.append({"index": i, "name": d["name"]})
        return devs
    except Exception as e:
        print(f"[Soundboard/web] sounddevice not available: {e}")
        return []


def _load_audio_numpy(path: str):
    """Load any audio file -> (samples_float32 shape [N,2], samplerate).
    Same approach as modules/soundboard/ui.py::_load_audio_numpy."""
    import numpy as np

    ext = os.path.splitext(path)[1].lower()
    try:
        import soundfile as sf
        import subprocess
        import tempfile

        if ext in (".mp3", ".m4a", ".ogg", ".flac"):
            import shutil
            tmp_in = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_in.close()
            tmp_out.close()
            try:
                shutil.copy2(path, tmp_in.name)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in.name, "-ar", "44100",
                     "-ac", "2", "-f", "wav", tmp_out.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                )
                data, sr = sf.read(tmp_out.name, dtype="float32", always_2d=True)
            finally:
                for f in (tmp_in.name, tmp_out.name):
                    try:
                        os.unlink(f)
                    except Exception:
                        pass
        else:
            data, sr = sf.read(path, dtype="float32", always_2d=True)

        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        return data, sr
    except Exception as e:
        print(f"[Soundboard/web] Failed to load {path}: {e}")
        return None, 0


def _play_on_device(samples, samplerate, device_index, volume=1.0):
    try:
        import numpy as np
        import sounddevice as sd
        out = (samples * volume).astype(np.float32)
        sd.play(out, samplerate=samplerate, device=device_index, blocking=False)
    except Exception as e:
        print(f"[Soundboard/web] Playback error on device {device_index}: {e}")


class _Handler(BaseHTTPRequestHandler):

    server_version = "SoundboardWeb/1.0"

    def log_message(self, fmt, *args):
        pass

    def _srv(self):
        return self.server.owner  # SoundboardWebServer instance

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

    def do_GET(self):
        path = urlsplit(self.path).path
        srv = self._srv()

        if path == "/api/status":
            settings = srv.settings
            self._send_json(200, {
                "ok": True,
                "folder": settings["folder"],
                "folder_valid": bool(settings["folder"]) and os.path.isdir(settings["folder"]),
                "device_indices": settings["device_indices"],
                "sound_count": len(srv.list_sounds()),
            })
        elif path == "/api/sounds":
            sounds = [
                {"id": _sound_id(p), "name": os.path.splitext(os.path.basename(p))[0]}
                for p in srv.list_sounds()
            ]
            sounds.sort(key=lambda s: s["name"].lower())
            self._send_json(200, {"ok": True, "sounds": sounds})
        elif path == "/api/devices":
            self._send_json(200, {"ok": True, "devices": _get_output_devices()})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        srv = self._srv()

        if path == "/api/play":
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return
            sound_id = (body.get("id") or "").strip()
            match = next(
                (p for p in srv.list_sounds() if _sound_id(p) == sound_id), None
            )
            if match is None:
                self._send_json(404, {"ok": False, "error": "unknown sound id"})
                return
            ok, err = srv.play(match)
            if not ok:
                self._send_json(500, {"ok": False, "error": err})
                return
            self._send_json(200, {"ok": True})

        elif path == "/api/stop":
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return
            srv.stop_all()
            self._send_json(200, {"ok": True})

        elif path == "/api/settings":
            if not self._code_ok(srv):
                self._send_json(401, {"ok": False, "error": "wrong or missing access code"})
                return
            body = self._read_json_body()
            if body is None:
                self._send_json(400, {"ok": False, "error": "invalid JSON body"})
                return
            srv.update_settings(body)
            self._send_json(200, {"ok": True, "settings": srv.settings})

        else:
            self._send_json(404, {"ok": False, "error": "not found"})


class SoundboardWebServer:
    """Loopback HTTP server exposing a folder of sound clips + a play
    trigger routed to a chosen local output device (e.g. a Bluetooth
    speaker paired to this PC). Independent of any open UI page."""

    def __init__(self):
        self.settings = _load_settings()
        self.access_code = ""  # optional — see _code_ok() above; blank = no gate

        self.port = None
        self._httpd = None
        self._thread = None

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

    def list_sounds(self):
        folder = self.settings.get("folder") or ""
        if not folder or not os.path.isdir(folder):
            return []
        out = []
        try:
            for entry in os.listdir(folder):
                if entry.lower().endswith(AUDIO_EXT):
                    out.append(os.path.join(folder, entry))
        except Exception as e:
            print(f"[Soundboard/web] Couldn't list {folder}: {e}")
        return out

    def update_settings(self, patch: dict):
        if "folder" in patch:
            self.settings["folder"] = (patch.get("folder") or "").strip()
        if "device_indices" in patch:
            try:
                self.settings["device_indices"] = [int(i) for i in patch["device_indices"]]
            except Exception:
                pass
        _save_settings(self.settings)

    def play(self, path: str):
        samples, samplerate = _load_audio_numpy(path)
        if samples is None:
            return False, "couldn't decode that file"
        indices = self.settings.get("device_indices") or [None]
        for idx in indices:
            threading.Thread(
                target=_play_on_device,
                args=(samples, samplerate, idx),
                daemon=True,
            ).start()
        return True, None

    def stop_all(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
