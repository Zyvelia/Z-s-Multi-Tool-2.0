"""Qt Notes — list, editor, pin, links."""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import importlib

storage = importlib.import_module("modules.Productivity.Notes.storage")


class NotesPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.current_id = None
        self.links = []

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Notes")
        title.setObjectName("AccentTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes…")
        self.search.textChanged.connect(self.refresh_list)
        header.addWidget(title)
        header.addWidget(self.search, 1)
        root.addLayout(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        new = QPushButton("+ New note")
        new.setObjectName("Primary")
        new.clicked.connect(self._new)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        ll.addWidget(new)
        ll.addWidget(self.list, 1)

        right = QWidget()
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Note title…")
        self.pin_btn = QPushButton("☆")
        self.pin_btn.setFixedWidth(42)
        self.pin_btn.clicked.connect(self._toggle_pin)
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(self._delete)
        top.addWidget(self.title_edit, 1)
        top.addWidget(self.pin_btn)
        top.addWidget(delete)
        rl.addLayout(top)

        rl.addWidget(QLabel("Links"))
        self.links_host = QWidget()
        self.links_lay = QVBoxLayout(self.links_host)
        self.links_lay.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.links_host)
        add_row = QHBoxLayout()
        self.link_label = QLineEdit()
        self.link_label.setPlaceholderText("Label (optional)")
        self.link_url = QLineEdit()
        self.link_url.setPlaceholderText("https://…")
        self.link_url.returnPressed.connect(self._add_link)
        add_link = QPushButton("Add link")
        add_link.clicked.connect(self._add_link)
        add_row.addWidget(self.link_label)
        add_row.addWidget(self.link_url, 1)
        add_row.addWidget(add_link)
        rl.addLayout(add_row)

        self.body = QPlainTextEdit()
        rl.addWidget(self.body, 1)
        save = QPushButton("Save note")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        rl.addWidget(save)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        self.refresh_list()
        self._new()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        from core.qt.remote_common import SimpleRemoteSettings, ensure_manager_server

        web_mod = importlib.import_module("modules.Productivity.Notes.web_server")
        return SimpleRemoteSettings(
            parent,
            manager,
            get_server=lambda: ensure_manager_server(
                manager, "notes_web_server", web_mod.NotesWebServer
            ),
            app_key="notes",
            default_port=8768,
            title="Remote access (notes on phone)",
            hint="Phone can read and edit notes over your tailnet. Hub Go Live maps this too.",
        )

    def on_show(self):
        self.refresh_list()

    def refresh_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        notes = storage.search_notes(self.search.text())
        for note in notes:
            title = note.get("title") or "Untitled"
            if note.get("pinned"):
                title = "📌 " + title
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, note["id"])
            self.list.addItem(item)
            if note["id"] == self.current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def _on_select(self, item):
        if item is None:
            return
        note = storage.get_note(item.data(Qt.ItemDataRole.UserRole))
        if note:
            self._load(note)

    def _clear_links(self):
        while self.links_lay.count():
            item = self.links_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.links = []

    def _render_links(self):
        while self.links_lay.count():
            item = self.links_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, link in enumerate(self.links):
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            display = link.get("label") or link.get("url") or ""
            btn = QPushButton(f"🔗 {display}")
            btn.setStyleSheet("text-align: left;")
            btn.clicked.connect(lambda _=False, u=link.get("url"): self._open_link(u))
            rm = QPushButton("✕")
            rm.setFixedWidth(28)
            rm.clicked.connect(lambda _=False, idx=i: self._remove_link(idx))
            hl.addWidget(btn, 1)
            hl.addWidget(rm)
            self.links_lay.addWidget(row)

    def _add_link(self):
        url = self.link_url.text().strip()
        if not url:
            return
        self.links.append({"label": self.link_label.text().strip(), "url": url})
        self.link_label.clear()
        self.link_url.clear()
        self._render_links()

    def _remove_link(self, idx):
        if 0 <= idx < len(self.links):
            self.links.pop(idx)
            self._render_links()

    def _open_link(self, url):
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)

    def _new(self):
        self.current_id = None
        self.title_edit.clear()
        self.body.clear()
        self._clear_links()
        self.pin_btn.setText("☆")
        self.title_edit.setFocus()
        self.refresh_list()

    def _load(self, note):
        self.current_id = note["id"]
        self.title_edit.setText(note.get("title") or "")
        self.body.setPlainText(note.get("body") or "")
        self.links = list(note.get("links") or [])
        self._render_links()
        self.pin_btn.setText("📌" if note.get("pinned") else "☆")

    def _save(self):
        title = self.title_edit.text().strip()
        body = self.body.toPlainText()
        if self.current_id is None:
            note = storage.create_note(title=title, body=body, links=self.links)
            self.current_id = note["id"]
        else:
            storage.update_note(self.current_id, title=title, body=body, links=self.links)
        self.refresh_list()

    def _delete(self):
        if self.current_id is None:
            self._new()
            return
        if QMessageBox.question(self, "Delete note", "Delete this note? This can't be undone.") != QMessageBox.StandardButton.Yes:
            return
        storage.delete_note(self.current_id)
        self._new()

    def _toggle_pin(self):
        if self.current_id is None:
            QMessageBox.information(self, "Save first", "Save the note before pinning it.")
            return
        note = storage.toggle_pin(self.current_id)
        if note:
            self.pin_btn.setText("📌" if note.get("pinned") else "☆")
            self.refresh_list()
