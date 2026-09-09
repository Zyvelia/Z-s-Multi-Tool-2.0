"""Qt Tailnet Social — invite keys, jukebox queue, tailnet peers."""

from __future__ import annotations

import json
import shutil
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import importlib

storage = importlib.import_module("modules.Network.Tailnet Social.storage")
_web = importlib.import_module("modules.Network.Tailnet Social.web_server")
LOOPBACK_PORT = _web.LOOPBACK_PORT
start_http = _web.start


class TailnetSocialPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        start_http(LOOPBACK_PORT)

        root = QVBoxLayout(self)
        title = QLabel("Tailnet Social")
        title.setObjectName("AccentTitle")
        hint = QLabel(
            "Invite keys for friends on your tailnet. They get a jukebox queue, "
            "soundboard name, and optional limited server console. Messages is still this PC."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        local = QLabel(f"Local page: http://127.0.0.1:{LOOPBACK_PORT}/  (Hub Go Live maps it on the tailnet)")
        local.setObjectName("Success")
        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(local)

        issue = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Friend label")
        self.console = QCheckBox("Allow console")
        issue_btn = QPushButton("Issue key")
        issue_btn.setObjectName("Primary")
        issue_btn.clicked.connect(self._issue)
        issue.addWidget(self.name)
        issue.addWidget(self.console)
        issue.addWidget(issue_btn)
        issue.addStretch(1)
        root.addLayout(issue)

        split = QSplitter(Qt.Orientation.Horizontal)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        self.keys_host = QWidget()
        self.keys_lay = QVBoxLayout(self.keys_host)
        left_scroll.setWidget(self.keys_host)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        self.right_host = QWidget()
        self.right_lay = QVBoxLayout(self.right_host)
        right_scroll.setWidget(self.right_host)
        split.addWidget(left_scroll)
        split.addWidget(right_scroll)
        root.addWidget(split, 1)
        self.reload()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        from core.qt.remote_common import SimpleRemoteSettings, ensure_manager_server

        return SimpleRemoteSettings(
            parent,
            manager,
            get_server=lambda: ensure_manager_server(
                manager, "social_web_server", _web.SocialWebServer
            ),
            app_key="social",
            default_port=LOOPBACK_PORT,
            title="Remote access (night page on phone)",
            hint="Friends on your tailnet open this page for the jukebox queue and soundboard. Hub Go Live maps it too.",
        )

    def on_show(self):
        self.reload()

    def _issue(self):
        invite = storage.issue_invite(self.name.text(), console=self.console.isChecked())
        QApplication.clipboard().setText(invite["key"])
        self.reload()

    def _copy(self, key):
        QApplication.clipboard().setText(key)

    def _revoke(self, key):
        storage.revoke_invite(key)
        self.reload()

    def _clear_q(self):
        storage.queue_clear()
        self.reload()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def reload(self):
        self._clear_layout(self.keys_lay)
        heading = QLabel("Invite keys (copied on issue)")
        heading.setObjectName("CardTitle")
        self.keys_lay.addWidget(heading)
        for invite in storage.load().get("invites", []):
            row = QFrame()
            row.setObjectName("Card")
            hl = QHBoxLayout(row)
            extra = " · console" if invite.get("console") else ""
            lab = QLabel(f"{invite.get('label')}{extra}")
            copy = QPushButton("Copy")
            copy.clicked.connect(lambda _=False, k=invite["key"]: self._copy(k))
            revoke = QPushButton("Revoke")
            revoke.setObjectName("Danger")
            revoke.clicked.connect(lambda _=False, k=invite["key"]: self._revoke(k))
            hl.addWidget(lab, 1)
            hl.addWidget(copy)
            hl.addWidget(revoke)
            self.keys_lay.addWidget(row)
        self.keys_lay.addStretch(1)

        self._clear_layout(self.right_lay)
        qh = QLabel("Jukebox queue")
        qh.setObjectName("CardTitle")
        self.right_lay.addWidget(qh)
        queue = storage.queue_list()
        if not queue:
            empty = QLabel("Empty — friends add tracks from the night page.")
            empty.setObjectName("Muted")
            self.right_lay.addWidget(empty)
        for item in queue:
            self.right_lay.addWidget(QLabel(f"{item.get('title')}  ({item.get('by') or '?'})"))
        clear = QPushButton("Clear queue")
        clear.clicked.connect(self._clear_q)
        self.right_lay.addWidget(clear, alignment=Qt.AlignmentFlag.AlignLeft)
        ph = QLabel("Tailnet peers")
        ph.setObjectName("CardTitle")
        self.right_lay.addWidget(ph)
        for line in self._peers():
            lab = QLabel(line)
            lab.setObjectName("Muted")
            self.right_lay.addWidget(lab)
        self.right_lay.addStretch(1)

    def _peers(self):
        ts = shutil.which("tailscale")
        if not ts:
            return ["tailscale CLI not on PATH"]
        try:
            raw = subprocess.check_output([ts, "status", "--json"], timeout=8)
            data = json.loads(raw)
        except Exception as e:
            return [str(e)]
        lines = []
        self_name = (data.get("Self") or {}).get("HostName") or "this PC"
        lines.append(f"This device: {self_name}")
        for peer in (data.get("Peer") or {}).values():
            name = peer.get("HostName") or peer.get("DNSName") or "?"
            online = "online" if peer.get("Online") else "offline"
            lines.append(f"{name} · {online}")
        return lines or ["No peers."]
