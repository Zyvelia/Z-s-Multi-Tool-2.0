"""Qt Quick Send — inbox/outbox folders and recently received files."""

from __future__ import annotations

import os
import time

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

import importlib

storage = importlib.import_module("modules.Network.quick_send.storage")


def _format_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _time_ago(ts):
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _open_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        os.startfile(path)
    except Exception as exc:
        QMessageBox.warning(None, "Couldn't open folder", str(exc))


class QuickSendPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Quick Send")
        title.setObjectName("AccentTitle")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(refresh)
        root.addLayout(header)

        self.inbox_path = QLabel("")
        self.inbox_path.setObjectName("Muted")
        self.outbox_path = QLabel("")
        self.outbox_path.setObjectName("Muted")
        root.addWidget(self._folder_card(
            "INBOX  (files your phone sends land here)",
            self.inbox_path,
            lambda: _open_folder(storage.get_config()["inbox_dir"]),
            self._change_inbox,
        ))
        root.addWidget(self._folder_card(
            "SHARED  (drop photos & files here for your phone to pull down)",
            self.outbox_path,
            lambda: _open_folder(storage.get_config()["outbox_dir"]),
            self._change_outbox,
        ))

        received = QLabel("RECENTLY RECEIVED")
        received.setObjectName("CardCat")
        root.addWidget(received)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        scroll.setWidget(self.list_host)
        root.addWidget(scroll, 1)
        self.refresh()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        from core.qt.remote_common import SimpleRemoteSettings, ensure_manager_server

        web_mod = importlib.import_module("modules.Network.quick_send.web_server")
        return SimpleRemoteSettings(
            parent,
            manager,
            get_server=lambda: ensure_manager_server(
                manager, "quick_send_web_server", web_mod.QuickSendWebServer
            ),
            app_key="send",
            default_port=8769,
            title="Remote access (files on phone)",
            hint="Phone can drop files into inbox and pull from the shared folder over your tailnet.",
        )

    def _folder_card(self, caption, path_label, open_fn, change_fn):
        card = QFrame()
        card.setObjectName("Panel")
        lay = QVBoxLayout(card)
        cap = QLabel(caption)
        cap.setObjectName("Muted")
        row = QHBoxLayout()
        row.addWidget(path_label, 1)
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(open_fn)
        change = QPushButton("Change…")
        change.clicked.connect(change_fn)
        row.addWidget(open_btn)
        row.addWidget(change)
        lay.addWidget(cap)
        lay.addLayout(row)
        return card

    def on_show(self):
        self.refresh()

    def _change_inbox(self):
        current = storage.get_config()["inbox_dir"]
        chosen = QFileDialog.getExistingDirectory(self, "Choose inbox folder", current)
        if chosen:
            storage.set_inbox_dir(chosen)
            self.refresh()

    def _change_outbox(self):
        current = storage.get_config()["outbox_dir"]
        chosen = QFileDialog.getExistingDirectory(self, "Choose shared folder", current)
        if chosen:
            storage.set_outbox_dir(chosen)
            self.refresh()

    def refresh(self):
        cfg = storage.get_config()
        self.inbox_path.setText(cfg["inbox_dir"])
        self.outbox_path.setText(cfg["outbox_dir"])
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        entries = storage.get_received_log()[:30]
        if not entries:
            empty = QLabel("Nothing received yet.")
            empty.setObjectName("Muted")
            self.list_lay.addWidget(empty)
        for entry in entries:
            row = QFrame()
            row.setObjectName("Card")
            rl = QVBoxLayout(row)
            name = QLabel(entry.get("filename") or "?")
            name.setObjectName("CardTitle")
            meta = QLabel(f'{_format_size(entry.get("size", 0))} · {_time_ago(entry.get("received_at", 0))}')
            meta.setObjectName("Muted")
            rl.addWidget(name)
            rl.addWidget(meta)
            self.list_lay.addWidget(row)
        self.list_lay.addStretch(1)
