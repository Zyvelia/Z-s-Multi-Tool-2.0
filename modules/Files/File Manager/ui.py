"""Qt File Manager — drives, folder list, text/hex/image/audio/archive."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    _QT_AUDIO = True
except Exception:
    _QT_AUDIO = False

_utils = importlib.import_module("modules.Files.File Manager.utils")
_handlers = importlib.import_module("modules.Files.File Manager.file_handlers")
_mod = importlib.import_module("modules.Files.File Manager.module")


class FileViewerUI(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._cwd = Path.home()
        self._current_file = None
        self._player = None
        self._audio_out = None
        if _QT_AUDIO:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._audio_out.setVolume(0.8)

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("File Manager")
        title.setObjectName("AccentTitle")
        header.addWidget(title)
        header.addStretch(1)
        up = QPushButton("Up")
        up.clicked.connect(self._go_up)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        open_os = QPushButton("Open in OS")
        open_os.setObjectName("Primary")
        open_os.clicked.connect(self._open_os)
        save = QPushButton("Save text")
        save.clicked.connect(self._save_text)
        header.addWidget(up)
        header.addWidget(refresh)
        header.addWidget(open_os)
        header.addWidget(save)
        root.addLayout(header)

        self.path_label = QLabel(str(self._cwd))
        self.path_label.setObjectName("Muted")
        self.path_label.setWordWrap(True)
        root.addWidget(self.path_label)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        drives_cap = QLabel("Drives")
        drives_cap.setObjectName("CardTitle")
        ll.addWidget(drives_cap)
        self.drives = QListWidget()
        self.drives.itemActivated.connect(self._enter_drive)
        self.drives.itemDoubleClicked.connect(self._enter_drive)
        ll.addWidget(self.drives)
        folder_cap = QLabel("Folder")
        folder_cap.setObjectName("CardTitle")
        ll.addWidget(folder_cap)
        self.files = QListWidget()
        self.files.itemClicked.connect(self._on_file_click)
        self.files.itemDoubleClicked.connect(self._on_file_activate)
        ll.addWidget(self.files, 1)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.preview_meta = QLabel("Select a file")
        self.preview_meta.setObjectName("Muted")
        rl.addWidget(self.preview_meta)
        self.stack = QStackedWidget()
        self.text = QPlainTextEdit()
        self.hex = QPlainTextEdit()
        self.hex.setReadOnly(True)
        self.image = QLabel("No image")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_page = self._build_audio()
        self.archive_page = self._build_archive()
        self.stack.addWidget(self.text)
        self.stack.addWidget(self.hex)
        self.stack.addWidget(self.image)
        self.stack.addWidget(self.audio_page)
        self.stack.addWidget(self.archive_page)
        rl.addWidget(self.stack, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        self._load_drives()
        self._refresh()

    def _build_audio(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.art = QLabel("♪")
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art.setFixedSize(180, 180)
        self.audio_title = QLabel("No track")
        self.audio_title.setObjectName("CardTitle")
        self.audio_title.setWordWrap(True)
        self.audio_artist = QLabel("")
        self.audio_artist.setObjectName("Muted")
        self.audio_info = QLabel("")
        self.audio_info.setObjectName("Muted")
        lay.addWidget(self.art, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.audio_title)
        lay.addWidget(self.audio_artist)
        lay.addWidget(self.audio_info)
        row = QHBoxLayout()
        play = QPushButton("Play")
        play.setObjectName("Primary")
        play.clicked.connect(self._audio_play)
        pause = QPushButton("Pause")
        pause.clicked.connect(self._audio_pause)
        stop = QPushButton("Stop")
        stop.clicked.connect(self._audio_stop)
        row.addWidget(play)
        row.addWidget(pause)
        row.addWidget(stop)
        lay.addLayout(row)
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Volume"))
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.valueChanged.connect(self._audio_volume)
        vol_row.addWidget(self.vol, 1)
        lay.addLayout(vol_row)
        self.tag_form = QFormLayout()
        self.tag_edits = {}
        for key in _handlers.EDITABLE_TAG_FIELDS:
            edit = QLineEdit()
            self.tag_edits[key] = edit
            self.tag_form.addRow(key.capitalize(), edit)
        lay.addLayout(self.tag_form)
        save_tags = QPushButton("Save tags")
        save_tags.clicked.connect(self._save_audio_tags)
        lay.addWidget(save_tags, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        return page

    def _build_archive(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        cap = QLabel("Archive contents")
        cap.setObjectName("CardTitle")
        lay.addWidget(cap)
        self.archive_list = QListWidget()
        self.archive_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        lay.addWidget(self.archive_list, 1)
        row = QHBoxLayout()
        extract_sel = QPushButton("Extract selected")
        extract_sel.clicked.connect(self._extract_selected)
        extract_all = QPushButton("Extract all")
        extract_all.setObjectName("Primary")
        extract_all.clicked.connect(self._extract_all)
        add_files = QPushButton("Add files to zip")
        add_files.clicked.connect(self._add_to_zip)
        row.addWidget(extract_sel)
        row.addWidget(extract_all)
        row.addWidget(add_files)
        lay.addLayout(row)
        return page

    def _load_drives(self):
        self.drives.clear()
        for drive in _utils.list_drives():
            item = QListWidgetItem(drive.get("label") or drive["path"])
            item.setData(Qt.ItemDataRole.UserRole, drive["path"])
            self.drives.addItem(item)

    def _enter_drive(self, item):
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._cwd = Path(path)
            self._refresh()

    def _go_up(self):
        parent = self._cwd.parent
        if parent != self._cwd:
            self._cwd = parent
            self._refresh()

    def _refresh(self):
        self.path_label.setText(str(self._cwd))
        self.files.clear()
        try:
            entries = sorted(self._cwd.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as exc:
            self.preview_meta.setText(str(exc))
            return
        for entry in entries:
            prefix = "[DIR] " if entry.is_dir() else ""
            item = QListWidgetItem(prefix + entry.name)
            item.setData(Qt.ItemDataRole.UserRole, str(entry))
            self.files.addItem(item)

    def _on_file_click(self, item):
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if path.is_file():
            self._preview(path)

    def _on_file_activate(self, item):
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if path.is_dir():
            self._cwd = path
            self._refresh()
        elif path.is_file():
            self._preview(path)

    def _preview(self, path: Path):
        self._audio_stop()
        self._current_file = path
        kind = _utils.detect_viewer(path)
        try:
            size = _utils.human_size(path.stat().st_size)
        except OSError:
            size = "?"
        self.preview_meta.setText(f"{path.name}  ·  {kind}  ·  {size}")
        if kind == "text":
            self.stack.setCurrentWidget(self.text)
            try:
                text, enc = _utils.safe_read_text(path, max_bytes=_mod.TEXT_SIZE_LIMIT)
                self.text.setPlainText(text)
                self.preview_meta.setText(f"{path.name}  ·  text ({enc})  ·  {size}")
            except Exception as exc:
                self.text.setPlainText(str(exc))
            return
        if kind == "image":
            self.stack.setCurrentWidget(self.image)
            pix = QPixmap(str(path))
            if pix.isNull():
                self.image.setText("Could not load image")
            else:
                self.image.setPixmap(pix.scaled(
                    self.image.size() if self.image.size().width() > 40 else self.stack.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            return
        if kind == "audio":
            self._show_audio(path)
            return
        if kind == "archive":
            self._show_archive(path)
            return
        self.stack.setCurrentWidget(self.hex)
        rows = []
        try:
            for off, hx, ascii_s in _handlers.hex_rows(path, 0, _mod.HEX_INITIAL_ROWS):
                rows.append(f"{off}  {hx}  {ascii_s}")
        except OSError as exc:
            rows = [str(exc)]
        self.hex.setPlainText("\n".join(rows) or "(empty)")

    def _show_audio(self, path: Path):
        self.stack.setCurrentWidget(self.audio_page)
        meta = _handlers.audio_metadata(path)
        self.audio_title.setText(meta.get("Title") or path.stem)
        album = meta.get("Album")
        artist = meta.get("Artist") or ""
        self.audio_artist.setText(f"{artist}  ·  {album}" if album else artist)
        bits = [meta.get("Duration") or "", meta.get("Bitrate") or ""]
        self.audio_info.setText("  ·  ".join(b for b in bits if b))
        art = _handlers.audio_artwork(path)
        if art:
            pix = QPixmap()
            pix.loadFromData(art)
            self.art.setPixmap(pix.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.art.setText("")
        else:
            self.art.setPixmap(QPixmap())
            self.art.setText("♪")
        easy = {k.lower(): v for k, v in meta.items()}
        for key, edit in self.tag_edits.items():
            edit.setText(easy.get(key, ""))
        if self._player is not None:
            self._player.setSource(QUrl.fromLocalFile(str(path)))

    def _show_archive(self, path: Path):
        self.stack.setCurrentWidget(self.archive_page)
        self.archive_list.clear()
        entries = _handlers.list_archive(path)
        if not entries:
            self.preview_meta.setText(f"{path.name}  ·  archive (empty or unsupported, e.g. 7z)")
            return
        for entry in entries:
            prefix = "[DIR] " if entry.is_dir else ""
            size = _utils.human_size(entry.size)
            item = QListWidgetItem(f"{prefix}{entry.name}  ·  {size}")
            item.setData(Qt.ItemDataRole.UserRole, entry.name)
            self.archive_list.addItem(item)

    def _audio_play(self):
        if self._player is None:
            QMessageBox.information(self, "File Manager", "Qt multimedia isn't available in this build.")
            return
        self._player.play()

    def _audio_pause(self):
        if self._player is not None:
            self._player.pause()

    def _audio_stop(self):
        if self._player is not None:
            self._player.stop()

    def _audio_volume(self, value):
        if self._audio_out is not None:
            self._audio_out.setVolume(value / 100.0)

    def _save_audio_tags(self):
        if self._current_file is None or _utils.detect_viewer(self._current_file) != "audio":
            return
        tags = {key: edit.text().strip() for key, edit in self.tag_edits.items()}
        try:
            _handlers.save_audio_metadata(self._current_file, tags)
            self.preview_meta.setText(f"Saved tags on {self._current_file.name}")
            self.preview_meta.setObjectName("Success")
        except Exception as exc:
            QMessageBox.warning(self, "File Manager", str(exc))
            return
        self.preview_meta.style().unpolish(self.preview_meta)
        self.preview_meta.style().polish(self.preview_meta)

    def _extract_selected(self):
        if self._current_file is None:
            return
        names = [item.data(Qt.ItemDataRole.UserRole) for item in self.archive_list.selectedItems()]
        names = [n for n in names if n]
        if not names:
            QMessageBox.information(self, "File Manager", "Select archive members first.")
            return
        dest = QFileDialog.getExistingDirectory(self, "Extract to")
        if not dest:
            return
        try:
            _handlers.extract_archive(self._current_file, dest, names)
        except Exception as exc:
            QMessageBox.warning(self, "File Manager", str(exc))
            return
        self.preview_meta.setText(f"Extracted {len(names)} item(s)")

    def _extract_all(self):
        if self._current_file is None:
            return
        dest = QFileDialog.getExistingDirectory(self, "Extract all to")
        if not dest:
            return
        try:
            _handlers.extract_archive(self._current_file, dest)
        except Exception as exc:
            QMessageBox.warning(self, "File Manager", str(exc))
            return
        self.preview_meta.setText(f"Extracted to {dest}")

    def _add_to_zip(self):
        if self._current_file is None or self._current_file.suffix.lower() != ".zip":
            QMessageBox.information(self, "File Manager", "Adding files only works on .zip archives.")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add to zip")
        if not paths:
            return
        try:
            _handlers.add_to_zip(self._current_file, paths)
        except Exception as exc:
            QMessageBox.warning(self, "File Manager", str(exc))
            return
        self._show_archive(self._current_file)
        self.preview_meta.setText(f"Added {len(paths)} file(s)")

    def _save_text(self):
        if self._current_file is None or _utils.detect_viewer(self._current_file) != "text":
            QMessageBox.information(self, "File Manager", "Open a text file first.")
            return
        try:
            self._current_file.write_text(self.text.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "File Manager", str(exc))
            return
        self.preview_meta.setText(f"Saved {self._current_file.name}")
        self.preview_meta.setObjectName("Success")
        self.preview_meta.style().unpolish(self.preview_meta)
        self.preview_meta.style().polish(self.preview_meta)

    def _open_os(self):
        target = self._current_file or self._cwd
        try:
            os.startfile(str(target))
        except OSError as exc:
            QMessageBox.warning(self, "File Manager", str(exc))

    def on_hide(self):
        self._audio_stop()
