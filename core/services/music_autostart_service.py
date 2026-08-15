# core/services/music_autostart_service.py
#
# Owns the "start the Music Player's remote-access web server as soon as
# the app launches" behavior, controlled by the "Auto-start" toggle in
# that page's Remote Access tab. Without this, the server is only ever
# created the first time the user actually opens the Music Player page
# (see modules/media_player/ui.py) — this service is what lets it come
# up earlier, before the page has ever been visited.
#
# It also re-applies the Tailscale `serve` HTTPS mapping for this port
# if Tailscale is already running (see note in start_if_enabled below) —
# starting only the loopback server without this left remote access
# looking "on" in the app while actually being unreachable from a phone
# away from home, with nothing telling the user that had happened.
#
# Pulled out of app.py so App.__init__ doesn't need to know anything
# about how Music Player stores its settings or builds its web server —
# it just hands this service the page_manager and asks it to start
# itself if enabled.

from modules.media_player import db as music_db
from modules.media_player.web_server import MusicWebServer

DEFAULT_PORT = 8766


class MusicAutoStartService:

    def __init__(self, page_manager):
        self.page_manager = page_manager

    def start_if_enabled(self):
        """Start Music Player's remote-access server now if the user has
        turned on Auto-start for it. Safe to call unconditionally — a
        no-op (aside from one settings read) when it's off. Never lets
        an error here take down the rest of app startup."""
        try:
            library = music_db.Library()
            if library.get_setting("auto_start_server", "0") != "1":
                return

            web_server = MusicWebServer(library=library)
            port = int(library.get_setting("remote_port", DEFAULT_PORT) or DEFAULT_PORT)
            web_server.start(port)

            # Stashed on page_manager (not this service) because that's
            # where the rest of the app — MusicPage on first open,
            # App.quit_app on shutdown — already expects to find it.
            self.page_manager.music_web_server = web_server

            # The loopback server above is only half of what makes remote
            # access actually work — the phone reaches it through
            # `tailscale serve`'s HTTPS mapping, not directly. That
            # mapping is a separate piece of state, and starting the
            # local server here does nothing to guarantee it's still in
            # place (a Windows update, a Tailscale reinstall/update, or
            # `tailscale up --reset` being run some other way can all
            # drop it independently of this app). Turning "Auto-start"
            # on implies the user wants this reachable from their phone
            # without having to open the Remote Access tab and click
            # Start every time — re-applying the mapping here (it's
            # idempotent, safe to call even if it's already active) is
            # what actually delivers that, instead of just starting a
            # server nothing can reach.
            #
            # Deliberately does NOT call tailscale.connect() itself —
            # only re-applies the serve mapping if Tailscale is already
            # running. If it isn't, this stays a no-op rather than
            # popping a login flow at every app launch; the user still
            # has to connect Tailscale at least once themselves (it then
            # normally stays connected across reboots on its own).
            tailscale = getattr(self.page_manager.container, "tailscale_service", None)
            if tailscale is not None:
                try:
                    status = tailscale.get_status()
                    if status.get("running"):
                        tailscale.enable_app_serve("music", port)
                except Exception as e:
                    print(f"[MusicAutoStartService] Couldn't re-apply Tailscale serve mapping: {e}")
        except Exception as e:
            print(f"[MusicAutoStartService] Couldn't auto-start Music Player server: {e}")