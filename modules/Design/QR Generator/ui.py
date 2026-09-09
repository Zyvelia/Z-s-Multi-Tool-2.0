"""Qt QR Generator — type fields, live preview, save PNG, copy payload."""

from __future__ import annotations

import importlib

from io import BytesIO

from PySide6.QtCore import QBuffer, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

qr_builder = importlib.import_module("modules.Design.QR Generator.qr_builder")

PREVIEW_SIZE = 320


def _pil_to_pixmap(image) -> QPixmap:
    raw = BytesIO()
    image.save(raw, format="PNG")
    buf = QBuffer()
    buf.setData(raw.getvalue())
    pix = QPixmap()
    pix.loadFromData(buf.data())
    return pix


class QRGeneratorModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._current_image = None
        self._current_payload = ""
        self._fields = {}
        self._regen = QTimer(self)
        self._regen.setSingleShot(True)
        self._regen.setInterval(300)
        self._regen.timeout.connect(self._regenerate)

        root = QHBoxLayout(self)
        left = QFrame()
        left.setObjectName("Panel")
        ll = QVBoxLayout(left)
        title = QLabel("QR Code Generator")
        title.setObjectName("AccentTitle")
        ll.addWidget(title)

        type_lab = QLabel("Type")
        type_lab.setObjectName("Muted")
        ll.addWidget(type_lab)
        self.type_combo = QComboBox()
        self.type_combo.addItems(qr_builder.QR_TYPES)
        self.type_combo.currentTextChanged.connect(self._rebuild_type_fields)
        ll.addWidget(self.type_combo)

        self.fields_host = QWidget()
        self.fields_lay = QVBoxLayout(self.fields_host)
        self.fields_lay.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.fields_host)

        ec_lab = QLabel("Error Correction")
        ec_lab.setObjectName("Muted")
        ll.addWidget(ec_lab)
        self.ec_combo = QComboBox()
        self.ec_combo.addItems(list(qr_builder.ERROR_CORRECTION_LEVELS.keys()))
        self.ec_combo.setCurrentText(qr_builder.DEFAULT_ERROR_CORRECTION)
        self.ec_combo.currentTextChanged.connect(self._schedule)
        ll.addWidget(self.ec_combo)

        colors = QFormLayout()
        self.fg_edit = QLineEdit("#000000")
        self.bg_edit = QLineEdit("#ffffff")
        self.fg_edit.textChanged.connect(self._schedule)
        self.bg_edit.textChanged.connect(self._schedule)
        colors.addRow("Foreground", self.fg_edit)
        colors.addRow("Background", self.bg_edit)
        ll.addLayout(colors)

        self.error = QLabel("")
        self.error.setObjectName("Danger")
        self.error.setWordWrap(True)
        ll.addWidget(self.error)
        ll.addStretch(1)

        right = QFrame()
        right.setObjectName("Panel")
        rl = QVBoxLayout(right)
        self.preview = QLabel("Enter a value to preview")
        self.preview.setObjectName("Muted")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        rl.addWidget(self.preview, 1)

        btns = QHBoxLayout()
        save = QPushButton("Save PNG")
        save.setObjectName("Primary")
        save.clicked.connect(self._save_png)
        copy = QPushButton("Copy payload")
        copy.clicked.connect(self._copy_payload)
        btns.addWidget(save)
        btns.addWidget(copy)
        btns.addStretch(1)
        rl.addLayout(btns)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        rl.addWidget(self.status)

        root.addWidget(left, 0)
        root.addWidget(right, 1)
        self._rebuild_type_fields()

    def _clear_fields(self):
        while self.fields_lay.count():
            item = self.fields_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._fields = {}

    def _add_line(self, key, label, *, password=False, multiline=False):
        cap = QLabel(label)
        cap.setObjectName("Muted")
        self.fields_lay.addWidget(cap)
        if multiline:
            w = QPlainTextEdit()
            w.setMaximumHeight(80)
            w.textChanged.connect(self._schedule)
        else:
            w = QLineEdit()
            if password:
                w.setEchoMode(QLineEdit.EchoMode.Password)
            w.textChanged.connect(self._schedule)
        self.fields_lay.addWidget(w)
        self._fields[key] = w
        return w

    def _field_text(self, key):
        w = self._fields[key]
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        return w.text()

    def _rebuild_type_fields(self, _text=None):
        self._clear_fields()
        qr_type = self.type_combo.currentText()
        if qr_type == "Text / URL":
            self._add_line("text", "Text or URL", multiline=True)
        elif qr_type == "Wi-Fi Network":
            self._add_line("ssid", "Network Name (SSID)")
            self._add_line("password", "Password", password=True)
            cap = QLabel("Security")
            cap.setObjectName("Muted")
            self.fields_lay.addWidget(cap)
            sec = QComboBox()
            sec.addItems(qr_builder.WIFI_SECURITY_TYPES)
            sec.currentTextChanged.connect(self._schedule)
            self.fields_lay.addWidget(sec)
            self._fields["security"] = sec
            hidden = QCheckBox("Hidden network")
            hidden.toggled.connect(self._schedule)
            self.fields_lay.addWidget(hidden)
            self._fields["hidden"] = hidden
        elif qr_type == "Email":
            self._add_line("address", "Email Address")
            self._add_line("subject", "Subject (optional)")
            self._add_line("body", "Body (optional)", multiline=True)
        elif qr_type == "Phone Number":
            self._add_line("phone", "Phone Number")
        elif qr_type == "SMS":
            self._add_line("number", "Phone Number")
            self._add_line("message", "Message (optional)", multiline=True)
        self._schedule()

    def _schedule(self, *_args):
        self._regen.start()

    def _build_payload(self):
        qr_type = self.type_combo.currentText()
        v = self._field_text
        if qr_type == "Text / URL":
            return qr_builder.build_payload(qr_type, text=v("text"))
        if qr_type == "Wi-Fi Network":
            return qr_builder.build_payload(
                qr_type,
                wifi=qr_builder.WifiFields(
                    ssid=v("ssid"),
                    password=v("password"),
                    security=v("security"),
                    hidden=bool(v("hidden")),
                ),
            )
        if qr_type == "Email":
            return qr_builder.build_payload(
                qr_type,
                email=qr_builder.EmailFields(
                    address=v("address"),
                    subject=v("subject"),
                    body=v("body"),
                ),
            )
        if qr_type == "Phone Number":
            return qr_builder.build_payload(qr_type, phone=v("phone"))
        if qr_type == "SMS":
            return qr_builder.build_payload(
                qr_type,
                sms=qr_builder.SmsFields(number=v("number"), message=v("message")),
            )
        return qr_builder.build_payload(qr_type)

    def _regenerate(self):
        self.error.setText("")
        try:
            payload = self._build_payload()
        except qr_builder.QRBuildError as exc:
            self._placeholder(str(exc))
            return
        fg = self.fg_edit.text().strip() or "#000000"
        bg = self.bg_edit.text().strip() or "#ffffff"
        for value, name in ((fg, "Foreground"), (bg, "Background")):
            if not (value.startswith("#") and len(value) in (4, 7)):
                self.error.setText(f"{name} color must be a hex code like #000000.")
                return
        try:
            img = qr_builder.generate_image(
                payload,
                error_correction=self.ec_combo.currentText(),
                fill_color=fg,
                back_color=bg,
            )
        except qr_builder.QRBuildError as exc:
            self._placeholder(str(exc))
            return
        except Exception as exc:
            self.error.setText(f"Couldn't generate QR code: {exc}")
            return
        self._current_image = img
        self._current_payload = payload
        display = img.copy()
        display.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
        pix = _pil_to_pixmap(display)
        self.preview.setPixmap(pix)
        self.preview.setObjectName("")
        self.status.setText(f"{len(payload)} character(s) encoded")

    def _placeholder(self, message):
        self._current_image = None
        self._current_payload = ""
        self.preview.clear()
        self.preview.setText(message)
        self.preview.setObjectName("Muted")
        self.status.setText("")

    def _save_png(self):
        if self._current_image is None:
            self.status.setText("Nothing to save yet — fix the fields first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save QR Code", "qrcode.png", "PNG image (*.png)"
        )
        if not path:
            return
        try:
            self._current_image.save(path)
            self.status.setText(f"Saved to {path}")
        except Exception as exc:
            self.status.setText(f"Couldn't save: {exc}")

    def _copy_payload(self):
        if not self._current_payload:
            self.status.setText("Nothing to copy yet — fix the fields first.")
            return
        QApplication.clipboard().setText(self._current_payload)
        self.status.setText("Encoded text copied to clipboard")
