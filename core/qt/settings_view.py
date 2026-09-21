from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import paths
from core import updater
from pages.catalog_theme import list_catalog_themes

DISCORD_URL = "https://discord.gg/vSX49HJMHS"
GITHUB_URL = "https://github.com/Zyvelia/Z-s-Multi-Tool-2.0/tree/main"


class SettingsView(QWidget):
    def __init__(self, settings, plugin_manager, page_manager, apply_theme_cb, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsRoot")
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.page_manager = page_manager
        self._apply_theme_cb = apply_theme_cb
        self._tool_boxes = {}
        self._theme_cards = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(20, 16, 20, 20)
        self._body.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self._build_header()
        self._build_system()
        self._build_catalog_themes()
        self._build_updates()
        self._build_marketplace()
        self._build_tools()
        self._build_about()
        self._body.addStretch(1)

    def on_show(self):
        self._refresh_tools_list()
        self._refresh_theme_selection(self.settings.get("catalog_theme") or "neon")

    def _panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(8)
        return frame, lay

    def _title(self, layout, text):
        lab = QLabel(text)
        lab.setObjectName("CardTitle")
        layout.addWidget(lab)

    def _build_header(self):
        header, lay = self._panel()
        row = QHBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("AccentTitle")
        row.addWidget(title)
        row.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self.page_manager.show_page("catalog"))
        row.addWidget(back)
        lay.addLayout(row)
        self._body.addWidget(header)

    def _build_system(self):
        frame, lay = self._panel()
        self._title(lay, "System")
        row = QHBoxLayout()
        save = QPushButton("Save Settings")
        save.setObjectName("Primary")
        save.clicked.connect(self.settings.save)
        reset = QPushButton("Reset Settings")
        reset.setObjectName("Danger")
        reset.clicked.connect(self._reset)
        row.addWidget(save)
        row.addWidget(reset)
        row.addStretch(1)
        lay.addLayout(row)
        self._body.addWidget(frame)

    def _build_catalog_themes(self):
        frame, lay = self._panel()
        self._title(lay, "Home / Catalog")
        hint = QLabel("Choose a color theme for the tool grid. Changes apply immediately.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        current = self.settings.get("catalog_theme") or "neon"
        for bundle in list_catalog_themes():
            card = self._theme_card(bundle, bundle.id == current)
            self._theme_cards[bundle.id] = card
            row.addWidget(card)
        row.addStretch(1)
        lay.addLayout(row)
        self._body.addWidget(frame)

    def _theme_card(self, bundle, selected):
        card = QFrame()
        card.setObjectName("ThemeCard")
        card.setProperty("selected", "true" if selected else "false")
        card.setFixedSize(210, 108)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(card)
        swatch = QHBoxLayout()
        for color in (bundle.t.BG, bundle.t.ACCENT, bundle.t.TEXT):
            box = QFrame()
            box.setFixedSize(30, 14)
            box.setStyleSheet(f"background:{color}; border-radius:4px;")
            swatch.addWidget(box)
        swatch.addStretch(1)
        lay.addLayout(swatch)
        name = QLabel(bundle.name)
        name.setObjectName("CardTitle")
        lay.addWidget(name)
        desc = QLabel(bundle.description)
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        lay.addStretch(1)

        def on_click(_e=None, theme_id=bundle.id):
            self._select_theme(theme_id)

        card.mousePressEvent = lambda e, fn=on_click: fn()
        return card

    def _select_theme(self, theme_id):
        self.settings.set("catalog_theme", theme_id)
        self._refresh_theme_selection(theme_id)
        if self._apply_theme_cb:
            self._apply_theme_cb(theme_id)

    def _refresh_theme_selection(self, selected_id):
        for theme_id, card in self._theme_cards.items():
            card.setProperty("selected", "true" if theme_id == selected_id else "false")
            card.style().unpolish(card)
            card.style().polish(card)

    def _build_updates(self):
        frame, lay = self._panel()
        self._title(lay, "Updates")
        row = QHBoxLayout()
        self.auto_update = QCheckBox("Check for updates on launch")
        self.auto_update.setChecked(bool(self.settings.get("auto_update_check")))
        self.auto_update.toggled.connect(
            lambda on: self.settings.set("auto_update_check", bool(on))
        )
        check = QPushButton("Check for Updates Now")
        check.clicked.connect(self._check_updates)
        row.addWidget(self.auto_update)
        row.addWidget(check)
        row.addStretch(1)
        lay.addLayout(row)
        self._body.addWidget(frame)

    def _check_updates(self):
        update = updater.check_for_update()
        if update is None:
            if not updater.is_configured():
                QMessageBox.information(
                    self,
                    "Updates Not Configured",
                    "GITHUB_OWNER/GITHUB_REPO haven't been set in core/updater.py yet.",
                )
            else:
                QMessageBox.information(
                    self, "Up to Date", "You're already on the latest version.",
                )
            return
        box = QMessageBox(self)
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

    def _build_marketplace(self):
        frame, lay = self._panel()
        self._title(lay, "Module Marketplace")
        hint = QLabel(
            "Point this at your marketplace index.json to install modules "
            "without updating Z's Multi Tool itself."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.marketplace_url = QLineEdit()
        self.marketplace_url.setPlaceholderText("https://example.com/marketplace/index.json")
        self.marketplace_url.setText(str(self.settings.get("marketplace_url") or ""))
        self.marketplace_url.editingFinished.connect(self._save_marketplace_url)
        lay.addWidget(self.marketplace_url)

        self.marketplace_only = QCheckBox("Use marketplace modules only")
        self.marketplace_only.setChecked(bool(self.settings.get("marketplace_only")))
        self.marketplace_only.setToolTip(
            "When enabled, modules shipped inside the app are not loaded. "
            "Only modules installed through the Marketplace are available."
        )
        self.marketplace_only.toggled.connect(self._save_marketplace_only)
        lay.addWidget(self.marketplace_only)

        marketplace_mode_hint = QLabel(
            "Enable this after you have published the modules you want users to choose. "
            "Changing this setting requires restarting the app."
        )
        marketplace_mode_hint.setObjectName("Muted")
        marketplace_mode_hint.setWordWrap(True)
        lay.addWidget(marketplace_mode_hint)

        open_market = QPushButton("Open Marketplace")
        open_market.setObjectName("Primary")
        open_market.clicked.connect(lambda: self.page_manager.show_page("marketplace"))
        lay.addWidget(open_market, alignment=Qt.AlignmentFlag.AlignLeft)
        self._body.addWidget(frame)

    def _save_marketplace_url(self):
        self.settings.set("marketplace_url", self.marketplace_url.text().strip())

    def _save_marketplace_only(self, enabled):
        self.settings.set("marketplace_only", bool(enabled))

    def _build_tools(self):
        frame, lay = self._panel()
        self._title(lay, "Manage Tools")
        hint = QLabel(
            "Uncheck a tool to hide it from the home screen. "
            "Use x on a card to hide it quickly. Drag a card onto another to reorder."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        reset = QPushButton("Reset Tool Order")
        reset.clicked.connect(self._reset_order)
        lay.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        self._tools_host = QWidget()
        self._tools_layout = QVBoxLayout(self._tools_host)
        self._tools_layout.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(self._tools_host)
        self._refresh_tools_list()
        self._body.addWidget(frame)

    def _refresh_tools_list(self):
        while self._tools_layout.count():
            item = self._tools_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._tool_boxes.clear()
        hidden = set(self.settings.get("hidden_tools") or [])
        tools = sorted(self.plugin_manager.get_tools(), key=lambda t: t.get("name", ""))
        if not tools:
            self._tools_layout.addWidget(QLabel("No tools loaded yet."))
            return
        for tool in tools:
            name = tool.get("name", "")
            box = QCheckBox(name)
            box.setChecked(name not in hidden)
            box.toggled.connect(lambda on, n=name: self._toggle_tool(n, on))
            self._tools_layout.addWidget(box)
            self._tool_boxes[name] = box

    def _toggle_tool(self, name, visible):
        hidden = set(self.settings.get("hidden_tools") or [])
        if visible:
            hidden.discard(name)
        else:
            hidden.add(name)
        self.settings.set("hidden_tools", list(hidden))
        catalog = self.page_manager.pages.get("catalog")
        if catalog is not None:
            catalog._build_pills()
            catalog.render()

    def _reset_order(self):
        self.settings.set("tool_order", [])
        catalog = self.page_manager.pages.get("catalog")
        if catalog is not None:
            catalog.render()

    def _reset(self):
        self.settings.reset()
        self.auto_update.setChecked(bool(self.settings.get("auto_update_check")))
        self.marketplace_url.setText(str(self.settings.get("marketplace_url") or ""))
        self._refresh_tools_list()
        self._refresh_theme_selection(self.settings.get("catalog_theme") or "neon")
        if self._apply_theme_cb:
            self._apply_theme_cb(self.settings.get("catalog_theme"))
        catalog = self.page_manager.pages.get("catalog")
        if catalog is not None:
            catalog._build_pills()
            catalog.render()

    def _build_about(self):
        frame, lay = self._panel()
        self._title(lay, "About")
        row = QHBoxLayout()
        icon = QLabel()
        try:
            pix = QPixmap(paths.resource_path("assets", "icon.ico"))
            if not pix.isNull():
                icon.setPixmap(pix.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
                row.addWidget(icon)
        except Exception:
            pass
        col = QVBoxLayout()
        name = QLabel("Z's Multi Tool")
        name.setObjectName("CardTitle")
        col.addWidget(name)
        ver = QLabel(f"v{updater.APP_VERSION}  •  Built by Z")
        ver.setObjectName("Muted")
        col.addWidget(ver)
        row.addLayout(col)
        row.addStretch(1)
        lay.addLayout(row)
        links = QHBoxLayout()
        discord = QPushButton("Discord")
        discord.clicked.connect(lambda: webbrowser.open(DISCORD_URL))
        github = QPushButton("GitHub")
        github.clicked.connect(lambda: webbrowser.open(GITHUB_URL) if GITHUB_URL else None)
        if not GITHUB_URL:
            github.setEnabled(False)
        links.addWidget(discord)
        links.addWidget(github)
        links.addStretch(1)
        lay.addLayout(links)
        self._body.addWidget(frame)
