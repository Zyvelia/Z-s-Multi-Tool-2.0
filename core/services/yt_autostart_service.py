# core/services/yt_autostart_service.py
#
# Same idea as MusicAutoStartService, for the YouTube Downloader's
# extension-facing web server (used by the "Send to Downloader" button
# in the browser extension). Normally created lazily the first time the
# YouTube Downloader page is opened (see modules/yt_downloader/ui.py);
# this service starts it at launch instead when the user has "Auto-start
# remote" turned on in that page's settings.
#
# Pulled out of app.py for the same reason as the music one — App
# shouldn't need to know that this module keeps its settings in its own
# JSON file, or how to build its web server.

import json
import os

from modules.yt_downloader import ui as yt_downloader_ui
from modules.yt_downloader.web_server import YTWebServer

DEFAULT_PORT = 8767


class YTAutoStartService:

    def __init__(self, page_manager):
        self.page_manager = page_manager

    def start_if_enabled(self):
        """Start the YouTube Downloader's remote server now if "Auto-start
        remote" is on in its settings. Safe to call unconditionally —
        a no-op when it's off, and never lets an error here take down
        the rest of app startup."""
        try:
            settings = self._load_settings()
            if not settings.get("auto_start_remote"):
                return

            output_dir = settings.get("output_dir") or os.path.expanduser("~")
            cookie_file = settings.get("cookie_file") or ""

            web_server = YTWebServer(
                get_output_dir=lambda: output_dir,
                get_cookie_file=lambda: cookie_file,
                get_ffmpeg_dir=lambda: None,
                default_format=settings.get("format", "mp4"),
                default_type=settings.get("type", "video"),
                default_quality=settings.get("quality", "192"),
            )
            port = int(settings.get("remote_port", DEFAULT_PORT) or DEFAULT_PORT)
            web_server.start(port)

            # Stashed on page_manager (not this service) because that's
            # where the rest of the app already expects to find it —
            # YTDownloaderPage on first open, App.quit_app on shutdown.
            self.page_manager.yt_web_server = web_server
        except Exception as e:
            print(f"[YTAutoStartService] Couldn't auto-start YouTube Downloader server: {e}")

    @staticmethod
    def _load_settings():
        if os.path.exists(yt_downloader_ui.SETTINGS_FILE):
            with open(yt_downloader_ui.SETTINGS_FILE) as f:
                return json.load(f)
        return {}