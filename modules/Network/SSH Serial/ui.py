"""Qt SSH / Serial consoles."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_backend = importlib.import_module("modules.Network.SSH Serial.backend")
_storage = importlib.import_module("modules.Network.SSH Serial.storage")
SSHSession = _backend.SSHSession
SerialSession = _backend.SerialSession
SessionError = _backend.SessionError
list_com_ports = _backend.list_com_ports


class SSHSerialPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.ssh = SSHSession()
        self.serial = SerialSession()

        root = QVBoxLayout(self)
        title = QLabel("SSH / Serial")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        hint = QLabel("SSH into a Pi, VPS, or LAN box. Serial is for a console cable / COM port. Passwords are not saved.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        tabs = QTabWidget()
        tabs.addTab(self._build_ssh(), "SSH")
        tabs.addTab(self._build_serial(), "Serial")
        root.addWidget(tabs, 1)
        self._reload_hosts()
        self._reload_ports()

    def closeEvent(self, event):
        self.ssh.close()
        self.serial.close()
        super().closeEvent(event)

    def on_hide(self):
        pass

    def _build_ssh(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        form = QFormLayout()
        self.ssh_name = QLineEdit()
        self.ssh_host = QLineEdit()
        self.ssh_port = QLineEdit("22")
        self.ssh_user = QLineEdit()
        self.ssh_pass = QLineEdit()
        self.ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_key = QLineEdit()
        form.addRow("Name", self.ssh_name)
        form.addRow("Host", self.ssh_host)
        form.addRow("Port", self.ssh_port)
        form.addRow("User", self.ssh_user)
        form.addRow("Password", self.ssh_pass)
        key_row = QHBoxLayout()
        key_row.addWidget(self.ssh_key, 1)
        browse = QPushButton("Key…")
        browse.clicked.connect(self._browse_key)
        key_row.addWidget(browse)
        form.addRow("Key file", key_row)
        lay.addLayout(form)

        btns = QHBoxLayout()
        connect = QPushButton("Connect")
        connect.setObjectName("Primary")
        connect.clicked.connect(self._ssh_connect)
        disc = QPushButton("Disconnect")
        disc.setObjectName("Danger")
        disc.clicked.connect(self._ssh_close)
        save = QPushButton("Save host")
        save.clicked.connect(self._save_host)
        wt = QPushButton("Open in Windows Terminal")
        wt.clicked.connect(self._open_wt)
        btns.addWidget(connect)
        btns.addWidget(disc)
        btns.addWidget(save)
        btns.addWidget(wt)
        btns.addStretch(1)
        lay.addLayout(btns)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        saved = QLabel("Saved")
        saved.setObjectName("CardTitle")
        ll.addWidget(saved)
        self.host_list = QListWidget()
        self.host_list.itemClicked.connect(self._apply_host_item)
        ll.addWidget(self.host_list, 1)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete_host)
        ll.addWidget(delete)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.ssh_out = QPlainTextEdit()
        self.ssh_out.setReadOnly(True)
        self.ssh_in = QLineEdit()
        self.ssh_in.setPlaceholderText("Type and press Enter (sends a line)")
        self.ssh_in.returnPressed.connect(self._ssh_send)
        rl.addWidget(self.ssh_out, 1)
        rl.addWidget(self.ssh_in)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        lay.addWidget(split, 1)
        self.ssh_status = QLabel("Disconnected")
        self.ssh_status.setObjectName("Muted")
        lay.addWidget(self.ssh_status)
        return page

    def _build_serial(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(QLabel("Port"))
        self.com = QComboBox()
        row.addWidget(self.com)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._reload_ports)
        row.addWidget(refresh)
        row.addWidget(QLabel("Baud"))
        self.baud = QComboBox()
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200", "230400"])
        saved = _storage.load().get("serial") or {}
        baud = str(saved.get("baud") or "115200")
        idx = self.baud.findText(baud)
        self.baud.setCurrentIndex(idx if idx >= 0 else 4)
        row.addWidget(self.baud)
        connect = QPushButton("Connect")
        connect.setObjectName("Primary")
        connect.clicked.connect(self._ser_connect)
        disc = QPushButton("Disconnect")
        disc.setObjectName("Danger")
        disc.clicked.connect(self._ser_close)
        row.addWidget(connect)
        row.addWidget(disc)
        row.addStretch(1)
        lay.addLayout(row)
        self.ser_out = QPlainTextEdit()
        self.ser_out.setReadOnly(True)
        self.ser_in = QLineEdit()
        self.ser_in.setPlaceholderText("Type and press Enter")
        self.ser_in.returnPressed.connect(self._ser_send)
        lay.addWidget(self.ser_out, 1)
        lay.addWidget(self.ser_in)
        self.ser_status = QLabel("Disconnected")
        self.ser_status.setObjectName("Muted")
        lay.addWidget(self.ser_status)
        return page

    def _reload_hosts(self):
        self.host_list.clear()
        for host in _storage.load().get("hosts", []):
            name = host.get("name") or host.get("hostname")
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, host)
            self.host_list.addItem(item)

    def _apply_host_item(self, item):
        host = item.data(Qt.ItemDataRole.UserRole) or {}
        self.ssh_name.setText(host.get("name") or "")
        self.ssh_host.setText(host.get("hostname") or "")
        self.ssh_port.setText(str(host.get("port") or 22))
        self.ssh_user.setText(host.get("username") or "")
        self.ssh_key.setText(host.get("key_path") or "")

    def _save_host(self):
        name = self.ssh_name.text().strip() or self.ssh_host.text().strip()
        if not name or not self.ssh_host.text().strip():
            QMessageBox.information(self, "SSH", "Need a host (and a name).")
            return
        _storage.upsert_host({
            "name": name,
            "hostname": self.ssh_host.text(),
            "port": self.ssh_port.text() or 22,
            "username": self.ssh_user.text(),
            "key_path": self.ssh_key.text(),
        })
        self._reload_hosts()

    def _delete_host(self):
        name = self.ssh_name.text().strip()
        if name:
            _storage.delete_host(name)
            self._reload_hosts()

    def _browse_key(self):
        path, _ = QFileDialog.getOpenFileName(self, "SSH private key")
        if path:
            self.ssh_key.setText(path)

    def _ssh_connect(self):
        host = self.ssh_host.text().strip()
        user = self.ssh_user.text().strip()
        if not host or not user:
            QMessageBox.information(self, "SSH", "Host and user are required.")
            return
        try:
            port = int(self.ssh_port.text() or 22)
        except ValueError:
            QMessageBox.warning(self, "SSH", "Port must be a number.")
            return
        password = self.ssh_pass.text()
        key_path = self.ssh_key.text().strip()
        self.ssh_status.setText(f"Connecting to {user}@{host}…")
        self.ssh_status.setObjectName("Muted")
        self.ssh_status.style().unpolish(self.ssh_status)
        self.ssh_status.style().polish(self.ssh_status)

        def on_data(text):
            QTimer.singleShot(0, lambda t=text: self._append(self.ssh_out, t))

        def work():
            try:
                self.ssh.connect(
                    hostname=host,
                    port=port,
                    username=user,
                    password=password,
                    key_path=key_path,
                    on_data=on_data,
                )
            except SessionError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self._ssh_failed(m))
                return
            QTimer.singleShot(0, lambda: self._ssh_ok(user, host))

        threading.Thread(target=work, daemon=True).start()

    def _append(self, box, text):
        box.moveCursor(QTextCursor.MoveOperation.End)
        box.insertPlainText(text)
        box.moveCursor(QTextCursor.MoveOperation.End)

    def _ssh_failed(self, msg):
        QMessageBox.warning(self, "SSH", msg)
        self.ssh_status.setText("Disconnected")
        self.ssh_status.setObjectName("Muted")
        self.ssh_status.style().unpolish(self.ssh_status)
        self.ssh_status.style().polish(self.ssh_status)

    def _ssh_ok(self, user, host):
        self.ssh_status.setText(f"Connected to {user}@{host}")
        self.ssh_status.setObjectName("Success")
        self.ssh_status.style().unpolish(self.ssh_status)
        self.ssh_status.style().polish(self.ssh_status)

    def _ssh_close(self):
        self.ssh.close()
        self.ssh_status.setText("Disconnected")
        self.ssh_status.setObjectName("Muted")
        self.ssh_status.style().unpolish(self.ssh_status)
        self.ssh_status.style().polish(self.ssh_status)

    def _ssh_send(self):
        line = self.ssh_in.text()
        self.ssh_in.clear()
        try:
            self.ssh.send(line + "\r")
        except SessionError as e:
            QMessageBox.warning(self, "SSH", str(e))

    def _open_wt(self):
        host = self.ssh_host.text().strip()
        user = self.ssh_user.text().strip()
        port = self.ssh_port.text().strip() or "22"
        if not host or not user:
            QMessageBox.information(self, "SSH", "Host and user are required.")
            return
        args = ["ssh", "-p", port]
        key = self.ssh_key.text().strip()
        if key:
            args.extend(["-i", key])
        args.append(f"{user}@{host}")
        wt = shutil.which("wt")
        try:
            kwargs = {}
            if not wt:
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen([wt, *args] if wt else args, **kwargs)
        except OSError as e:
            QMessageBox.warning(self, "SSH", f"Could not open an external client: {e}")

    def _reload_ports(self):
        ports = list_com_ports() or ["(none)"]
        current = (_storage.load().get("serial") or {}).get("port") or ports[0]
        self.com.clear()
        self.com.addItems(ports)
        idx = self.com.findText(current)
        self.com.setCurrentIndex(idx if idx >= 0 else 0)

    def _ser_connect(self):
        port = self.com.currentText()
        if not port or port == "(none)":
            QMessageBox.information(self, "Serial", "No COM port selected. Plug in a cable and hit Refresh.")
            return
        baud = self.baud.currentText()
        _storage.save_serial(port, baud)
        self.ser_status.setText(f"Opening {port}…")

        def on_data(text):
            QTimer.singleShot(0, lambda t=text: self._append(self.ser_out, t))

        def work():
            try:
                self.serial.connect(port, int(baud), on_data=on_data)
            except SessionError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: QMessageBox.warning(self, "Serial", m))
                QTimer.singleShot(0, lambda: self.ser_status.setText("Disconnected"))
                return
            QTimer.singleShot(0, lambda: self._ser_ok(port, baud))

        threading.Thread(target=work, daemon=True).start()

    def _ser_ok(self, port, baud):
        self.ser_status.setText(f"Open {port} @ {baud}")
        self.ser_status.setObjectName("Success")
        self.ser_status.style().unpolish(self.ser_status)
        self.ser_status.style().polish(self.ser_status)

    def _ser_close(self):
        self.serial.close()
        self.ser_status.setText("Disconnected")
        self.ser_status.setObjectName("Muted")
        self.ser_status.style().unpolish(self.ser_status)
        self.ser_status.style().polish(self.ser_status)

    def _ser_send(self):
        line = self.ser_in.text()
        self.ser_in.clear()
        try:
            self.serial.send(line + "\n")
        except SessionError as e:
            QMessageBox.warning(self, "Serial", str(e))
