"""Queue yt-dlp jobs the same way Remote Hub / the phone page does."""

from __future__ import annotations

import json
import os

from core.services.agent_registry import get_registry

from . import library
from .web_server import SETTINGS_FILE, YTWebServer, is_youtube_url


def _page_manager():
    plugins = get_registry().plugin_manager
    app = getattr(plugins, "app", None) if plugins is not None else None
    return getattr(app, "page_manager", None)


def _settings() -> dict:
    settings = {}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                settings = json.load(fh)
    except Exception:
        settings = {}
    if not isinstance(settings, dict):
        settings = {}
    return settings


def get_server() -> YTWebServer:
    manager = _page_manager()
    if manager is not None:
        existing = getattr(manager, "yt_web_server", None)
        if existing:
            return existing

    settings = _settings()
    output_dir = settings.get("output_dir") or os.path.expanduser("~")
    server = YTWebServer(
        get_output_dir=lambda: output_dir,
        get_cookie_file=lambda: settings.get("cookie_file", ""),
        get_ffmpeg_dir=lambda: None,
        default_format=settings.get("format", "mp4"),
        default_type=settings.get("type", "video"),
        default_quality=settings.get("quality", "192"),
    )
    server.access_code = settings.get("access_code", "")
    if manager is not None:
        manager.yt_web_server = server
    return server


def queue_download(url: str, fmt: str = "", dl_type: str = "", quality: str = "") -> dict:
    url = (url or "").strip()
    if not is_youtube_url(url):
        return {"ok": False, "error": "That doesn't look like a YouTube URL."}
    server = get_server()
    settings = _settings()
    fmt = (fmt or settings.get("format") or "mp4").lower()
    if fmt not in ("mp3", "mp4"):
        fmt = "mp4"
    dl_type = (dl_type or settings.get("type") or "video").lower()
    if dl_type not in ("video", "playlist"):
        dl_type = "video"
    quality = str(quality or settings.get("quality") or "192")
    job = server.queue_download(url, fmt, dl_type, quality)
    return {"ok": True, "job": _public(job)}


def job_status(job_id: str = "") -> dict:
    server = get_server()
    if job_id:
        job = server.get_job(job_id)
        if job is None:
            return {"ok": False, "error": f"No job {job_id}."}
        return {"ok": True, "job": job}
    jobs = server.list_jobs()
    return {"ok": True, "jobs": jobs[-10:], "count": len(jobs)}


def wait_for_job(job_id: str, timeout_seconds: float = 300) -> dict:
    import time

    timeout = max(5.0, min(float(timeout_seconds or 300), 900.0))
    deadline = time.time() + timeout
    server = get_server()
    while time.time() < deadline:
        job = server.get_job(job_id)
        if job is None:
            return {"ok": False, "error": f"No job {job_id}."}
        status = job.get("status")
        if status == "done":
            return {"ok": True, "job": job}
        if status == "error":
            return {"ok": False, "error": job.get("message") or "Download failed.", "job": job}
        time.sleep(1.5)
    job = server.get_job(job_id)
    return {
        "ok": False,
        "error": f"Timed out after {int(timeout)}s waiting for download {job_id}.",
        "job": job,
    }


def watch_channel(url: str, name: str = "", interval_minutes: int = 60,
                   fmt: str = "", dl_type: str = "", quality: str = "") -> dict:
    """Start auto-downloading new uploads from a channel or playlist link."""
    server = get_server()
    settings = _settings()
    fmt = (fmt or settings.get("format") or "mp4").lower()
    if fmt not in ("mp3", "mp4"):
        fmt = "mp4"
    dl_type = (dl_type or settings.get("type") or "video").lower()
    if dl_type not in ("video", "playlist"):
        dl_type = "video"
    quality = str(quality or settings.get("quality") or "192")
    return server.channel_watcher.add_channel(
        url, name=name, interval_minutes=interval_minutes,
        fmt=fmt, dl_type=dl_type, quality=quality,
    )


def list_watched_channels() -> dict:
    server = get_server()
    return {"ok": True, "channels": server.channel_watcher.list_channels()}


def unwatch_channel(channel_id: str) -> dict:
    server = get_server()
    return server.channel_watcher.remove_channel(channel_id)


def check_channel_now(channel_id: str) -> dict:
    server = get_server()
    return server.channel_watcher.check_now(channel_id)


def list_library(limit: int = 100) -> dict:
    """Browse videos/audio already downloaded to disk, newest first."""
    server = get_server()
    files = library.scan_library(server.get_output_dir(), limit=limit)
    return {"ok": True, "files": files, "count": len(files)}


def _public(job: dict) -> dict:
    return {
        "id": job.get("id"),
        "url": job.get("url"),
        "status": job.get("status"),
        "format": job.get("format"),
        "type": job.get("type"),
        "message": job.get("message"),
    }
