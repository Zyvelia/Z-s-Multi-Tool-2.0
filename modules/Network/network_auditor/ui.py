"""Qt Network Auditor — ARP discover, nmap scan, threat report."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
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

from modules.Network.network_auditor.port_scanner import PortScanner, PortScannerError
from modules.Network.network_auditor.scanner import NetworkScanner, NetworkScannerError
from modules.Network.network_auditor.threat_report import ThreatReporter


class NetworkAuditorUI(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.scanner = NetworkScanner()
        self.port_scanner = PortScanner()
        self.threat_reporter = ThreatReporter()
        self.devices = []

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Network Auditor")
        title.setObjectName("AccentTitle")
        self.network = QLineEdit()
        self.network.setPlaceholderText("e.g. 192.168.1.0/24")
        detect = QPushButton("Auto detect")
        detect.clicked.connect(self.auto_detect_network)
        discover = QPushButton("Discover")
        discover.setObjectName("Primary")
        discover.clicked.connect(self.discover_devices)
        header.addWidget(title)
        header.addWidget(self.network, 1)
        header.addWidget(detect)
        header.addWidget(discover)
        root.addLayout(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        devices_title = QLabel("Devices")
        devices_title.setObjectName("CardTitle")
        ll.addWidget(devices_title)
        hint = QLabel("Discovered devices on the network.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        ll.addWidget(hint)
        self.device_pick = QComboBox()
        self.device_pick.addItem("No devices found")
        ll.addWidget(self.device_pick)
        scan = QPushButton("Scan device")
        scan.setObjectName("Primary")
        scan.clicked.connect(self.scan_selected)
        ll.addWidget(scan)
        self.device_count = QLabel("No devices discovered yet.")
        self.device_count.setObjectName("Muted")
        ll.addWidget(self.device_count)
        ll.addStretch(1)

        right = QFrame()
        right.setObjectName("Panel")
        rl = QVBoxLayout(right)
        results_title = QLabel("Scan results")
        results_title.setObjectName("CardTitle")
        rl.addWidget(results_title)
        sub = QLabel("Open ports and threat analysis for the selected device.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        rl.addWidget(sub)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.results_host = QWidget()
        self.results_lay = QVBoxLayout(self.results_host)
        scroll.setWidget(self.results_host)
        rl.addWidget(scroll, 1)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        self._render_placeholder()
        self.auto_detect_network()
        if not PortScanner.is_nmap_available():
            self.status.setText("Nmap not found — port scanning is disabled until it's installed (nmap.org).")

    def _clear_results(self):
        while self.results_lay.count():
            item = self.results_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_placeholder(self):
        self._clear_results()
        empty = QLabel("Select a device and click Scan device.")
        empty.setObjectName("Muted")
        self.results_lay.addWidget(empty)
        self.results_lay.addStretch(1)

    def auto_detect_network(self):
        def work():
            network = self.scanner.auto_detect_network()
            QTimer.singleShot(0, lambda: self.network.setText(network))

        threading.Thread(target=work, daemon=True).start()

    def discover_devices(self):
        self.status.setText("Scanning network…")
        network = self.network.text().strip() or "192.168.1.0/24"

        def work():
            try:
                devices = self.scanner.discover(network)
            except NetworkScannerError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self.status.setText(m))
                return
            QTimer.singleShot(0, lambda: self._update_devices(devices))

        threading.Thread(target=work, daemon=True).start()

    def _update_devices(self, devices):
        self.devices = devices
        self.device_pick.clear()
        if devices:
            for d in devices:
                self.device_pick.addItem(f"{d.vendor}  ({d.ip})", d.ip)
            n = len(devices)
            self.device_count.setText(f"{n} device{'s' if n != 1 else ''} found.")
        else:
            self.device_pick.addItem("No devices found")
            self.device_count.setText("No devices discovered yet.")
        self.status.setText(f"Found {len(devices)} devices")

    def scan_selected(self):
        if not self.devices:
            self.status.setText("No devices found — run Discover first.")
            return
        ip = self.device_pick.currentData()
        if not ip:
            self.status.setText("No device selected.")
            return
        self.status.setText(f"Scanning {ip}…")

        def work():
            try:
                ports = self.port_scanner.scan(ip)
            except PortScannerError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self.status.setText(m))
                return
            threats = self.threat_reporter.analyze(ports)
            QTimer.singleShot(0, lambda: self._update_results(ports, threats))

        threading.Thread(target=work, daemon=True).start()

    def _update_results(self, ports, threats):
        self._clear_results()
        ports_title = QLabel("Open ports")
        ports_title.setObjectName("CardTitle")
        self.results_lay.addWidget(ports_title)
        if not ports:
            none = QLabel("No open ports found.")
            none.setObjectName("Muted")
            self.results_lay.addWidget(none)
        else:
            for port in ports:
                row = QLabel(f"{port.port}  ·  {port.service}")
                self.results_lay.addWidget(row)
        threat_title = QLabel("Threat report")
        threat_title.setObjectName("CardTitle")
        self.results_lay.addWidget(threat_title)
        if not threats:
            ok = QLabel("No threats detected.")
            ok.setObjectName("Success")
            self.results_lay.addWidget(ok)
        else:
            for threat in threats:
                card = QFrame()
                card.setObjectName("Panel")
                cl = QVBoxLayout(card)
                head = QHBoxLayout()
                t = QLabel(threat.title)
                t.setObjectName("CardTitle")
                sev = QLabel(threat.severity.upper())
                sev.setObjectName("Danger" if threat.severity.lower() in ("high", "critical") else "Muted")
                head.addWidget(t, 1)
                head.addWidget(sev)
                desc = QLabel(threat.description)
                desc.setObjectName("Muted")
                desc.setWordWrap(True)
                cl.addLayout(head)
                cl.addWidget(desc)
                self.results_lay.addWidget(card)
        self.results_lay.addStretch(1)
        self.status.setText(
            f"Scan complete — {len(ports)} open port{'s' if len(ports) != 1 else ''}, "
            f"{len(threats)} threat{'s' if len(threats) != 1 else ''} found."
        )
