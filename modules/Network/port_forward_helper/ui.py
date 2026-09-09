"""Qt Port Forward Helper — UPnP IGD mappings."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
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
)

from modules.Network.port_forward_helper import upnp_client
from modules.Network.port_forward_helper.upnp_client import UPnPError


class PortForwardHelperUI(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.device = None
        self.mappings = []
        self.local_ip = upnp_client.get_local_ip()
        self._busy = False

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Port Forward Helper")
        title.setObjectName("AccentTitle")
        rescan = QPushButton("Rescan router")
        rescan.setObjectName("Primary")
        rescan.clicked.connect(self.detect_router)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(rescan)
        root.addLayout(header)

        stats = QFrame()
        stats.setObjectName("Panel")
        sl = QHBoxLayout(stats)
        self.router_label = self._stat(sl, "Router", "Detecting…")
        self.external_ip_label = self._stat(sl, "External IP", "—")
        self.local_ip_label = self._stat(sl, "This PC (LAN)", self.local_ip)
        root.addWidget(stats)

        add = QFrame()
        add.setObjectName("Panel")
        al = QVBoxLayout(add)
        add_title = QLabel("Add port forward")
        add_title.setObjectName("CardTitle")
        al.addWidget(add_title)
        row = QHBoxLayout()
        self.ext_port = QLineEdit()
        self.ext_port.setPlaceholderText("External e.g. 25565")
        self.int_port = QLineEdit()
        self.int_port.setPlaceholderText("Internal e.g. 25565")
        self.protocol = QComboBox()
        self.protocol.addItems(["TCP", "UDP"])
        self.internal_ip = QLineEdit(self.local_ip)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Description e.g. Minecraft")
        self.add_btn = QPushButton("Add")
        self.add_btn.setObjectName("Primary")
        self.add_btn.clicked.connect(self.add_mapping)
        row.addWidget(self.ext_port)
        row.addWidget(self.int_port)
        row.addWidget(self.protocol)
        row.addWidget(self.internal_ip)
        row.addWidget(self.desc, 1)
        row.addWidget(self.add_btn)
        al.addLayout(row)
        root.addWidget(add)

        table = QFrame()
        table.setObjectName("Panel")
        tl = QVBoxLayout(table)
        head = QHBoxLayout()
        map_title = QLabel("Current port mappings")
        map_title.setObjectName("CardTitle")
        self.mapping_count = QLabel("")
        self.mapping_count.setObjectName("Muted")
        head.addWidget(map_title)
        head.addStretch(1)
        head.addWidget(self.mapping_count)
        tl.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.table_host = QWidget()
        self.table_lay = QVBoxLayout(self.table_host)
        scroll.setWidget(self.table_host)
        tl.addWidget(scroll, 1)
        root.addWidget(table, 1)

        self._render_placeholder("Detecting your router…")
        QTimer.singleShot(150, self.detect_router)

    def _stat(self, parent_lay, label, value):
        cell = QVBoxLayout()
        lab = QLabel(label.upper())
        lab.setObjectName("Muted")
        val = QLabel(value)
        val.setObjectName("CardTitle")
        cell.addWidget(lab)
        cell.addWidget(val)
        parent_lay.addLayout(cell)
        return val

    def _clear_table(self):
        while self.table_lay.count():
            item = self.table_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_placeholder(self, text):
        self._clear_table()
        empty = QLabel(text)
        empty.setObjectName("Muted")
        empty.setWordWrap(True)
        self.table_lay.addWidget(empty)
        self.table_lay.addStretch(1)
        self.mapping_count.setText("")

    def _render_mappings(self):
        self._clear_table()
        if not self.mappings:
            empty = QLabel("No port mappings on this router yet.")
            empty.setObjectName("Muted")
            self.table_lay.addWidget(empty)
            self.table_lay.addStretch(1)
            self.mapping_count.setText("")
            return
        n = len(self.mappings)
        self.mapping_count.setText(f"{n} mapping{'s' if n != 1 else ''}")
        for m in self.mappings:
            row = QFrame()
            row.setObjectName("Panel")
            hl = QHBoxLayout(row)
            ext = QLabel(str(m.external_port))
            ext.setObjectName("AccentTitle")
            dest = QLabel(f"{m.internal_client}:{m.internal_port}")
            proto = QLabel(m.protocol)
            desc = QLabel(m.description or "—")
            desc.setObjectName("Muted")
            hl.addWidget(ext)
            hl.addWidget(QLabel("→"))
            hl.addWidget(dest)
            hl.addWidget(proto)
            hl.addWidget(desc, 1)
            if not m.enabled:
                off = QLabel("disabled")
                off.setObjectName("Danger")
                hl.addWidget(off)
            remove = QPushButton("Remove")
            remove.setObjectName("Danger")
            remove.clicked.connect(lambda _=False, mm=m: self.remove_mapping(mm))
            hl.addWidget(remove)
            self.table_lay.addWidget(row)
        self.table_lay.addStretch(1)

    def detect_router(self):
        if self._busy:
            return
        self._busy = True
        self.router_label.setText("Detecting…")
        self._render_placeholder("Detecting your router…")

        def work():
            try:
                device = upnp_client.discover()
                ip = upnp_client.get_external_ip(device)
                mappings = upnp_client.list_mappings(device)
            except UPnPError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self._detect_failed(m))
                return
            except Exception as e:
                msg = f"Unexpected error: {e}"
                QTimer.singleShot(0, lambda m=msg: self._detect_failed(m))
                return
            QTimer.singleShot(0, lambda: self._detect_succeeded(device, ip, mappings))

        threading.Thread(target=work, daemon=True).start()

    def _detect_failed(self, message):
        self._busy = False
        self.device = None
        self.router_label.setText("Not found")
        self.external_ip_label.setText("—")
        self._render_placeholder(message)

    def _detect_succeeded(self, device, external_ip, mappings):
        self._busy = False
        self.device = device
        self.mappings = mappings
        self.router_label.setText(device.friendly_name)
        self.external_ip_label.setText(external_ip)
        self._render_mappings()

    def add_mapping(self):
        if not self.device:
            QMessageBox.warning(self, "No router", "No router detected yet — click Rescan router first.")
            return
        ext_raw = self.ext_port.text().strip()
        int_raw = self.int_port.text().strip() or ext_raw
        protocol = self.protocol.currentText()
        internal_ip = self.internal_ip.text().strip() or self.local_ip
        description = self.desc.text().strip() or "Z's Multi Tool"
        if not ext_raw.isdigit() or not int_raw.isdigit():
            QMessageBox.warning(self, "Invalid port", "External/Internal port must be numbers.")
            return
        ext_port, int_port = int(ext_raw), int(int_raw)
        if not (1 <= ext_port <= 65535) or not (1 <= int_port <= 65535):
            QMessageBox.warning(self, "Invalid port", "Ports must be between 1 and 65535.")
            return
        self.add_btn.setEnabled(False)
        self.add_btn.setText("Adding…")

        def work():
            try:
                upnp_client.add_mapping(
                    self.device, ext_port, int_port, internal_ip,
                    protocol=protocol, description=description,
                )
                mappings = upnp_client.list_mappings(self.device)
            except UPnPError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self._add_failed(m))
                return
            QTimer.singleShot(0, lambda: self._add_succeeded(mappings))

        threading.Thread(target=work, daemon=True).start()

    def _add_failed(self, message):
        self.add_btn.setEnabled(True)
        self.add_btn.setText("Add")
        QMessageBox.warning(self, "Couldn't add mapping", message)

    def _add_succeeded(self, mappings):
        self.add_btn.setEnabled(True)
        self.add_btn.setText("Add")
        self.mappings = mappings
        self._render_mappings()
        self.ext_port.clear()
        self.int_port.clear()
        self.desc.clear()

    def remove_mapping(self, mapping):
        if not self.device:
            return
        if QMessageBox.question(
            self, "Remove port mapping",
            f"Remove the forward for external port {mapping.external_port}/{mapping.protocol}?",
        ) != QMessageBox.StandardButton.Yes:
            return

        def work():
            try:
                upnp_client.delete_mapping(self.device, mapping.external_port, mapping.protocol)
                mappings = upnp_client.list_mappings(self.device)
            except UPnPError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: QMessageBox.warning(self, "Couldn't remove mapping", m))
                return
            QTimer.singleShot(0, lambda: self._remove_succeeded(mappings))

        threading.Thread(target=work, daemon=True).start()

    def _remove_succeeded(self, mappings):
        self.mappings = mappings
        self._render_mappings()
