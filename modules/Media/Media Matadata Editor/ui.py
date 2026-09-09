"""Qt Media Metadata Editor — audio tags, image EXIF, file timestamps."""

from __future__ import annotations

import importlib
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_audio = importlib.import_module("modules.Media.Media Matadata Editor.audio_backend")
_image = importlib.import_module("modules.Media.Media Matadata Editor.image_backend")
_time = importlib.import_module("modules.Media.Media Matadata Editor.timestamp_backend")

BULK_FIELDS = [pair for pair in _audio.TAG_FIELDS if pair[0] not in ("title", "tracknumber")]


class MetadataEditorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        root = QVBoxLayout(self)
        title = QLabel("Media Metadata Editor")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        tabs = QTabWidget()
        tabs.addTab(_AudioTab(self, manager), "Audio tags")
        tabs.addTab(_BatchAudioTab(self, manager), "Batch audio")
        tabs.addTab(_ImageTab(self, manager), "Image EXIF")
        tabs.addTab(_StampTab(self, manager), "File timestamps")
        root.addWidget(tabs, 1)


class _AudioTab(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.path = None
        self.audio = None
        self.kind = None
        self.cover_path = None
        self.edits = {}

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        open_btn = QPushButton("Open audio")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open)
        self.path_label = QLabel("No file loaded")
        self.path_label.setObjectName("Muted")
        top.addWidget(open_btn)
        top.addWidget(self.path_label, 1)
        root.addLayout(top)

        body = QHBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        form = QFormLayout(host)
        for key, label in _audio.TAG_FIELDS:
            edit = QLineEdit()
            self.edits[key] = edit
            form.addRow(label, edit)
        scroll.setWidget(host)
        body.addWidget(scroll, 1)

        side = QVBoxLayout()
        cover_title = QLabel("Cover")
        cover_title.setObjectName("CardTitle")
        self.cover = QLabel("No cover")
        self.cover.setObjectName("Muted")
        self.cover.setFixedSize(180, 180)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pick = QPushButton("Set cover")
        pick.clicked.connect(self._pick_cover)
        strip = QPushButton("Strip cover")
        strip.setObjectName("Danger")
        strip.clicked.connect(self._strip_cover)
        save = QPushButton("Save tags")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        side.addWidget(cover_title)
        side.addWidget(self.cover)
        side.addWidget(pick)
        side.addWidget(strip)
        side.addWidget(save)
        side.addStretch(1)
        body.addLayout(side)
        root.addLayout(body, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)
        if not _audio.MUTAGEN_AVAILABLE:
            self.status.setText("mutagen is not installed. Run: pip install mutagen")
            self.status.setObjectName("Danger")

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Audio", "",
            "Audio (*.mp3 *.flac *.m4a *.mp4 *.ogg *.wav);;All files (*.*)",
        )
        if path:
            self._load(path)

    def _load(self, path):
        try:
            self.audio, self.kind = _audio.load_audio(path)
            self.path = path
            self.cover_path = None
            self.path_label.setText(os.path.basename(path))
            for key, edit in self.edits.items():
                edit.setText(_audio.get_field_value(self.audio, self.kind, key))
            self._show_cover(_audio.extract_cover_bytes(path, self.kind, self.audio))
            self.status.setText("Loaded successfully.")
            self.status.setObjectName("Muted")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Metadata Editor", f"Could not load file:\n{e}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _show_cover(self, data):
        if not data:
            self.cover.setPixmap(QPixmap())
            self.cover.setText("No cover")
            return
        pix = QPixmap()
        pix.loadFromData(data)
        self.cover.setText("")
        self.cover.setPixmap(pix.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _pick_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cover image", "", "Images (*.jpg *.jpeg *.png);;All files (*.*)")
        if path:
            self.cover_path = path
            pix = QPixmap(path)
            self.cover.setText("")
            self.cover.setPixmap(pix.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _strip_cover(self):
        self.cover_path = ""
        self.cover.setPixmap(QPixmap())
        self.cover.setText("No cover")

    def _save(self):
        if not self.path or self.audio is None:
            return
        try:
            for key, edit in self.edits.items():
                _audio.set_field_value(self.audio, self.kind, key, edit.text().strip())
            _audio.save_audio(self.audio)
            if self.cover_path == "":
                _audio.strip_cover(self.path, self.kind)
            elif self.cover_path:
                _audio.embed_cover(self.path, self.kind, self.cover_path)
            self.cover_path = None
            self.status.setText("Saved successfully.")
            self.status.setObjectName("Success")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Metadata Editor", f"Could not save changes:\n{e}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class _BatchAudioTab(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.rows = []
        self.cover_path = None
        root = QVBoxLayout(self)
        hint = QLabel("Blank fields are left unchanged. Apply-if-filled across the selected files.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        top = QHBoxLayout()
        add = QPushButton("Add files")
        add.setObjectName("Primary")
        add.clicked.connect(self._add_files)
        folder = QPushButton("Add folder")
        folder.clicked.connect(self._add_folder)
        clear = QPushButton("Clear list")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear)
        self.count = QLabel("0 files")
        self.count.setObjectName("Muted")
        top.addWidget(add)
        top.addWidget(folder)
        top.addWidget(clear)
        top.addStretch(1)
        top.addWidget(self.count)
        root.addLayout(top)

        split = QHBoxLayout()
        left = QVBoxLayout()
        sel = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.clicked.connect(lambda: self._check_all(True))
        none_btn = QPushButton("Select none")
        none_btn.clicked.connect(lambda: self._check_all(False))
        sel.addWidget(all_btn)
        sel.addWidget(none_btn)
        sel.addStretch(1)
        left.addLayout(sel)
        self.list = QListWidget()
        left.addWidget(self.list, 1)
        split.addLayout(left, 1)

        form_host = QWidget()
        form = QFormLayout(form_host)
        self.edits = {}
        for key, label in BULK_FIELDS:
            edit = QLineEdit()
            self.edits[key] = edit
            form.addRow(label, edit)
        self.auto_number = QCheckBox("Auto-number tracks, starting at")
        self.track_start = QSpinBox()
        self.track_start.setRange(1, 999)
        self.track_start.setValue(1)
        form.addRow(self.auto_number, self.track_start)
        cover = QPushButton("Set cover for selected…")
        cover.clicked.connect(self._pick_cover)
        strip = QPushButton("Remove cover from selected")
        strip.setObjectName("Danger")
        strip.clicked.connect(self._queue_strip)
        apply_btn = QPushButton("Apply to selected")
        apply_btn.setObjectName("Primary")
        apply_btn.clicked.connect(self._apply)
        form.addRow(cover)
        form.addRow(strip)
        form.addRow(apply_btn)
        split.addWidget(form_host)
        root.addLayout(split, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

    def _add_files(self):
        if not _audio.MUTAGEN_AVAILABLE:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Audio files", "",
            "Audio (*.mp3 *.flac *.m4a *.mp4 *.ogg *.wav);;All files (*.*)",
        )
        self._add_paths(paths)

    def _add_folder(self):
        if not _audio.MUTAGEN_AVAILABLE:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder of audio")
        if not folder:
            return
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if os.path.splitext(name)[1].lower() in _audio.AUDIO_EXTS:
                    found.append(os.path.join(root, name))
        found.sort()
        self._add_paths(found)

    def _add_paths(self, paths):
        existing = {row["path"] for row in self.rows}
        added = 0
        for path in paths:
            if path in existing:
                continue
            item = QListWidgetItem(os.path.basename(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            preview = "(unread)"
            audio_obj = kind = None
            try:
                audio_obj, kind = _audio.load_audio(path)
                artist = _audio.get_field_value(audio_obj, kind, "artist")
                title = _audio.get_field_value(audio_obj, kind, "title")
                preview = f"{artist} - {title}" if artist or title else "(no tags)"
            except Exception as exc:
                preview = f"Failed: {exc}"
            item.setToolTip(f"{path}\n{preview}")
            self.list.addItem(item)
            self.rows.append({"path": path, "item": item, "audio": audio_obj, "kind": kind})
            added += 1
        self.count.setText(f"{len(self.rows)} files")
        if added:
            self.status.setText(f"Added {added} file(s).")

    def _clear(self):
        self.list.clear()
        self.rows.clear()
        self.cover_path = None
        self.count.setText("0 files")
        self.status.setText("List cleared.")

    def _check_all(self, on):
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for row in self.rows:
            row["item"].setCheckState(state)

    def _selected(self):
        return [
            row for row in self.rows
            if row["item"].checkState() == Qt.CheckState.Checked and row["audio"] is not None
        ]

    def _pick_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cover image", "", "Images (*.jpg *.jpeg *.png);;All files (*.*)")
        if path:
            self.cover_path = path
            self.status.setText(f"Cover queued: {os.path.basename(path)}")

    def _queue_strip(self):
        self.cover_path = ""
        self.status.setText("Cover removal queued.")

    def _apply(self):
        selected = self._selected()
        if not selected:
            self.status.setText("No files selected.")
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            return
        errors = []
        for i, row in enumerate(selected):
            try:
                for key, edit in self.edits.items():
                    value = edit.text().strip()
                    if value:
                        _audio.set_field_value(row["audio"], row["kind"], key, value)
                if self.auto_number.isChecked():
                    _audio.set_field_value(
                        row["audio"], row["kind"], "tracknumber",
                        str(self.track_start.value() + i),
                    )
                _audio.save_audio(row["audio"])
                if self.cover_path == "":
                    _audio.strip_cover(row["path"], row["kind"])
                elif self.cover_path:
                    _audio.embed_cover(row["path"], row["kind"], self.cover_path)
                row["audio"], row["kind"] = _audio.load_audio(row["path"])
            except Exception as exc:
                errors.append(f"{os.path.basename(row['path'])}: {exc}")
        self.cover_path = None
        if errors:
            self.status.setText(f"Applied with {len(errors)} error(s).")
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Batch audio", "Some files failed:\n\n" + "\n".join(errors))
        else:
            self.status.setText(f"Applied to {len(selected)} file(s).")
            self.status.setObjectName("Success")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class _ImageTab(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.path = None
        self.edits = {}
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        open_btn = QPushButton("Open image")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open)
        self.path_label = QLabel("No file loaded")
        self.path_label.setObjectName("Muted")
        top.addWidget(open_btn)
        top.addWidget(self.path_label, 1)
        root.addLayout(top)
        body = QHBoxLayout()
        form_host = QWidget()
        form = QFormLayout(form_host)
        for tag_id, label in _image.EXIF_FIELDS:
            edit = QLineEdit()
            self.edits[tag_id] = edit
            form.addRow(label, edit)
        note = QLabel("Only common top-level EXIF fields. GPS and maker notes are left alone.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        body.addWidget(form_host, 1)
        side = QVBoxLayout()
        self.preview = QLabel("No image")
        self.preview.setObjectName("Muted")
        self.preview.setFixedSize(180, 180)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        strip = QPushButton("Strip all EXIF")
        strip.setObjectName("Danger")
        strip.clicked.connect(self._strip)
        save = QPushButton("Save changes")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        reload_btn = QPushButton("Reload / discard")
        reload_btn.clicked.connect(lambda: self.path and self._load(self.path))
        side.addWidget(self.preview)
        side.addWidget(strip)
        side.addWidget(save)
        side.addWidget(reload_btn)
        side.addStretch(1)
        body.addLayout(side)
        root.addLayout(body, 1)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Image", "",
            "Images (*.jpg *.jpeg *.png *.tif *.tiff);;All files (*.*)",
        )
        if path:
            self._load(path)

    def _load(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext not in _image.IMAGE_EXTS:
            self.status.setText(f"Unsupported file type: {ext}")
            return
        try:
            self.path = path
            self.path_label.setText(os.path.basename(path))
            values = _image.read_exif(path)
            for tag_id, edit in self.edits.items():
                edit.setText(values.get(tag_id, ""))
            pix = QPixmap(path)
            self.preview.setText("")
            self.preview.setPixmap(pix.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.status.setText("Loaded successfully.")
            self.status.setObjectName("Muted")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Metadata Editor", f"Could not load file:\n{e}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _save(self):
        if not self.path:
            return
        try:
            _image.write_exif(self.path, {tag_id: edit.text() for tag_id, edit in self.edits.items()})
            self.status.setText("Saved successfully.")
            self.status.setObjectName("Success")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Metadata Editor", f"Could not save changes:\n{e}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _strip(self):
        if not self.path:
            return
        try:
            _image.strip_exif(self.path)
            for edit in self.edits.values():
                edit.clear()
            self.status.setText("EXIF data stripped.")
            self.status.setObjectName("Success")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class _StampTab(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.path = None
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        open_btn = QPushButton("Open file")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open)
        self.path_label = QLabel("No file loaded")
        self.path_label.setObjectName("Muted")
        top.addWidget(open_btn)
        top.addWidget(self.path_label, 1)
        root.addLayout(top)
        form = QFormLayout()
        self.created = QLineEdit()
        self.modified = QLineEdit()
        self.accessed = QLineEdit()
        form.addRow("Created", self.created)
        form.addRow("Modified", self.modified)
        form.addRow("Accessed", self.accessed)
        note = QLabel(_time.creation_note())
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        if not _time.creation_editable():
            self.created.setEnabled(False)
        root.addLayout(form)
        row = QHBoxLayout()
        now = QPushButton("Set to now")
        now.clicked.connect(self._set_now)
        save = QPushButton("Save changes")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        reload_btn = QPushButton("Reload / discard")
        reload_btn.clicked.connect(lambda: self.path and self._load(self.path))
        row.addWidget(now)
        row.addWidget(save)
        row.addWidget(reload_btn)
        row.addStretch(1)
        root.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)
        root.addStretch(1)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            self._load(path)

    def _load(self, path):
        try:
            times = _time.read_times(path)
            self.path = path
            self.path_label.setText(os.path.basename(path))
            self.created.setText(times["Created"])
            self.modified.setText(times["Modified"])
            self.accessed.setText(times["Accessed"])
            self.status.setText("Loaded successfully.")
            self.status.setObjectName("Muted")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Metadata Editor", f"Could not load file:\n{e}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _set_now(self):
        import datetime
        now = datetime.datetime.now().strftime(_time.DATE_FMT)
        self.modified.setText(now)
        self.accessed.setText(now)
        if self.created.isEnabled():
            self.created.setText(now)

    def _save(self):
        if not self.path:
            return
        try:
            created = self.created.text() if self.created.isEnabled() else None
            _time.write_times(self.path, self.modified.text(), self.accessed.text(), created)
            self.status.setText("Saved successfully.")
            self.status.setObjectName("Success")
        except ValueError:
            self.status.setText(f"Dates must match format: {_time.DATE_FMT}")
            self.status.setObjectName("Danger")
        except Exception as e:
            self.status.setText(str(e))
            self.status.setObjectName("Danger")
            QMessageBox.warning(self, "Metadata Editor", f"Could not save changes:\n{e}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
