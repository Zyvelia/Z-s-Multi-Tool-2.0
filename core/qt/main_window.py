from __future__ import annotations

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import paths
from core.qt.catalog_view import CatalogView
from core.qt.marketplace_view import MarketplaceView
from core.qt.now_view import NowView
from core.qt.settings_view import SettingsView
from core.qt.theme import bundle_from_settings, qss_for_bundle


class MainWindow(QMainWindow):
    def __init__(self, qt_app, settings, plugin_manager, page_manager):
        super().__init__()
        self.qt_app = qt_app
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.page_manager = page_manager

        self.setWindowTitle("Z's Multi Tool")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)
        try:
            self.setWindowIcon(QIcon(paths.resource_path("assets", "icon.ico")))
        except Exception:
            pass

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = self._build_header()
        root.addWidget(self._header)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.catalog = CatalogView(settings, plugin_manager, page_manager)
        self.now = NowView(settings, plugin_manager, page_manager)
        self.marketplace = MarketplaceView(settings, plugin_manager, page_manager)
        self.settings_view = SettingsView(
            settings, plugin_manager, page_manager, self.apply_theme,
        )
        self.qt_tool_host = QStackedWidget()
        self.qt_tool_host.setObjectName("QtToolHost")

        self.stack.addWidget(self.catalog)
        self.stack.addWidget(self.now)
        self.stack.addWidget(self.marketplace)
        self.stack.addWidget(self.settings_view)
        self.stack.addWidget(self.qt_tool_host)

        page_manager.pages["catalog"] = self.catalog
        page_manager.pages["now"] = self.now
        page_manager.pages["marketplace"] = self.marketplace
        page_manager.pages["settings"] = self.settings_view

        self.apply_theme()

    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("Panel")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(12)

        title_col = QVBoxLayout()
        title = QLabel("Z's Multi Tool")
        title.setObjectName("AccentTitle")
        self._status = QLabel("SYSTEM ONLINE")
        self._status.setObjectName("Muted")
        title_col.addWidget(title)
        title_col.addWidget(self._status)
        lay.addLayout(title_col, 1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tools…")
        self.search.textChanged.connect(self._on_search)
        lay.addWidget(self.search, 2)

        now_btn = QPushButton("Now")
        now_btn.clicked.connect(lambda: self.page_manager.show_page("now"))
        market_btn = QPushButton("Market")
        market_btn.clicked.connect(lambda: self.page_manager.show_page("marketplace"))
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(lambda: self.page_manager.show_page("settings"))
        lay.addWidget(now_btn)
        lay.addWidget(market_btn)
        lay.addWidget(settings_btn)
        return bar

    def _on_search(self, text):
        self.catalog.set_search(text)
        if self.stack.currentWidget() is not self.catalog:
            self.page_manager.show_page("catalog")

    def apply_theme(self, theme_id=None):
        if theme_id:
            self.settings.set("catalog_theme", theme_id)
        bundle = bundle_from_settings(self.settings)
        self.qt_app.qapp.setStyleSheet(qss_for_bundle(bundle))
        self.catalog.apply_theme(theme_id)

    def show_qt_page(self, name):
        if name == "catalog":
            self.stack.setCurrentWidget(self.catalog)
        elif name == "now":
            self.stack.setCurrentWidget(self.now)
        elif name == "marketplace":
            self.stack.setCurrentWidget(self.marketplace)
        elif name == "settings":
            self.stack.setCurrentWidget(self.settings_view)
        elif name == "qt_tool":
            self.stack.setCurrentWidget(self.qt_tool_host)

    def show_qt_tool(self, page):
        if self.qt_tool_host.indexOf(page) < 0:
            self.qt_tool_host.addWidget(page)
        self.qt_tool_host.setCurrentWidget(page)
        self.show_qt_page("qt_tool")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.page_manager.current_name != "catalog":
                self.page_manager.show_page("catalog")
                return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                self.qt_app.minimize_to_tray()
        super().changeEvent(event)

    def closeEvent(self, event):
        self.qt_app.quit_app()
        event.accept()
