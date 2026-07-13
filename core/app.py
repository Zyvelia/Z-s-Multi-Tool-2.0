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

        self.discord_service = DiscordService() # Added DiscordService initialization
        self.discord_service.connect()          # Added DiscordService connection

        self.vault_service = VaultService(
            self.crypto_service
        )

        self.totp_service = TotpService(
            self.crypto_service
        )

        # =====================================================
        # PAGE MANAGER
        # =====================================================

        self.page_manager = PageManager(self)

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
            self.quit()
        finally:
            self.destroy()