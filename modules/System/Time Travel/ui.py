"""Qt Time Travel — parked shell around existing snapshot backends."""

from __future__ import annotations

import importlib
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_backend = importlib.import_module("modules.System.Time Travel.backend")


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class TimeTravelPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._rows = []

        root = QVBoxLayout(self)
        title = QLabel("Time Travel")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "GSM world zips, Gaming Hub save backups, live AppData files, and Windows VSS shadows. Restore overwrites."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self):
        self.status_placeholder()

        def work():
            rows = _backend.timeline()
            QTimer.singleShot(0, lambda: self._show(rows))

        threading.Thread(target=work, daemon=True).start()

    def status_placeholder(self):
        _clear(self.list_lay)
        waiting = QLabel("Loading timeline…")
        waiting.setObjectName("Muted")
        self.list_lay.addWidget(waiting)

    def _show(self, rows: list):
        self._rows = rows
        _clear(self.list_lay)
        if not rows:
            empty = QLabel("No backups found yet.")
            empty.setObjectName("Muted")
            self.list_lay.addWidget(empty)
            self.list_lay.addStretch(1)
            return
        for item in rows:
            self._row(item)
        self.list_lay.addStretch(1)

    def _row(self, item: dict):
        frame = QFrame()
        frame.setObjectName("Panel")
        hl = QHBoxLayout(frame)
        when = _backend.format_ts(item.get("ts") or 0)
        lab = QLabel(f"[{item.get('kind')}] {item.get('title')}  {when}")
        lab.setWordWrap(True)
        hl.addWidget(lab, 1)
        copy = QPushButton("Copy…")
        copy.clicked.connect(lambda _=False, i=item: self._copy(i))
        hl.addWidget(copy)
        if item.get("kind") == "gsm" and item.get("target"):
            restore = QPushButton("Restore")
            restore.setObjectName("Danger")
            restore.clicked.connect(lambda _=False, i=item: self._restore(i))
            hl.addWidget(restore)
        self.list_lay.addWidget(frame)

    def _copy(self, item: dict):
        dest = QFileDialog.getExistingDirectory(self, "Copy snapshot to")
        if not dest:
            return
        try:
            out = _backend.copy_snapshot(item["path"], dest)
        except OSError as exc:
            QMessageBox.warning(self, "Time Travel", str(exc))
            return
        QMessageBox.information(self, "Time Travel", f"Copied to {out}")

    def _restore(self, item: dict):
        if QMessageBox.question(
            self,
            "Time Travel",
            f"Overwrite the server folder with this zip?\n\n{item.get('target')}\n{item.get('path')}",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            _backend.restore_gsm_zip(item["path"], item["target"])
        except Exception as exc:
            QMessageBox.warning(self, "Time Travel", str(exc))
            return
        QMessageBox.information(self, "Time Travel", "Restore finished.")
