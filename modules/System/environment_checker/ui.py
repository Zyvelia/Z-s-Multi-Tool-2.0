"""Qt Environment Checker — dependency health and optional pip upgrades."""

from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.services.environment_checker import list_outdated_packages, run_all_checks, upgrade_packages


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class EnvironmentCheckerPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._outdated = []
        self._pkg_busy = False

        root = QVBoxLayout(self)
        title = QLabel("Environment Checker")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "Health checks only read your system. Green means ready; red means a feature may be broken. "
            "Package updates below are a separate, opt-in write (pip install -U)."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        btn_row = QHBoxLayout()
        recheck = QPushButton("Re-check")
        recheck.setObjectName("Primary")
        recheck.clicked.connect(self.run_checks)
        self.summary = QLabel("")
        btn_row.addWidget(recheck)
        btn_row.addWidget(self.summary)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.list_lay = QVBoxLayout(host)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        pkgs = QFrame()
        pkgs.setObjectName("Panel")
        pl = QVBoxLayout(pkgs)
        pkg_title = QLabel("Python packages")
        pkg_title.setObjectName("CardTitle")
        pl.addWidget(pkg_title)
        pkg_sub = QLabel("Compares this interpreter to PyPI. Update only if you want newer wheels in this env.")
        pkg_sub.setObjectName("Muted")
        pkg_sub.setWordWrap(True)
        pl.addWidget(pkg_sub)
        prow = QHBoxLayout()
        scan = QPushButton("Check package updates")
        scan.clicked.connect(self._scan_packages)
        self.update_all = QPushButton("Update all outdated")
        self.update_all.setObjectName("Primary")
        self.update_all.clicked.connect(self._update_all)
        self.pkg_status = QLabel("")
        self.pkg_status.setObjectName("Muted")
        prow.addWidget(scan)
        prow.addWidget(self.update_all)
        prow.addWidget(self.pkg_status, 1)
        pl.addLayout(prow)
        self.pkg_host = QWidget()
        self.pkg_lay = QVBoxLayout(self.pkg_host)
        pl.addWidget(self.pkg_host)
        root.addWidget(pkgs)
        self.run_checks()

    def run_checks(self):
        _clear(self.list_lay)
        results = run_all_checks()
        passed = sum(1 for r in results if r["ok"])
        total = len(results)
        self.summary.setText(f"{passed}/{total} checks passed")
        self.summary.setObjectName("Success" if passed == total else "Danger")
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        for item in results:
            self._add_row(item)
        self.list_lay.addStretch(1)

    def _add_row(self, item: dict):
        row = QFrame()
        row.setObjectName("Panel")
        lay = QVBoxLayout(row)
        head = QHBoxLayout()
        mark = QLabel("✓" if item["ok"] else "✗")
        mark.setObjectName("Success" if item["ok"] else "Danger")
        name = QLabel(item["name"])
        name.setObjectName("CardTitle")
        head.addWidget(mark)
        head.addWidget(name, 1)
        lay.addLayout(head)
        detail = QLabel(item["detail"])
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        lay.addWidget(detail)
        if item.get("fix") and not item["ok"]:
            fix = QLabel(f"Fix: {item['fix']}")
            fix.setObjectName("Muted")
            fix.setWordWrap(True)
            lay.addWidget(fix)
        self.list_lay.addWidget(row)

    def _scan_packages(self):
        if self._pkg_busy:
            return
        self._pkg_busy = True
        self.pkg_status.setText("Asking pip…")

        def work():
            rows, err = list_outdated_packages()
            QTimer.singleShot(0, lambda: self._show_packages(rows, err))

        threading.Thread(target=work, daemon=True).start()

    def _show_packages(self, rows, err):
        self._pkg_busy = False
        self._outdated = rows
        _clear(self.pkg_lay)
        if err:
            self.pkg_status.setText(err)
            self.pkg_status.setObjectName("Danger")
            self.pkg_status.style().unpolish(self.pkg_status)
            self.pkg_status.style().polish(self.pkg_status)
            return
        self.pkg_status.setText("All packages current" if not rows else f"{len(rows)} outdated")
        self.pkg_status.setObjectName("Success" if not rows else "Muted")
        self.pkg_status.style().unpolish(self.pkg_status)
        self.pkg_status.style().polish(self.pkg_status)
        for item in rows:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(f"{item['name']}  {item['version']} → {item['latest']}")
            btn = QPushButton("Update")
            btn.clicked.connect(lambda _=False, n=item["name"]: self._update_one(n))
            hl.addWidget(lab, 1)
            hl.addWidget(btn)
            self.pkg_lay.addWidget(row)

    def _update_one(self, name: str):
        self._run_upgrade([name])

    def _update_all(self):
        names = [r["name"] for r in self._outdated]
        if not names:
            self.pkg_status.setText("Scan first — nothing queued.")
            return
        self._run_upgrade(names)

    def _run_upgrade(self, names: list[str]):
        if self._pkg_busy:
            return
        self._pkg_busy = True
        extra = "…" if len(names) > 4 else ""
        self.pkg_status.setText(f"Updating {', '.join(names[:4])}{extra}…")

        def work():
            ok, msg = upgrade_packages(names)
            QTimer.singleShot(0, lambda: self._upgrade_done(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _upgrade_done(self, ok, msg):
        self._pkg_busy = False
        self.pkg_status.setText("Updated. Re-scan to confirm." if ok else msg)
        self.pkg_status.setObjectName("Success" if ok else "Danger")
        self.pkg_status.style().unpolish(self.pkg_status)
        self.pkg_status.style().polish(self.pkg_status)
        if ok:
            self._scan_packages()
