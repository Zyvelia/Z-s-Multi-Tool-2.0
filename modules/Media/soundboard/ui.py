"""Qt Soundboard — play clips locally and serve the same folder to the phone."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.qt.remote_common import AppServePanel, TailscalePanel
from core.services.tailscale_service import APP_HTTPS_PORTS
from modules.Media.soundboard.audio import (
    AUDIO_EXT,
    get_output_devices,
    load_audio_numpy,
    play_on_device,
    stop_all,
)
from modules.Media.soundboard.web_server import SoundboardWebServer

GRID_COLS = 4


def _ensure_server(manager):
    web = getattr(manager, "soundboard_web_server", None)
    if web is not None:
        return web
    web = SoundboardWebServer()
    manager.soundboard_web_server = web
    return web


class SoundboardPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.web = _ensure_server(manager)
        self.slots = []
        self.master_volume = 1.0
        self._device_a = None
        self._device_b = None
        self._all_devices = []

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Soundboard")
        title.setObjectName("AccentTitle")
        self.status = QLabel("No sounds loaded")
        self.status.setObjectName("Muted")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status)
        root.addLayout(header)

        hint = QLabel("Play clips on this PC. Load a folder to share the same board with the phone over Tailscale.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        bar = QHBoxLayout()
        add = QPushButton("Add files")
        add.setObjectName("Primary")
        add.clicked.connect(self._add_files)
        folder = QPushButton("Load folder")
        folder.clicked.connect(self._load_folder)
        clear = QPushButton("Clear all")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_all)
        stop = QPushButton("Stop all")
        stop.clicked.connect(self._stop_all)
        bar.addWidget(add)
        bar.addWidget(folder)
        bar.addWidget(clear)
        bar.addWidget(stop)
        bar.addStretch(1)
        bar.addWidget(QLabel("Master volume"))
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setMaximumWidth(160)
        self.vol.valueChanged.connect(self._set_master)
        bar.addWidget(self.vol)
        root.addLayout(bar)

        devices = QHBoxLayout()
        devices.addWidget(QLabel("You hear"))
        self.dev_a = QComboBox()
        self.dev_a.currentIndexChanged.connect(lambda _: self._on_device_pick())
        devices.addWidget(self.dev_a, 1)
        devices.addWidget(QLabel("Second output"))
        self.dev_b = QComboBox()
        self.dev_b.currentIndexChanged.connect(lambda _: self._on_device_pick())
        devices.addWidget(self.dev_b, 1)
        refresh = QPushButton("Refresh devices")
        refresh.clicked.connect(self._refresh_devices)
        devices.addWidget(refresh)
        root.addLayout(devices)

        board = QFrame()
        board.setObjectName("Panel")
        bl = QVBoxLayout(board)
        count_row = QHBoxLayout()
        sounds_title = QLabel("Sounds")
        sounds_title.setObjectName("CardTitle")
        self.count = QLabel("0 sounds")
        self.count.setObjectName("Muted")
        count_row.addWidget(sounds_title)
        count_row.addStretch(1)
        count_row.addWidget(self.count)
        bl.addLayout(count_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        scroll.setWidget(self.grid_host)
        bl.addWidget(scroll, 1)
        root.addWidget(board, 1)

        self._refresh_devices()
        saved_folder = (self.web.settings.get("folder") or "").strip()
        if saved_folder and os.path.isdir(saved_folder):
            QTimer.singleShot(0, lambda: self._load_paths_from_folder(saved_folder, persist=False))
        else:
            self._rebuild_grid()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _SoundboardSettings(parent, manager)

    def _refresh_devices(self):
        self._all_devices = get_output_devices()
        self.dev_a.blockSignals(True)
        self.dev_b.blockSignals(True)
        self.dev_a.clear()
        self.dev_b.clear()
        self.dev_a.addItem("Default", None)
        self.dev_b.addItem("None", None)
        for d in self._all_devices:
            self.dev_a.addItem(d["name"], d["index"])
            self.dev_b.addItem(d["name"], d["index"])
        for i, d in enumerate(self._all_devices):
            name = (d["name"] or "").lower()
            if "voicemeeter" in name and "input" in name:
                self.dev_b.setCurrentIndex(i + 1)
                break
        saved = self.web.settings.get("device_indices") or []
        if saved:
            idx_a = self.dev_a.findData(saved[0])
            if idx_a >= 0:
                self.dev_a.setCurrentIndex(idx_a)
            if len(saved) > 1:
                idx_b = self.dev_b.findData(saved[1])
                if idx_b >= 0:
                    self.dev_b.setCurrentIndex(idx_b)
        self.dev_a.blockSignals(False)
        self.dev_b.blockSignals(False)
        self.status.setText(f"Found {len(self._all_devices)} output devices")
        self._sync_devices()

    def _on_device_pick(self):
        self._sync_devices()

    def _active_indices(self):
        a = self.dev_a.currentData()
        b = self.dev_b.currentData()
        if b is None:
            return [a]
        if a == b:
            return [a]
        return [a, b]

    def _sync_devices(self):
        self.web.update_settings({"device_indices": [i for i in self._active_indices() if i is not None]})

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add sounds", "",
            "Audio (*.mp3 *.wav *.flac *.ogg *.m4a);;All files (*.*)",
        )
        if paths:
            existing = {s["path"] for s in self.slots}
            self._add_slots([p for p in paths if p not in existing])

    def _load_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Sound folder")
        if folder:
            self._load_paths_from_folder(folder, persist=True)

    def _load_paths_from_folder(self, folder, persist=True):
        if persist:
            self.web.update_settings({"folder": folder})
        existing = {s["path"] for s in self.slots}
        new_paths = sorted(
            os.path.join(root, f)
            for root, _dirs, files in os.walk(folder)
            for f in files
            if f.lower().endswith(AUDIO_EXT)
        )
        new_paths = [p for p in new_paths if p not in existing]
        if not new_paths:
            self.status.setText("No new audio files found")
            return
        self._add_slots(new_paths)

    def _add_slots(self, paths):
        self.status.setText(f"Loading {len(paths)} sound(s)…")

        def work():
            loaded = []
            for path in paths:
                samples, sr = load_audio_numpy(path)
                loaded.append({
                    "path": path,
                    "name": os.path.splitext(os.path.basename(path))[0],
                    "volume": self.master_volume,
                    "samples": samples,
                    "sr": sr,
                })
            QTimer.singleShot(0, lambda: self._append_slots(loaded))

        threading.Thread(target=work, daemon=True).start()

    def _append_slots(self, new_slots):
        self.slots.extend(new_slots)
        self._rebuild_grid()
        self._update_count()

    def _clear_layout(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_grid(self):
        self._clear_layout()
        if not self.slots:
            empty = QLabel("No sounds yet. Add files or load a folder.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(empty, 0, 0, 1, GRID_COLS)
            return
        for i, slot in enumerate(self.slots):
            row, col = divmod(i, GRID_COLS)
            card = QFrame()
            card.setObjectName("Panel")
            cl = QVBoxLayout(card)
            name = QLabel(slot["name"])
            name.setObjectName("CardTitle")
            name.setWordWrap(True)
            play = QPushButton("Play")
            play.setObjectName("Primary")
            play.clicked.connect(lambda _=False, s=slot: self._play(s))
            vol = QSlider(Qt.Orientation.Horizontal)
            vol.setRange(0, 100)
            vol.setValue(int(float(slot.get("volume") or 1.0) * 100))
            vol.valueChanged.connect(lambda v, s=slot: self._set_slot_volume(s, v))
            remove = QPushButton("Remove")
            remove.setObjectName("Danger")
            remove.clicked.connect(lambda _=False, idx=i: self._remove(idx))
            cl.addWidget(name)
            cl.addWidget(play)
            cl.addWidget(QLabel("Volume"))
            cl.addWidget(vol)
            cl.addWidget(remove)
            self.grid.addWidget(card, row, col)

    def _play(self, slot):
        if slot.get("samples") is None:
            self.status.setText(f"Couldn't decode {slot['name']}")
            return
        indices = self._active_indices()
        vol = float(slot.get("volume") or self.master_volume)

        def work():
            for idx in indices:
                play_on_device(slot["samples"], slot["sr"], idx, vol)

        threading.Thread(target=work, daemon=True).start()
        self.status.setText(f"Playing {slot['name']}")

    def _stop_all(self):
        stop_all()
        self.status.setText("All sounds stopped")

    def _set_slot_volume(self, slot, value):
        slot["volume"] = max(0.0, min(1.0, value / 100.0))

    def _set_master(self, value):
        self.master_volume = max(0.0, min(1.0, value / 100.0))
        for slot in self.slots:
            slot["volume"] = self.master_volume

    def _remove(self, idx):
        if 0 <= idx < len(self.slots):
            del self.slots[idx]
            self._rebuild_grid()
            self._update_count()

    def _clear_all(self):
        self._stop_all()
        self.slots.clear()
        self._rebuild_grid()
        self._update_count()
        self.status.setText("Board cleared")

    def _update_count(self):
        n = len(self.slots)
        self.count.setText(f"{n} {'sound' if n == 1 else 'sounds'}")
        self.status.setText(f"{n} sound(s) ready" if n else "No sounds loaded")

    def on_hide(self):
        self._stop_all()


class _SoundboardSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.web = _ensure_server(manager)
        lay = QVBoxLayout(self)
        title = QLabel("Phone folder & access")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(self.web.settings.get("folder") or "")
        self.folder.setPlaceholderText("Folder served to the phone…")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        lay.addLayout(folder_row)
        self.access = QLineEdit(self.web.access_code or self.web.settings.get("access_code") or "")
        self.access.setPlaceholderText("Optional phone access code")
        lay.addWidget(self.access)
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        lay.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)

        tailscale = manager.container.tailscale_service
        self.ts = TailscalePanel(self, tailscale)
        self.serve = AppServePanel(
            self,
            tailscale=tailscale,
            get_server=lambda: self.web,
            app_key="soundboard",
            default_port=APP_HTTPS_PORTS["soundboard"],
            title="Remote access (play from phone)",
            hint="Serves the saved folder on 127.0.0.1:8447. Tailscale maps it onto the tailnet.",
        )
        lay.addWidget(self.ts)
        lay.addWidget(self.serve)
        self._poll = QTimer(self)
        self._poll.setInterval(4000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Sound folder", self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def _save(self):
        self.web.update_settings({
            "folder": self.folder.text().strip(),
            "access_code": self.access.text().strip(),
        })

    def _refresh(self):
        def work():
            status = self.manager.container.tailscale_service.get_status()
            running = self.web.is_running()
            QTimer.singleShot(0, lambda: self._apply(status, running))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status, running):
        self.ts.apply_status(status)
        self.serve.apply_status(status, running)
