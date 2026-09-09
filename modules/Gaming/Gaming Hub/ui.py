"""Qt Gaming Hub — library scan/launch plus save backup / deny-write."""

from __future__ import annotations

import json
import os
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

import importlib

from core import paths
from core.qt.remote_common import AppServePanel, TailscalePanel
from core.services.tailscale_service import APP_HTTPS_PORTS

_scanner = importlib.import_module("modules.Gaming.Gaming Hub.game_scanner")
_launcher = importlib.import_module("modules.Gaming.Gaming Hub.launcher")
_saves = importlib.import_module("modules.Gaming.Gaming Hub.save_manager")
_web = importlib.import_module("modules.Gaming.Gaming Hub.web_server")
GameScanner = _scanner.GameScanner
GameLauncher = _launcher.GameLauncher
SaveManager = _saves.SaveManager
GamingHubWebServer = _web.GamingHubWebServer

HUB_SETTINGS_FILE = paths.data_path("gaming_hub", "hub_settings.json")


def load_hub_settings():
    detected = GameScanner.detect_drives()
    defaults = {"auto_scan": False, "auto_backup": False, "scan_drives": detected}
    try:
        with open(HUB_SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        saved = {}
    merged = {**defaults, **saved}
    known = set(merged.get("scan_drives") or [])
    for drive in detected:
        if drive not in known and drive not in (saved.get("_seen_drives") or []):
            merged["scan_drives"].append(drive)
    merged["_seen_drives"] = detected
    return merged


def save_hub_settings(hub_settings):
    try:
        os.makedirs(os.path.dirname(HUB_SETTINGS_FILE), exist_ok=True)
        with open(HUB_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(hub_settings, f, indent=4)
    except Exception as e:
        print(f"[GamingHub] Failed saving settings: {e}")


class GamingHubUI(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.scanner = GameScanner()
        self.launcher = GameLauncher()
        self.save_manager = SaveManager()
        self.games = []
        self.hub_settings = load_hub_settings()
        self.web_server = getattr(manager, "gaming_hub_web_server", None) or GamingHubWebServer()
        manager.gaming_hub_web_server = self.web_server

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Gaming Hub")
        title.setObjectName("AccentTitle")
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games…")
        self.search.textChanged.connect(self._filter)
        scan = QPushButton("Scan")
        scan.setObjectName("Primary")
        scan.clicked.connect(self.scan_games)
        header.addWidget(title)
        header.addWidget(self.count)
        header.addWidget(self.search, 1)
        header.addWidget(scan)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_library(), "Library")
        self.tabs.addTab(self._build_saves(), "Saves")
        root.addWidget(self.tabs, 1)

        cached = self.scanner.load_cache()
        if cached:
            self.display_games(cached)
        if self.hub_settings.get("auto_scan"):
            QTimer.singleShot(200, self.scan_games)

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _HubSettings(parent, manager)

    def _build_library(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        scroll.setWidget(self.list_host)
        lay.addWidget(scroll, 1)
        return page

    def _build_saves(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.game_pick = QComboBox()
        self.game_pick.currentTextChanged.connect(self._load_save_path)
        lay.addWidget(QLabel("Game"))
        lay.addWidget(self.game_pick)
        path_row = QHBoxLayout()
        self.save_path = QLineEdit()
        self.save_path.setPlaceholderText("Path to save folder…")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_save)
        save = QPushButton("Save path")
        save.clicked.connect(self._save_path)
        path_row.addWidget(self.save_path, 1)
        path_row.addWidget(browse)
        path_row.addWidget(save)
        lay.addLayout(path_row)
        btns = QHBoxLayout()
        backup = QPushButton("Backup")
        backup.setObjectName("Primary")
        backup.clicked.connect(self._backup)
        self.lock_btn = QPushButton("Deny write")
        self.lock_btn.clicked.connect(self._toggle_lock)
        hide = QPushButton("Hide from save list")
        hide.clicked.connect(self._hide_save)
        btns.addWidget(backup)
        btns.addWidget(self.lock_btn)
        btns.addWidget(hide)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.save_info = QLabel("")
        self.save_info.setObjectName("Muted")
        self.save_info.setWordWrap(True)
        lay.addWidget(self.save_info)
        lay.addStretch(1)
        return page

    def on_show(self):
        self.hub_settings = load_hub_settings()

    def scan_games(self):
        self.count.setText("Scanning…")

        def work():
            self.hub_settings = load_hub_settings()
            drives = self.hub_settings.get("scan_drives") or GameScanner.detect_drives()
            try:
                games = self.scanner.scan(drives=drives)
            except Exception as e:
                QTimer.singleShot(0, lambda: self.count.setText(str(e)))
                return
            QTimer.singleShot(0, lambda: self.display_games(games))

        threading.Thread(target=work, daemon=True).start()

    def display_games(self, games):
        self.games = games
        self.web_server.refresh_from_cache()
        n = len(games)
        self.count.setText(f"{n} {'game' if n == 1 else 'games'} found")
        names = sorted(
            (g.name for g in games if not self.save_manager.is_blocked(g.name)),
            key=str.lower,
        )
        current = self.game_pick.currentText()
        self.game_pick.blockSignals(True)
        self.game_pick.clear()
        if names:
            self.game_pick.addItems(names)
            idx = self.game_pick.findText(current)
            self.game_pick.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.game_pick.addItem("No Games Found")
        self.game_pick.blockSignals(False)
        self._load_save_path()
        self._filter()

    def _filter(self):
        q = (self.search.text() or "").lower()
        shown = [g for g in self.games if not q or q in g.name.lower()]
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not shown:
            empty = QLabel("No games found. Scan or check the drives in ⚙ settings.")
            empty.setObjectName("Muted")
            self.list_lay.addWidget(empty)
            self.list_lay.addStretch(1)
            return
        for game in shown:
            card = QFrame()
            card.setObjectName("Card")
            cl = QVBoxLayout(card)
            top = QHBoxLayout()
            name = QLabel(game.name)
            name.setObjectName("CardTitle")
            launcher = QLabel((game.launcher or "Unknown").upper())
            launcher.setObjectName("CardCat")
            top.addWidget(name, 1)
            top.addWidget(launcher)
            path = QLabel(game.path or "")
            path.setObjectName("Muted")
            path.setWordWrap(True)
            row = QHBoxLayout()
            folder = QPushButton("Folder")
            folder.clicked.connect(lambda _=False, g=game: self._open_folder(g))
            hide = QPushButton("Hide")
            hide.clicked.connect(lambda _=False, g=game: self._hide_game(g))
            launch = QPushButton("Launch")
            launch.setObjectName("Primary")
            launch.clicked.connect(lambda _=False, g=game: self._launch(g))
            row.addWidget(folder)
            row.addWidget(hide)
            row.addStretch(1)
            row.addWidget(launch)
            cl.addLayout(top)
            cl.addWidget(path)
            cl.addLayout(row)
            self.list_lay.addWidget(card)
        self.list_lay.addStretch(1)

    def _launch(self, game):
        try:
            self.launcher.launch(game)
        except Exception as exc:
            QMessageBox.warning(self, "Launch failed", str(exc))

    def _open_folder(self, game):
        if game.path and os.path.exists(game.path):
            try:
                os.startfile(game.path)
            except Exception as exc:
                QMessageBox.warning(self, "Folder", str(exc))
        else:
            QMessageBox.information(self, "Folder", "Game path not found.")

    def _hide_game(self, game):
        self.scanner.block_game(game.name)
        self.games = [g for g in self.games if g.name.lower() != game.name.lower()]
        self.scanner.save_cache(self.games)
        self.display_games(self.games)

    def _selected_save_game(self):
        name = self.game_pick.currentText()
        if not name or name == "No Games Found":
            return ""
        return name

    def _load_save_path(self):
        name = self._selected_save_game()
        self.save_path.setText(self.save_manager.get_path(name) if name else "")
        self._refresh_lock_label()

    def _browse_save(self):
        chosen = QFileDialog.getExistingDirectory(self, "Save folder", self.save_path.text())
        if chosen:
            self.save_path.setText(chosen)

    def _save_path(self):
        name = self._selected_save_game()
        path = self.save_path.text().strip().strip('"').strip("'")
        if not name or not path:
            return
        self.save_manager.set_path(name, path)
        self.save_path.setText(self.save_manager.get_path(name))
        self.save_info.setText("Save path stored.")

    def _hide_save(self):
        name = self._selected_save_game()
        if not name:
            return
        self.save_manager.block_game(name)
        self.display_games(self.games)

    def _backup(self):
        name = self._selected_save_game()
        if not name:
            return
        try:
            backup = self.save_manager.backup_game(name)
            self.save_info.setText(f"Backed up to:\n{backup}")
        except Exception as exc:
            self.save_info.setText(f"Backup failed: {exc}")

    def _toggle_lock(self):
        name = self._selected_save_game()
        path = self.save_manager.get_path(name) if name else ""
        if not path:
            self.save_info.setText("No save folder set for this game.")
            return
        self.lock_btn.setEnabled(False)
        self.save_info.setText("Working…")

        def work():
            try:
                if self.save_manager.is_locked(path):
                    self.save_manager.unlock_path(path)
                    msg = "Write access restored."
                else:
                    self.save_manager.lock_path(path)
                    msg = "Write denied on save folder."
            except Exception as exc:
                msg = str(exc)
            QTimer.singleShot(0, lambda: self._lock_done(msg))

        threading.Thread(target=work, daemon=True).start()

    def _lock_done(self, msg):
        self.lock_btn.setEnabled(True)
        self.save_info.setText(msg)
        self._refresh_lock_label()

    def _refresh_lock_label(self):
        name = self._selected_save_game()
        path = self.save_manager.get_path(name) if name else ""
        if path and self.save_manager.is_locked(path):
            self.lock_btn.setText("Allow write")
        else:
            self.lock_btn.setText("Deny write")


class _HubSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.save_manager = SaveManager()
        self.hub_settings = load_hub_settings()
        lay = QVBoxLayout(self)
        title = QLabel("Preferences")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        self.auto_scan = QCheckBox("Scan on startup")
        self.auto_scan.setChecked(bool(self.hub_settings.get("auto_scan")))
        self.auto_scan.toggled.connect(lambda on: self._toggle("auto_scan", on))
        self.auto_backup = QCheckBox("Auto-backup saves")
        self.auto_backup.setChecked(bool(self.hub_settings.get("auto_backup")))
        self.auto_backup.toggled.connect(lambda on: self._toggle("auto_backup", on))
        lay.addWidget(self.auto_scan)
        lay.addWidget(self.auto_backup)
        lay.addWidget(QLabel("Drives to scan"))
        selected = set(self.hub_settings.get("scan_drives") or GameScanner.detect_drives())
        self.drive_boxes = {}
        drive_row = QHBoxLayout()
        for drive in GameScanner.detect_drives():
            cb = QCheckBox(drive)
            cb.setChecked(drive in selected)
            cb.toggled.connect(lambda on, d=drive: self._toggle_drive(d, on))
            self.drive_boxes[drive] = cb
            drive_row.addWidget(cb)
        drive_row.addStretch(1)
        lay.addLayout(drive_row)
        backup_row = QHBoxLayout()
        self.backup_folder = QLineEdit(self.save_manager.settings.get("backup_folder") or "")
        self.backup_folder.setPlaceholderText("Default app data folder")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_backup)
        save = QPushButton("Save backup folder")
        save.clicked.connect(self._save_backup)
        backup_row.addWidget(self.backup_folder, 1)
        backup_row.addWidget(browse)
        backup_row.addWidget(save)
        lay.addLayout(backup_row)

        web = getattr(manager, "gaming_hub_web_server", None)
        if web is None:
            web = GamingHubWebServer()
            manager.gaming_hub_web_server = web
        self.web = web
        tailscale = manager.container.tailscale_service
        self.ts = TailscalePanel(self, tailscale)
        self.serve = AppServePanel(
            self,
            tailscale=tailscale,
            get_server=lambda: self.web,
            app_key="games",
            default_port=APP_HTTPS_PORTS["games"],
            title="Remote access (launch from phone)",
            hint="Exposes the cached library and launch trigger on the tailnet.",
        )
        lay.addWidget(self.ts)
        lay.addWidget(self.serve)
        self._poll = QTimer(self)
        self._poll.setInterval(4000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    def _toggle(self, key, on):
        self.hub_settings[key] = bool(on)
        save_hub_settings(self.hub_settings)

    def _toggle_drive(self, drive, on):
        drives = set(self.hub_settings.get("scan_drives") or [])
        if on:
            drives.add(drive)
        else:
            drives.discard(drive)
        self.hub_settings["scan_drives"] = sorted(drives)
        save_hub_settings(self.hub_settings)

    def _browse_backup(self):
        chosen = QFileDialog.getExistingDirectory(self, "Backup folder", self.backup_folder.text())
        if chosen:
            self.backup_folder.setText(chosen)

    def _save_backup(self):
        self.save_manager.set_backup_folder(self.backup_folder.text().strip())

    def _refresh(self):
        def work():
            status = self.manager.container.tailscale_service.get_status()
            running = self.web.is_running()
            QTimer.singleShot(0, lambda: self._apply(status, running))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status, running):
        self.ts.apply_status(status)
        self.serve.apply_status(status, running)
