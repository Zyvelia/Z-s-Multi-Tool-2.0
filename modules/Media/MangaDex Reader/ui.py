"""Qt MangaDex Reader — search, library, download, simple page viewer."""

from __future__ import annotations

import importlib
import os
import tempfile
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

_api = importlib.import_module("modules.Media.MangaDex Reader.api")
_dl = importlib.import_module("modules.Media.MangaDex Reader.downloader")
_lib = importlib.import_module("modules.Media.MangaDex Reader.library")
_utils = importlib.import_module("modules.Media.MangaDex Reader.utils")
_assist = importlib.import_module("modules.Media.MangaDex Reader.page_assist")

MangaDexClient = _api.MangaDexClient
MangaDexError = _api.MangaDexError
DownloadManager = _dl.DownloadManager
DownloadJob = _dl.DownloadJob
Library = _lib.Library


class MangaDexPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.api = MangaDexClient()
        self.library = Library()
        self.dl = DownloadManager(self.api)
        self.manga = None
        self.chapters = []
        self.pages = []
        self.page_index = 0
        self._pix = QPixmap()

        root = QVBoxLayout(self)
        title = QLabel("MangaDex Reader")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        self.progress_banner = QLabel("")
        self.progress_banner.setObjectName("Muted")
        self.progress_banner.setWordWrap(True)
        root.addWidget(self.progress_banner)
        self._refresh_progress()

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title…")
        self.search.returnPressed.connect(self._search)
        go = QPushButton("Search")
        go.setObjectName("Primary")
        go.clicked.connect(self._search)
        lib = QPushButton("Library")
        lib.clicked.connect(self._show_library)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(go)
        search_row.addWidget(lib)
        root.addLayout(search_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        self.results = QListWidget()
        self.results.itemClicked.connect(self._pick_manga)
        self.chapters_list = QListWidget()
        self.chapters_list.itemClicked.connect(self._pick_chapter)
        ll.addWidget(QLabel("Titles"))
        ll.addWidget(self.results, 1)
        ll.addWidget(QLabel("Chapters"))
        ll.addWidget(self.chapters_list, 1)
        dl_row = QHBoxLayout()
        self.fmt = QComboBox()
        self.fmt.addItem("Folder", "images")
        self.fmt.addItem("CBZ", "cbz")
        dl_btn = QPushButton("Download")
        dl_btn.setObjectName("Primary")
        dl_btn.clicked.connect(self._download)
        read_btn = QPushButton("Read")
        read_btn.clicked.connect(self._read_selected)
        dl_row.addWidget(self.fmt)
        dl_row.addWidget(dl_btn)
        dl_row.addWidget(read_btn)
        ll.addLayout(dl_row)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.manga_title = QLabel("Pick a title")
        self.manga_title.setObjectName("CardTitle")
        self.manga_title.setWordWrap(True)
        rl.addWidget(self.manga_title)
        self.page_label = QLabel("No page loaded")
        self.page_label.setObjectName("Muted")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setMinimumHeight(320)
        rl.addWidget(self.page_label, 1)
        nav = QHBoxLayout()
        prev = QPushButton("Prev")
        prev.clicked.connect(lambda: self._step(-1))
        next_btn = QPushButton("Next")
        next_btn.setObjectName("Primary")
        next_btn.clicked.connect(lambda: self._step(1))
        self.page_info = QLabel("")
        self.page_info.setObjectName("Muted")
        nav.addWidget(prev)
        nav.addWidget(self.page_info, 1)
        nav.addWidget(next_btn)
        rl.addLayout(nav)
        ocr_row = QHBoxLayout()
        self.ocr_lang = QComboBox()
        for label in _assist.OCR_LANGS:
            self.ocr_lang.addItem(label)
        self.dest_lang = QComboBox()
        for label in _assist.TRANSLATE_LANGS:
            self.dest_lang.addItem(label)
        ocr = QPushButton("OCR + translate")
        ocr.clicked.connect(lambda: self._run_assist(translate=True, read=False))
        speak_btn = QPushButton("Read aloud")
        speak_btn.setObjectName("Primary")
        speak_btn.clicked.connect(lambda: self._run_assist(translate=True, read=True))
        stop = QPushButton("Stop")
        stop.clicked.connect(self._stop_speech)
        self.auto_read = QCheckBox("Auto-read on page change")
        ocr_row.addWidget(self.ocr_lang)
        ocr_row.addWidget(self.dest_lang)
        ocr_row.addWidget(ocr)
        ocr_row.addWidget(speak_btn)
        ocr_row.addWidget(stop)
        rl.addLayout(ocr_row)
        rl.addWidget(self.auto_read)
        self.assist_out = QPlainTextEdit()
        self.assist_out.setReadOnly(True)
        self.assist_out.setMaximumHeight(120)
        rl.addWidget(self.assist_out)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        self.status = QLabel(_assist.ocr_status())
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._drain_dl)
        self._tick.start()
        self._show_library()

    def on_hide(self):
        self._tick.stop()
        self._stop_speech()

    def on_show(self):
        if not self._tick.isActive():
            self._tick.start()

    def _search(self):
        q = self.search.text().strip()
        if not q:
            return
        self.status.setText("Searching…")

        def work():
            try:
                results = self.api.search_manga(q)
            except MangaDexError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self.status.setText(m))
                return
            QTimer.singleShot(0, lambda r=results: self._fill_results(r))

        threading.Thread(target=work, daemon=True).start()

    def _fill_results(self, results):
        self.results.clear()
        for m in results:
            item = QListWidgetItem(m.get("title") or "Untitled")
            item.setData(Qt.ItemDataRole.UserRole, m)
            self.results.addItem(item)
        self.status.setText(f"{len(results)} title(s)")

    def _show_library(self):
        self.results.clear()
        seen = {}
        for row in self.library.list_downloads():
            manga_id, chapter_id, manga_title, chapter_label, language, fmt, path, downloaded_at = row
            if manga_id in seen:
                continue
            seen[manga_id] = True
            item = QListWidgetItem(f"{manga_title}  (library)")
            item.setData(Qt.ItemDataRole.UserRole, {"id": manga_id, "title": manga_title, "library": True})
            self.results.addItem(item)
        self.status.setText(f"{len(seen)} title(s) in library")

    def _pick_manga(self, item):
        manga = item.data(Qt.ItemDataRole.UserRole) or {}
        self.manga = manga
        self.manga_title.setText(manga.get("title") or "Untitled")
        self.status.setText("Loading chapters…")
        mid = manga.get("id")

        def work():
            try:
                chapters = self.api.get_chapters(mid, languages=["en"]) or self.api.get_chapters(mid)
            except MangaDexError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self.status.setText(m))
                return
            QTimer.singleShot(0, lambda c=chapters: self._fill_chapters(c))

        threading.Thread(target=work, daemon=True).start()

    def _fill_chapters(self, chapters):
        self.chapters = chapters
        self.chapters_list.clear()
        for ch in chapters:
            label = f"Ch.{ch.get('chapter') or '?'}  {ch.get('title') or ''}  [{ch.get('language') or '?'}]"
            item = QListWidgetItem(label.strip())
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self.chapters_list.addItem(item)
        self.status.setText(f"{len(chapters)} chapter(s)")

    def _selected_chapter(self):
        item = self.chapters_list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _download(self):
        chapter = self._selected_chapter()
        if not chapter or not self.manga:
            QMessageBox.information(self, "MangaDex", "Pick a title and chapter first.")
            return
        job = DownloadJob(
            chapter, self.manga["id"], self.manga.get("title") or "Untitled",
            self.fmt.currentData(), False,
        )
        self.dl.enqueue(job)
        self.status.setText("Queued download")

    def _drain_dl(self):
        while True:
            try:
                event = self.dl.events.get_nowait()
            except Exception:
                break
            kind = event[0]
            if kind == "page":
                self.status.setText(f"Downloading page {event[2]}/{event[3]}")
            elif kind == "done":
                self.status.setText(f"Saved {event[2]}")
            elif kind == "error":
                self.status.setText(f"Download error: {event[2]}")
            elif kind == "start":
                self.status.setText(f"Downloading {event[2]} pages…")

    def _read_selected(self):
        chapter = self._selected_chapter()
        if not chapter:
            QMessageBox.information(self, "MangaDex", "Pick a chapter.")
            return
        cid = chapter["id"]
        local = None
        for row in self.library.list_downloads():
            if row[1] == cid:
                local = row[6]
                break
        if local:
            if local.lower().endswith(".cbz"):
                self.pages = _utils.extract_cbz(local)
            else:
                self.pages = _utils.list_chapter_images(local)
            self.page_index = 0
            self._show_page()
            return
        self.status.setText("Fetching pages…")

        def work():
            try:
                urls = self.api.get_page_urls(cid)
            except MangaDexError as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self.status.setText(m))
                return
            tmp = tempfile.mkdtemp(prefix="mangadex_qt_")
            paths = []
            for i, url in enumerate(urls):
                ext = os.path.splitext(url)[1] or ".jpg"
                dest = os.path.join(tmp, f"{i + 1:03}{ext}")
                try:
                    _utils.download_bytes(self.api.session, url, dest)
                    paths.append(dest)
                except Exception:
                    pass
            QTimer.singleShot(0, lambda p=paths: self._set_pages(p))

        threading.Thread(target=work, daemon=True).start()

    def _set_pages(self, paths):
        self.pages = paths
        self.page_index = 0
        self.status.setText(f"{len(paths)} page(s)")
        self._show_page()

    def _show_page(self):
        if not self.pages:
            self.page_label.setText("No pages")
            return
        path = self.pages[self.page_index]
        self._pix = QPixmap(path)
        self.page_label.setPixmap(
            self._pix.scaled(
                max(self.page_label.width(), 200),
                max(self.page_label.height(), 200),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.page_info.setText(f"Page {self.page_index + 1} / {len(self.pages)}")
        if self.manga:
            ch = self._selected_chapter() or {}
            self.library.save_progress(
                self.manga["id"], self.manga.get("title") or "",
                ch.get("id"), ch.get("chapter"), self.page_index,
            )
            self._refresh_progress()
        if self.auto_read.isChecked():
            self._run_assist(translate=True, read=True)

    def _step(self, delta):
        if not self.pages:
            return
        self.page_index = max(0, min(len(self.pages) - 1, self.page_index + delta))
        self._show_page()

    def _refresh_progress(self):
        recent = self.library.recent_progress(limit=1)
        if not recent:
            self.progress_banner.setText("No manga in progress yet.")
            return
        _mid, title, chapter, page, _when = recent[0]
        self.progress_banner.setText(f"In progress: {title}  ·  ch {chapter or '?'}  ·  page {page + 1}")

    def _stop_speech(self):
        try:
            _assist.stop_speech()
        except Exception:
            pass
        self.status.setText("Stopped.")

    def _run_assist(self, *, translate: bool, read: bool):
        if not self.pages:
            return
        path = self.pages[self.page_index]
        ocr_label = self.ocr_lang.currentText()
        dest_label = self.dest_lang.currentText()
        self.status.setText("Reading the page…")

        def work():
            try:
                text = _assist.ocr_page(path, ocr_label)
                translated = _assist.translate_text(text, dest_label) if translate else ""
                spoken = translated or text
                if read:
                    _assist.speak(spoken)
            except Exception as e:
                msg = str(e)
                QTimer.singleShot(0, lambda m=msg: self.status.setText(m))
                return
            QTimer.singleShot(0, lambda a=text, b=translated, r=read: self._show_assist(a, b, r))

        threading.Thread(target=work, daemon=True).start()

    def _show_assist(self, text, translated, read=False):
        body = translated or "(no translation)"
        self.assist_out.setPlainText(f"{body}\n\n--- OCR ---\n{text}")
        self.status.setText("Reading…" if read else "OCR done")
