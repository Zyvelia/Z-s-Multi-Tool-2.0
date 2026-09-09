"""Qt File Shredder — overwrite then delete files and folders."""

from __future__ import annotations

import importlib
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_shred = importlib.import_module("modules.Files.File Shredder.shredder")
PassPattern = _shred.PassPattern
ShredderWorker = _shred.ShredderWorker
collect_targets = _shred.collect_targets

POLL_MS = 60


class FolderShredderModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._targets: list[Path] = []
        self._worker = None
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_worker)

        root = QVBoxLayout(self)
        title = QLabel("Folder Shredder")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "Overwrites files before deleting them, then removes the folder. "
            "This cannot be undone. On SSDs, overwrite passes are mostly cosmetic."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        panel = QFrame()
        panel.setObjectName("Panel")
        pl = QVBoxLayout(panel)
        btn_row = QHBoxLayout()
        add_files = QPushButton("Add Files")
        add_files.clicked.connect(self._add_files)
        add_folder = QPushButton("Add Folder")
        add_folder.clicked.connect(self._add_folder)
        clear = QPushButton("Clear Queue")
        clear.clicked.connect(self._clear_queue)
        self.pattern = QComboBox()
        for p in PassPattern:
            self.pattern.addItem(p.value, p)
        btn_row.addWidget(add_files)
        btn_row.addWidget(add_folder)
        btn_row.addWidget(clear)
        btn_row.addStretch(1)
        btn_row.addWidget(self.pattern)
        pl.addLayout(btn_row)
        self.queue_box = QPlainTextEdit()
        self.queue_box.setReadOnly(True)
        pl.addWidget(self.queue_box, 1)
        root.addWidget(panel, 1)

        action = QHBoxLayout()
        self.shred_btn = QPushButton("Shred Queue")
        self.shred_btn.setObjectName("Danger")
        self.shred_btn.clicked.connect(self._confirm_and_shred)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        action.addWidget(self.shred_btn)
        action.addWidget(self.progress, 1)
        root.addLayout(action)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        log_title = QLabel("Log")
        log_title.setObjectName("CardTitle")
        root.addWidget(log_title)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        root.addWidget(self.log_box)
        self._refresh_queue_view()

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to shred")
        self._targets.extend(Path(p) for p in paths)
        self._refresh_queue_view()

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select a folder to shred")
        if path:
            self._targets.append(Path(path))
        self._refresh_queue_view()

    def _clear_queue(self):
        self._targets.clear()
        self._refresh_queue_view()

    def _refresh_queue_view(self):
        if not self._targets:
            self.queue_box.setPlainText("  (queue is empty — add files or a folder above)")
            return
        lines = []
        for p in self._targets:
            kind = "DIR " if p.is_dir() else "FILE"
            lines.append(f"  [{kind}] {p}")
        self.queue_box.setPlainText("\n".join(lines))

    def _log(self, text: str):
        self.log_box.appendPlainText(text)

    def _confirm_and_shred(self):
        if not self._targets:
            self.status.setText("Queue is empty — nothing to shred.")
            return
        if self._worker is not None and self._worker.is_alive():
            return
        count = len(self._targets)
        answer, ok = QInputDialog.getText(
            self,
            "Confirm Shred",
            f"This will permanently destroy {count} item(s). This cannot be undone.\n\nType {count} to confirm:",
        )
        if not ok:
            return
        try:
            confirmed = int(answer.strip())
        except ValueError:
            confirmed = -1
        if confirmed != count:
            self.status.setText("Confirmation didn't match — nothing was shredded.")
            return
        self._start_shred()

    def _start_shred(self):
        pattern = self.pattern.currentData()
        items = collect_targets(self._targets)
        self.shred_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText(f"Shredding {len(items)} item(s)…")
        self._log(f"--- starting shred of {len(items)} item(s), pattern: {pattern.value} ---")
        self._worker = ShredderWorker(items, pattern)
        self._worker.start()
        self._poll.start()

    def _poll_worker(self):
        if self._worker is None:
            self._poll.stop()
            return
        try:
            while True:
                event = self._worker.events.get_nowait()
                self._handle_event(event)
        except Exception:
            pass
        if self._worker is not None and self._worker.is_alive():
            return
        self._poll.stop()

    def _handle_event(self, event):
        if event.kind == "item_start":
            return
        if event.kind == "item_done":
            r = event.result
            if r and r.ok:
                self._log(f"shredded: {r.path}")
            elif r:
                self._log(f"SKIPPED ({r.error}): {r.path}")
            if event.total_count:
                self.progress.setValue(int(100 * event.done_count / event.total_count))
                self.status.setText(f"{event.done_count}/{event.total_count} processed")
        elif event.kind == "overall_done":
            self._log(f"--- {event.message} ---")
            self.status.setText(event.message)
            self.shred_btn.setEnabled(True)
            self._targets.clear()
            self._refresh_queue_view()
            self._worker = None
            self._poll.stop()
        elif event.kind == "fatal_error":
            self._log(f"FATAL: {event.message}")
            self.status.setText("Error — see log")
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            self.shred_btn.setEnabled(True)
            self._worker = None
            self._poll.stop()
