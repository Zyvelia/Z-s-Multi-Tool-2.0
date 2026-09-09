"""Qt Disk Map — parked shell around existing folder-size backend."""

from __future__ import annotations

import importlib
import os
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_backend = importlib.import_module("modules.System.Disk Map.backend")


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class DiskMapPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        drives = _backend.list_drives()
        self._root = drives[0] if drives else "C:\\"
        self._busy = False

        root = QVBoxLayout(self)
        title = QLabel("Disk Map")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel("Biggest folders first. Click a bar to go in. Large drives take a minute.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        row = QHBoxLayout()
        self.drive = QComboBox()
        self.drive.addItems(drives)
        if self._root in drives:
            self.drive.setCurrentText(self._root)
        self.drive.currentTextChanged.connect(self._on_drive)
        self.path_label = QLabel(self._root)
        self.path_label.setObjectName("Muted")
        up = QPushButton("Up")
        up.clicked.connect(self._up)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        row.addWidget(self.drive)
        row.addWidget(self.path_label, 1)
        row.addWidget(up)
        row.addWidget(browse)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.body = QVBoxLayout(host)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        QTimer.singleShot(100, self.refresh)

    def _on_drive(self, path: str):
        if path:
            self._root = path
            self.refresh()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Folder to map")
        if path:
            self._root = path
            self.refresh()

    def _up(self):
        parent = os.path.dirname(self._root.rstrip("\\/"))
        if parent and parent != self._root:
            self._root = parent
            self.refresh()

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        self.path_label.setText(self._root)
        self.status.setText("Scanning…")
        folder = self._root

        def work():
            rows = _backend.folder_children(folder)
            QTimer.singleShot(0, lambda: self._apply(rows))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, rows: list):
        self._busy = False
        _clear(self.body)
        if not rows:
            self.status.setText("Empty or unreadable.")
            self.body.addStretch(1)
            return
        total = sum(r["bytes"] for r in rows) or 1
        self.status.setText(f"{len(rows)} entries · {_backend.fmt(total)} in this view")
        for item in rows:
            frac = item["bytes"] / total
            row = QFrame()
            row.setObjectName("Panel")
            rl = QVBoxLayout(row)
            btn = QPushButton(f"{item['name']}  {_backend.fmt(item['bytes'])}")
            btn.clicked.connect(lambda _=False, p=item: self._open(p))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(min(1.0, frac) * 1000))
            bar.setTextVisible(False)
            rl.addWidget(btn)
            rl.addWidget(bar)
            self.body.addWidget(row)
        self.body.addStretch(1)

    def _open(self, item: dict):
        if item.get("is_dir"):
            self._root = item["path"]
            self.refresh()
