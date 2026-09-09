"""Qt stand-in for core.module_shell — gear bar, theme, vault swap."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.module_themes import (
    get_saved_module_theme,
    list_module_themes,
    resolve_module_theme,
    save_module_theme,
)
from core.qt.theme import qss_for_bundle


class QtModuleShell(QWidget):
    is_qt_tool = True

    def __init__(self, manager, module_id: str, page_class, parent=None):
        super().__init__(parent)
        self.setObjectName("ModuleShell")
        self.manager = manager
        self.module_id = module_id
        self.page_class = page_class
        self.settings = getattr(manager, "settings", None) or getattr(
            getattr(manager, "container", None), "settings", None
        )
        self._inner = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._main = QWidget()
        main_lay = QVBoxLayout(self._main)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        gear_bar = QFrame()
        gear_bar.setObjectName("Panel")
        gear_lay = QHBoxLayout(gear_bar)
        gear_lay.setContentsMargins(12, 6, 12, 6)
        gear_lay.addStretch(1)
        gear = QPushButton("⚙")
        gear.setFixedSize(36, 36)
        gear.clicked.connect(self.show_settings)
        gear_lay.addWidget(gear)
        gear_lay.addStretch(1)
        main_lay.addWidget(gear_bar)

        self._content = QWidget()
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.addWidget(self._content, 1)

        self._settings = _SettingsPage(self)
        self._stack.addWidget(self._main)
        self._stack.addWidget(self._settings)

        self._load_theme(None)
        self._apply_shell_theme()
        self._mount_inner(page_class)

    def _mount_inner(self, page_class):
        if self._inner is not None:
            self._content_lay.removeWidget(self._inner)
            self._inner.deleteLater()
        self._inner = page_class(self._content, self.manager)
        self._content_lay.addWidget(self._inner, 1)

    def open_vault_dashboard(self, page_class):
        self._mount_inner(page_class)
        if hasattr(self._inner, "on_show"):
            try:
                self._inner.on_show()
            except Exception as e:
                print(f"[QtModuleShell] vault dashboard on_show: {e}")

    def show_settings(self):
        self._settings.refresh()
        self._stack.setCurrentWidget(self._settings)

    def show_main(self):
        self._stack.setCurrentWidget(self._main)
        if hasattr(self._inner, "on_show"):
            try:
                self._inner.on_show()
            except Exception:
                pass

    def _load_theme(self, theme_id):
        bundle = resolve_module_theme(
            theme_id if theme_id is not None
            else get_saved_module_theme(self.settings, self.module_id)
        )
        self._theme_id = bundle.id
        self._bundle = bundle

    def _apply_shell_theme(self):
        self.setStyleSheet(qss_for_bundle(self._bundle))

    def apply_theme(self, theme_id: str):
        if theme_id == self._theme_id:
            return
        save_module_theme(self.settings, self.module_id, theme_id)
        self._load_theme(theme_id)
        self._apply_shell_theme()
        if hasattr(self._inner, "apply_theme"):
            self._inner.apply_theme(theme_id)
        elif hasattr(self._inner, "apply_module_theme"):
            self._inner.apply_module_theme(theme_id)

    def on_show(self):
        saved = get_saved_module_theme(self.settings, self.module_id)
        if saved != self._theme_id:
            self.apply_theme(saved)
        if hasattr(self._inner, "on_show"):
            try:
                self._inner.on_show()
            except Exception as e:
                print(f"[QtModuleShell] on_show failed for {self.module_id}: {e}")

    def on_hide(self):
        if hasattr(self._inner, "on_hide"):
            try:
                self._inner.on_hide()
            except Exception:
                pass


class _SettingsPage(QWidget):
    def __init__(self, shell: QtModuleShell):
        super().__init__()
        self.shell = shell
        self._theme_cards = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 20)
        header = QHBoxLayout()
        back = QPushButton("←  Back")
        back.clicked.connect(shell.show_main)
        title = QLabel(f"⚙  {shell.module_id} Settings")
        title.setObjectName("CardTitle")
        header.addWidget(back)
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self._body = QVBoxLayout(host)
        self._body.setContentsMargins(0, 8, 0, 8)
        self._body.setSpacing(12)

        theme_hint = QLabel("Color theme for this module.")
        theme_hint.setObjectName("Muted")
        self._body.addWidget(theme_hint)
        cards_host = QWidget()
        self._cards = QHBoxLayout(cards_host)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._body.addWidget(cards_host)

        extra_title = QLabel("Module options")
        extra_title.setObjectName("CardTitle")
        self._body.addWidget(extra_title)
        self._extra_host = QWidget()
        self._extra_lay = QVBoxLayout(self._extra_host)
        self._extra_lay.setContentsMargins(0, 0, 0, 0)
        self._body.addWidget(self._extra_host)
        self._body.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

    def refresh(self):
        while self._cards.count():
            item = self._cards.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._theme_cards.clear()
        current = get_saved_module_theme(self.shell.settings, self.shell.module_id)
        for bundle in list_module_themes():
            card = QFrame()
            card.setObjectName("ThemeCard")
            card.setProperty("selected", "true" if bundle.id == current else "false")
            card.setFixedSize(200, 96)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            cl = QVBoxLayout(card)
            name = QLabel(bundle.name)
            name.setObjectName("CardTitle")
            desc = QLabel(bundle.description)
            desc.setObjectName("Muted")
            desc.setWordWrap(True)
            cl.addWidget(name)
            cl.addWidget(desc)
            card.mousePressEvent = lambda e, tid=bundle.id: self._pick_theme(tid)
            self._cards.addWidget(card)
            self._theme_cards[bundle.id] = card
        self._cards.addStretch(1)
        self._mount_extra_settings()

    def _pick_theme(self, theme_id: str):
        self.shell.apply_theme(theme_id)
        for tid, card in self._theme_cards.items():
            card.setProperty("selected", "true" if tid == theme_id else "false")
            card.style().unpolish(card)
            card.style().polish(card)

    def _mount_extra_settings(self):
        while self._extra_lay.count():
            item = self._extra_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        inner = self.shell._inner
        builder = getattr(inner, "build_qt_module_settings", None)
        if builder is None:
            empty = QLabel("This module has no extra options — theme only.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self._extra_lay.addWidget(empty)
            return
        try:
            extra = builder(self._extra_host, self.shell.manager)
        except Exception as exc:
            err = QLabel(f"Couldn't load module options: {exc}")
            err.setObjectName("Error")
            err.setWordWrap(True)
            self._extra_lay.addWidget(err)
            return
        if extra is not None:
            self._extra_lay.addWidget(extra)


def open_qt_module(manager, module_id: str, page_class):
    return QtModuleShell(manager, module_id, page_class)


def find_qt_module_shell(widget):
    w = widget
    while w is not None:
        if isinstance(w, QtModuleShell):
            return w
        w = w.parent()
    return None
