from __future__ import annotations

import importlib
import sys
import threading

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction
from PySide6.QtCore import QTimer

from core import paths
from core import updater
from core.win_subprocess import install as install_hidden_subprocess
from core.plugin_manager import PluginManager
from core.qt.main_window import MainWindow
from core.qt.page_bridge import PageBridge
from core.qt.tk_after import schedule
from core.services.alert_service import AlertService
from core.services.auth_service import AuthService
from core.services.crypto_service import CryptoService
from core.services.discord_service import DiscordService
from core.services.hardware_key_service import HardwareKeyService
from core.services.tailscale_service import TailscaleService
from core.services.totp_service import TotpService
from core.services.vault_service import VaultService
from core.services.vault_web_server import VaultWebServer


class ServiceHost:
    """Holds shared services for the Qt app (after() hops via QTimer)."""

    def __init__(self, qt_app: "QtApp"):
        self._qt_app = qt_app

    def after(self, ms, func=None, *args):
        if func is None:
            return None
        return schedule(ms, func, *args)


class QtApp:
    def __init__(self, settings):
        self.settings = settings
        install_hidden_subprocess()
        self.qapp = QApplication.instance() or QApplication(sys.argv)
        self.qapp.setApplicationName("Z's Multi Tool")
        from core.qt.tk_after import install as install_tk_after

        install_tk_after()
        try:
            self.qapp.setWindowIcon(QIcon(paths.resource_path("assets", "icon.ico")))
        except Exception:
            pass

        self.host = ServiceHost(self)
        self._attach_services(self.host)
        self.host.settings = settings
        self.host.quit_app = self.quit_app

        self.plugin_manager = PluginManager()
        self.plugin_manager.app = self.host
        self.plugin_manager.load_plugins()

        self.page_manager = PageBridge(self.host, None, self.plugin_manager, settings)
        self.host.page_manager = self.page_manager

        self.window = MainWindow(
            self, settings, self.plugin_manager, self.page_manager,
        )
        self.page_manager.window = self.window

        self._wire_agent()
        from core.services.watchdog import start_polling

        start_polling(self.host, self.settings)

        self.tray = QSystemTrayIcon(self.window)
        try:
            self.tray.setIcon(QIcon(paths.resource_path("assets", "icon.ico")))
        except Exception:
            pass
        self.tray.setToolTip("Z's Multi Tool")
        menu = QMenu()
        open_act = QAction("Open Z's Multi Tool", self.window)
        open_act.triggered.connect(self.restore_from_tray)
        quit_act = QAction("Quit", self.window)
        quit_act.triggered.connect(self.quit_app)
        menu.addAction(open_act)
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)

        if self.settings.get("auto_update_check"):
            self._check_update_async()

        self.page_manager.show_page("catalog")
        self.window.show()

    def _attach_services(self, host):
        host.crypto_service = CryptoService()
        host.auth_service = AuthService()
        host.hardware_key_service = HardwareKeyService(host.auth_service)
        host.alert_service = AlertService()
        host.discord_service = DiscordService()
        host.discord_service.connect()
        host.vault_service = VaultService(host.crypto_service)
        host.totp_service = TotpService(host.crypto_service)
        host.tailscale_service = TailscaleService()
        host.vault_web_server = VaultWebServer({
            "auth_service": host.auth_service,
            "vault_service": host.vault_service,
            "totp_service": host.totp_service,
            "alert_service": host.alert_service,
        })
        self.crypto_service = host.crypto_service
        self.auth_service = host.auth_service
        self.hardware_key_service = host.hardware_key_service
        self.alert_service = host.alert_service
        self.discord_service = host.discord_service
        self.vault_service = host.vault_service
        self.totp_service = host.totp_service
        self.tailscale_service = host.tailscale_service
        self.vault_web_server = host.vault_web_server

    def _wire_agent(self):
        from modules.AI.agent_registry import get_registry

        registry = get_registry()
        registry.plugin_manager = self.plugin_manager
        try:
            from modules.AI.agent_tools import ensure_registered

            ensure_registered(self.plugin_manager)
        except Exception as e:
            print(f"[QtApp] Agent tools: {e}")

        def confirm_write(name, args):
            if self.settings.get("agent_confirm_writes") is False:
                return True
            from core.services import agent_confirm

            if agent_confirm.is_phone_context():
                return agent_confirm.ask_phone(name, args or {})
            done = threading.Event()
            answer = {"ok": False}

            def ask():
                try:
                    box = QMessageBox(self.window)
                    box.setWindowTitle("Agent")
                    box.setText(f"Allow the agent to run:\n\n{name}")
                    box.setStandardButtons(
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    answer["ok"] = box.exec() == QMessageBox.StandardButton.Yes
                except Exception:
                    answer["ok"] = False
                done.set()

            QTimer.singleShot(0, ask)
            if not done.wait(timeout=90):
                return False
            return bool(answer["ok"])

        registry.confirm_write = confirm_write

    def _check_update_async(self):
        def worker():
            update = updater.check_for_update()
            if not update:
                return

            def prompt():
                box = QMessageBox(self.window)
                box.setWindowTitle("Update Available")
                box.setText(
                    f"Version {update['version']} is available "
                    f"(you have {updater.APP_VERSION}).\n\n"
                    "Update now? The app will restart automatically."
                )
                box.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if box.exec() == QMessageBox.StandardButton.Yes:
                    updater.apply_update(update["url"])

            QTimer.singleShot(0, prompt)

        threading.Timer(1.5, worker).start()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.restore_from_tray()

    def minimize_to_tray(self):
        try:
            self.auth_service.lock()
        except Exception:
            pass
        self.window.hide()
        self.tray.show()

    def restore_from_tray(self):
        self.tray.hide()
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        page = getattr(self.page_manager, "current", None)
        if page is not None and hasattr(page, "on_show"):
            try:
                page.on_show()
            except Exception:
                pass

    def quit_app(self):
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        self.tray.hide()
        host = self.host
        pm = self.page_manager
        try:
            self.tailscale_service.cancel_auto_off_timer()
            if self.vault_web_server.is_running():
                self.tailscale_service.disable_serve()
                self.vault_web_server.stop()
        except Exception:
            pass
        for attr, serve in (
            ("music_web_server", True),
            ("yt_web_server", False),
            ("gaming_hub_web_server", "games"),
            ("soundboard_web_server", "soundboard"),
        ):
            try:
                srv = getattr(pm, attr, None)
                if srv and srv.is_running():
                    if serve is True:
                        self.tailscale_service.disable_serve()
                    elif serve:
                        self.tailscale_service.disable_app_serve(serve)
                    srv.stop()
            except Exception:
                pass
        try:
            importlib.import_module(
                "modules.Gaming.Arcade.brick_breaker.webview_service"
            ).get_service(host).destroy()
        except Exception:
            pass
        try:
            arcade_srv = getattr(host, "arcade_web_server", None)
            if arcade_srv and arcade_srv.is_running():
                self.tailscale_service.disable_app_serve("arcade")
                arcade_srv.stop()
        except Exception:
            pass
        self.qapp.quit()

    def exec(self):
        return self.qapp.exec()


def run(settings):
    app = QtApp(settings)
    return app.exec()
