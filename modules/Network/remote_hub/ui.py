"""Qt Remote Hub — same HubController as the CTk page."""

from __future__ import annotations

import io
import threading

import qrcode
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.services import device_trust, hub_service
from modules.Network.remote_hub.controller import APPS, HubController

STATUS_POLL_MS = 4000


class RemoteHubPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.controller = HubController(manager)
        self._hub_link = ""
        self._app_labels = {}

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
        self._build_go_live()
        self._build_trust()
        self._build_qr()
        self._build_inbox()
        self._build_status()
        self._body.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(STATUS_POLL_MS)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()
        self._refresh_status()

    def on_hide(self):
        self._timer.stop()

    def on_show(self):
        if not self._timer.isActive():
            self._timer.start()
        self._refresh_status()

    def _panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        return frame, lay

    def _build_header(self):
        title = QLabel("📡 Remote Hub")
        title.setObjectName("AccentTitle")
        hint = QLabel(
            "One address for your phone that links to whichever of your apps are live, "
            "instead of remembering three. Reachable only from devices on your own Tailscale network."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self._body.addWidget(title)
        self._body.addWidget(hint)

    def _build_go_live(self):
        frame, lay = self._panel()
        self.hub_status = QLabel("Checking…")
        self.hub_status.setObjectName("Muted")
        self.hub_status.setWordWrap(True)
        lay.addWidget(self.hub_status)
        row = QHBoxLayout()
        self.go_live_btn = QPushButton("Go Live")
        self.go_live_btn.setObjectName("Primary")
        self.go_live_btn.clicked.connect(self._on_go_live)
        self.go_offline_btn = QPushButton("Go Offline")
        self.go_offline_btn.setObjectName("Danger")
        self.go_offline_btn.clicked.connect(self._on_go_offline)
        row.addWidget(self.go_live_btn)
        row.addWidget(self.go_offline_btn)
        lay.addLayout(row)
        self._body.addWidget(frame)

    def _build_trust(self):
        frame, lay = self._panel()
        title = QLabel("This phone only")
        title.setObjectName("CardTitle")
        hint = QLabel(
            "Pair your phone with a one-time code. After you turn on "
            "“Only paired phones”, a stolen copy of the app stops when you "
            "revoke it here. This is not malware detection — revoke is the kill switch. "
            "The Night page still uses invite keys so friends can join."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(hint)
        self.required_box = QCheckBox(
            "Only paired phones can use Vault, Chat, servers, notes, and the rest"
        )
        self.required_box.setChecked(device_trust.is_required())
        self.required_box.toggled.connect(self._on_trust_required)
        lay.addWidget(self.required_box)
        row = QHBoxLayout()
        issue = QPushButton("Issue pairing code")
        issue.clicked.connect(self._on_issue_pair_code)
        self.pair_code = QLabel("")
        self.pair_code.setObjectName("AccentTitle")
        self.pair_hint = QLabel("Go Live first, then type the code in the phone app → Settings.")
        self.pair_hint.setObjectName("Muted")
        row.addWidget(issue)
        row.addWidget(self.pair_code)
        row.addWidget(self.pair_hint, 1)
        lay.addLayout(row)
        self.device_host = QWidget()
        self.device_lay = QVBoxLayout(self.device_host)
        self.device_lay.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(self.device_host)
        self._body.addWidget(frame)
        self._refresh_device_list()

    def _build_qr(self):
        frame, lay = self._panel()
        row = QHBoxLayout()
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(160, 160)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = QVBoxLayout()
        scan = QLabel("Scan on your phone")
        scan.setObjectName("CardTitle")
        self.qr_url = QLabel("Go Live to generate a QR code for your hub URL.")
        self.qr_url.setObjectName("Muted")
        self.qr_url.setWordWrap(True)
        self.qr_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = QPushButton("Copy hub link")
        copy.clicked.connect(self._copy_hub_link)
        col.addWidget(scan)
        col.addWidget(self.qr_url)
        col.addWidget(copy, alignment=Qt.AlignmentFlag.AlignLeft)
        col.addStretch(1)
        row.addWidget(self.qr_label)
        row.addLayout(col, 1)
        lay.addLayout(row)
        self._body.addWidget(frame)

    def _build_inbox(self):
        frame, lay = self._panel()
        title = QLabel("Unified inbox")
        title.setObjectName("CardTitle")
        hint = QLabel(
            "Recent files from Quick Send — same list appears on the phone hub page when Send is live."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(hint)
        self.inbox_host = QWidget()
        self.inbox_lay = QVBoxLayout(self.inbox_host)
        self.inbox_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.inbox_host)
        self._body.addWidget(frame)

    def _build_status(self):
        frame, lay = self._panel()
        title = QLabel("Per-app status")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        for key, label in APPS:
            row = QHBoxLayout()
            name = QLabel(label)
            status = QLabel("Off")
            status.setObjectName("Muted")
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(status)
            lay.addLayout(row)
            self._app_labels[key] = status
        note = QLabel(
            "Fine-grained on/off for a single app still lives in that app's own "
            "⚙ settings — this page is for the phone-facing address as a whole."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self._body.addWidget(frame)

    def _on_trust_required(self, on):
        device_trust.set_required(bool(on))
        self._refresh_device_list()

    def _on_issue_pair_code(self):
        code = device_trust.issue_pair_code()
        self.pair_code.setText(code)
        self.pair_hint.setText("Valid about 10 minutes. Enter it on the phone, then flip the switch.")

    def _on_revoke_device(self, device_id):
        box = QMessageBox.question(
            self,
            "Revoke this phone?",
            "That copy of the app will stop talking to this PC until you pair again.",
        )
        if box != QMessageBox.StandardButton.Yes:
            return
        device_trust.revoke(device_id)
        self._refresh_device_list()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh_device_list(self):
        self._clear_layout(self.device_lay)
        devices = device_trust.list_devices()
        if not devices:
            empty = QLabel("No phones paired yet.")
            empty.setObjectName("Muted")
            self.device_lay.addWidget(empty)
            return
        for d in devices:
            row = QHBoxLayout()
            revoked = d.get("revoked")
            label = QLabel(f"{d.get('label') or 'phone'}{' — revoked' if revoked else ''}")
            if revoked:
                label.setObjectName("Muted")
            row.addWidget(label, 1)
            if not revoked:
                btn = QPushButton("Revoke")
                btn.setObjectName("Danger")
                btn.clicked.connect(lambda _=False, i=d.get("id"): self._on_revoke_device(i))
                row.addWidget(btn)
            self.device_lay.addLayout(row)

    def _copy_hub_link(self):
        if not self._hub_link:
            QMessageBox.information(self, "Remote Hub", "Go Live first — then the hub link will be ready to copy.")
            return
        QApplication.clipboard().setText(self._hub_link)
        QMessageBox.information(self, "Remote Hub", "Hub link copied to clipboard.")

    def _set_qr(self, url):
        self._hub_link = url or ""
        if not url:
            self.qr_label.clear()
            self.qr_url.setText("Go Live to generate a QR code for your hub URL.")
            return
        self.qr_url.setText(url)
        qr = qrcode.QRCode(box_size=4, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0f1115", back_color="#e8ecf1").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        self.qr_label.setPixmap(pix.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))

    def _refresh_inbox(self, live_apps):
        self._clear_layout(self.inbox_lay)
        if not live_apps.get("send"):
            lab = QLabel("Quick Send is off — start it from Go Live or the Quick Send module.")
            lab.setObjectName("Muted")
            self.inbox_lay.addWidget(lab)
            return
        entries = hub_service._recent_quick_send(8)
        if not entries:
            lab = QLabel("No files received yet.")
            lab.setObjectName("Muted")
            self.inbox_lay.addWidget(lab)
            return
        for entry in entries:
            row = QHBoxLayout()
            name = QLabel(entry.get("filename") or "file")
            when = QLabel(hub_service._time_ago(entry.get("received_at", 0)))
            when.setObjectName("Muted")
            row.addWidget(name, 1)
            row.addWidget(when)
            self.inbox_lay.addLayout(row)

    def _on_go_live(self):
        self.go_live_btn.setEnabled(False)
        self.go_live_btn.setText("Starting…")

        def work():
            fatal, errors = self.controller.go_live_sync()
            if fatal:
                QTimer.singleShot(0, lambda: self._go_live_failed(fatal))
            else:
                QTimer.singleShot(0, lambda: self._go_live_done(errors))

        threading.Thread(target=work, daemon=True).start()

    def _go_live_failed(self, msg):
        self.go_live_btn.setEnabled(True)
        self.go_live_btn.setText("Go Live")
        QMessageBox.critical(self, "Couldn't go live", msg)
        self._refresh_status()

    def _go_live_done(self, errors):
        self.go_live_btn.setEnabled(True)
        self.go_live_btn.setText("Go Live")
        if errors:
            QMessageBox.warning(
                self, "Went live with some issues",
                "Some apps didn't come up cleanly:\n\n" + "\n".join(errors),
            )
        self._refresh_status()

    def _on_go_offline(self):
        self.go_offline_btn.setEnabled(False)
        self.go_offline_btn.setText("Stopping…")

        def work():
            self.controller.go_offline_sync()
            QTimer.singleShot(0, self._go_offline_done)

        threading.Thread(target=work, daemon=True).start()

    def _go_offline_done(self):
        self.go_offline_btn.setEnabled(True)
        self.go_offline_btn.setText("Go Offline")
        self._refresh_status()

    def _refresh_status(self):
        def work():
            status, live_apps = self.controller.get_status_sync()
            QTimer.singleShot(0, lambda: self._apply_status(status, live_apps))

        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, status, live_apps):
        for key, live in live_apps.items():
            lbl = self._app_labels.get(key)
            if lbl:
                lbl.setText("Live" if live else "Off")
                lbl.setObjectName("Success" if live else "Muted")
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
        if not status["installed"]:
            self.hub_status.setText(
                "Tailscale isn't installed on this device — install it first "
                "(any app's ⚙ settings has a shortcut)."
            )
            self.hub_status.setObjectName("Muted")
            self._set_qr(None)
        elif not status["running"]:
            self.hub_status.setText(
                "Not connected to your tailnet yet. Tap Go Live to connect and "
                "bring everything up in one step."
            )
            self.hub_status.setObjectName("Muted")
            self._set_qr(None)
        elif any(live_apps.values()):
            hostname = status.get("hostname") or "this-device"
            url = f"https://{hostname}/"
            self.hub_status.setText(
                f"Live — open {url} on your phone (same tailnet) or scan the QR below."
            )
            self.hub_status.setObjectName("Success")
            self._set_qr(url)
        else:
            self.hub_status.setText("Connected to Tailscale, but nothing is live yet. Tap Go Live.")
            self.hub_status.setObjectName("Muted")
            self._set_qr(None)
        self.hub_status.style().unpolish(self.hub_status)
        self.hub_status.style().polish(self.hub_status)
        self._refresh_inbox(live_apps)
        try:
            self._refresh_device_list()
        except Exception:
            pass
