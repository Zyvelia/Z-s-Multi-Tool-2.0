"""Qt Messages — desktop side of phone chat over Tailscale."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import importlib

storage = importlib.import_module("modules.Productivity.Messaging.storage")
web_server = importlib.import_module("modules.Productivity.Messaging.web_server")

DESKTOP_SENDER_ID = "desktop"
DEFAULT_PORT = 8452


class MessagingPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Messages")
        title.setObjectName("AccentTitle")
        self.status = QLabel("starting…")
        self.status.setObjectName("Muted")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        scroll.setWidget(self.list_host)
        root.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Message…")
        self.entry.returnPressed.connect(self._send)
        send = QPushButton("Send")
        send.setObjectName("Primary")
        send.clicked.connect(self._send)
        row.addWidget(self.entry, 1)
        row.addWidget(send)
        root.addLayout(row)

        ok, msg = web_server.ensure_started(DEFAULT_PORT)
        self.status.setText(f"listening on 127.0.0.1:{DEFAULT_PORT}" if ok else msg)
        web_server.add_local_listener(self._on_incoming)
        self.refresh()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        from core.qt.remote_common import SimpleRemoteSettings

        return SimpleRemoteSettings(
            parent,
            manager,
            get_server=lambda: web_server.server,
            app_key="messages",
            default_port=DEFAULT_PORT,
            title="Remote access (chat on phone)",
            hint="Phones on your tailnet use this relay. The desktop tab also keeps it listening.",
        )

    def on_show(self):
        self.refresh()

    def closeEvent(self, event):
        web_server.remove_local_listener(self._on_incoming)
        super().closeEvent(event)

    def _on_incoming(self, _message):
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        messages = storage.get_messages_since(0)
        if not messages:
            empty = QLabel("No messages yet.")
            empty.setObjectName("Muted")
            self.list_lay.addWidget(empty)
        for message in messages:
            mine = message.get("sender_id") == DESKTOP_SENDER_ID
            bubble = QLabel(f"{message.get('text', '')}\n{self._format_time(message.get('sent_at', 0))}")
            bubble.setWordWrap(True)
            bubble.setObjectName("Card")
            bubble.setAlignment(Qt.AlignmentFlag.AlignRight if mine else Qt.AlignmentFlag.AlignLeft)
            self.list_lay.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignRight if mine else Qt.AlignmentFlag.AlignLeft)
        self.list_lay.addStretch(1)

    @staticmethod
    def _format_time(epoch_seconds):
        try:
            dt = datetime.datetime.fromtimestamp(epoch_seconds)
        except Exception:
            return ""
        return dt.strftime("%I:%M %p").lstrip("0")

    def _send(self):
        text = self.entry.text().strip()
        if not text:
            return
        self.entry.clear()
        try:
            web_server.send_from_desktop(DESKTOP_SENDER_ID, text)
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't send", str(exc))
            return
        self.refresh()
