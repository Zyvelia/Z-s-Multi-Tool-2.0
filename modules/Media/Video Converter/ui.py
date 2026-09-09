"""Qt Video to GIF converter — ffmpeg two-pass with progress."""

from __future__ import annotations

import importlib
import os
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

_converter = importlib.import_module("modules.Media.Video Converter.converter")


class Mp4ToGifPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.input_path = None
        self.last_output = None
        self.cancel_event = None
        self.converting = False

        root = QVBoxLayout(self)
        title = QLabel("Video to GIF")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        hint = QLabel("Pick a video, set FPS / width / loop, then convert. Uses ffmpeg two-pass palettes.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.setAcceptDrops(True)
        drop = QLabel("Drop a video here, or pick one.")
        drop.setObjectName("Muted")
        drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop.setMinimumHeight(56)
        root.addWidget(drop)

        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("Muted")
        browse = QPushButton("Pick video")
        browse.setObjectName("Primary")
        browse.clicked.connect(self._pick)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(browse)
        root.addLayout(file_row)

        form = QFormLayout()
        self.fps = QSpinBox()
        self.fps.setRange(4, 30)
        self.fps.setValue(15)
        self.width = QSpinBox()
        self.width.setRange(80, 1920)
        self.width.setValue(480)
        self.loop = QCheckBox("Loop GIF")
        self.loop.setChecked(True)
        self.fit_box = QCheckBox("Fit inside a box (max height)")
        self.max_height = QSpinBox()
        self.max_height.setRange(80, 1920)
        self.max_height.setValue(320)
        self.max_height.setEnabled(False)
        self.fit_box.toggled.connect(self.max_height.setEnabled)
        self.compress = QCheckBox("Compress to under")
        self.target_mb = QDoubleSpinBox()
        self.target_mb.setRange(0.5, 200)
        self.target_mb.setValue(10)
        self.target_mb.setSuffix(" MB")
        self.target_mb.setEnabled(False)
        self.compress.toggled.connect(self.target_mb.setEnabled)
        form.addRow("FPS", self.fps)
        form.addRow("Width", self.width)
        form.addRow("", self.loop)
        form.addRow("", self.fit_box)
        form.addRow("Max height", self.max_height)
        form.addRow("", self.compress)
        form.addRow("Target size", self.target_mb)
        root.addLayout(form)

        out_row = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setPlaceholderText("Output path (defaults next to the video)")
        out_browse = QPushButton("Browse")
        out_browse.clicked.connect(self._pick_out)
        out_row.addWidget(self.output, 1)
        out_row.addWidget(out_browse)
        root.addLayout(out_row)

        btns = QHBoxLayout()
        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.clicked.connect(self._convert)
        self.open_btn = QPushButton("Open output")
        self.open_btn.clicked.connect(self._open_out)
        self.open_btn.setEnabled(False)
        btns.addWidget(self.convert_btn)
        btns.addWidget(self.open_btn)
        btns.addStretch(1)
        root.addLayout(btns)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)
        root.addStretch(1)

        if not _converter.find_ffmpeg():
            self.status.setText("ffmpeg not found — put it on PATH or in the module bin folder.")
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.splitext(path)[1].lower() in VIDEO_EXTS:
                self._set_input(path)
                return

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Video", "",
            "Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All files (*.*)",
        )
        if path:
            self._set_input(path)

    def _set_input(self, path):
        self.input_path = path
        self.file_label.setText(os.path.basename(path))
        base, _ = os.path.splitext(path)
        if not self.output.text().strip():
            self.output.setText(base + ".gif")

        def work():
            info = _converter.probe(path)
            QTimer.singleShot(0, lambda: self._show_probe(info))

        threading.Thread(target=work, daemon=True).start()

    def _show_probe(self, info):
        bits = []
        if info.get("width") and info.get("height"):
            bits.append(f"{info['width']}×{info['height']}")
        if info.get("duration"):
            bits.append(f"{info['duration']:.1f}s")
        self.status.setText(" · ".join(bits) if bits else "")

    def _pick_out(self):
        path, _ = QFileDialog.getSaveFileName(self, "GIF output", self.output.text() or "", "GIF (*.gif)")
        if path:
            self.output.setText(path)

    def _convert(self):
        if self.converting:
            return
        if not self.input_path:
            QMessageBox.information(self, "GIF", "Pick a video first.")
            return
        out = self.output.text().strip()
        if not out:
            base, _ = os.path.splitext(self.input_path)
            out = base + ".gif"
            self.output.setText(out)
        self.converting = True
        self.convert_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Converting…")
        cancel = threading.Event()
        self.cancel_event = cancel
        fps = self.fps.value()
        width = self.width.value()
        loop = self.loop.isChecked()
        max_height = self.max_height.value() if self.fit_box.isChecked() else None
        compress = self.compress.isChecked()
        target_mb = self.target_mb.value()
        src = self.input_path

        def on_progress(frac):
            pct = int(frac * 100)
            QTimer.singleShot(0, lambda p=pct: self.progress.setValue(p))

        def on_attempt(n, a_fps, a_width, colors):
            QTimer.singleShot(0, lambda: self.status.setText(
                f"Attempt {n}: {a_width}px · {a_fps} fps · {colors} colors"
            ))

        def work():
            try:
                if compress:
                    _path, size, attempts, met = _converter.convert_within_size(
                        src, out, max_size_mb=target_mb, fps=fps, width=width,
                        max_height=max_height, loop=loop, on_progress=on_progress,
                        on_attempt=on_attempt, cancel_event=cancel,
                    )
                    mb = size / (1024 * 1024)
                    msg = (
                        f"Done — {mb:.1f} MB in {attempts} attempt(s)"
                        if met else
                        f"Still {mb:.1f} MB after {attempts} attempt(s)"
                    )
                    QTimer.singleShot(0, lambda m=msg, p=out: self._done(m, p))
                    return
                _converter.convert(
                    src, out, fps=fps, width=width, max_height=max_height,
                    loop=loop, on_progress=on_progress, cancel_event=cancel,
                )
            except _converter.ConversionCancelled:
                QTimer.singleShot(0, lambda: self._done("Cancelled", None))
                return
            except _converter.ConversionError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self._done(m, None))
                return
            except Exception as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self._done(m, None))
                return
            QTimer.singleShot(0, lambda p=out: self._done("Done", p))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, msg, out):
        self.converting = False
        self.convert_btn.setEnabled(True)
        self.status.setText(msg)
        if out:
            self.last_output = out
            self.progress.setValue(100)
            self.open_btn.setEnabled(True)
            self.status.setObjectName("Success")
        else:
            self.status.setObjectName("Danger" if msg != "Cancelled" else "Muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _open_out(self):
        path = self.last_output
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.warning(self, "Open", str(e))
