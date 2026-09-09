"""Qt Hash Tools — generate and verify MD5/SHA hashes."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.Hash_Tools.hash_core import hash_bytes, hash_file, verify_file


class HashToolsPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._gen_path = ""
        self._verify_path = ""

        root = QVBoxLayout(self)
        title = QLabel("Hash Tools")
        title.setObjectName("AccentTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        tabs.addTab(self._build_generate(), "Generate")
        tabs.addTab(self._build_verify(), "Verify")

    def _build_generate(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Text"))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Paste text to hash…")
        self.text.setMaximumHeight(110)
        lay.addWidget(self.text)

        row = QHBoxLayout()
        gen = QPushButton("Generate from text")
        gen.setObjectName("Primary")
        gen.clicked.connect(self._from_text)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        row.addWidget(gen)
        row.addWidget(clear)
        row.addStretch(1)
        lay.addLayout(row)

        self.hash_edits = {}
        form = QFormLayout()
        for name in ("MD5", "SHA1", "SHA256", "SHA512"):
            edit = QLineEdit()
            edit.setReadOnly(True)
            copy = QPushButton("Copy")
            copy.clicked.connect(lambda _=False, e=edit: self._copy(e.text()))
            cell = QWidget()
            hl = QHBoxLayout(cell)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(edit, 1)
            hl.addWidget(copy)
            form.addRow(name, cell)
            self.hash_edits[name] = edit
        lay.addLayout(form)

        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("Muted")
        browse = QPushButton("Browse file")
        browse.clicked.connect(self._pick_gen_file)
        from_file = QPushButton("Generate from file")
        from_file.setObjectName("Primary")
        from_file.clicked.connect(self._from_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(browse)
        file_row.addWidget(from_file)
        lay.addLayout(file_row)
        lay.addStretch(1)
        return page

    def _build_verify(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.verify_label = QLabel("No file selected")
        self.verify_label.setObjectName("Muted")
        browse = QPushButton("Browse file")
        browse.clicked.connect(self._pick_verify_file)
        row = QHBoxLayout()
        row.addWidget(self.verify_label, 1)
        row.addWidget(browse)
        lay.addLayout(row)

        self.algo = QComboBox()
        self.algo.addItems(["MD5", "SHA1", "SHA256", "SHA512"])
        self.expected = QLineEdit()
        self.expected.setPlaceholderText("Paste expected hash…")
        form = QFormLayout()
        form.addRow("Algorithm", self.algo)
        form.addRow("Expected", self.expected)
        lay.addLayout(form)

        verify = QPushButton("Verify hash")
        verify.setObjectName("Primary")
        verify.clicked.connect(self._verify)
        self.verify_result = QLabel("")
        lay.addWidget(verify)
        lay.addWidget(self.verify_result)
        lay.addStretch(1)
        return page

    def _set_hashes(self, hashes: dict):
        for name, edit in self.hash_edits.items():
            edit.setText(hashes.get(name, ""))

    def _from_text(self):
        data = self.text.toPlainText().strip().encode()
        self._set_hashes(hash_bytes(data))

    def _from_file(self):
        if not self._gen_path:
            return
        self._set_hashes(hash_file(self._gen_path))

    def _pick_gen_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "File to hash")
        if path:
            self._gen_path = path
            self.file_label.setText(path)
            self.file_label.setObjectName("")

    def _pick_verify_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "File to verify")
        if path:
            self._verify_path = path
            self.verify_label.setText(path)
            self.verify_label.setObjectName("")

    def _verify(self):
        if not self._verify_path:
            return
        ok, actual = verify_file(self._verify_path, self.algo.currentText(), self.expected.text())
        if ok:
            self.verify_result.setText("Match")
            self.verify_result.setObjectName("Success")
        else:
            self.verify_result.setText(f"Mismatch — actual {actual}")
            self.verify_result.setObjectName("Danger")
        self.verify_result.style().unpolish(self.verify_result)
        self.verify_result.style().polish(self.verify_result)

    def _clear(self):
        self.text.clear()
        self._set_hashes({})
        self._gen_path = ""
        self.file_label.setText("No file selected")
        self.file_label.setObjectName("Muted")

    def _copy(self, value: str):
        if value:
            QApplication.clipboard().setText(value)
