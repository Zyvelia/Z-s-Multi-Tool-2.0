import customtkinter as ctk

from core import theme
from core import paths
from core.page_manager import PageManager
from core.plugin_manager import PluginManager
from core.tray import TrayIcon
from core import updater

from core.services.crypto_service import CryptoService
from core.services.vault_service import VaultService
from core.services.auth_service import AuthService
from core.services.totp_service import TotpService
from core.services.discord_service import DiscordService # Added import
from core.services.tailscale_service import TailscaleService
from core.services.vault_web_server import VaultWebServer
from core.services.alert_service import AlertService

from modules.music_player import db as music_db
from modules.music_player.web_server import MusicWebServer

from pages.catalog_page import CatalogPage
from pages.settings_page import SettingsPage


class App(ctk.CTk):

    def __init__(self, settings):
        theme.apply_appearance()

        super().__init__()

        # =====================================================
        # APP SETTINGS
        # =====================================================

        self.settings = settings

        self.title("Z's Multi Tool")
        self.geometry("1200x800")
        self.minsize(900, 600)
        self.configure(fg_color=theme.BG)

        # Window + taskbar icon. .ico only (Windows requires it for
        # iconbitmap/taskbar); works both running from source and as a
        # frozen exe since resource_path() resolves against sys._MEIPASS.
        try:
            self.iconbitmap(paths.resource_path("assets", "icon.ico"))
        except Exception as e:
            print(f"[App] Could not set window icon: {e}")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # =====================================================
        # CORE SERVICES
        # =====================================================

        self.crypto_service = CryptoService()

        self.auth_service = AuthService()

        self.alert_service = AlertService()

        self.discord_service = DiscordService() # Added DiscordService initialization
        self.discord_service.connect()          # Added DiscordService connection

        self.vault_service = VaultService(
            self.crypto_service
        )

        self.totp_service = TotpService(
            self.crypto_service
        )

        # =====================================================
        # REMOTE ACCESS (Tailscale + loopback web server)
        # =====================================================
        # Lets the Security Vault's Settings tab expose passwords/TOTP
        # codes to your phone over your own Tailscale network. The web
        # server only ever binds to 127.0.0.1; reachability from the
        # phone comes from `tailscale serve` reverse-proxying that
        # loopback port over HTTPS to your tailnet. Nothing is started
        # here — it stays off until toggled on from Settings.

        self.tailscale_service = TailscaleService()

        self.vault_web_server = VaultWebServer({
            "auth_service": self.auth_service,
            "vault_service": self.vault_service,
            "totp_service": self.totp_service,
            "alert_service": self.alert_service,
        })

        # =====================================================
        # PAGE MANAGER
        # =====================================================

        self.page_manager = PageManager(self)

        # Music Player's local server (used by the browser extension and
        # phone streaming) is normally created lazily the first time the
        # Music Player page is opened — see modules/music_player/ui.py.
        # If "Auto-start" is turned on in that page's Remote Access tab,
        # start it here instead, so it's already up as soon as the app
        # opens rather than only after you visit that page. This never
        # touches Tailscale/phone access — only the loopback server —
        # matching the Security Vault side, which stays fully manual.
        try:
            _music_library = music_db.Library()
            if _music_library.get_setting("auto_start_server", "0") == "1":
                self.page_manager.music_web_server = MusicWebServer(library=_music_library)
                port = int(_music_library.get_setting("remote_port", "8766") or 8766)
                self.page_manager.music_web_server.start(port)
        except Exception as e:
            print(f"[App] Couldn't auto-start Music Player server: {e}")

        # =====================================================
        # PLUGIN MANAGER
        # =====================================================

        self.plugin_manager = PluginManager()
        self.plugin_manager.app = self
        self.plugin_manager.load_plugins()

        # =====================================================
        # CORE PAGES
        # =====================================================

        self.catalog_page = CatalogPage(
            self,
            self.page_manager,
            self.plugin_manager
        )

        self.settings_page = SettingsPage(
            self,
            self.page_manager,
            self.settings,
            self.plugin_manager
        )

        self.page_manager.add_page(
            "catalog",
            self.catalog_page
        )

        self.page_manager.add_page(
            "settings",
            self.settings_page
        )

        # =====================================================
        # START PAGE
        # =====================================================

        self.page_manager.show_page("catalog")

        # =====================================================
        # SYSTEM TRAY
        # =====================================================
        # Minimizing hides the window and shows a tray icon instead of a
        # taskbar entry. The X button (below) still fully quits — only
        # the minimize button sends it to tray.

        self.tray = TrayIcon(self)
        self.bind("<Unmap>", self._on_minimize)

        # =====================================================
        # AUTO-UPDATE CHECK
        # =====================================================
        # Runs off the main thread and only interrupts the user (a
        # confirm dialog) if an update is actually found. Controlled by
        # the "Check for updates on launch" toggle in Settings; the
        # "Check for Updates Now" button there always works regardless.

        if self.settings.get("auto_update_check"):
            updater.check_on_launch_async(self)

        # =====================================================
        # CLEAN SHUTDOWN
        # =====================================================
        # On some CustomTkinter + Python 3.13 combinations, closing
        # the window triggers destroy() while the Tk mainloop is
        # still actively dispatching, and a button widget gets torn
        # down mid-construction (AttributeError: '_font'). Stopping
        # the mainloop first, then destroying widgets afterward,
        # avoids that race.
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

    def _on_minimize(self, event):
        # <Unmap> also fires for reasons other than the user minimizing
        # (e.g. our own withdraw() call when going to tray) — only react
        # when it's really this top-level window going "iconic".
        if event.widget is self and self.state() == "iconic":
            self.tray.show()

    def quit_app(self):
        """Full quit: X button or tray 'Quit'. Never leaves a tray icon behind."""
        self.tray.hide()
        try:
            self.tailscale_service.cancel_auto_off_timer()
            if self.vault_web_server.is_running():
                self.tailscale_service.disable_serve()
                self.vault_web_server.stop()
        except Exception:
            pass
        try:
            # Music Player's remote-access server is created lazily (on the
            # page_manager, not here) the first time that page is opened, so
            # it may not exist at all — only stop it if it does.
            music_web_server = getattr(self.page_manager, "music_web_server", None)
            if music_web_server and music_web_server.is_running():
                self.tailscale_service.disable_serve()
                music_web_server.stop()
        except Exception:
            pass
        try:
            self.quit()
        finally:
            self.destroy()