"""Qt Color Picker — hex/RGB/HSV, screen eyedropper, harmony swatches."""

from __future__ import annotations

import importlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

color_utils = importlib.import_module("modules.Design.Color Picker.color_utils")

DEFAULT_HEX = "#4d8fe0"


class _EyedropperOverlay(QWidget):
    def __init__(self, on_pick):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._on_pick = on_pick
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        screen = QGuiApplication.primaryScreen()
        self._grab = screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self._hover = None
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._grab)
        if self._hover is None:
            return
        x, y, hex_color = self._hover
        painter.fillRect(x + 18, y + 18, 110, 28, Qt.GlobalColor.white)
        painter.fillRect(x + 20, y + 20, 24, 24, QColor(hex_color))
        painter.drawText(x + 48, y + 38, hex_color)

    def _sample(self, pos):
        img = self._grab.toImage()
        x = max(0, min(img.width() - 1, pos.x()))
        y = max(0, min(img.height() - 1, pos.y()))
        c = img.pixelColor(x, y)
        return x, y, f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

    def mouseMoveEvent(self, event):
        self._hover = self._sample(event.position().toPoint())
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            _x, _y, hex_color = self._sample(event.position().toPoint())
            self.close()
            self._on_pick(hex_color)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()


class ColorPickerModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._updating = False
        self._rgb = color_utils.hex_to_rgb(DEFAULT_HEX)
        self._overlay = None

        root = QHBoxLayout(self)
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        title = QLabel("Color Picker")
        title.setObjectName("AccentTitle")
        ll.addWidget(title)

        self.preview = QFrame()
        self.preview.setMinimumHeight(90)
        ll.addWidget(self.preview)

        hex_row = QHBoxLayout()
        self.hex_edit = QLineEdit(DEFAULT_HEX)
        self.hex_edit.editingFinished.connect(self._on_hex)
        pick = QPushButton("Eyedropper")
        pick.setObjectName("Primary")
        pick.clicked.connect(self._start_eyedropper)
        hex_row.addWidget(self.hex_edit, 1)
        hex_row.addWidget(pick)
        ll.addLayout(hex_row)

        self.error = QLabel("")
        self.error.setObjectName("Danger")
        self.error.setWordWrap(True)
        ll.addWidget(self.error)

        rgb_lab = QLabel("RGB")
        rgb_lab.setObjectName("CardTitle")
        ll.addWidget(rgb_lab)
        self.r = self._channel(ll, "R", 0, 255, self._on_rgb)
        self.g = self._channel(ll, "G", 0, 255, self._on_rgb)
        self.b = self._channel(ll, "B", 0, 255, self._on_rgb)

        hsv_lab = QLabel("HSV")
        hsv_lab.setObjectName("CardTitle")
        ll.addWidget(hsv_lab)
        self.h = self._channel(ll, "H", 0, 360, self._on_hsv)
        self.s = self._channel(ll, "S", 0, 100, self._on_hsv)
        self.v = self._channel(ll, "V", 0, 100, self._on_hsv)

        copies = QHBoxLayout()
        copy_hex = QPushButton("Copy HEX")
        copy_hex.setObjectName("Primary")
        copy_hex.clicked.connect(lambda: self._copy(self.hex_edit.text()))
        copy_rgb = QPushButton("Copy RGB")
        copy_rgb.clicked.connect(self._copy_rgb)
        copies.addWidget(copy_hex)
        copies.addWidget(copy_rgb)
        ll.addLayout(copies)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        ll.addWidget(self.status)
        ll.addStretch(1)

        right = QFrame()
        right.setObjectName("Panel")
        rl = QVBoxLayout(right)
        scheme_row = QHBoxLayout()
        pal_lab = QLabel("Palette")
        pal_lab.setObjectName("Muted")
        self.scheme = QComboBox()
        self.scheme.addItems(color_utils.HARMONY_SCHEMES)
        self.scheme.currentTextChanged.connect(self._refresh_palette)
        scheme_row.addWidget(pal_lab)
        scheme_row.addWidget(self.scheme, 1)
        rl.addLayout(scheme_row)
        self.swatch_host = QWidget()
        self.swatch_lay = QHBoxLayout(self.swatch_host)
        self.swatch_lay.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.swatch_host)
        rl.addStretch(1)

        root.addWidget(left, 0)
        root.addWidget(right, 1)
        self._apply_rgb(*self._rgb, source=None)

    def _channel(self, layout, name, lo, hi, callback):
        row = QHBoxLayout()
        lab = QLabel(name)
        lab.setObjectName("Muted")
        lab.setFixedWidth(16)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        spin.valueChanged.connect(lambda v: self._sync_pair(slider, spin, v, callback))
        slider.valueChanged.connect(lambda v: self._sync_pair(spin, slider, v, callback))
        row.addWidget(lab)
        row.addWidget(slider, 1)
        row.addWidget(spin)
        layout.addLayout(row)
        return spin, slider

    def _sync_pair(self, other, source, value, callback):
        if other.value() != value:
            other.blockSignals(True)
            other.setValue(value)
            other.blockSignals(False)
        callback()

    def _set_pair(self, pair, value):
        spin, slider = pair
        value = int(round(value))
        spin.blockSignals(True)
        slider.blockSignals(True)
        spin.setValue(value)
        slider.setValue(value)
        spin.blockSignals(False)
        slider.blockSignals(False)

    def _apply_rgb(self, r, g, b, *, source):
        self._updating = True
        try:
            r, g, b = (max(0, min(255, int(round(c)))) for c in (r, g, b))
            self._rgb = (r, g, b)
            hex_color = color_utils.rgb_to_hex(r, g, b)
            h, s, v = color_utils.rgb_to_hsv(r, g, b)
            self.preview.setStyleSheet(f"background:{hex_color}; border-radius:8px;")
            if source != "hex":
                self.hex_edit.setText(hex_color)
            if source != "rgb":
                self._set_pair(self.r, r)
                self._set_pair(self.g, g)
                self._set_pair(self.b, b)
            if source != "hsv":
                self._set_pair(self.h, h)
                self._set_pair(self.s, s)
                self._set_pair(self.v, v)
            self.error.setText("")
        finally:
            self._updating = False
        self._refresh_palette()

    def _on_hex(self):
        if self._updating:
            return
        try:
            normalized = color_utils.normalize_hex(self.hex_edit.text())
        except color_utils.InvalidColorError as exc:
            self.error.setText(str(exc))
            return
        self._apply_rgb(*color_utils.hex_to_rgb(normalized), source="hex")

    def _on_rgb(self):
        if self._updating:
            return
        self._apply_rgb(self.r[0].value(), self.g[0].value(), self.b[0].value(), source="rgb")

    def _on_hsv(self):
        if self._updating:
            return
        rgb = color_utils.hsv_to_rgb(self.h[0].value(), self.s[0].value(), self.v[0].value())
        self._apply_rgb(*rgb, source="hsv")

    def _clear_swatches(self):
        while self.swatch_lay.count():
            item = self.swatch_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh_palette(self, *_args):
        self._clear_swatches()
        hex_color = color_utils.rgb_to_hex(*self._rgb)
        try:
            swatches = color_utils.harmony_palette(hex_color, self.scheme.currentText())
        except color_utils.InvalidColorError:
            return
        for swatch_hex in swatches:
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(4, 4, 4, 4)
            swatch = QPushButton("")
            swatch.setFixedSize(64, 64)
            swatch.setStyleSheet(f"background:{swatch_hex}; border-radius:8px;")
            swatch.clicked.connect(
                lambda _=False, hx=swatch_hex: self._apply_rgb(
                    *color_utils.hex_to_rgb(hx), source=None
                )
            )
            copy = QPushButton(swatch_hex)
            copy.clicked.connect(lambda _=False, hx=swatch_hex: self._copy(hx))
            cl.addWidget(swatch)
            cl.addWidget(copy)
            self.swatch_lay.addWidget(cell)
        self.swatch_lay.addStretch(1)

    def _start_eyedropper(self):
        try:
            self._overlay = _EyedropperOverlay(
                lambda hx: self._apply_rgb(*color_utils.hex_to_rgb(hx), source=None)
            )
        except Exception as exc:
            QMessageBox.warning(self, "Eyedropper", f"Couldn't capture the screen: {exc}")

    def _copy_rgb(self):
        r, g, b = self._rgb
        self._copy(f"rgb({r}, {g}, {b})")

    def _copy(self, text):
        QApplication.clipboard().setText(text)
        self.status.setText(f"Copied {text}")
