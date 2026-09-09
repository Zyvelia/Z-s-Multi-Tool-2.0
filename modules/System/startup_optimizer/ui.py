"""Qt Startup Optimizer — scan startup apps/services, classify, toggle."""

from __future__ import annotations

import ctypes
import json
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.System.startup_optimizer.startup_optimizer.classifier import (
    Classifier,
    _data_dir,
    load_change_log,
    log_change,
)
from modules.System.startup_optimizer.startup_optimizer.scanner import (
    PYWIN32_SERVICE_AVAILABLE,
    REGISTRY_AVAILABLE,
    create_restore_point,
    is_admin,
    list_services,
    list_startup_items,
    set_service_start_type,
    set_startup_enabled,
)
from modules.System.startup_optimizer.startup_optimizer.sync import check_and_update

STATUS_ORDER = ["red", "yellow", "green"]
STATUS_LABEL = {
    "red": "🔴 Recommended to disable",
    "yellow": "🟡 Review before deciding",
    "green": "🟢 Keep enabled",
}
IMPACT_RAM_MB = {"low": 30, "medium": 90, "high": 180, "critical": 0, "unknown": 40}
START_TYPES = ["Auto", "Manual", "Disabled"]


def _relaunch_as_admin() -> bool:
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(f'"{a}"' for a in sys.argv), None, 1,
        )
        return True
    except Exception:
        return False


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class StartupOptimizerModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.classifier = Classifier()
        self._startup_items = []
        self._service_items = []
        self._collapsed = {
            "startup_apps:red": False,
            "startup_apps:yellow": False,
            "startup_apps:green": False,
            "services:red": True,
            "services:yellow": True,
            "services:green": True,
        }
        self._scan_gen = 0

        root = QVBoxLayout(self)
        title = QLabel("Startup Optimizer")
        title.setObjectName("AccentTitle")
        hint = QLabel(
            "Everything that launches at sign-in, plus background services — classified "
            "so you know what's safe to turn off. Disabling is reversible from here."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name…")
        self.search.textChanged.connect(self._render_all)
        rescan = QPushButton("Rescan")
        rescan.clicked.connect(self.refresh)
        undo = QPushButton("Undo last")
        undo.clicked.connect(self._undo_last)
        export = QPushButton("Export state")
        export.clicked.connect(self._export_state)
        cleanup = QPushButton("Apply recommended cleanup")
        cleanup.setObjectName("Primary")
        cleanup.clicked.connect(self._apply_recommended_cleanup)
        bar.addWidget(self.search, 1)
        bar.addWidget(rescan)
        bar.addWidget(undo)
        bar.addWidget(export)
        bar.addWidget(cleanup)
        root.addLayout(bar)

        self.tabs = QTabWidget()
        self.startup_summary, self.startup_list = self._tab()
        self.services_summary, self.services_list = self._tab()
        self.tabs.addTab(self._wrap(self.startup_summary, self.startup_list), "Startup Apps")
        self.tabs.addTab(self._wrap(self.services_summary, self.services_list), "Services")
        root.addWidget(self.tabs, 1)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)
        if not REGISTRY_AVAILABLE:
            self.status.setText("This module reads the Windows registry and services — unavailable on this platform.")
        elif not PYWIN32_SERVICE_AVAILABLE:
            self.status.setText("pywin32 not found — Services tab is using a slower PowerShell fallback.")

        self.refresh()
        self._check_for_db_update()

    def _tab(self):
        summary = QLabel("")
        summary.setObjectName("Muted")
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        return summary, lay

    def _wrap(self, summary, list_lay):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setLayout(list_lay)
        list_lay.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        return page

    def _check_for_db_update(self):
        def work():
            result = check_and_update(_data_dir())
            QTimer.singleShot(0, lambda: self._on_db_update(*result))

        threading.Thread(target=work, daemon=True).start()

    def _on_db_update(self, updated, message):
        if updated:
            self.classifier.reload_seed()
            self._render_all()
        self.status.setText(message)

    def refresh(self):
        if not REGISTRY_AVAILABLE:
            return
        self._scan_gen += 1
        gen = self._scan_gen
        self.status.setText("Scanning…")

        def work():
            err = None
            startup, services = [], []
            try:
                startup = list_startup_items()
                services = list_services()
            except Exception as exc:
                err = exc
            QTimer.singleShot(0, lambda: self._on_scan_done(gen, startup, services, err))

        threading.Thread(target=work, daemon=True).start()

    def _on_scan_done(self, gen, startup, services, err):
        if gen != self._scan_gen:
            return
        if err is not None:
            self.status.setObjectName("Danger")
            self.status.setText(f"Scan failed: {err}")
            return
        self._startup_items = startup
        self._service_items = services
        self._render_all()
        self.status.setText(
            f"Last scan: {len(self._startup_items)} startup item(s), "
            f"{len(self._service_items)} service(s)."
        )

    def _render_all(self):
        self._render_group(self.startup_list, self.startup_summary, self._startup_items, "startup_apps")
        self._render_group(self.services_list, self.services_summary, self._service_items, "services")

    def _classified(self, items, kind):
        query = self.search.text().strip().lower()
        out = []
        for item in items:
            name = item.name if kind == "startup_apps" else item.display_name
            if query and query not in name.lower() and query not in item.name.lower():
                continue
            info = self.classifier.classify(item.name, kind)
            out.append((item, info))
        return out

    def _is_enabled(self, item, kind):
        if kind == "startup_apps":
            return item.enabled
        return item.status == "Running" or item.start_type in ("Auto", "Boot", "System")

    def _render_group(self, layout, summary_label, items, kind):
        stretch = layout.takeAt(layout.count() - 1) if layout.count() else None
        _clear(layout)
        rows = self._classified(items, kind)
        buckets = {s: [] for s in STATUS_ORDER}
        for item, info in rows:
            buckets[info["status"]].append((item, info))
        ram = sum(
            IMPACT_RAM_MB.get(info.get("impact", "unknown"), 40)
            for item, info in rows if self._is_enabled(item, kind)
        )
        summary_label.setText(
            f"{len(rows)} shown · est. ~{ram} MB RAM in active startup load (rough estimate)"
        )
        for status in STATUS_ORDER:
            bucket = buckets[status]
            if not bucket:
                continue
            section_key = f"{kind}:{status}"
            header = QPushButton(f"{'▸' if self._collapsed.get(section_key) else '▾'}  {STATUS_LABEL[status]} ({len(bucket)})")
            if status == "red":
                header.setObjectName("Danger")
            elif status == "green":
                header.setObjectName("Success")
            header.clicked.connect(lambda _=False, k=section_key: self._toggle_section(k))
            layout.addWidget(header)
            if self._collapsed.get(section_key):
                continue
            for item, info in bucket:
                layout.addWidget(self._row(item, info, kind))
        layout.addStretch(1)
        if stretch is not None:
            del stretch

    def _toggle_section(self, key):
        self._collapsed[key] = not self._collapsed.get(key, False)
        self._render_all()

    def _row(self, item, info, kind):
        name = item.name if kind == "startup_apps" else item.display_name
        protected = bool(info.get("protected"))
        card = QFrame()
        card.setObjectName("Panel")
        lay = QHBoxLayout(card)
        enabled = QCheckBox()
        enabled.setChecked(self._is_enabled(item, kind))
        enabled.setEnabled(not protected)
        enabled.toggled.connect(lambda on, i=item, k=kind, inf=info, box=enabled: self._on_toggle(i, on, k, inf, box))
        lay.addWidget(enabled)
        col = QVBoxLayout()
        title = QLabel(name + ("  PROTECTED" if protected else "") + ("  (your override)" if info.get("user_override") else ""))
        title.setObjectName("CardTitle")
        detail = QLabel(f"{info.get('description', '')}  ·  impact: {info.get('impact', 'unknown')}")
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        col.addWidget(title)
        col.addWidget(detail)
        if kind == "services":
            extra = QLabel(f"{item.name} · {item.status} · {item.start_type}")
            extra.setObjectName("Muted")
            col.addWidget(extra)
        lay.addLayout(col, 1)
        if kind == "services" and not protected:
            start = QComboBox()
            start.addItems(START_TYPES)
            idx = start.findText(item.start_type if item.start_type in START_TYPES else "Manual")
            start.setCurrentIndex(max(0, idx))
            start.currentTextChanged.connect(lambda t, i=item: self._change_start_type(i, t))
            lay.addWidget(start)
        override = QComboBox()
        override.addItems(["green", "yellow", "red"])
        override.setCurrentText(info["status"])
        override.currentTextChanged.connect(lambda s, i=item, k=kind: self._set_override(i, k, s))
        lay.addWidget(override)
        return card

    def _on_toggle(self, item, enabled, kind, info, box):
        box.blockSignals(True)
        if not enabled and info["status"] == "green":
            if QMessageBox.question(
                self, "Flagged as required",
                f'"{item.name if kind == "startup_apps" else item.display_name}" is flagged 🟢. Disable it anyway?',
            ) != QMessageBox.StandardButton.Yes:
                box.setChecked(True)
                box.blockSignals(False)
                return
        try:
            if kind == "startup_apps":
                previous = item.enabled
                set_startup_enabled(item, enabled)
                log_change({"type": "startup_app", "name": item.name, "previous_state": previous, "new_state": enabled})
                self.status.setText(f"{'Enabled' if enabled else 'Disabled'} \"{item.name}\".")
            else:
                if not is_admin():
                    if QMessageBox.question(
                        self, "Administrator rights needed",
                        "Changing a service's start type needs admin rights. Restart as administrator now?",
                    ) == QMessageBox.StandardButton.Yes:
                        _relaunch_as_admin()
                    box.setChecked(not enabled)
                    box.blockSignals(False)
                    return
                previous = item.start_type
                new_type = "Auto" if enabled else "Disabled"
                set_service_start_type(item.name, new_type)
                item.start_type = new_type
                log_change({"type": "service", "name": item.name, "previous_state": previous, "new_state": new_type})
                self.status.setText(f"Set \"{item.display_name}\" start type to {new_type}.")
        except (OSError, NotImplementedError) as e:
            box.setChecked(not enabled)
            self.status.setObjectName("Danger")
            self.status.setText(f"Couldn't change \"{item.name}\": {e}")
        box.blockSignals(False)

    def _change_start_type(self, item, start_type):
        if start_type == item.start_type:
            return
        if not is_admin():
            QMessageBox.information(self, "Administrator rights needed", "Restart as administrator to change service start type.")
            self._render_all()
            return
        try:
            previous = item.start_type
            set_service_start_type(item.name, start_type)
            item.start_type = start_type
            log_change({"type": "service", "name": item.name, "previous_state": previous, "new_state": start_type})
            self.status.setText(f"Set \"{item.display_name}\" start type to {start_type}.")
        except OSError as e:
            QMessageBox.warning(self, "Startup Optimizer", str(e))
            self._render_all()

    def _set_override(self, item, kind, status):
        self.classifier.set_override(item.name, kind, status)
        self._render_all()

    def _undo_last(self):
        entries = load_change_log()
        if not entries:
            self.status.setText("Nothing to undo.")
            return
        last = entries[-1]
        try:
            if last["type"] == "startup_app":
                match = next((i for i in self._startup_items if i.name == last["name"]), None)
                if match:
                    set_startup_enabled(match, last["previous_state"])
            else:
                if not is_admin():
                    QMessageBox.information(self, "Administrator rights needed", "Restart as administrator to undo a service change.")
                    return
                set_service_start_type(last["name"], last["previous_state"])
            self.status.setText(f"Reverted last change to \"{last['name']}\".")
            self.refresh()
        except OSError as e:
            self.status.setText(f"Couldn't undo: {e}")

    def _apply_recommended_cleanup(self):
        red_startup = [
            i for i in self._startup_items
            if self._is_enabled(i, "startup_apps")
            and self.classifier.classify(i.name, "startup_apps")["status"] == "red"
        ]
        red_services = [
            i for i in self._service_items
            if self._is_enabled(i, "services")
            and self.classifier.classify(i.name, "services")["status"] == "red"
            and not self.classifier.classify(i.name, "services").get("protected")
        ]
        total = len(red_startup) + len(red_services)
        if total == 0:
            self.status.setText("Nothing flagged 🔴 to clean up.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Confirm")
        box.setText(f"Disable {total} item(s) flagged 🔴 as safe to turn off?")
        rp = QCheckBox("Create a System Restore point first")
        box.setCheckBox(rp)
        box.setStandardButtons(QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        if rp.isChecked():
            self.status.setText("Creating restore point…")

            def work():
                create_restore_point("Startup Optimizer — Apply Recommended Cleanup")
                QTimer.singleShot(0, lambda: self._finish_cleanup(red_startup, red_services))

            threading.Thread(target=work, daemon=True).start()
            return
        self._finish_cleanup(red_startup, red_services)

    def _finish_cleanup(self, red_startup, red_services):
        if red_services and not is_admin():
            QMessageBox.information(
                self, "Administrator rights needed",
                "Restart as administrator to disable flagged services too — startup apps will still be cleaned up now.",
            )
            red_services = []
        for item in red_startup:
            try:
                previous = item.enabled
                set_startup_enabled(item, False)
                log_change({"type": "startup_app", "name": item.name, "previous_state": previous, "new_state": False})
            except OSError:
                pass
        for item in red_services:
            try:
                previous = item.start_type
                set_service_start_type(item.name, "Disabled")
                log_change({"type": "service", "name": item.name, "previous_state": previous, "new_state": "Disabled"})
            except OSError:
                pass
        self.status.setText(f"Cleanup applied to {len(red_startup) + len(red_services)} item(s).")
        self.refresh()

    def _export_state(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export state", "startup_optimizer_export.json", "JSON (*.json)"
        )
        if not path:
            return
        data = {
            "startup_apps": [
                {"name": i.name, "source": i.source, "enabled": i.enabled, **self.classifier.classify(i.name, "startup_apps")}
                for i in self._startup_items
            ],
            "services": [
                {
                    "name": i.name, "display_name": i.display_name, "status": i.status,
                    "start_type": i.start_type, **self.classifier.classify(i.name, "services"),
                }
                for i in self._service_items
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.status.setText(f"Exported to {path}")
