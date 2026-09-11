"""GUI-free Remote Hub controller (Go Live / Offline / status)."""

from __future__ import annotations

import importlib
import json
import os

from core.services import hub_service
from core.services.tailscale_service import APP_HTTPS_PORTS

APPS = [
    ("vault", "🔒 Security Vault"),
    ("music", "🎵 Music Player"),
    ("yt", "⬇️ YouTube Downloader"),
    ("notes", "📝 Notes"),
    ("games", "🎮 Gaming Hub"),
    ("gsm", "🖥 Game servers"),
    ("soundboard", "🔊 Soundboard"),
    ("send", "📤 Quick Send"),
    ("messages", "💬 Messages"),
    ("social", "🟠 Night page"),
    ("chat", "🤖 AI Chat"),
]


class HubController:
    """
    All the "actually talk to Tailscale and the per-app web servers"
    logic, with no UI attached. Pulled out of RemoteHubPage so the
    dashboard mini widget (mini_widget.py) can drive the exact same
    Go Live / Go Offline behavior from a single button without needing
    the full Remote Hub page to have been opened first.

    Every method here is blocking — callers run them off the Tk main
    thread (see RemoteHubPage._on_go_live / mini_widget.py for the
    pattern) and hop back with .after(0, ...) to touch widgets.
    """

    def __init__(self, manager):
        self.manager = manager
        self.tailscale = manager.container.tailscale_service

    # =====================================================
    # LAZY SERVER ACCESS — mirrors core/app.py's own auto-start logic,
    # for the case where you go live before ever opening a given app's
    # own page this session.
    # =====================================================

    def _get_vault_web_server(self):
        existing = getattr(self.manager.container, "vault_web_server", None)
        if existing is not None:
            return existing
        # Match the other services: create it lazily when Remote Hub is
        # opened before the Vault page has ever been initialized.
        from core.services.vault_web_server import VaultWebServer
        server = VaultWebServer()
        self.manager.container.vault_web_server = server
        return server

    def _get_music_web_server(self):
        existing = getattr(self.manager, "music_web_server", None)
        if existing:
            return existing
        # Music Player now lives at modules/Media/Media Player/ — the space
        # in the folder name means it can't be written as a normal
        # `from modules.x import y` statement, so we go through
        # importlib with the dotted path as a plain string instead.
        music_db = importlib.import_module("modules.Media.Media Player.db")
        web_server_mod = importlib.import_module("modules.Media.Media Player.web_server")
        server = web_server_mod.MusicWebServer(library=music_db.Library())
        self.manager.music_web_server = server
        return server

    def _get_yt_web_server(self):
        existing = getattr(self.manager, "yt_web_server", None)
        if existing:
            return existing
        # Now at modules/Media/YouTube Downloader/ — same importlib
        # workaround as Music Player above.
        yt_web_server_mod = importlib.import_module("modules.Media.YouTube Downloader.web_server")
        YTWebServer = yt_web_server_mod.YTWebServer
        settings = {}
        try:
            if os.path.exists(yt_web_server_mod.SETTINGS_FILE):
                with open(yt_web_server_mod.SETTINGS_FILE) as f:
                    settings = json.load(f)
        except Exception:
            settings = {}
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
        self.manager.yt_web_server = server
        return server

    def _get_notes_web_server(self):
        existing = getattr(self.manager, "notes_web_server", None)
        if existing:
            return existing
        # Now at modules/Productivity/Notes/
        web_server_mod = importlib.import_module("modules.Productivity.Notes.web_server")
        server = web_server_mod.NotesWebServer()
        self.manager.notes_web_server = server
        return server

    def _get_quick_send_web_server(self):
        existing = getattr(self.manager, "quick_send_web_server", None)
        if existing:
            return existing
        # Now at modules/Network/quick_send/ (gained the Network category
        # prefix, but the folder itself is unchanged)
        web_server_mod = importlib.import_module("modules.Network.quick_send.web_server")
        server = web_server_mod.QuickSendWebServer()
        self.manager.quick_send_web_server = server
        return server

    def _get_games_web_server(self):
        # Same lazy-create-and-stash pattern Gaming Hub's own page uses
        # (modules/gaming_hub/ui.py) — sharing the "gaming_hub_web_server"
        # attribute name on the manager means whichever page opens first
        # (this one or Gaming Hub itself) creates it, and the other reuses it.
        existing = getattr(self.manager, "gaming_hub_web_server", None)
        if existing:
            return existing
        # Now at modules/Gaming/Gaming Hub/
        web_server_mod = importlib.import_module("modules.Gaming.Gaming Hub.web_server")
        server = web_server_mod.GamingHubWebServer()
        self.manager.gaming_hub_web_server = server
        return server

    def _get_soundboard_web_server(self):
        # Same lazy-create-and-stash pattern as Gaming Hub above — mirrors
        # modules/soundboard/ui.py's own RemoteAccessPanel wiring, sharing
        # the "soundboard_web_server" attribute name on the manager.
        existing = getattr(self.manager, "soundboard_web_server", None)
        if existing:
            return existing
        # Now at modules/Media/soundboard/ (gained the Media category
        # prefix, but the folder itself is unchanged)
        web_server_mod = importlib.import_module("modules.Media.soundboard.web_server")
        server = web_server_mod.SoundboardWebServer()
        self.manager.soundboard_web_server = server
        return server

    def _get_messaging_web_server(self):
        # Messaging (modules/Productivity/Messaging/web_server.py) exposes a
        # module-level singleton instead of a class you instantiate — its
        # own page (MessagingPage) calls ensure_started() on the same
        # singleton the first time its tab is opened, so whichever comes
        # up first (this page or that one) is the one both share, same
        # "whichever page opens first" convention as Gaming Hub/Soundboard
        # above, just via a singleton rather than a manager attribute.
        existing = getattr(self.manager, "messaging_web_server", None)
        if existing:
            return existing
        web_server_mod = importlib.import_module("modules.Productivity.Messaging.web_server")
        server = web_server_mod.server
        self.manager.messaging_web_server = server
        return server

    def _get_social_web_server(self):
        existing = getattr(self.manager, "social_web_server", None)
        if existing:
            return existing
        web_server_mod = importlib.import_module("modules.Network.Tailnet Social.web_server")
        server = web_server_mod.SocialWebServer()
        self.manager.social_web_server = server
        return server

    def _get_gsm_web_server(self):
        existing = getattr(self.manager, "gsm_web_server", None)
        if existing:
            return existing
        web_server_mod = importlib.import_module(
            "modules.Gaming.Game Server Manager.web_server"
        )
        server = web_server_mod.GsmWebServer()
        self.manager.gsm_web_server = server
        return server

    def _get_chat_web_server(self):
        existing = getattr(self.manager, "chat_web_server", None)
        if existing:
            return existing
        web_server_mod = importlib.import_module("modules.AI.web_server")
        server = web_server_mod.ChatWebServer()
        self.manager.chat_web_server = server
        return server

    def _get_trust_web_server(self):
        existing = getattr(self.manager, "trust_web_server", None)
        if existing:
            return existing
        web_server_mod = importlib.import_module("core.services.device_trust_server")
        server = web_server_mod.DeviceTrustWebServer()
        self.manager.trust_web_server = server
        return server

    def _ports(self):
        vault_cfg = self.tailscale.load_config()
        music_db = importlib.import_module("modules.Media.Media Player.db")
        music_port = int(music_db.Library().get_setting("remote_port", "8766") or 8766)

        yt_web = importlib.import_module("modules.Media.YouTube Downloader.web_server")
        yt_settings = {}
        try:
            if os.path.exists(yt_web.SETTINGS_FILE):
                with open(yt_web.SETTINGS_FILE) as f:
                    yt_settings = json.load(f)
        except Exception:
            pass
        yt_port = int(yt_settings.get("remote_port", 8767) or 8767)

        return {
            "vault": int(vault_cfg.get("web_port", 8765) or 8765),
            "music": music_port,
            "yt": yt_port,
            "notes": 8768,  # no Settings tab yet for Notes, so this is fixed
            "send": 8769,  # no Settings tab yet for Quick Send either, so this is fixed;
            # this is just the local loopback port — enable_app_serve() below maps
            # it to the fixed public port in APP_HTTPS_PORTS["send"] (8449), which
            # is what the mobile app's ModulePorts.send expects
            # Gaming Hub's own page (modules/gaming_hub/ui.py) always starts
            # its loopback server on APP_HTTPS_PORTS["games"] via
            # RemoteAccessPanel — matching that here means whichever page
            # starts it first, the other one finds it already running.
            "games": APP_HTTPS_PORTS["games"],
            # Same deal for Soundboard (modules/soundboard/ui.py).
            "soundboard": APP_HTTPS_PORTS["soundboard"],
            # Messaging's own page (MessagingPage) always starts its
            # loopback server on APP_HTTPS_PORTS["messages"] too — same
            # reasoning as games/soundboard above.
            "messages": APP_HTTPS_PORTS["messages"],
            "social": 8770,
            "gsm": 8771,
            "chat": 8772,
            "trust": 8773,
        }

    # =====================================================
    # GO LIVE / GO OFFLINE / STATUS — blocking, call off-thread
    # =====================================================

    def go_live_sync(self):
        """
        Runs the full "Go Live" sequence. Returns (fatal, errors):
          fatal  -- a message if we couldn't even attempt to go live
                    (Tailscale missing, or couldn't connect), else None
          errors -- per-app warnings collected along the way; only
                    meaningful when fatal is None
        """
        errors = []

        status = self.tailscale.get_status()
        if not status["installed"]:
            return "Tailscale isn't installed on this device.", []
        if not status["running"]:
            cfg = self.tailscale.load_config()
            ok, msg = self.tailscale.connect(
                hostname=cfg.get("hostname") or None,
                auth_key=cfg.get("auth_key") or None,
                accept_routes=cfg.get("accept_routes", True),
            )
            if not ok:
                return f"Couldn't connect to Tailscale: {msg}", []
            status = self.tailscale.get_status()

        ports = self._ports()

        def start_app(key, label, getter):
            """Start one app and expose it through Tailscale.

            Remote Hub is intentionally best-effort: one optional module being
            unavailable must not prevent the remaining apps from going live.
            """
            port = ports[key]
            try:
                server = getter()
                if not server.is_running():
                    ok, msg = server.start(port)
                    if not ok:
                        errors.append(f"{label} server: {msg}")
                        return
                if server.is_running():
                    ok, msg = self.tailscale.enable_app_serve(key, port)
                    if not ok:
                        errors.append(f"{label} Tailscale: {msg}")
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        start_app("vault", "Security Vault", self._get_vault_web_server)
        start_app("music", "Music Player", self._get_music_web_server)
        start_app("yt", "YouTube Downloader", self._get_yt_web_server)
        start_app("notes", "Notes", self._get_notes_web_server)
        start_app("send", "Quick Send", self._get_quick_send_web_server)
        start_app("games", "Gaming Hub", self._get_games_web_server)
        start_app("soundboard", "Soundboard", self._get_soundboard_web_server)
        start_app("messages", "Messages", self._get_messaging_web_server)
        start_app("social", "Night page", self._get_social_web_server)
        start_app("gsm", "Game servers", self._get_gsm_web_server)
        start_app("chat", "AI Chat", self._get_chat_web_server)
        start_app("trust", "Phone pairing", self._get_trust_web_server)

        live_apps = [key for key in ("vault", "music", "yt", "notes", "games", "soundboard",
                                      "send", "messages", "social", "gsm", "chat")
                     if self.tailscale.is_app_serving(key)]
        hostname = status.get("hostname") or "this-device"
        hub_path = hub_service.write_hub_html(hostname, live_apps)
        ok, msg = self.tailscale.enable_hub_page(hub_path)
        if not ok:
            errors.append(f"Hub landing page: {msg}")

        return None, errors

    def go_offline_sync(self):
        errors = []
        try:
            self.tailscale.disable_hub_page()
        except Exception as exc:
            errors.append(f"Hub landing page: {exc}")

        for key, _ in APPS:
            try:
                self.tailscale.disable_app_serve(key)
            except Exception as exc:
                errors.append(f"{key}: {exc}")

        try:
            self.tailscale.disable_app_serve("trust")
        except Exception as exc:
            errors.append(f"trust: {exc}")

        return errors

    def get_status_sync(self):
        status = self.tailscale.get_status()
        live_apps = {key: self.tailscale.is_app_serving(key) for key, _ in APPS} \
            if status["running"] else {key: False for key, _ in APPS}
        return status, live_apps

