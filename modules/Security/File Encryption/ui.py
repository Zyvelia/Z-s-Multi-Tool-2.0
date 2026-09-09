"""Qt File Encryption — master-password lock, then encrypt/decrypt tabs."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.qt.module_shell import find_qt_module_shell
from core.services.crypto_service import CryptoService

MIN_PASSWORD_LENGTH = 8


class FileEncryptorLockScreen(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.auth = manager.container.auth_service
        self.hw = getattr(manager.container, "hardware_key_service", None)

        lay = QVBoxLayout(self)
        lay.addStretch(1)
        card = QFrame()
        card.setObjectName("Panel")
        card.setMaximumWidth(440)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 28)
        title = QLabel("File Encryptor")
        title.setObjectName("AccentTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        first = not self.auth.is_initialized()
        hint = QLabel(
            "Choose a master password to protect this tool."
            if first else
            "Enter your master password to continue."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(title)
        cl.addWidget(hint)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Master password")
        self.password.returnPressed.connect(self._submit)
        cl.addWidget(self.password)

        if first:
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("Confirm password")
            self.confirm.returnPressed.connect(self._submit)
            cl.addWidget(self.confirm)
            note = QLabel(
                f"Minimum {MIN_PASSWORD_LENGTH} characters. Same vault master password."
            )
            note.setObjectName("Muted")
            note.setWordWrap(True)
            cl.addWidget(note)
            create = QPushButton("Create and unlock")
            create.setObjectName("Primary")
            create.clicked.connect(self.create_master)
            cl.addWidget(create)
        else:
            self.confirm = None
            unlock = QPushButton("Unlock")
            unlock.setObjectName("Primary")
            unlock.clicked.connect(self.unlock)
            cl.addWidget(unlock)
            self.hw_btn = QPushButton("Unlock with security key")
            self.hw_btn.clicked.connect(self.unlock_hw)
            self.hw_btn.setEnabled(bool(self.hw and self.hw.is_enabled()))
            cl.addWidget(self.hw_btn)

        self.error = QLabel("")
        self.error.setObjectName("Danger")
        self.error.setWordWrap(True)
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.error)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.password.setFocus()

    def _submit(self):
        if self.auth.is_initialized():
            self.unlock()
        else:
            self.create_master()

    def create_master(self):
        self.error.setText("")
        password = self.password.text()
        confirm = self.confirm.text() if self.confirm is not None else ""
        if len(password) < MIN_PASSWORD_LENGTH:
            self.error.setText(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
            return
        if password != confirm:
            self.error.setText("Passwords do not match.")
            return
        try:
            self.auth.create_master_password(password)
        except Exception as exc:
            self.error.setText(f"Couldn't create vault: {exc}")
            return
        self.open_encryptor()

    def unlock(self):
        if self.auth.verify_master_password(self.password.text()):
            self.open_encryptor()
        else:
            self.error.setText("Incorrect password.")
            self.password.clear()
            self.password.setFocus()

    def unlock_hw(self):
        self.error.setText("")
        if self.hw is None:
            self.error.setText("No hardware key service on this device.")
            return
        try:
            if self.hw.verify_and_unlock():
                self.open_encryptor()
            else:
                self.error.setText("Security key verification failed.")
        except Exception as exc:
            self.error.setText(str(exc))

    def open_encryptor(self):
        shell = find_qt_module_shell(self)
        if shell is not None:
            shell.open_vault_dashboard(FileEncryptorPage)


class FileEncryptorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.crypto: CryptoService = manager.container.crypto_service
        self.encrypt_path = ""
        self.decrypt_path = ""
        self.last_output = None

        root = QVBoxLayout(self)
        title = QLabel("File Encryptor")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        tabs.addTab(self._build_encrypt(), "Encrypt")
        tabs.addTab(self._build_decrypt(), "Decrypt")

        self.open_btn = QPushButton("Open output folder")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output)
        root.addWidget(self.open_btn, alignment=Qt.AlignmentFlag.AlignLeft)

    def _build_encrypt(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        head = QLabel("Encrypt file")
        head.setObjectName("CardTitle")
        lay.addWidget(head)
        row = QHBoxLayout()
        self.enc_file = QLabel("No file selected")
        self.enc_file.setObjectName("Muted")
        self.enc_size = QLabel("Size: --")
        self.enc_size.setObjectName("Muted")
        pick = QPushButton("Select file")
        pick.setObjectName("Primary")
        pick.clicked.connect(self._pick_encrypt)
        row.addWidget(self.enc_file, 1)
        row.addWidget(pick)
        lay.addLayout(row)
        lay.addWidget(self.enc_size)
        self.enc_password = QLineEdit()
        self.enc_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.enc_password.setPlaceholderText("Password")
        self.enc_confirm = QLineEdit()
        self.enc_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.enc_confirm.setPlaceholderText("Confirm password")
        lay.addWidget(self.enc_password)
        lay.addWidget(self.enc_confirm)
        run = QPushButton("Encrypt file")
        run.setObjectName("Primary")
        run.clicked.connect(self._encrypt)
        lay.addWidget(run)
        lay.addStretch(1)
        return page

    def _build_decrypt(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        head = QLabel("Decrypt file")
        head.setObjectName("CardTitle")
        lay.addWidget(head)
        row = QHBoxLayout()
        self.dec_file = QLabel("No file selected")
        self.dec_file.setObjectName("Muted")
        self.dec_size = QLabel("Size: --")
        self.dec_size.setObjectName("Muted")
        pick = QPushButton("Select .enc file")
        pick.setObjectName("Primary")
        pick.clicked.connect(self._pick_decrypt)
        row.addWidget(self.dec_file, 1)
        row.addWidget(pick)
        lay.addLayout(row)
        lay.addWidget(self.dec_size)
        self.dec_password = QLineEdit()
        self.dec_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.dec_password.setPlaceholderText("Password")
        lay.addWidget(self.dec_password)
        run = QPushButton("Decrypt file")
        run.setObjectName("Primary")
        run.clicked.connect(self._decrypt)
        lay.addWidget(run)
        lay.addStretch(1)
        return page

    def _set_status(self, text, name="Muted"):
        self.status.setText(text)
        self.status.setObjectName(name)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _set_file_meta(self, label, size_label, path):
        label.setText(os.path.basename(path))
        label.setObjectName("")
        size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
        size_label.setText(f"Size: {size_mb} MB")

    def _pick_encrypt(self):
        path, _ = QFileDialog.getOpenFileName(self, "File to encrypt")
        if not path:
            return
        self.encrypt_path = path
        self._set_file_meta(self.enc_file, self.enc_size, path)
        self._set_status("File selected")

    def _pick_decrypt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Encrypted file", "", "Encrypted files (*.enc);;All files (*.*)"
        )
        if not path:
            return
        self.decrypt_path = path
        self._set_file_meta(self.dec_file, self.dec_size, path)
        self._set_status("Encrypted file selected")

    def _encrypt(self):
        if not self.encrypt_path:
            self._set_status("No file selected", "Danger")
            return
        password = self.enc_password.text()
        confirm = self.enc_confirm.text()
        if not password or password != confirm:
            self._set_status("Passwords do not match or are empty", "Danger")
            return
        try:
            self.last_output = self.crypto.encrypt_file(self.encrypt_path, password)
            self._set_status(f"Encrypted: {os.path.basename(self.last_output)}", "Success")
            self.enc_password.clear()
            self.enc_confirm.clear()
            self.encrypt_path = ""
            self.enc_file.setText("No file selected")
            self.enc_file.setObjectName("Muted")
            self.enc_size.setText("Size: --")
            self.open_btn.setEnabled(True)
        except Exception as exc:
            self._set_status(f"Error: {exc}", "Danger")

    def _decrypt(self):
        if not self.decrypt_path:
            self._set_status("No file selected", "Danger")
            return
        password = self.dec_password.text()
        if not password:
            self._set_status("Password cannot be empty", "Danger")
            return
        try:
            self.last_output = self.crypto.decrypt_file(self.decrypt_path, password)
            self._set_status(f"Decrypted: {os.path.basename(self.last_output)}", "Success")
            self.dec_password.clear()
            self.decrypt_path = ""
            self.dec_file.setText("No file selected")
            self.dec_file.setObjectName("Muted")
            self.dec_size.setText("Size: --")
            self.open_btn.setEnabled(True)
        except Exception:
            self._set_status("Incorrect password or corrupted file", "Danger")

    def _open_output(self):
        if not self.last_output:
            return
        folder = os.path.dirname(self.last_output)
        try:
            os.startfile(folder)
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't open folder", str(exc))
