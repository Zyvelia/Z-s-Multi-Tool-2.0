"""Qt Game Server Manager — list, start/stop, console, files, backups, config."""

from __future__ import annotations

import os
import threading
import uuid
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import importlib

_runtime = importlib.import_module("modules.Gaming.Game Server Manager.runtime")
_adapters = importlib.import_module("modules.Gaming.Game Server Manager.adapters")
_api = importlib.import_module("modules.Gaming.Game Server Manager.agent_api")
_settings = importlib.import_module("modules.Gaming.Game Server Manager.core.settings")
_files = importlib.import_module("modules.Gaming.Game Server Manager.server_files")
_mc_backend = importlib.import_module("modules.Gaming.Game Server Manager.backend")
_mc_loaders = importlib.import_module("modules.Gaming.Game Server Manager.adapters.minecraft_loaders")
runtime = _runtime
game_choices = _adapters.game_choices
get_adapter = _adapters.get_adapter
send_console = _api.send_console
start_server = _api.start_server
stop_server = _api.stop_server
default_server_folder_for = _settings.default_server_folder_for
load_servers = _settings.load_servers
save_servers = _settings.save_servers
create_backup_zip = _files.create_backup_zip
restore_backup_zip = _files.restore_backup_zip
read_player_list = _files.read_player_list
add_player_list_name = _files.add_player_list_name
remove_player_list_name = _files.remove_player_list_name
is_editable_file = _files.is_editable_file
read_text_file = _files.read_text_file
write_text_file = _files.write_text_file
list_mc_versions = _mc_backend.list_versions
write_mc_eula = _mc_backend.write_eula
mc_eula_accepted = _mc_backend.eula_accepted
create_mc_install_worker = _mc_loaders.create_install_worker
mc_loader_choices = _mc_loaders.loader_choices
mc_loader_name = _mc_loaders.loader_name
get_mc_loader_versions = _mc_loaders.get_loader_versions


class GameServerManagerModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.servers = load_servers()
        self._selected_id = self.servers[0]["id"] if self.servers else None
        self._seen_events = 0
        self._files_rel = Path(".")
        self._config_fields = {}

        split = QSplitter(Qt.Orientation.Horizontal)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(split, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Servers"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        remove = QPushButton("Remove")
        remove.setObjectName("Danger")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(remove)
        ll.addLayout(row)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.title = QLabel("No server selected")
        self.title.setObjectName("AccentTitle")
        self.state = QLabel("")
        self.state.setObjectName("Muted")
        rl.addWidget(self.title)
        rl.addWidget(self.state)
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("Primary")
        self.stop_btn = QPushButton("Stop")
        self.restart_btn = QPushButton("Restart")
        self.kill_btn = QPushButton("Kill")
        self.kill_btn.setObjectName("Danger")
        self.backup_btn = QPushButton("Backup")
        self.start_btn.clicked.connect(lambda: self._act("start"))
        self.stop_btn.clicked.connect(lambda: self._act("stop"))
        self.restart_btn.clicked.connect(lambda: self._act("restart"))
        self.kill_btn.clicked.connect(lambda: self._act("kill"))
        self.backup_btn.clicked.connect(lambda: self._act("backup"))
        for b in (self.start_btn, self.stop_btn, self.restart_btn, self.kill_btn, self.backup_btn):
            controls.addWidget(b)
        controls.addStretch(1)
        rl.addLayout(controls)

        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        rl.addWidget(self.meta)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_console(), "Console")
        self.tabs.addTab(self._build_players(), "Players")
        self.tabs.addTab(self._build_files(), "Files")
        self.tabs.addTab(self._build_backups(), "Backups")
        self.tabs.addTab(self._build_config(), "Config")
        self.tabs.addTab(self._build_mods(), "Mods")
        rl.addWidget(self.tabs, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._render_list()
        self._refresh_detail()
        self._refresh_side_tabs()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        from core.qt.remote_common import SimpleRemoteSettings, ensure_manager_server

        web_mod = importlib.import_module("modules.Gaming.Game Server Manager.web_server")
        return SimpleRemoteSettings(
            parent,
            manager,
            get_server=lambda: ensure_manager_server(
                manager, "gsm_web_server", web_mod.GsmWebServer
            ),
            app_key="gsm",
            default_port=8771,
            title="Remote access (server console on phone)",
            hint="Limited console for invite keys that allow it. Hub Go Live maps this too.",
        )

    def _build_console(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        lay.addWidget(self.console, 1)
        cmd_row = QHBoxLayout()
        self.cmd = QLineEdit()
        self.cmd.setPlaceholderText("Console command")
        self.cmd.returnPressed.connect(self._send)
        send = QPushButton("Send")
        send.clicked.connect(self._send)
        cmd_row.addWidget(self.cmd, 1)
        cmd_row.addWidget(send)
        lay.addLayout(cmd_row)
        return page

    def _build_players(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.players_lab = QLabel("Nobody on")
        self.players_lab.setObjectName("Muted")
        lay.addWidget(self.players_lab)
        self.players_list = QListWidget()
        lay.addWidget(self.players_list, 1)
        kick = QPushButton("Kick selected")
        kick.clicked.connect(self._kick)
        lay.addWidget(kick, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(QLabel("Whitelist / allowlist"))
        self.whitelist = QListWidget()
        lay.addWidget(self.whitelist, 1)
        wl_row = QHBoxLayout()
        self.wl_name = QLineEdit()
        self.wl_name.setPlaceholderText("Player name")
        add_wl = QPushButton("Add")
        add_wl.clicked.connect(self._add_whitelist)
        rm_wl = QPushButton("Remove")
        rm_wl.clicked.connect(self._remove_whitelist)
        wl_row.addWidget(self.wl_name, 1)
        wl_row.addWidget(add_wl)
        wl_row.addWidget(rm_wl)
        lay.addLayout(wl_row)
        return page

    def _build_files(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        nav = QHBoxLayout()
        self.files_path = QLabel("")
        self.files_path.setObjectName("Muted")
        up = QPushButton("Up")
        up.clicked.connect(self._files_up)
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(self._open_server_dir)
        nav.addWidget(self.files_path, 1)
        nav.addWidget(up)
        nav.addWidget(open_btn)
        lay.addLayout(nav)
        self.files_list = QListWidget()
        self.files_list.itemDoubleClicked.connect(self._open_file)
        lay.addWidget(self.files_list, 1)
        return page

    def _build_backups(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        row = QHBoxLayout()
        create = QPushButton("Create backup")
        create.setObjectName("Primary")
        create.clicked.connect(lambda: self._act("backup"))
        restore = QPushButton("Restore selected")
        restore.clicked.connect(self._restore_backup)
        row.addWidget(create)
        row.addWidget(restore)
        row.addStretch(1)
        lay.addLayout(row)
        self.backups_list = QListWidget()
        lay.addWidget(self.backups_list, 1)
        return page

    def _build_config(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        install_row = QHBoxLayout()
        self.install_btn = QPushButton("Install / change version…")
        self.install_btn.clicked.connect(self._open_install_dialog)
        self.install_btn.setVisible(False)
        install_row.addWidget(self.install_btn)
        install_row.addStretch(1)
        lay.addLayout(install_row)
        self.config_form = QFormLayout()
        lay.addLayout(self.config_form)
        save = QPushButton("Save config")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_config)
        lay.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        return page

    def _build_mods(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.mods_hint = QLabel("")
        self.mods_hint.setObjectName("Muted")
        self.mods_hint.setWordWrap(True)
        lay.addWidget(self.mods_hint)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_mods)
        open_mods = QPushButton("Open mods folder")
        open_mods.clicked.connect(self._open_mods)
        self.modrinth_btn = QPushButton("Modrinth")
        self.curse_btn = QPushButton("CurseForge")
        self.modrinth_btn.clicked.connect(lambda: self._open_mod_url("modrinth"))
        self.curse_btn.clicked.connect(lambda: self._open_mod_url("curseforge"))
        row.addWidget(refresh)
        row.addWidget(open_mods)
        row.addWidget(self.modrinth_btn)
        row.addWidget(self.curse_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.mods_list = QListWidget()
        lay.addWidget(self.mods_list, 1)
        return page

    def on_hide(self):
        self._timer.stop()

    def on_show(self):
        if not self._timer.isActive():
            self._timer.start()
        self.servers = load_servers()
        self._render_list()
        self._refresh_detail()
        self._refresh_side_tabs()

    def _selected(self):
        for srv in self.servers:
            if srv.get("id") == self._selected_id:
                return srv
        return None

    def _adapter(self):
        srv = self._selected()
        if srv is None:
            return None
        return get_adapter(srv.get("game_type"))

    def _render_list(self):
        current = self._selected_id
        self.list.blockSignals(True)
        self.list.clear()
        for srv in self.servers:
            snap = runtime.snapshot(srv.get("id", ""))
            mark = "● " if snap.get("running") else "○ "
            item = QListWidgetItem(f"{mark}{srv.get('name') or 'Server'}")
            item.setData(Qt.ItemDataRole.UserRole, srv.get("id"))
            self.list.addItem(item)
            if srv.get("id") == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def _on_select(self, item):
        if item is None:
            return
        self._selected_id = item.data(Qt.ItemDataRole.UserRole)
        self._seen_events = 0
        self._files_rel = Path(".")
        self.console.clear()
        self._refresh_detail()
        self._refresh_side_tabs()

    def _refresh_detail(self):
        srv = self._selected()
        if srv is None:
            self.title.setText("No server selected")
            self.state.setText("")
            self.meta.setText("")
            return
        snap = runtime.snapshot(srv.get("id", ""))
        running = bool(snap.get("running"))
        ready = bool(snap.get("ready"))
        players = snap.get("players") or []
        self.title.setText(srv.get("name") or "Server")
        self.state.setText("ready" if ready else ("running" if running else "stopped"))
        self.state.setObjectName("Success" if running else "Muted")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.meta.setText(
            f"{srv.get('game_type') or ''}  ·  {srv.get('server_dir') or ''}\n"
            f"Players: {', '.join(players) if players else 'nobody on'}"
        )
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.restart_btn.setEnabled(running)
        self.kill_btn.setEnabled(running)
        self._refresh_live_players(players)

    def _refresh_live_players(self, players):
        self.players_lab.setText(
            f"{len(players)} online" if players else "Nobody on"
        )
        current = [self.players_list.item(i).text() for i in range(self.players_list.count())]
        if current == list(players):
            return
        self.players_list.clear()
        for name in players:
            self.players_list.addItem(name)

    def _refresh_side_tabs(self):
        self._refresh_whitelist()
        self._refresh_files()
        self._refresh_backups()
        self._refresh_config()
        self._refresh_mods()

    def _refresh_whitelist(self):
        self.whitelist.clear()
        srv = self._selected()
        if srv is None:
            return
        folder = Path(srv.get("server_dir") or "")
        if not folder.is_dir():
            return
        try:
            for name in read_player_list(folder, srv.get("game_type") or ""):
                self.whitelist.addItem(name)
        except Exception:
            pass

    def _add_whitelist(self):
        srv = self._selected()
        name = self.wl_name.text().strip()
        if srv is None or not name:
            return
        add_player_list_name(Path(srv["server_dir"]), srv.get("game_type") or "", name)
        self.wl_name.clear()
        self._refresh_whitelist()

    def _remove_whitelist(self):
        srv = self._selected()
        item = self.whitelist.currentItem()
        if srv is None or item is None:
            return
        remove_player_list_name(Path(srv["server_dir"]), srv.get("game_type") or "", item.text())
        self._refresh_whitelist()

    def _kick(self):
        srv = self._selected()
        item = self.players_list.currentItem()
        adapter = self._adapter()
        if srv is None or item is None or adapter is None:
            return
        cmd = adapter.player_command("kick", item.text())
        if not cmd:
            QMessageBox.information(self, "Kick", "This game has no kick command.")
            return
        result = send_console(srv, cmd)
        if not result.get("ok"):
            QMessageBox.warning(self, "Kick", str(result.get("error") or "Failed"))

    def _server_root(self):
        srv = self._selected()
        if srv is None:
            return None
        root = Path(srv.get("server_dir") or "")
        return root if root.is_dir() else None

    def _refresh_files(self):
        self.files_list.clear()
        root = self._server_root()
        if root is None:
            self.files_path.setText("")
            return
        current = (root / self._files_rel).resolve()
        if root not in current.parents and current != root.resolve():
            self._files_rel = Path(".")
            current = root
        self.files_path.setText(str(current))
        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for path in entries:
            if path.name == "_backups":
                continue
            prefix = "[dir] " if path.is_dir() else ""
            item = QListWidgetItem(f"{prefix}{path.name}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.files_list.addItem(item)

    def _files_up(self):
        if self._files_rel == Path("."):
            return
        self._files_rel = self._files_rel.parent
        self._refresh_files()

    def _open_file(self, item):
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if path.is_dir():
            root = self._server_root()
            if root is None:
                return
            self._files_rel = path.relative_to(root)
            self._refresh_files()
            return
        if not is_editable_file(path):
            try:
                os.startfile(path)
            except Exception as exc:
                QMessageBox.warning(self, "Open", str(exc))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(path.name)
        lay = QVBoxLayout(dlg)
        editor = QPlainTextEdit()
        editor.setPlainText(read_text_file(path))
        lay.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        dlg.resize(720, 480)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        write_text_file(path, editor.toPlainText())

    def _open_server_dir(self):
        root = self._server_root()
        if root is None:
            return
        try:
            os.startfile(root)
        except Exception as exc:
            QMessageBox.warning(self, "Open folder", str(exc))

    def _refresh_backups(self):
        self.backups_list.clear()
        root = self._server_root()
        if root is None:
            return
        dest = root / "_backups"
        if not dest.is_dir():
            return
        zips = sorted(dest.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for zip_path in zips:
            item = QListWidgetItem(zip_path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(zip_path))
            self.backups_list.addItem(item)

    def _restore_backup(self):
        srv = self._selected()
        item = self.backups_list.currentItem()
        if srv is None or item is None:
            return
        if runtime.snapshot(srv["id"]).get("running"):
            QMessageBox.warning(self, "Restore", "Stop the server first.")
            return
        if QMessageBox.question(
            self, "Restore backup",
            f"Extract {item.text()} into the server folder? Matching files will be overwritten.",
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            restore_backup_zip(Path(srv["server_dir"]), Path(item.data(Qt.ItemDataRole.UserRole)))
            QMessageBox.information(self, "Restore", "Backup restored.")
        except Exception as exc:
            QMessageBox.warning(self, "Restore failed", str(exc))

    def _clear_form(self, form):
        while form.rowCount():
            form.removeRow(0)

    def _refresh_config(self):
        self._clear_form(self.config_form)
        self._config_fields = {}
        srv = self._selected()
        adapter = self._adapter()
        self.install_btn.setVisible(bool(srv) and srv.get("game_type") == "minecraft_java")
        if srv is None or adapter is None:
            return
        folder = Path(srv.get("server_dir") or "")
        stored = dict(srv.get("config") or {})
        try:
            stored.update(adapter.read_config(folder) or {})
        except Exception:
            pass
        for field in adapter.config_fields(folder):
            value = stored.get(field.key, field.default)
            if field.kind == "checkbox":
                widget = QCheckBox(field.label)
                widget.setChecked(str(value).lower() in ("1", "true", "yes", "on"))
                self.config_form.addRow(widget)
            elif field.kind == "menu":
                widget = QComboBox()
                widget.addItems(field.choices or [])
                idx = widget.findText(str(value))
                widget.setCurrentIndex(idx if idx >= 0 else 0)
                self.config_form.addRow(field.label, widget)
            else:
                widget = QLineEdit(str(value if value is not None else ""))
                self.config_form.addRow(field.label, widget)
            self._config_fields[field.key] = (field, widget)

    def _save_config(self):
        srv = self._selected()
        adapter = self._adapter()
        if srv is None or adapter is None:
            return
        updates = {}
        for key, (field, widget) in self._config_fields.items():
            if field.kind == "checkbox":
                updates[key] = "true" if widget.isChecked() else "false"
            elif field.kind == "menu":
                updates[key] = widget.currentText()
            else:
                updates[key] = widget.text().strip()
        srv.setdefault("config", {}).update(updates)
        save_servers(self.servers)
        try:
            adapter.write_config(Path(srv["server_dir"]), updates)
        except Exception as exc:
            QMessageBox.warning(self, "Config", str(exc))
            return
        QMessageBox.information(self, "Config", "Saved.")

    def _open_install_dialog(self):
        srv = self._selected()
        if srv is None or srv.get("game_type") != "minecraft_java":
            return
        if runtime.snapshot(srv.get("id", "")).get("running"):
            QMessageBox.warning(self, "Install", "Stop the server first.")
            return
        server_dir = Path(srv.get("server_dir") or "")
        existing_cfg = dict(srv.get("config") or {})

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Install Minecraft server — {srv.get('name') or ''}")
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)

        loader_combo = QComboBox()
        for loader in mc_loader_choices():
            loader_combo.addItem(mc_loader_name(loader), loader)
        cur_loader = str(existing_cfg.get("loader") or "vanilla").lower()
        idx = loader_combo.findData(cur_loader)
        loader_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Loader", loader_combo)

        snapshots_chk = QCheckBox("Show snapshots / betas")
        form.addRow("", snapshots_chk)

        version_combo = QComboBox()
        version_combo.addItem("Loading versions…", None)
        version_combo.setEnabled(False)
        form.addRow("Minecraft version", version_combo)

        loader_version_label = QLabel("Loader version")
        loader_version_combo = QComboBox()
        loader_version_combo.setEnabled(False)
        form.addRow(loader_version_label, loader_version_combo)

        eula_chk = QCheckBox("I agree to Mojang's EULA (required)")
        eula_chk.setChecked(mc_eula_accepted(server_dir))
        form.addRow(eula_chk)

        status = QLabel(
            "Installing into this server's own folder won't affect any other server "
            "you've added — each one gets its own files, version, and port."
        )
        status.setWordWrap(True)
        status.setObjectName("Muted")
        form.addRow(status)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setVisible(False)
        form.addRow(progress)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        install_button = QPushButton("Install")
        install_button.setObjectName("Primary")
        buttons.addButton(install_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        state = {"versions": [], "closed": False}
        dlg.finished.connect(lambda _r: state.__setitem__("closed", True))

        def set_loader_version_visible(visible: bool):
            loader_version_label.setVisible(visible)
            loader_version_combo.setVisible(visible)

        def fetch_loader_versions():
            loader = loader_combo.currentData()
            mc_version = version_combo.currentData()
            if loader == "vanilla" or not mc_version:
                set_loader_version_visible(loader != "vanilla")
                loader_version_combo.clear()
                loader_version_combo.setEnabled(False)
                return
            set_loader_version_visible(True)
            loader_version_combo.clear()
            loader_version_combo.addItem("Loading…", None)
            loader_version_combo.setEnabled(False)

            def work():
                versions, error = get_mc_loader_versions(loader, mc_version)

                def done():
                    if state["closed"]:
                        return
                    loader_version_combo.clear()
                    if error:
                        loader_version_combo.addItem(error, None)
                        loader_version_combo.setEnabled(False)
                        return
                    if not versions:
                        loader_version_combo.addItem("No loader versions found", None)
                        loader_version_combo.setEnabled(False)
                        return
                    for lv in versions:
                        loader_version_combo.addItem(lv.label, lv.id)
                    idx2 = loader_version_combo.findData(existing_cfg.get("loader_version"))
                    loader_version_combo.setCurrentIndex(idx2 if idx2 >= 0 else 0)
                    loader_version_combo.setEnabled(True)

                QTimer.singleShot(0, done)

            threading.Thread(target=work, daemon=True).start()

        def repopulate_version_combo():
            versions = state["versions"]
            if not snapshots_chk.isChecked():
                versions = [v for v in versions if v.type == "release"]
            version_combo.blockSignals(True)
            version_combo.clear()
            if versions:
                for v in versions:
                    version_combo.addItem(v.id, v.id)
                version_combo.setEnabled(True)
                target = existing_cfg.get("installed_version")
                found = version_combo.findData(target) if target else -1
                version_combo.setCurrentIndex(found if found >= 0 else 0)
            else:
                version_combo.addItem("No versions found", None)
                version_combo.setEnabled(False)
            version_combo.blockSignals(False)
            fetch_loader_versions()

        def fetch_versions():
            versions, error = list_mc_versions()

            def done():
                if state["closed"]:
                    return
                if error:
                    version_combo.clear()
                    version_combo.addItem("Couldn't load versions", None)
                    status.setText(error)
                    return
                state["versions"] = versions
                repopulate_version_combo()

            QTimer.singleShot(0, done)

        threading.Thread(target=fetch_versions, daemon=True).start()

        loader_combo.currentIndexChanged.connect(lambda _i: fetch_loader_versions())
        version_combo.currentIndexChanged.connect(lambda _i: fetch_loader_versions())
        snapshots_chk.toggled.connect(lambda _c: repopulate_version_combo())
        set_loader_version_visible(loader_combo.currentData() != "vanilla")

        def start_install():
            loader = loader_combo.currentData()
            mc_version = version_combo.currentData()
            if not mc_version:
                QMessageBox.warning(dlg, "Install", "Pick a Minecraft version first.")
                return
            loader_version = ""
            if loader != "vanilla":
                loader_version = loader_version_combo.currentData()
                if not loader_version:
                    QMessageBox.warning(dlg, "Install", f"Pick a {mc_loader_name(loader)} version first.")
                    return
            if not eula_chk.isChecked():
                QMessageBox.warning(dlg, "Install", "You must agree to Mojang's EULA to install a Java server.")
                return
            widgets = (loader_combo, version_combo, loader_version_combo, snapshots_chk, eula_chk, install_button)
            for w in widgets:
                w.setEnabled(False)
            cancel_btn.setEnabled(False)
            progress.setVisible(True)
            progress.setRange(0, 0)
            status.setText("Starting install…")

            worker = create_mc_install_worker(server_dir, loader, mc_version, loader_version or "")
            worker.start()

            poll = QTimer(dlg)
            poll.setInterval(200)

            def finish(success: bool, message: str):
                poll.stop()
                progress.setVisible(False)
                cancel_btn.setEnabled(True)
                for w in widgets:
                    w.setEnabled(True)
                if not success:
                    status.setText(message or "Install failed.")
                    QMessageBox.warning(dlg, "Install failed", message or "Install failed.")
                    return
                if eula_chk.isChecked():
                    write_mc_eula(server_dir)
                cfg = srv.setdefault("config", {})
                cfg["loader"] = loader
                cfg["installed_version"] = mc_version
                cfg["loader_version"] = loader_version
                save_servers(self.servers)
                self._refresh_detail()
                self._refresh_config()
                self._refresh_mods()
                QMessageBox.information(dlg, "Install", f"{mc_loader_name(loader)} {mc_version} installed.")
                dlg.accept()

            def poll_events():
                if state["closed"]:
                    poll.stop()
                    return
                try:
                    while True:
                        event = worker.events.get_nowait()
                        kind = getattr(event, "kind", "")
                        if kind == "progress":
                            total = getattr(event, "total", 0) or 0
                            downloaded = getattr(event, "downloaded", 0) or 0
                            if total > 0:
                                progress.setRange(0, 100)
                                progress.setValue(int(downloaded / total * 100))
                                status.setText(f"{downloaded // 1024} KB / {total // 1024} KB")
                            else:
                                progress.setRange(0, 0)
                                status.setText(f"{downloaded // 1024} KB downloaded…")
                        elif kind == "error":
                            finish(False, getattr(event, "message", ""))
                            return
                        elif kind == "done":
                            finish(True, getattr(event, "message", ""))
                            return
                except Exception:
                    pass

            poll.timeout.connect(poll_events)
            poll.start()

        install_button.clicked.connect(start_install)
        dlg.exec()

    def _refresh_mods(self):
        self.mods_list.clear()
        adapter = self._adapter()
        srv = self._selected()
        if adapter is None or srv is None or not adapter.supports_mods():
            self.mods_hint.setText("This game does not use a mods folder.")
            self.modrinth_btn.hide()
            self.curse_btn.hide()
            return
        urls = adapter.mods_browser_urls() or {}
        self.modrinth_btn.setVisible("modrinth" in urls)
        self.curse_btn.setVisible("curseforge" in urls)
        files = adapter.collect_mod_files(Path(srv["server_dir"]))
        if not files:
            self.mods_hint.setText(adapter.mods_empty_message())
            return
        self.mods_hint.setText(f"{len(files)} installed")
        for path in files:
            self.mods_list.addItem(path.name)

    def _open_mods(self):
        adapter = self._adapter()
        srv = self._selected()
        if adapter is None or srv is None:
            return
        folder = adapter.mods_directory(Path(srv["server_dir"]))
        if folder is None:
            return
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as exc:
            QMessageBox.warning(self, "Mods", str(exc))

    def _open_mod_url(self, key):
        adapter = self._adapter()
        if adapter is None:
            return
        url = (adapter.mods_browser_urls() or {}).get(key)
        if url:
            webbrowser.open(url)

    def _tick(self):
        self._render_list()
        self._refresh_detail()
        srv = self._selected()
        if srv is None:
            return
        proc = runtime.get_process(srv.get("id", ""))
        drained = 0
        try:
            while True:
                event = proc.events.get_nowait()
                msg = getattr(event, "message", None) or str(event)
                self.console.appendPlainText(msg)
                drained += 1
        except Exception:
            pass
        if drained:
            self._seen_events += drained

    def _act(self, kind):
        srv = self._selected()
        if srv is None:
            return

        def work():
            try:
                if kind == "start":
                    result = start_server(srv)
                elif kind == "stop":
                    result = stop_server(srv)
                elif kind == "restart":
                    stop_server(srv)
                    result = start_server(srv)
                elif kind == "kill":
                    runtime.mark_expected_stop(srv["id"])
                    runtime.get_process(srv["id"]).stop(graceful=False)
                    result = {"ok": True}
                elif kind == "backup":
                    zip_path = create_backup_zip(
                        Path(srv["server_dir"]),
                        srv.get("name") or "server",
                        keep=int((srv.get("config") or {}).get("backup_keep") or 5),
                    )
                    result = {"ok": True, "backup": str(zip_path)}
                else:
                    result = {"ok": False, "error": kind}
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            QTimer.singleShot(0, lambda: self._act_done(kind, result))

        threading.Thread(target=work, daemon=True).start()

    def _act_done(self, kind, result):
        if not result.get("ok"):
            QMessageBox.warning(self, "Game Server Manager", str(result.get("error") or "Failed"))
        elif kind == "backup" and result.get("backup"):
            QMessageBox.information(self, "Backup", f"Saved {result['backup']}")
        self.servers = load_servers()
        self._render_list()
        self._refresh_detail()
        if kind == "backup":
            self._refresh_backups()

    def _send(self):
        srv = self._selected()
        cmd = self.cmd.text().strip()
        if srv is None or not cmd:
            return
        result = send_console(srv, cmd)
        if not result.get("ok"):
            QMessageBox.warning(self, "Console", str(result.get("error") or "Failed"))
        else:
            self.console.appendPlainText(f"> {cmd}")
            self.cmd.clear()

    def _add(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add server")
        form = QFormLayout(dlg)
        name = QLineEdit()
        game = QComboBox()
        for game_type, display, _icon in game_choices():
            game.addItem(f"{display}", game_type)
        folder = QLineEdit()
        pick = QPushButton("Browse")

        def fill_folder():
            gt = game.currentData()
            path, suggested = default_server_folder_for(gt)
            folder.setText(path)
            if not name.text().strip():
                name.setText(suggested)

        pick.clicked.connect(lambda: folder.setText(
            QFileDialog.getExistingDirectory(self, "Server folder", folder.text()) or folder.text()
        ))
        game.currentIndexChanged.connect(lambda _i: fill_folder())
        fill_folder()
        fold_row = QHBoxLayout()
        fold_row.addWidget(folder, 1)
        fold_row.addWidget(pick)
        form.addRow("Name", name)
        form.addRow("Game", game)
        form.addRow("Folder", fold_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        gt = game.currentData()
        adapter = get_adapter(gt)
        default_port = adapter.default_port() if adapter else 25565
        port = str(self._next_free_port(default_port))
        folder_path = folder.text().strip()
        if not name.text().strip() or not folder_path:
            QMessageBox.warning(self, "Add server", "Name and folder are required.")
            return
        Path(folder_path).mkdir(parents=True, exist_ok=True)
        self.servers.append({
            "id": uuid.uuid4().hex[:12],
            "name": name.text().strip(),
            "game_type": gt,
            "server_dir": folder_path,
            "config": {"port": port},
        })
        # Lock the chosen port into the server's own config file right away, so a
        # second server of the same game (e.g. a 2nd vanilla Minecraft server on a
        # different version) doesn't silently inherit the same default port and
        # collide with the first one when both are started.
        if gt == "minecraft_java":
            try:
                adapter.write_config(Path(folder_path), {"server-port": port})
            except Exception:
                pass
        save_servers(self.servers)
        self._selected_id = self.servers[-1]["id"]
        self._render_list()
        self._refresh_detail()
        self._refresh_side_tabs()

    def _next_free_port(self, default_port: int) -> int:
        """Pick the first port >= default_port not already used by another
        configured server, so adding a 2nd server of the same game type
        doesn't default to a port the first one is already using."""
        used = set()
        for s in self.servers:
            cfg = s.get("config") or {}
            for key in ("port", "server-port"):
                val = cfg.get(key)
                if val is None:
                    continue
                try:
                    used.add(int(val))
                except (TypeError, ValueError):
                    pass
        port = int(default_port)
        while port in used:
            port += 1
        return port

    def _remove(self):
        srv = self._selected()
        if srv is None:
            return
        if QMessageBox.question(self, "Remove", f"Remove {srv.get('name')} from the list?") != QMessageBox.StandardButton.Yes:
            return
        snap = runtime.snapshot(srv["id"])
        if snap.get("running"):
            QMessageBox.warning(self, "Remove", "Stop the server first.")
            return
        self.servers = [s for s in self.servers if s.get("id") != srv["id"]]
        save_servers(self.servers)
        self._selected_id = self.servers[0]["id"] if self.servers else None
        self._render_list()
        self._refresh_detail()
        self._refresh_side_tabs()
