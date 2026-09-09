"""Qt Image Palette Extractor — dominant colors as copyable swatches."""

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
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

palette_math = importlib.import_module("modules.Design.Image Palette Extractor.palette_math")

PREVIEW_MAX = 320


def _pil_to_pixmap(image) -> QPixmap:
    raw = BytesIO()
    image.save(raw, format="PNG")
    buf = QBuffer()
    buf.setData(raw.getvalue())
    pix = QPixmap()
    pix.loadFromData(buf.data())
    return pix


class ImagePaletteExtractorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.image_path = None
        self._palette = []

        root = QHBoxLayout(self)
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        title = QLabel("Image Palette Extractor")
        title.setObjectName("AccentTitle")
        ll.addWidget(title)

        self.preview = QLabel("No image loaded")
        self.preview.setObjectName("Muted")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(PREVIEW_MAX)
        ll.addWidget(self.preview)

        choose = QPushButton("Choose image…")
        choose.setObjectName("Primary")
        choose.clicked.connect(self._choose_image)
        ll.addWidget(choose)
        self.file_label = QLabel("")
        self.file_label.setObjectName("Muted")
        self.file_label.setWordWrap(True)
        ll.addWidget(self.file_label)

        count_row = QHBoxLayout()
        colors_lab = QLabel("Colors")
        colors_lab.setObjectName("Muted")
        self.count_slider = QSlider(Qt.Orientation.Horizontal)
        self.count_slider.setRange(2, 16)
        self.count_slider.setValue(6)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(2, 16)
        self.count_spin.setValue(6)
        self.count_slider.valueChanged.connect(self.count_spin.setValue)
        self.count_spin.valueChanged.connect(self.count_slider.setValue)
        count_row.addWidget(colors_lab)
        count_row.addWidget(self.count_slider, 1)
        count_row.addWidget(self.count_spin)
        ll.addLayout(count_row)

        self.extract_btn = QPushButton("Extract palette")
        self.extract_btn.setObjectName("Primary")
        self.extract_btn.setEnabled(False)
        self.extract_btn.clicked.connect(self._extract)
        ll.addWidget(self.extract_btn)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        ll.addWidget(self.status)
        ll.addStretch(1)

        right = QFrame()
        right.setObjectName("Panel")
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        pal_lab = QLabel("Extracted palette")
        pal_lab.setObjectName("CardTitle")
        self.copy_all = QPushButton("Copy all hex")
        self.copy_all.setEnabled(False)
        self.copy_all.clicked.connect(self._copy_all)
        top.addWidget(pal_lab)
        top.addStretch(1)
        top.addWidget(self.copy_all)
        rl.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        scroll.setWidget(self.list_host)
        rl.addWidget(scroll, 1)
        self._render_empty()

        root.addWidget(left, 0)
        root.addWidget(right, 1)

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose an image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff);;All files (*.*)",
        )
        if not path:
            return
        try:
            img = Image.open(path)
            img.verify()
            img = Image.open(path).convert("RGB")
        except Exception as exc:
            QMessageBox.warning(self, "Image Palette Extractor", f"Couldn't open that image:\n{exc}")
            return
        self.image_path = path
        self.file_label.setText(os.path.basename(path))
        self.extract_btn.setEnabled(True)
        self.status.setText("")
        thumb = img.copy()
        thumb.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
        self.preview.setPixmap(_pil_to_pixmap(thumb))
        self.preview.setObjectName("")

    def _extract(self):
        if not self.image_path:
            return
        self.extract_btn.setEnabled(False)
        self.extract_btn.setText("Extracting…")
        self.status.setText("Extracting palette…")
        path = self.image_path
        n_colors = self.count_spin.value()

        def worker():
            try:
                palette = palette_math.extract_palette(path, n_colors)
                error = None
            except palette_math.PaletteError as exc:
                palette = None
                error = str(exc)
            QTimer.singleShot(0, lambda: self._on_extracted(palette, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_extracted(self, palette, error):
        self.extract_btn.setEnabled(True)
        self.extract_btn.setText("Extract palette")
        if error:
            self.status.setText(error)
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            return
        self._palette = palette or []
        self.status.setObjectName("Muted")
        self.status.setText(f"{len(self._palette)} colors extracted")
        self.copy_all.setEnabled(bool(self._palette))
        self._render_palette()

    def _clear_list(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_empty(self):
        self._clear_list()
        empty = QLabel("Choose an image and hit Extract palette to see its colors here.")
        empty.setObjectName("Muted")
        empty.setWordWrap(True)
        self.list_lay.addWidget(empty)
        self.list_lay.addStretch(1)

    def _render_palette(self):
        self._clear_list()
        if not self._palette:
            self._render_empty()
            return
        for swatch in self._palette:
            hex_color = swatch["hex"]
            r, g, b = swatch["rgb"]
            rgb_text = f"rgb({r}, {g}, {b})"
            text_color = palette_math.readable_text_color(r, g, b)
            card = QFrame()
            card.setObjectName("Panel")
            card.setStyleSheet(f"background:{hex_color}; border-radius:8px;")
            cl = QHBoxLayout(card)
            info = QVBoxLayout()
            title = QLabel(f"{hex_color}   {rgb_text}")
            title.setStyleSheet(f"color:{text_color};")
            pct = QLabel(f"{swatch['percent']}% of image")
            pct.setStyleSheet(f"color:{text_color};")
            info.addWidget(title)
            info.addWidget(pct)
            cl.addLayout(info, 1)
            copy_hex = QPushButton("Copy HEX")
            copy_hex.clicked.connect(lambda _=False, t=hex_color: self._copy(t))
            copy_rgb = QPushButton("Copy RGB")
            copy_rgb.clicked.connect(lambda _=False, t=rgb_text: self._copy(t))
            btns = QVBoxLayout()
            btns.addWidget(copy_hex)
            btns.addWidget(copy_rgb)
            cl.addLayout(btns)
            self.list_lay.addWidget(card)
        self.list_lay.addStretch(1)

    def _copy(self, text):
        QApplication.clipboard().setText(text)
        self.status.setText(f"Copied {text}")
        self.status.setObjectName("Muted")

    def _copy_all(self):
        if not self._palette:
            return
        self._copy(", ".join(s["hex"] for s in self._palette))
