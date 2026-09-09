"""Qt Duplicate File Finder — scan folders, show groups, delete extras."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules.System.duplicate_finder.backend import (
    DuplicateScanWorker,
    ScanOptions,
    delete_files,
)

POLL_MS = 80

SIZE_CHOICES = {
    "Any size": 0,
    "≥ 100 KB": 100 * 1024,
    "≥ 1 MB": 1024 * 1024,
    "≥ 10 MB": 10 * 1024 * 1024,
}


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class DuplicateFinderModule(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._roots: list[Path] = []
        self._worker = None
        self._groups = []
        self._checks: dict[str, QCheckBox] = {}
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_worker)

        root = QVBoxLayout(self)
        title = QLabel("Duplicate File Finder")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "Finds byte-identical files by size, then content hash. "
            "Deletion here is permanent, not sent to the Recycle Bin."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        picker = QFrame()
        picker.setObjectName("Panel")
        pl = QVBoxLayout(picker)
        btn_row = QHBoxLayout()
        add = QPushButton("Add Folder")
        add.clicked.connect(self._add_folder)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_roots)
        self.subfolders = QCheckBox("Include subfolders")
        self.subfolders.setChecked(True)
        self.min_size = QComboBox()
        self.min_size.addItems(list(SIZE_CHOICES.keys()))
        btn_row.addWidget(add)
        btn_row.addWidget(clear)
        btn_row.addWidget(self.subfolders)
        btn_row.addWidget(QLabel("Minimum size:"))
        btn_row.addWidget(self.min_size)
        btn_row.addStretch(1)
        pl.addLayout(btn_row)
        self.roots_box = QPlainTextEdit()
        self.roots_box.setReadOnly(True)
        self.roots_box.setMaximumHeight(80)
        pl.addWidget(self.roots_box)
        root.addWidget(picker)

        action = QHBoxLayout()
        self.scan_btn = QPushButton("Scan for Duplicates")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.clicked.connect(self._start_scan)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        action.addWidget(self.scan_btn)
        action.addWidget(self.progress, 1)
        root.addLayout(action)
        self.status = QLabel("Add one or more folders to begin.")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.results_lay = QVBoxLayout(host)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        del_row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._confirm_delete)
        self.selection_label = QLabel("")
        self.selection_label.setObjectName("Muted")
        del_row.addWidget(self.delete_btn)
        del_row.addWidget(self.selection_label, 1)
        root.addLayout(del_row)
        self._refresh_roots_view()

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select a folder to scan")
        if path:
            p = Path(path)
            if p not in self._roots:
                self._roots.append(p)
        self._refresh_roots_view()

    def _clear_roots(self):
        self._roots.clear()
        self._refresh_roots_view()

    def _refresh_roots_view(self):
        if not self._roots:
            self.roots_box.setPlainText("  (no folders selected — click Add Folder)")
            return
        self.roots_box.setPlainText("\n".join(f"  {p}" for p in self._roots))

    def _start_scan(self):
        if not self._roots:
            self.status.setText("Add at least one folder first.")
            return
        if self._worker is not None and self._worker.is_alive():
            return
        options = ScanOptions(
            roots=list(self._roots),
            include_subfolders=self.subfolders.isChecked(),
            min_size_bytes=SIZE_CHOICES[self.min_size.currentText()],
        )
        _clear(self.results_lay)
        self._checks.clear()
        self.scan_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.status.setText("Scanning…")
        self._worker = DuplicateScanWorker(options)
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
        if event.kind == "scanning":
            self.status.setText(event.message)
        elif event.kind == "hashing":
            if event.total_count:
                self.progress.setRange(0, 100)
                self.progress.setValue(int(100 * event.done_count / max(event.total_count, 1)))
            self.status.setText(event.message)
        elif event.kind == "overall_done":
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if event.groups else 0)
            self.status.setText(event.message)
            self.scan_btn.setEnabled(True)
            self._groups = event.groups
            self._render_groups()
            self._worker = None
            self._poll.stop()
        elif event.kind == "fatal_error":
            self.progress.setRange(0, 100)
            self.status.setText(f"Error: {event.message}")
            self.status.setObjectName("Danger")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
            self.scan_btn.setEnabled(True)
            self._worker = None
            self._poll.stop()

    def _render_groups(self):
        _clear(self.results_lay)
        self._checks.clear()
        if not self._groups:
            empty = QLabel("No duplicates found.")
            empty.setObjectName("Muted")
            self.results_lay.addWidget(empty)
            self._update_selection_label()
            self.results_lay.addStretch(1)
            return
        for group in self._groups:
            card = QFrame()
            card.setObjectName("Panel")
            cl = QVBoxLayout(card)
            title = QLabel(
                f"{len(group.paths)} copies · {_human_size(group.size)} each · "
                f"{_human_size(group.size * (len(group.paths) - 1))} reclaimable"
            )
            title.setObjectName("CardTitle")
            cl.addWidget(title)
            for i, path in enumerate(group.paths):
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(0, 0, 0, 0)
                box = QCheckBox(str(path))
                box.setChecked(i != 0)
                box.stateChanged.connect(self._update_selection_label)
                self._checks[str(path)] = box
                locate = QPushButton("Locate")
                locate.clicked.connect(lambda _=False, p=path: self._open_location(p))
                hl.addWidget(box, 1)
                hl.addWidget(locate)
                cl.addWidget(row)
            self.results_lay.addWidget(card)
        self.results_lay.addStretch(1)
        self._update_selection_label()

    def _open_location(self, path: Path):
        try:
            os.startfile(path.parent)
        except OSError:
            pass

    def _update_selection_label(self):
        selected = [Path(p) for p, box in self._checks.items() if box.isChecked()]
        self.delete_btn.setEnabled(bool(selected))
        if selected:
            total = sum(p.stat().st_size for p in selected if p.exists())
            self.selection_label.setText(f"{len(selected)} file(s) selected · {_human_size(total)}")
        else:
            self.selection_label.setText("")

    def _confirm_delete(self):
        selected = [Path(p) for p, box in self._checks.items() if box.isChecked()]
        if not selected:
            return
        count = len(selected)
        answer, ok = QInputDialog.getText(
            self,
            "Confirm Delete",
            f"This will permanently delete {count} file(s). This cannot be undone.\n\nType {count} to confirm:",
        )
        if not ok:
            return
        try:
            confirmed = int(answer.strip())
        except ValueError:
            confirmed = -1
        if confirmed != count:
            self.status.setText("Confirmation didn't match — nothing was deleted.")
            return
        results = delete_files(selected)
        ok_n = sum(1 for _p, success, _e in results if success)
        failed = [(p, e) for p, success, e in results if not success]
        self.status.setText(
            f"Deleted {ok_n}/{count} file(s)."
            + (f" {len(failed)} failed (locked/in-use)." if failed else "")
        )
        self._start_scan()
