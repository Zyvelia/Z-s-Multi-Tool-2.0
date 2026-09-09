"""Qt Disposable Sandbox — VMware linked clone lifecycle."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

backend = importlib.import_module("modules.System.Disposable Sandbox.backend")


class DisposableSandboxPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._busy = False
        self._watch = False
        self._vms = []

        root = QVBoxLayout(self)
        title = QLabel("Disposable Sandbox")
        title.setObjectName("AccentTitle")
        hint = QLabel(
            "Uses VMware Workstation: a linked clone of a snapshot you choose. "
            "Close that VM window and the clone is deleted. The base VM is not written. "
            "Only the drop folder is shared, read-only. Encryption passwords are not saved."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(hint)

        header = QFrame()
        header.setObjectName("Panel")
        hl = QVBoxLayout(header)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        hl.addWidget(self.status)

        cfg = backend.load_config()
        form = QHBoxLayout()
        self.vm = QComboBox()
        self.vm.setMinimumWidth(240)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_vm)
        self.snap = QLineEdit(cfg.get("snapshot") or backend.SNAPSHOT_DEFAULT)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText("if the VM is encrypted")
        form.addWidget(QLabel("Base VM"))
        form.addWidget(self.vm, 1)
        form.addWidget(browse)
        form.addWidget(QLabel("Snapshot"))
        form.addWidget(self.snap)
        form.addWidget(QLabel("Password"))
        form.addWidget(self.pw)
        hl.addLayout(form)
        row = QHBoxLayout()
        recheck = QPushButton("Re-check")
        recheck.clicked.connect(self._refresh_all)
        snap_btn = QPushButton("Create snapshot")
        snap_btn.clicked.connect(self._create_snapshot)
        open_vm = QPushButton("Open VMware")
        open_vm.clicked.connect(self._open_vmware)
        row.addWidget(recheck)
        row.addWidget(snap_btn)
        row.addWidget(open_vm)
        row.addStretch(1)
        hl.addLayout(row)
        root.addWidget(header)

        body = QHBoxLayout()
        drop = QFrame()
        drop.setObjectName("Panel")
        dl = QVBoxLayout(drop)
        dt = QLabel("Drop folder (read-only share: drop)")
        dt.setObjectName("CardTitle")
        dl.addWidget(dt)
        path_lbl = QLabel(str(backend.drop_dir()))
        path_lbl.setObjectName("Success")
        path_lbl.setWordWrap(True)
        dl.addWidget(path_lbl)
        guest = QLabel("Inside the guest: \\\\vmware-host\\Shared Folders\\drop   (or /mnt/hgfs/drop)")
        guest.setObjectName("Muted")
        guest.setWordWrap(True)
        dl.addWidget(guest)
        dbtns = QHBoxLayout()
        add = QPushButton("Add file…")
        add.setObjectName("Primary")
        add.clicked.connect(self._add_file)
        open_drop = QPushButton("Open folder")
        open_drop.clicked.connect(self._open_drop)
        clear = QPushButton("Clear drop")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_drop)
        dbtns.addWidget(add)
        dbtns.addWidget(open_drop)
        dbtns.addWidget(clear)
        dbtns.addStretch(1)
        dl.addLayout(dbtns)
        self.drop_list = QListWidget()
        dl.addWidget(self.drop_list, 1)
        body.addWidget(drop, 1)

        launch = QFrame()
        launch.setObjectName("Panel")
        ll = QVBoxLayout(launch)
        lt = QLabel("Launch")
        lt.setObjectName("CardTitle")
        ll.addWidget(lt)
        self.net = QCheckBox("Networking inside the VM (off is safer)")
        self.clip = QCheckBox("Clipboard in/out (VMware Tools)")
        self.clip.setChecked(True)
        ll.addWidget(self.net)
        ll.addWidget(self.clip)
        btns = QHBoxLayout()
        self.launch_btn = QPushButton("Launch clone")
        self.launch_btn.setObjectName("Primary")
        self.launch_btn.clicked.connect(self._launch)
        self.discard_btn = QPushButton("Discard now")
        self.discard_btn.setObjectName("Danger")
        self.discard_btn.clicked.connect(self._discard)
        btns.addWidget(self.launch_btn)
        btns.addWidget(self.discard_btn)
        btns.addStretch(1)
        ll.addLayout(btns)
        note = QLabel(
            "Needs a snapshot on the base VM (default name zs-clean). "
            "Create one while that VM is powered off. When you power off the clone, "
            "we delete it — desktop, installs, and registry from that session are gone."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        ll.addWidget(note)
        ll.addStretch(1)
        body.addWidget(launch, 1)
        root.addLayout(body, 1)

        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(3000)
        self._watch_timer.timeout.connect(self._poll_session)

        self._reload_vms()
        self._refresh_status()
        self._refresh_drop()
        leftover = backend.session_vmx().is_file() and not backend.session_running()
        if leftover:
            threading.Thread(target=lambda: self._cleanup_leftover(""), daemon=True).start()

    def _password(self) -> str:
        return self.pw.text()

    def _selected_vmx(self) -> str:
        idx = self.vm.currentIndex()
        if 0 <= idx < len(self._vms):
            return self._vms[idx]["vmx"]
        return backend.load_config().get("base_vmx") or ""

    def _reload_vms(self):
        vms = backend.inventory_vms()
        cfg = backend.load_config().get("base_vmx") or ""
        self._vms = list(vms)
        self.vm.blockSignals(True)
        self.vm.clear()
        if not self._vms:
            self.vm.addItem("(browse for a .vmx)")
        else:
            for item in self._vms:
                self.vm.addItem(item["name"])
            chosen = 0
            for i, item in enumerate(self._vms):
                if item["vmx"] == cfg:
                    chosen = i
                    break
            self.vm.setCurrentIndex(chosen)
        self.vm.blockSignals(False)

    def _browse_vm(self):
        path, _ = QFileDialog.getOpenFileName(self, "Base VMware VM", "", "VMware VM (*.vmx);;All files (*.*)")
        if not path:
            return
        backend.save_config(path, self.snap.text())
        self._reload_vms()
        self._refresh_status()

    def _refresh_all(self):
        vmx = self._selected_vmx()
        if vmx:
            backend.save_config(vmx, self.snap.text())
        self._reload_vms()
        self._refresh_status()

    def _refresh_status(self):
        info = backend.status()
        ok = bool(info.get("available"))
        self.status.setObjectName("Success" if ok else "Danger")
        self.status.setText(info.get("detail") or "")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if backend.session_running() and not self._watch:
            self._start_watch()

    def _refresh_drop(self):
        self.drop_list.clear()
        root = backend.drop_dir()
        for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            self.drop_list.addItem(path.name)

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "File to copy into the drop folder")
        if not path:
            return
        try:
            backend.copy_into_drop(path)
        except OSError as e:
            QMessageBox.warning(self, "Sandbox", str(e))
            return
        self._refresh_drop()

    def _open_drop(self):
        os.startfile(backend.drop_dir())

    def _clear_drop(self):
        if QMessageBox.question(self, "Sandbox", "Delete everything in the drop folder on this PC?") != QMessageBox.StandardButton.Yes:
            return
        root = backend.drop_dir()
        for path in root.iterdir():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as e:
                QMessageBox.warning(self, "Sandbox", str(e))
                return
        self._refresh_drop()

    def _open_vmware(self):
        gui = backend.find_gui()
        if not gui:
            QMessageBox.warning(self, "Sandbox", "VMware Workstation / Player was not found.")
            return
        try:
            subprocess.Popen([str(gui)])
        except OSError as e:
            QMessageBox.warning(self, "Sandbox", str(e))

    def _set_busy(self, busy: bool, text: str = ""):
        self._busy = busy
        self.launch_btn.setEnabled(not busy)
        self.launch_btn.setText(text or "Launch clone")

    def _create_snapshot(self):
        if self._busy:
            return
        vmx = self._selected_vmx()
        if not vmx:
            QMessageBox.information(self, "Sandbox", "Pick a base VM first.")
            return
        name = self.snap.text().strip() or backend.SNAPSHOT_DEFAULT
        if QMessageBox.question(
            self, "Sandbox",
            f"Create snapshot “{name}” on the base VM?\nThe VM must be powered off.\n\n{vmx}",
        ) != QMessageBox.StandardButton.Yes:
            return
        backend.save_config(vmx, name)
        self._set_busy(True, "Snapshotting…")
        pw = self._password()

        def work():
            err = None
            try:
                backend.create_snapshot(vmx, name, pw)
            except backend.VmError as e:
                err = str(e)
            QTimer.singleShot(0, lambda: self._snapshot_done(name, err))

        threading.Thread(target=work, daemon=True).start()

    def _snapshot_done(self, name, err):
        self._set_busy(False)
        self._refresh_status()
        if err:
            QMessageBox.warning(self, "Sandbox", err)
        else:
            QMessageBox.information(self, "Sandbox", f"Snapshot “{name}” created.")

    def _launch(self):
        if self._busy:
            return
        info = backend.status()
        if not info.get("available"):
            QMessageBox.warning(self, "Sandbox", info.get("detail") or "VMware was not found.")
            return
        vmx = self._selected_vmx()
        if not vmx:
            QMessageBox.information(self, "Sandbox", "Pick a base VM (.vmx).")
            return
        backend.save_config(vmx, self.snap.text())
        self._set_busy(True, "Cloning…")
        snap = self.snap.text()
        pw = self._password()
        networking = self.net.isChecked()
        clipboard = self.clip.isChecked()

        def work():
            err = None
            try:
                backend.launch(base_vmx=vmx, snapshot=snap, password=pw, networking=networking, clipboard=clipboard)
            except backend.VmError as e:
                err = str(e)
            QTimer.singleShot(0, lambda: self._launch_done(err))

        threading.Thread(target=work, daemon=True).start()

    def _launch_done(self, err):
        self._set_busy(False)
        self._refresh_status()
        if err:
            QMessageBox.warning(self, "Sandbox", err)
            return
        self._start_watch()

    def _discard(self):
        if self._busy:
            return
        if QMessageBox.question(self, "Sandbox", "Power off the clone (if running) and delete it?") != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True, "Discarding…")
        pw = self._password()

        def work():
            err = None
            try:
                backend.discard_session(password=pw, missing_ok=True)
            except (backend.VmError, OSError) as e:
                err = str(e)
            QTimer.singleShot(0, lambda: self._discard_done(err))

        threading.Thread(target=work, daemon=True).start()

    def _discard_done(self, err):
        self._set_busy(False)
        self._refresh_status()
        if err:
            QMessageBox.warning(self, "Sandbox", err)

    def _cleanup_leftover(self, password: str = ""):
        try:
            backend.discard_session(password=password, missing_ok=True)
        except (backend.VmError, OSError):
            pass
        QTimer.singleShot(0, self._refresh_status)

    def _start_watch(self):
        self._watch = True
        if not self._watch_timer.isActive():
            self._watch_timer.start()

    def _poll_session(self):
        if backend.session_running():
            return
        self._watch = False
        self._watch_timer.stop()
        if backend.session_vmx().is_file():
            pw = self._password()
            threading.Thread(target=lambda: self._cleanup_leftover(pw), daemon=True).start()
        else:
            self._refresh_status()
