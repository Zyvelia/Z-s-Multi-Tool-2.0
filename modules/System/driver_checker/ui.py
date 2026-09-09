"""Qt Driver/Update Checker — installed drivers, WU drivers, winget."""

from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.System.driver_checker.backend import (
    WIN32COM_AVAILABLE,
    check_driver_updates,
    check_software_updates,
    list_installed_drivers,
)


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class DriverCheckerModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._drivers = []

        root = QVBoxLayout(self)
        title = QLabel("Driver / Update Checker")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "Installed drivers, pending driver updates via Windows Update, "
            "and pending app/package updates via winget — three separate checks."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        tabs.addTab(self._build_drivers_tab(), "Installed Drivers")
        tabs.addTab(self._build_driver_updates_tab(), "Driver Updates")
        tabs.addTab(self._build_software_updates_tab(), "Software Updates")

    def _header_row(self, label, command):
        row = QHBoxLayout()
        btn = QPushButton(label)
        btn.setObjectName("Primary")
        btn.clicked.connect(command)
        status = QLabel("")
        status.setObjectName("Muted")
        row.addWidget(btn)
        row.addWidget(status, 1)
        return row, btn, status

    def _scroll_host(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        scroll.setWidget(host)
        return scroll, lay

    def _build_drivers_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        row, self.drivers_btn, self.drivers_status = self._header_row(
            "Scan Installed Drivers", self._start_driver_scan
        )
        lay.addLayout(row)
        self.driver_search = QLineEdit()
        self.driver_search.setPlaceholderText("Filter by device name…")
        self.driver_search.textChanged.connect(self._render_driver_rows)
        lay.addWidget(self.driver_search)
        scroll, self.drivers_lay = self._scroll_host()
        lay.addWidget(scroll, 1)
        return page

    def _start_driver_scan(self):
        self.drivers_btn.setEnabled(False)
        self.drivers_status.setText("Querying installed drivers…")

        def work():
            drivers, error = list_installed_drivers()
            QTimer.singleShot(0, lambda: self._finish_driver_scan(drivers, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_driver_scan(self, drivers, error):
        self.drivers_btn.setEnabled(True)
        self._drivers = drivers
        self.drivers_status.setText(error or f"{len(drivers)} driver(s) found.")
        self._render_driver_rows()

    def _render_driver_rows(self):
        _clear(self.drivers_lay)
        query = self.driver_search.text().strip().lower()
        visible = [d for d in self._drivers if query in d.device_name.lower()] if query else self._drivers
        if not visible:
            empty = QLabel("No drivers to show — run a scan above." if not self._drivers else "No matches.")
            empty.setObjectName("Muted")
            self.drivers_lay.addWidget(empty)
            self.drivers_lay.addStretch(1)
            return
        for d in visible:
            row = QFrame()
            row.setObjectName("Panel")
            rl = QVBoxLayout(row)
            name = QLabel(d.device_name)
            name.setObjectName("CardTitle")
            detail = QLabel(
                f"{d.manufacturer or 'Unknown manufacturer'} · v{d.version or '?'} · "
                f"{d.date or 'no date'} · {d.device_class or 'Unclassified'}"
            )
            detail.setObjectName("Muted")
            rl.addWidget(name)
            rl.addWidget(detail)
            self.drivers_lay.addWidget(row)
        self.drivers_lay.addStretch(1)

    def _build_driver_updates_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        row, self.driver_upd_btn, self.driver_upd_status = self._header_row(
            "Check Windows Update for Drivers", self._start_driver_update_check
        )
        lay.addLayout(row)
        if not WIN32COM_AVAILABLE:
            self.driver_upd_btn.setEnabled(False)
            self.driver_upd_status.setText("Requires pywin32 (not installed on this machine).")
        scroll, self.driver_upd_lay = self._scroll_host()
        lay.addWidget(scroll, 1)
        return page

    def _start_driver_update_check(self):
        self.driver_upd_btn.setEnabled(False)
        self.driver_upd_status.setText("Checking Windows Update — this can take a minute…")

        def work():
            updates, error = check_driver_updates()
            QTimer.singleShot(0, lambda: self._finish_driver_update_check(updates, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_driver_update_check(self, updates, error):
        self.driver_upd_btn.setEnabled(True)
        _clear(self.driver_upd_lay)
        if error:
            self.driver_upd_status.setText(error)
            self.driver_upd_lay.addStretch(1)
            return
        self.driver_upd_status.setText(
            f"{len(updates)} pending driver update(s)." if updates else "No pending driver updates."
        )
        for u in updates:
            row = QFrame()
            row.setObjectName("Panel")
            rl = QVBoxLayout(row)
            name = QLabel(u.title)
            name.setObjectName("CardTitle")
            desc = (u.description[:180] + "…") if len(u.description) > 180 else u.description
            if u.kb_articles:
                desc = f"{u.kb_articles} — {desc}" if desc else u.kb_articles
            detail = QLabel(desc or "(no description)")
            detail.setObjectName("Muted")
            detail.setWordWrap(True)
            rl.addWidget(name)
            rl.addWidget(detail)
            self.driver_upd_lay.addWidget(row)
        self.driver_upd_lay.addStretch(1)

    def _build_software_updates_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        row, self.sw_upd_btn, self.sw_upd_status = self._header_row(
            "Check winget for Updates", self._start_software_update_check
        )
        lay.addLayout(row)
        scroll, self.sw_upd_lay = self._scroll_host()
        lay.addWidget(scroll, 1)
        return page

    def _start_software_update_check(self):
        self.sw_upd_btn.setEnabled(False)
        self.sw_upd_status.setText("Checking installed packages against winget…")

        def work():
            updates, error = check_software_updates()
            QTimer.singleShot(0, lambda: self._finish_software_update_check(updates, error))

        threading.Thread(target=work, daemon=True).start()

    def _finish_software_update_check(self, updates, error):
        self.sw_upd_btn.setEnabled(True)
        _clear(self.sw_upd_lay)
        if error:
            self.sw_upd_status.setText(error)
            self.sw_upd_lay.addStretch(1)
            return
        self.sw_upd_status.setText(
            f"{len(updates)} update(s) available." if updates else "Everything is up to date."
        )
        for u in updates:
            row = QFrame()
            row.setObjectName("Panel")
            rl = QVBoxLayout(row)
            name = QLabel(f"{u.name}  ({u.id})")
            name.setObjectName("CardTitle")
            detail = QLabel(
                f"{u.current_version or '?'} → {u.available_version or '?'} · {u.source or 'unknown source'}"
            )
            detail.setObjectName("Muted")
            rl.addWidget(name)
            rl.addWidget(detail)
            self.sw_upd_lay.addWidget(row)
        self.sw_upd_lay.addStretch(1)
