"""Qt App Installer — winget search/install, apps.json catalog, custom commands."""

from __future__ import annotations

import json
import os
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pathlib import Path

from modules.app_installer.backend import (
    CommandWorker,
    CustomApp,
    InstallWorker,
    SearchWorker,
    load_custom_apps,
    save_custom_apps,
    winget_available,
)
import modules.app_installer as _app_installer_pkg

DB_PATH = str(Path(_app_installer_pkg.__file__).with_name("apps.json"))


def load_database():
    if not os.path.exists(DB_PATH):
        return {"categories": {}}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_database(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class AppInstallerModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.db = load_database()
        self.checked: set[str] = set()
        self._worker = None
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._drain_events)

        root = QVBoxLayout(self)
        title = QLabel("App Installer")
        title.setObjectName("AccentTitle")
        hint = QLabel("Search winget, install from the bundled catalog, or run custom install commands.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        tabs = QTabWidget()
        tabs.addTab(self._build_catalog(), "Catalog")
        tabs.addTab(self._build_search(), "Winget search")
        tabs.addTab(self._build_custom(), "Custom commands")
        root.addWidget(tabs, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        root.addWidget(QLabel("Output"))
        root.addWidget(self.log)
        if not winget_available():
            self._append("winget was not found on PATH. Installs will fail until it's available.\n")

    def _build_catalog(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.cat_search = QLineEdit()
        self.cat_search.setPlaceholderText("Filter catalog…")
        self.cat_search.textChanged.connect(self._populate_catalog)
        add = QPushButton("Add to catalog")
        add.clicked.connect(self._add_app_dialog)
        reload_btn = QPushButton("Reload DB")
        reload_btn.clicked.connect(self._reload_db)
        bar.addWidget(self.cat_search, 1)
        bar.addWidget(add)
        bar.addWidget(reload_btn)
        lay.addLayout(bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["✔", "App", "Winget ID", "Category", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self._toggle_cell)
        lay.addWidget(self.table, 1)
        actions = QHBoxLayout()
        install = QPushButton("Install checked")
        install.setObjectName("Primary")
        install.clicked.connect(self._install_checked)
        all_btn = QPushButton("Check visible")
        all_btn.clicked.connect(lambda: self._set_visible(True))
        none_btn = QPushButton("Uncheck all")
        none_btn.clicked.connect(lambda: self._set_visible(False))
        actions.addWidget(install)
        actions.addWidget(all_btn)
        actions.addWidget(none_btn)
        actions.addStretch(1)
        lay.addLayout(actions)
        self._populate_catalog()
        return page

    def _build_search(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search winget…")
        self.query.returnPressed.connect(self._search)
        go = QPushButton("Search")
        go.setObjectName("Primary")
        go.clicked.connect(self._search)
        bar.addWidget(self.query, 1)
        bar.addWidget(go)
        lay.addLayout(bar)
        self.results = QListWidget()
        lay.addWidget(self.results, 1)
        inst = QPushButton("Install selected")
        inst.setObjectName("Primary")
        inst.clicked.connect(self._install_selected_search)
        lay.addWidget(inst)
        return page

    def _build_custom(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.custom_list = QListWidget()
        self.custom_list.currentItemChanged.connect(self._load_custom)
        lay.addWidget(self.custom_list, 1)
        form = QFrame()
        form.setObjectName("Panel")
        fl = QVBoxLayout(form)
        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText("Name")
        self.custom_cmd = QLineEdit()
        self.custom_cmd.setPlaceholderText("Command (e.g. winget install --id Foo.Bar -e --silent)")
        self.custom_cat = QComboBox()
        self.custom_cat.setEditable(True)
        self.custom_cat.addItems(["Utilities", "Browsers", "Dev Tools", "Media", "Productivity", "Gaming"])
        fl.addWidget(self.custom_name)
        fl.addWidget(self.custom_cmd)
        fl.addWidget(self.custom_cat)
        row = QHBoxLayout()
        save = QPushButton("Save custom app")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_custom)
        run = QPushButton("Run command")
        run.clicked.connect(self._run_custom)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete_custom)
        row.addWidget(save)
        row.addWidget(run)
        row.addWidget(delete)
        row.addStretch(1)
        fl.addLayout(row)
        oneoff = QLineEdit()
        oneoff.setPlaceholderText("Or paste a one-off command here…")
        self.oneoff = oneoff
        run_one = QPushButton("Run one-off")
        run_one.clicked.connect(lambda: self._run_command(self.oneoff.text().strip()))
        fl.addWidget(oneoff)
        fl.addWidget(run_one)
        lay.addWidget(form)
        self._refresh_custom_list()
        return page

    def _append(self, msg: str):
        self.log.appendPlainText(msg.rstrip("\n"))

    def _iter_apps(self):
        for category, apps in self.db.get("categories", {}).items():
            for app in apps:
                yield category, app

    def _populate_catalog(self):
        query = self.cat_search.text().strip().lower()
        rows = []
        for category, app in self._iter_apps():
            haystack = f"{app.get('name','')} {app.get('id','')} {category} {app.get('desc','')}".lower()
            if query and query not in haystack:
                continue
            rows.append((category, app))
        self.table.setRowCount(len(rows))
        for i, (category, app) in enumerate(rows):
            wid = app["id"]
            mark = QTableWidgetItem("☑" if wid in self.checked else "☐")
            mark.setData(Qt.ItemDataRole.UserRole, wid)
            self.table.setItem(i, 0, mark)
            self.table.setItem(i, 1, QTableWidgetItem(app.get("name", "")))
            self.table.setItem(i, 2, QTableWidgetItem(wid))
            self.table.setItem(i, 3, QTableWidgetItem(category))
            self.table.setItem(i, 4, QTableWidgetItem(app.get("desc", "")))

    def _toggle_cell(self, row, col):
        if col != 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        wid = item.data(Qt.ItemDataRole.UserRole)
        if wid in self.checked:
            self.checked.remove(wid)
        else:
            self.checked.add(wid)
        item.setText("☑" if wid in self.checked else "☐")

    def _set_visible(self, state: bool):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            wid = item.data(Qt.ItemDataRole.UserRole)
            if state:
                self.checked.add(wid)
            else:
                self.checked.discard(wid)
            item.setText("☑" if state else "☐")

    def _add_app_dialog(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "App name", "Display name:")
        if not ok or not name.strip():
            return
        wid, ok = QInputDialog.getText(self, "Winget ID", "Exact winget package ID (e.g. Google.Chrome):")
        if not ok or not wid.strip():
            return
        category, ok = QInputDialog.getText(self, "Category", "Category (e.g. Browsers):")
        category = category.strip() if ok and category else "Uncategorized"
        desc, ok = QInputDialog.getText(self, "Description", "Short description:")
        desc = desc.strip() if ok else ""
        self.db.setdefault("categories", {}).setdefault(category, [])
        for existing in self.db["categories"][category]:
            if existing["id"] == wid.strip():
                QMessageBox.information(self, "Already exists", f"{wid} is already in {category}.")
                return
        self.db["categories"][category].append({"name": name.strip(), "id": wid.strip(), "desc": desc})
        save_database(self.db)
        self._populate_catalog()
        self._append(f"Added {name} ({wid}) to {category}.")

    def _reload_db(self):
        self.db = load_database()
        self._populate_catalog()
        self._append("Database reloaded from apps.json.")

    def _install_checked(self):
        ids = [wid for wid in self.checked]
        if not ids:
            QMessageBox.information(self, "Nothing selected", "Check at least one app first.")
            return
        self._install_ids(ids)

    def _install_ids(self, ids: list[str]):
        if not winget_available():
            QMessageBox.warning(self, "winget not found", "winget isn't available on this machine's PATH.")
            return
        if self._worker:
            QMessageBox.information(self, "Busy", "An install is already running.")
            return

        def work():
            for wid in ids:
                worker = InstallWorker(wid)
                worker.start()
                worker.join()
                while True:
                    try:
                        ev = worker.events.get_nowait()
                    except Exception:
                        break
                    QTimer.singleShot(0, lambda e=ev: self._handle_event(e))
            QTimer.singleShot(0, self._idle)

        self._worker = True
        threading.Thread(target=work, daemon=True).start()

    def _idle(self):
        self._worker = None

    def _search(self):
        q = self.query.text().strip()
        self.results.clear()
        self._append(f"Searching for {q!r}…")
        worker = SearchWorker(q)
        self._attach(worker)
        worker.start()

    def _install_selected_search(self):
        item = self.results.currentItem()
        if item is None:
            return
        pkg_id = item.data(Qt.ItemDataRole.UserRole)
        if pkg_id:
            self._install_ids([pkg_id])

    def _refresh_custom_list(self):
        self.custom_list.clear()
        for app in load_custom_apps():
            item = QListWidgetItem(f"{app.name}  —  {app.category}")
            item.setData(Qt.ItemDataRole.UserRole, app)
            self.custom_list.addItem(item)

    def _load_custom(self, item):
        if item is None:
            return
        app = item.data(Qt.ItemDataRole.UserRole)
        self.custom_name.setText(app.name)
        self.custom_cmd.setText(app.command)
        self.custom_cat.setCurrentText(app.category)

    def _save_custom(self):
        name = self.custom_name.text().strip()
        command = self.custom_cmd.text().strip()
        category = self.custom_cat.currentText().strip() or "Utilities"
        if not name or not command:
            QMessageBox.information(self, "Custom app", "Name and command are required.")
            return
        apps = load_custom_apps()
        current = self.custom_list.currentItem()
        if current is not None:
            existing = current.data(Qt.ItemDataRole.UserRole)
            for i, app in enumerate(apps):
                if app.id == existing.id:
                    apps[i] = CustomApp(name=name, command=command, category=category, id=existing.id)
                    break
            else:
                apps.append(CustomApp(name=name, command=command, category=category))
        else:
            apps.append(CustomApp(name=name, command=command, category=category))
        save_custom_apps(apps)
        self._refresh_custom_list()
        self._append(f"Saved custom app {name}.")

    def _delete_custom(self):
        current = self.custom_list.currentItem()
        if current is None:
            return
        existing = current.data(Qt.ItemDataRole.UserRole)
        apps = [a for a in load_custom_apps() if a.id != existing.id]
        save_custom_apps(apps)
        self._refresh_custom_list()
        self.custom_name.clear()
        self.custom_cmd.clear()

    def _run_custom(self):
        current = self.custom_list.currentItem()
        cmd = self.custom_cmd.text().strip()
        if current is not None:
            cmd = current.data(Qt.ItemDataRole.UserRole).command
        self._run_command(cmd)

    def _run_command(self, cmd: str):
        if not cmd:
            return
        if self._worker:
            QMessageBox.information(self, "Busy", "A command is already running.")
            return
        worker = CommandWorker(cmd)
        self._attach(worker)
        worker.start()

    def _attach(self, worker):
        self._worker = worker
        self._poll.start()

    def _drain_events(self):
        worker = self._worker
        if worker is None or worker is True:
            return
        from queue import Empty
        while True:
            try:
                ev = worker.events.get_nowait()
            except Empty:
                break
            self._handle_event(ev)
        if not worker.is_alive() and worker.events.empty():
            self._poll.stop()
            self._worker = None

    def _handle_event(self, ev):
        if ev.kind == "log":
            self._append(ev.message)
        elif ev.kind == "fatal_error":
            self._append(ev.message)
            QMessageBox.warning(self, "App Installer", ev.message)
        elif ev.kind == "overall_done":
            self._append(ev.message)
        elif ev.kind == "search_done":
            self.results.clear()
            for app in ev.results:
                item = QListWidgetItem(f"{app.name}  ({app.id})  {app.version}  {app.source}")
                item.setData(Qt.ItemDataRole.UserRole, app.id)
                self.results.addItem(item)
            self._append(f"{len(ev.results)} result(s).")
