"""Qt Clipboard Manager — history search, pin, copy. Qt timer, not Tk after()."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from modules.Productivity.clipboard_manager.clipboard_history import (
    ClipboardSettings,
    ClipboardStore,
    MAX_MAX_ITEMS,
    MIN_MAX_ITEMS,
    POLL_INTERVAL_CHOICES_MS,
    UNLIMITED,
)

PREVIEW_LINE_LIMIT = 3
PREVIEW_CHAR_LIMIT = 220


def _preview(text: str) -> str:
    lines = text.splitlines() or [text]
    snippet = "\n".join(lines[:PREVIEW_LINE_LIMIT])
    if len(snippet) > PREVIEW_CHAR_LIMIT:
        snippet = snippet[:PREVIEW_CHAR_LIMIT] + "…"
    if len(lines) > PREVIEW_LINE_LIMIT:
        snippet += "\n…"
    return snippet


def _format_time(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


class QtClipboardMonitor:
    def __init__(self, store: ClipboardStore, interval_ms: int = 600):
        self.store = store
        self.interval_ms = interval_ms
        self._last_seen = None
        self._running = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)

    def start(self):
        if self._running:
            return
        self._running = True
        self._last_seen = QApplication.clipboard().text()
        self._timer.start(self.interval_ms)

    def stop(self):
        self._running = False
        self._timer.stop()

    def is_running(self):
        return self._running

    def set_interval(self, interval_ms: int):
        self.interval_ms = interval_ms
        if self._running:
            self._timer.start(self.interval_ms)

    def _tick(self):
        current = QApplication.clipboard().text()
        if current and current != self._last_seen:
            self._last_seen = current
            self.store.add(current)


def _get_or_create(host):
    settings = getattr(host, "_clipboard_settings", None)
    if settings is None:
        settings = ClipboardSettings.load()
        host._clipboard_settings = settings
    store = getattr(host, "_clipboard_store", None)
    if store is None:
        store = ClipboardStore(max_items=settings.max_items)
        host._clipboard_store = store
    monitor = getattr(host, "_qt_clipboard_monitor", None)
    if monitor is None:
        monitor = QtClipboardMonitor(store, interval_ms=settings.poll_interval_ms)
        if settings.capture_enabled:
            monitor.start()
        host._qt_clipboard_monitor = monitor
    return store, monitor, settings


def apply_qt_clipboard_settings(host, *, max_items, poll_interval_ms, capture_enabled):
    store, monitor, settings = _get_or_create(host)
    settings.max_items = max_items
    settings.poll_interval_ms = poll_interval_ms
    settings.capture_enabled = capture_enabled
    settings.save()
    store.set_max_items(max_items)
    monitor.set_interval(poll_interval_ms)
    if capture_enabled and not monitor.is_running():
        monitor.start()
    elif not capture_enabled and monitor.is_running():
        monitor.stop()


class ClipboardManagerModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        host = manager.container if manager is not None else parent
        self.store, self.monitor, self.settings = _get_or_create(host)
        self._query = ""
        self._signature = None

        root = QVBoxLayout(self)
        title = QLabel("Clipboard Manager")
        title.setObjectName("AccentTitle")
        hint = QLabel("Runs in the background — capture continues while you're on other pages.")
        hint.setObjectName("Muted")
        root.addWidget(title)
        root.addWidget(hint)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search history…")
        self.search.textChanged.connect(self._search)
        clear = QPushButton("Clear unpinned")
        clear.clicked.connect(self._clear_unpinned)
        bar.addWidget(self.search, 1)
        bar.addWidget(clear)
        root.addLayout(bar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        scroll.setWidget(self.list_host)
        root.addWidget(scroll, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)
        self._refresh(force=True)
        self._ui = QTimer(self)
        self._ui.setInterval(800)
        self._ui.timeout.connect(lambda: self._refresh(False))
        self._ui.start()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _ClipboardSettings(parent, manager)

    def on_hide(self):
        self._ui.stop()

    def on_show(self):
        if not self._ui.isActive():
            self._ui.start()
        self._refresh(force=True)

    def _search(self, text):
        self._query = text
        self._refresh(force=True)

    def _clear_unpinned(self):
        self.store.clear_unpinned()
        self._refresh(force=True)

    def _refresh(self, force=False):
        entries = self.store.search(self._query)
        signature = tuple((e.id, e.text, e.pinned) for e in entries)
        extra = f" matching '{self._query}'" if self._query else ""
        self.status.setText(f"{len(entries)} item(s){extra}")
        if not force and signature == self._signature:
            return
        self._signature = signature
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not entries:
            empty = QLabel("(nothing here yet — copy something to get started)")
            empty.setObjectName("Muted")
            self.list_lay.addWidget(empty)
            self.list_lay.addStretch(1)
            return
        for entry in entries:
            card = QFrame()
            card.setObjectName("Card")
            cl = QHBoxLayout(card)
            left = QVBoxLayout()
            text = QLabel(_preview(entry.text))
            text.setWordWrap(True)
            meta = QLabel(_format_time(entry.timestamp))
            meta.setObjectName("Muted")
            left.addWidget(text)
            left.addWidget(meta)
            cl.addLayout(left, 1)
            btns = QVBoxLayout()
            copy = QPushButton("Copy")
            copy.setObjectName("Primary")
            copy.clicked.connect(lambda _=False, e=entry: self._copy(e))
            pin = QPushButton("Unpin" if entry.pinned else "Pin")
            pin.clicked.connect(lambda _=False, e=entry: self._pin(e))
            delete = QPushButton("Delete")
            delete.setObjectName("Danger")
            delete.clicked.connect(lambda _=False, e=entry: self._delete(e))
            btns.addWidget(copy)
            btns.addWidget(pin)
            btns.addWidget(delete)
            cl.addLayout(btns)
            self.list_lay.addWidget(card)
        self.list_lay.addStretch(1)

    def _copy(self, entry):
        QApplication.clipboard().setText(entry.text)
        self.monitor._last_seen = entry.text
        self.status.setText("Copied to clipboard")

    def _pin(self, entry):
        self.store.toggle_pin(entry.id)
        self._refresh(force=True)

    def _delete(self, entry):
        self.store.delete(entry.id)
        self._refresh(force=True)


class _ClipboardSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        host = manager.container
        _, _, self.settings = _get_or_create(host)
        self.manager = manager
        lay = QVBoxLayout(self)
        title = QLabel("Capture & storage")
        title.setObjectName("CardTitle")
        hint = QLabel("Clipboard history runs in the background while the app is open.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self.capture = QCheckBox("Capture clipboard history")
        self.capture.setChecked(self.settings.capture_enabled)
        self.unlimited = QCheckBox("Unlimited")
        self.max_items = QLineEdit(
            "" if self.settings.max_items == UNLIMITED else str(self.settings.max_items)
        )
        self.unlimited.setChecked(self.settings.max_items == UNLIMITED)
        self.unlimited.toggled.connect(lambda on: self.max_items.setEnabled(not on))
        self.max_items.setEnabled(self.settings.max_items != UNLIMITED)
        self.interval = QComboBox()
        for ms in POLL_INTERVAL_CHOICES_MS:
            self.interval.addItem(f"{ms} ms", ms)
        idx = self.interval.findData(self.settings.poll_interval_ms)
        self.interval.setCurrentIndex(idx if idx >= 0 else 0)
        self.error = QLabel("")
        self.error.setObjectName("Error")
        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        clear = QPushButton("Clear ALL history (including pinned)")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_all)
        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addWidget(self.capture)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel(f"Max history ({MIN_MAX_ITEMS}–{MAX_MAX_ITEMS})"))
        size_row.addWidget(self.max_items)
        size_row.addWidget(self.unlimited)
        size_row.addStretch(1)
        lay.addLayout(size_row)
        int_row = QHBoxLayout()
        int_row.addWidget(QLabel("Check clipboard every"))
        int_row.addWidget(self.interval)
        int_row.addStretch(1)
        lay.addLayout(int_row)
        lay.addWidget(self.error)
        lay.addWidget(save)
        lay.addWidget(clear)
        lay.addStretch(1)

    def _save(self):
        if self.unlimited.isChecked():
            max_items = UNLIMITED
        else:
            try:
                max_items = int(self.max_items.text().strip())
            except ValueError:
                self.error.setText("Max history size must be a whole number.")
                return
            if not (MIN_MAX_ITEMS <= max_items <= MAX_MAX_ITEMS):
                self.error.setText(f"Max history size must be between {MIN_MAX_ITEMS} and {MAX_MAX_ITEMS}.")
                return
        apply_qt_clipboard_settings(
            self.manager.container,
            max_items=max_items,
            poll_interval_ms=int(self.interval.currentData()),
            capture_enabled=self.capture.isChecked(),
        )
        self.error.setObjectName("Success")
        self.error.setText("Saved.")
        inner = getattr(self.manager, "current", None)
        page = getattr(inner, "_inner", inner) if inner is not None else None
        if isinstance(page, ClipboardManagerModule):
            page._refresh(force=True)

    def _clear_all(self):
        if QMessageBox.question(
            self, "Confirm clear all",
            "This deletes ALL history, including pinned items, permanently. Continue?",
        ) != QMessageBox.StandardButton.Yes:
            return
        store, _, _ = _get_or_create(self.manager.container)
        store.clear_all()
        inner = getattr(self.manager, "current", None)
        page = getattr(inner, "_inner", inner) if inner is not None else None
        if isinstance(page, ClipboardManagerModule):
            page._refresh(force=True)
