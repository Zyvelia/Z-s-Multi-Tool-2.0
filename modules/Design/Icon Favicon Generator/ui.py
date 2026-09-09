"""Qt Icon/Favicon Generator — load image, fit/fill, generate icon set."""

from __future__ import annotations

import importlib
import os
import threading

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

generator = importlib.import_module("modules.Design.Icon Favicon Generator.generator")

PREVIEW_MAX = 220


def _pil_to_pixmap(image) -> QPixmap:
    raw = BytesIO()
    image.save(raw, format="PNG")
    buf = QBuffer()
    buf.setData(raw.getvalue())
    pix = QPixmap()
    pix.loadFromData(buf.data())
    return pix


def _open_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        os.startfile(path)
    except Exception as exc:
        QMessageBox.warning(None, "Couldn't open folder", str(exc))


class IconFaviconGeneratorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.source_path = None
        self.output_dir = None
        self._last_written = []

        root = QHBoxLayout(self)
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        title = QLabel("Icon / Favicon Generator")
        title.setObjectName("AccentTitle")
        ll.addWidget(title)

        self.preview = QLabel("No image loaded")
        self.preview.setObjectName("Muted")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(PREVIEW_MAX)
        ll.addWidget(self.preview)

        choose = QPushButton("Choose source image…")
        choose.setObjectName("Primary")
        choose.clicked.connect(self._choose_source)
        ll.addWidget(choose)
        self.source_label = QLabel("")
        self.source_label.setObjectName("Muted")
        self.source_label.setWordWrap(True)
        ll.addWidget(self.source_label)

        fit_lab = QLabel("Non-square images")
        fit_lab.setObjectName("CardTitle")
        ll.addWidget(fit_lab)
        self.fit_radio = QRadioButton("Fit (pad with transparency)")
        self.fill_radio = QRadioButton("Fill (crop to square)")
        self.fit_radio.setChecked(True)
        ll.addWidget(self.fit_radio)
        ll.addWidget(self.fill_radio)

        out_lab = QLabel("Outputs")
        out_lab.setObjectName("CardTitle")
        ll.addWidget(out_lab)
        self.make_png = QCheckBox("PNG set (16 to 512px, incl. apple-touch-icon)")
        self.make_ico = QCheckBox("favicon.ico (16/32/48px multi-size)")
        self.make_manifest = QCheckBox("site.webmanifest")
        self.make_png.setChecked(True)
        self.make_ico.setChecked(True)
        self.make_manifest.setChecked(True)
        ll.addWidget(self.make_png)
        ll.addWidget(self.make_ico)
        ll.addWidget(self.make_manifest)

        self.app_name = QLineEdit()
        self.app_name.setPlaceholderText("App name (used in manifest)")
        ll.addWidget(self.app_name)

        out_btn = QPushButton("Choose output folder…")
        out_btn.clicked.connect(self._choose_output)
        ll.addWidget(out_btn)
        self.output_label = QLabel("")
        self.output_label.setObjectName("Muted")
        self.output_label.setWordWrap(True)
        ll.addWidget(self.output_label)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setObjectName("Primary")
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._generate)
        ll.addWidget(self.generate_btn)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        ll.addWidget(self.status)
        ll.addStretch(1)

        right = QFrame()
        right.setObjectName("Panel")
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        gen_lab = QLabel("Generated files")
        gen_lab.setObjectName("CardTitle")
        self.open_btn = QPushButton("Open folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: _open_folder(self.output_dir) if self.output_dir else None)
        top.addWidget(gen_lab)
        top.addStretch(1)
        top.addWidget(self.open_btn)
        rl.addLayout(top)
        self.results = QLabel("Choose a source image and an output folder, then hit Generate.")
        self.results.setObjectName("Muted")
        self.results.setWordWrap(True)
        rl.addWidget(self.results)
        snippet_lab = QLabel("HTML <head> snippet")
        snippet_lab.setObjectName("Muted")
        rl.addWidget(snippet_lab)
        self.snippet = QPlainTextEdit(generator.HTML_SNIPPET)
        self.snippet.setReadOnly(True)
        self.snippet.setMaximumHeight(130)
        rl.addWidget(self.snippet)
        copy_snip = QPushButton("Copy snippet")
        copy_snip.clicked.connect(self._copy_snippet)
        rl.addWidget(copy_snip, alignment=Qt.AlignmentFlag.AlignRight)
        rl.addStretch(1)

        root.addWidget(left, 0)
        root.addWidget(right, 1)

    def _update_ready(self):
        self.generate_btn.setEnabled(bool(self.source_path and self.output_dir))

    def _choose_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a source image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff);;All files (*.*)",
        )
        if not path:
            return
        try:
            img = Image.open(path)
            img.verify()
            img = Image.open(path).convert("RGBA")
        except Exception as exc:
            QMessageBox.warning(self, "Icon/Favicon Generator", f"Couldn't open that image:\n{exc}")
            return
        self.source_path = path
        self.source_label.setText(os.path.basename(path))
        self._update_ready()
        self.status.setText("")
        thumb = img.copy()
        thumb.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        self.preview.setPixmap(_pil_to_pixmap(thumb))
        self.preview.setObjectName("")

    def _choose_output(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not chosen:
            return
        self.output_dir = chosen
        self.output_label.setText(chosen)
        self._update_ready()

    def _generate(self):
        if not (self.source_path and self.output_dir):
            return
        if not (self.make_png.isChecked() or self.make_ico.isChecked() or self.make_manifest.isChecked()):
            self.status.setText("Pick at least one output.")
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            return
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generating…")
        self.status.setObjectName("Muted")
        self.status.setText("Generating…")
        source_path = self.source_path
        output_dir = self.output_dir
        fit_mode = "fill" if self.fill_radio.isChecked() else "fit"
        make_png = self.make_png.isChecked()
        make_ico = self.make_ico.isChecked()
        make_manifest = self.make_manifest.isChecked()
        app_name = self.app_name.text().strip() or "App"

        def worker():
            try:
                written = generator.generate(
                    source_path,
                    output_dir,
                    fit_mode=fit_mode,
                    make_png=make_png,
                    make_ico=make_ico,
                    make_manifest=make_manifest,
                    app_name=app_name,
                )
                error = None
            except generator.IconGeneratorError as exc:
                written = None
                error = str(exc)
            QTimer.singleShot(0, lambda: self._on_generated(written, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_generated(self, written, error):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Generate")
        if error:
            self.status.setText(error)
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            return
        self._last_written = written or []
        self.status.setText(f"Generated {len(self._last_written)} file(s).")
        self.status.setObjectName("Success")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.open_btn.setEnabled(True)
        if not self._last_written:
            self.results.setText("Choose a source image and an output folder, then hit Generate.")
            return
        lines = []
        for path in self._last_written:
            size_kb = os.path.getsize(path) / 1024
            lines.append(f"{os.path.basename(path)}  ({size_kb:.1f} KB)")
        self.results.setText("\n".join(lines))
        self.results.setObjectName("")

    def _copy_snippet(self):
        QApplication.clipboard().setText(generator.HTML_SNIPPET)
        self.status.setText("Snippet copied.")
        self.status.setObjectName("Muted")
