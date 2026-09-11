"""Qt YouTube Downloader — queue via the same YTWebServer the phone uses.

Three tabs:
  - Download        the original one-off "paste a link" queue
  - Watch Channels   add a channel/playlist link once; new uploads get
                     auto-downloaded by web_server.ChannelWatcher
  - Library          browse everything already on disk (survives app
                     restarts, unlike the in-memory job list)
"""

from __future__ import annotations

import json
import os
import time
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import importlib

from core.qt.remote_common import AppServePanel, TailscalePanel

from . import library

_web = importlib.import_module("modules.Media.YouTube Downloader.web_server")
YTWebServer = _web.YTWebServer
is_youtube_url = _web.is_youtube_url
SETTINGS_FILE = _web.SETTINGS_FILE
DEFAULT_REMOTE_PORT = 8767

INTERVAL_CHOICES = [
    ("Every 30 min", 30),
    ("Every hour", 60),
    ("Every 3 hours", 180),
    ("Every 12 hours", 720),
    ("Once a day", 1440),
]


def _defaults():
    return {
        "output_dir": os.path.expanduser("~"),
        "cookie_file": "",
        "format": "mp3",
        "type": "video",
        "quality": "192",
        "remote_port": DEFAULT_REMOTE_PORT,
        "auto_start_remote": False,
        "access_code": "",
    }


def read_settings():
    data = _defaults()
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                data.update(json.load(f))
    except Exception:
        pass
    return data


def write_settings(updates: dict):
    data = read_settings()
    data.update(updates)
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _ensure_server(manager):
    web = getattr(manager, "yt_web_server", None)
    if web is not None:
        return web

    def output_dir():
        return read_settings().get("output_dir") or os.path.expanduser("~")

    def cookie_file():
        return read_settings().get("cookie_file") or ""

    s = read_settings()
    web = YTWebServer(
        get_output_dir=output_dir,
        get_cookie_file=cookie_file,
        get_ffmpeg_dir=lambda: None,
        default_format=s.get("format", "mp3"),
        default_type=s.get("type", "video"),
        default_quality=s.get("quality", "192"),
    )
    web.access_code = s.get("access_code", "")
    manager.yt_web_server = web
    return web


def _fmt_size(num_bytes):
    if not num_bytes:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _time_ago(ts):
    if not ts:
        return "never checked"
    mins = max(0, int((time.time() - ts) / 60))
    if mins < 1:
        return "checked just now"
    if mins < 60:
        return f"checked {mins}m ago"
    return f"checked {mins // 60}h ago"


class YTDownloaderPage(QWidget):
    # Worker threads (yt-dlp/channel watcher) must never touch Qt widgets
    # directly. Emitting these signals safely queues the work onto the Qt
    # GUI thread. This is especially important in frozen/PyInstaller builds,
    # where direct cross-thread widget access can terminate the process.
    _job_update_signal = Signal(object)
    _channel_update_signal = Signal(object)

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.web = _ensure_server(manager)

        # Connect signals while this QWidget is still on the GUI thread.
        # Calls to emit() from downloader/background threads are then queued
        # safely to this object's GUI-thread affinity.
        self._job_update_signal.connect(self._on_job)
        self._channel_update_signal.connect(self._on_channel_update)
        s = read_settings()

        root = QVBoxLayout(self)
        title = QLabel("YouTube Downloader")
        title.setObjectName("AccentTitle")
        root.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_download_tab(s), "Download")
        tabs.addTab(self._build_channels_tab(), "Watch Channels")
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(tabs, 1)
        self.tabs = tabs

        self.web.on_job_update = lambda job: self._job_update_signal.emit(dict(job))
        self._tick = QTimer(self)
        self._tick.setInterval(800)
        self._tick.timeout.connect(self._refresh_jobs)
        self._tick.start()
        self._refresh_jobs()

        self.web.channel_watcher.on_update = lambda channel: self._channel_update_signal.emit(dict(channel))
        self._channel_tick = QTimer(self)
        self._channel_tick.setInterval(3000)
        self._channel_tick.timeout.connect(self._refresh_channels)
        self._channel_tick.start()
        self._refresh_channels()
        self._refresh_library()

        if s.get("auto_start_remote") and not self.web.is_running():
            threading.Thread(
                target=lambda: self.web.start(int(s.get("remote_port") or DEFAULT_REMOTE_PORT)),
                daemon=True,
            ).start()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _YTSettings(parent, manager)

    @staticmethod
    def _set_combo(combo, value):
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def on_hide(self):
        self._tick.stop()
        self._channel_tick.stop()

    def on_show(self):
        if not self._tick.isActive():
            self._tick.start()
        if not self._channel_tick.isActive():
            self._channel_tick.start()
        self._refresh_jobs()
        self._refresh_channels()
        self._refresh_library()

    def _on_tab_changed(self, _index):
        # Library is scanned from disk on demand rather than polled, since
        # it can be a large folder — refresh it only when the tab is opened.
        if self.tabs.tabText(self.tabs.currentIndex()) == "Library":
            self._refresh_library()

    # =====================================================
    # Download tab (unchanged behavior from the original page)
    # =====================================================

    def _build_download_tab(self, s):
        page = QWidget()
        root = QVBoxLayout(page)
        hint = QLabel("Paste a YouTube URL. Jobs use the same queue as the phone page.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        url_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url.returnPressed.connect(self._queue)
        go = QPushButton("Queue")
        go.setObjectName("Primary")
        go.clicked.connect(self._queue)
        url_row.addWidget(self.url, 1)
        url_row.addWidget(go)
        root.addLayout(url_row)

        opts = QHBoxLayout()
        self.dl_type = QComboBox()
        self.dl_type.addItem("Single video", "video")
        self.dl_type.addItem("Playlist", "playlist")
        self.fmt = QComboBox()
        self.fmt.addItem("MP3", "mp3")
        self.fmt.addItem("MP4", "mp4")
        self.quality = QComboBox()
        for q in ("320", "256", "192", "128", "96"):
            self.quality.addItem(f"{q} kbps", q)
        self._set_combo(self.dl_type, s.get("type", "video"))
        self._set_combo(self.fmt, s.get("format", "mp3"))
        self._set_combo(self.quality, str(s.get("quality", "192")))
        for combo in (self.dl_type, self.fmt, self.quality):
            combo.currentIndexChanged.connect(self._persist_opts)
        opts.addWidget(QLabel("Type"))
        opts.addWidget(self.dl_type)
        opts.addWidget(QLabel("Format"))
        opts.addWidget(self.fmt)
        opts.addWidget(QLabel("Quality"))
        opts.addWidget(self.quality)
        opts.addStretch(1)
        root.addLayout(opts)

        self.jobs = QListWidget()
        root.addWidget(self.jobs, 1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(220)
        root.addWidget(self.log)
        return page

    def _persist_opts(self):
        write_settings({
            "format": self.fmt.currentData(),
            "type": self.dl_type.currentData(),
            "quality": self.quality.currentData(),
        })
        self.web.default_format = self.fmt.currentData()
        self.web.default_type = self.dl_type.currentData()
        self.web.default_quality = self.quality.currentData()

    def _queue(self):
        url = self.url.text().strip()
        if not url:
            return
        if not is_youtube_url(url):
            self._log("That doesn't look like a YouTube URL.")
            return
        self._persist_opts()
        job = self.web.queue_download(
            url, self.fmt.currentData(), self.dl_type.currentData(), self.quality.currentData(),
        )
        self.url.clear()
        self._log(f"Queued {job.get('id')}: {url}")
        self._refresh_jobs()

    def _on_job(self, job):
        # Keep the live log human-readable: only log meaningful state changes
        # and completed/failed downloads instead of flooding it with every
        # progress-hook update.
        job_id = job.get("id") or "--------"
        status = job.get("status", "?")
        message = (job.get("message") or "").strip()
        last_status = getattr(self, "_last_logged_status", {}).get(job_id)
        last_message = getattr(self, "_last_logged_message", {}).get(job_id)
        if not hasattr(self, "_last_logged_status"):
            self._last_logged_status = {}
            self._last_logged_message = {}

        should_log = status != last_status
        if status == "error" and message != last_message:
            should_log = True
        if status == "downloading" and last_status != "downloading":
            should_log = True

        if should_log:
            now = time.strftime("%H:%M:%S")
            icons = {
                "queued": "•",
                "starting": "→",
                "downloading": "↓",
                "done": "✓",
                "error": "✗",
            }
            icon = icons.get(status, "•")
            if status == "done":
                files = job.get("files") or []
                names = ", ".join(f.get("name", "file") for f in files[:3])
                if len(files) > 3:
                    names += f" (+{len(files) - 3} more)"
                line = f"[{now}] ✓ DONE  {job_id}  •  100%"
                if names:
                    line += f"  •  {names}"
            elif status == "error":
                line = f"[{now}] ✗ FAILED  {job_id}  •  {message or 'Unknown error'}"
            else:
                line = f"[{now}] {icon} {status.upper():<11} {job_id}  •  {message}"
            self._log(line)
            self._last_logged_status[job_id] = status
            self._last_logged_message[job_id] = message

        self._refresh_jobs()

    def _refresh_jobs(self):
        current = self.jobs.currentRow()
        self.jobs.clear()
        for job in reversed(self.web.list_jobs()):
            status = job.get("status", "?")
            # yt-dlp represents completion as 1.0 internally. The UI should
            # display that as 100%, not 1%.
            raw_pct = job.get("percent") or 0
            pct = raw_pct * 100 if raw_pct <= 1 else raw_pct
            pct = max(0, min(100, pct))

            icons = {
                "queued": "•",
                "starting": "→",
                "downloading": "↓",
                "done": "✓",
                "error": "✗",
            }
            icon = icons.get(status, "•")
            title = job.get("url", "")
            files = job.get("files") or []
            if status == "done" and files:
                title = files[0].get("name") or title

            label = (
                f"{icon} {status.upper()}  •  {pct:.0f}%\n"
                f"{job.get('format', '').upper()} / {job.get('type', '')}  •  {title}"
            )

            if status == "downloading" and job.get("message"):
                label += f"\n{job.get('message')}"
            elif status == "starting":
                label += "\nStarting download…"
            elif status == "done":
                if files:
                    label += f"\n✓ Download complete — {len(files)} file(s) saved"
                else:
                    label += "\n✓ Download complete"
            elif status == "error" and job.get("message"):
                label += f"\n⚠ {job.get('message')}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, job.get("id"))
            self.jobs.addItem(item)
        if 0 <= current < self.jobs.count():
            self.jobs.setCurrentRow(current)

    def _log(self, msg):
        self.log.appendPlainText(str(msg))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # =====================================================
    # Watch Channels tab
    # =====================================================

    def _build_channels_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        hint = QLabel(
            "Add a channel or playlist link once. New uploads are auto-downloaded "
            "on a schedule, even if this page isn't open — jobs land in a "
            "\"Watched - <name>\" subfolder of your output folder."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.ch_url = QLineEdit()
        self.ch_url.setPlaceholderText("https://www.youtube.com/@channel or a playlist link")
        self.ch_name = QLineEdit()
        self.ch_name.setPlaceholderText("Name (optional — used for the subfolder)")
        row = QHBoxLayout()
        self.ch_type = QComboBox()
        self.ch_type.addItem("Single videos", "video")
        self.ch_type.addItem("Playlist", "playlist")
        self.ch_fmt = QComboBox()
        self.ch_fmt.addItem("MP4", "mp4")
        self.ch_fmt.addItem("MP3", "mp3")
        self.ch_interval = QComboBox()
        for label, minutes in INTERVAL_CHOICES:
            self.ch_interval.addItem(label, minutes)
        self.ch_interval.setCurrentIndex(1)  # "Every hour"
        row.addWidget(self.ch_type)
        row.addWidget(self.ch_fmt)
        row.addWidget(self.ch_interval)
        form.addRow("Link", self.ch_url)
        form.addRow("Name", self.ch_name)
        form.addRow("Options", row)
        root.addLayout(form)

        add_row = QHBoxLayout()
        add_btn = QPushButton("Watch Channel")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(self._add_channel)
        add_row.addStretch(1)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        self.ch_error = QLabel("")
        self.ch_error.setObjectName("Muted")
        self.ch_error.setWordWrap(True)
        root.addWidget(self.ch_error)

        self.channel_list = QListWidget()
        root.addWidget(self.channel_list, 1)

        actions = QHBoxLayout()
        check_btn = QPushButton("Check Selected Now")
        check_btn.clicked.connect(self._check_selected_channel)
        missing_btn = QPushButton("Download All Missing")
        missing_btn.setObjectName("Primary")
        missing_btn.clicked.connect(self._download_all_missing)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected_channel)
        actions.addWidget(check_btn)
        actions.addWidget(missing_btn)
        actions.addWidget(remove_btn)
        actions.addStretch(1)
        root.addLayout(actions)
        return page

    def _add_channel(self):
        url = self.ch_url.text().strip()
        self.ch_error.setText("")
        if not url:
            return
        result = self.web.channel_watcher.add_channel(
            url,
            name=self.ch_name.text().strip(),
            interval_minutes=self.ch_interval.currentData(),
            fmt=self.ch_fmt.currentData(),
            dl_type=self.ch_type.currentData(),
            quality=read_settings().get("quality", "192"),
        )
        if not result.get("ok"):
            self.ch_error.setText(result.get("error") or "Couldn't watch that link.")
            return
        self.ch_url.clear()
        self.ch_name.clear()
        self._refresh_channels()

    def _selected_channel_id(self):
        item = self.channel_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _check_selected_channel(self):
        cid = self._selected_channel_id()
        if not cid:
            return
        self.web.channel_watcher.check_now(cid)

    def _download_all_missing(self):
        channels = self.web.channel_watcher.list_channels()
        if not channels:
            self.ch_error.setText("No watched channels yet.")
            return
        result = self.web.channel_watcher.download_missing_all()
        if result.get("ok"):
            count = result.get("queued", 0)
            self.ch_error.setText(
                f"Queued {count} missing video(s) from {len(channels)} watched channel(s). "
                "Downloads run one at a time with a delay to reduce rate limiting."
            )
            self._refresh_jobs()
            self._refresh_channels()
        else:
            self.ch_error.setText(result.get("error") or "Couldn't start the backfill.")

    def _remove_selected_channel(self):
        cid = self._selected_channel_id()
        if not cid:
            return
        item = self.channel_list.currentItem()
        name = item.text().split("\n")[0] if item else "this channel"
        confirm = QMessageBox.question(
            self, "Stop watching?", f"Stop watching {name}? Already-downloaded videos are kept.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.web.channel_watcher.remove_channel(cid)
        self._refresh_channels()

    def _on_channel_update(self, _channel):
        # This slot runs on the GUI thread because _channel_update_signal is
        # connected to a QWidget-owned Signal.
        self._refresh_channels()

    def _refresh_channels(self):
        if not hasattr(self, "channel_list"):
            return
        current = self._selected_channel_id()
        self.channel_list.clear()
        restore_row = -1
        for i, c in enumerate(self.web.channel_watcher.list_channels()):
            lines = f"{c['name']}\n{_time_ago(c['last_checked'])} · {c['downloaded_count']} seen · every {c['interval_minutes']}m"
            if c.get("last_error"):
                lines += f"\n⚠ {c['last_error']}"
            item = QListWidgetItem(lines)
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.channel_list.addItem(item)
            if c["id"] == current:
                restore_row = i
        if restore_row >= 0:
            self.channel_list.setCurrentRow(restore_row)

    # =====================================================
    # Library tab
    # =====================================================

    def _build_library_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        hint = QLabel("Everything downloaded so far — including past sessions and watched channels.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        actions = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_library)
        folder_btn = QPushButton("Open Output Folder")
        folder_btn.clicked.connect(self._open_output_folder)
        actions.addWidget(refresh_btn)
        actions.addWidget(folder_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.library_list = QListWidget()
        self.library_list.itemDoubleClicked.connect(lambda _item: self._open_selected_file())
        root.addWidget(self.library_list, 1)

        open_row = QHBoxLayout()
        open_btn = QPushButton("Open")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self._open_selected_file)
        youtube_btn = QPushButton("View on YouTube")
        youtube_btn.clicked.connect(self._open_selected_on_youtube)
        open_row.addStretch(1)
        open_row.addWidget(youtube_btn)
        open_row.addWidget(open_btn)
        root.addLayout(open_row)
        return page

    def _refresh_library(self):
        if not hasattr(self, "library_list"):
            return
        self.library_list.clear()
        output_dir = self.web.get_output_dir()
        for f in library.scan_library(output_dir):
            label = f"{f['name']}\n{f['folder'] or 'Downloads'} · {_fmt_size(f['size'])}"
            if f.get("video_id"):
                label += "  🔗"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, f["rel_path"])
            item.setData(Qt.ItemDataRole.UserRole + 1, f.get("video_url"))
            self.library_list.addItem(item)
        if self.library_list.count() == 0:
            self.library_list.addItem("Nothing downloaded yet.")

    def _open_selected_file(self):
        item = self.library_list.currentItem()
        if item is None:
            return
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        if not rel_path:
            return
        output_dir = self.web.get_output_dir()
        full_path = library.resolve_library_file(output_dir, rel_path)
        if full_path is None:
            QMessageBox.warning(self, "File missing", "That file couldn't be found — it may have been moved or deleted.")
            self._refresh_library()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(full_path))

    def _open_selected_on_youtube(self):
        item = self.library_list.currentItem()
        if item is None:
            return
        video_url = item.data(Qt.ItemDataRole.UserRole + 1)
        if not video_url:
            QMessageBox.information(
                self, "No link found",
                "This file has no hidden source-link tag — it may predate the tagging feature.",
            )
            return
        QDesktopServices.openUrl(QUrl(video_url))

    def _open_output_folder(self):
        output_dir = self.web.get_output_dir()
        if output_dir and os.path.isdir(output_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_dir))


class _YTSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.web = _ensure_server(manager)
        s = read_settings()
        lay = QVBoxLayout(self)
        title = QLabel("Output & cookies")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        form = QFormLayout()
        out_row = QHBoxLayout()
        self.output = QLineEdit(s.get("output_dir") or "")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        cookie_row = QHBoxLayout()
        self.cookie = QLineEdit(s.get("cookie_file") or "")
        browse_c = QPushButton("Browse")
        browse_c.clicked.connect(self._browse_cookie)
        cookie_row.addWidget(self.cookie, 1)
        cookie_row.addWidget(browse_c)
        self.access = QLineEdit(s.get("access_code") or "")
        self.access.setPlaceholderText("Optional phone access code")
        form.addRow("Output folder", out_row)
        form.addRow("Cookie file", cookie_row)
        form.addRow("Access code", self.access)
        lay.addLayout(form)
        save = QPushButton("Save paths")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        lay.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)

        tailscale = manager.container.tailscale_service
        self.ts = TailscalePanel(self, tailscale)
        self.serve = AppServePanel(
            self,
            tailscale=tailscale,
            get_server=lambda: self.web,
            app_key="yt",
            default_port=int(s.get("remote_port") or DEFAULT_REMOTE_PORT),
            title="Remote access (queue from phone)",
            hint="Phone and the browser extension hit this local server over the tailnet.",
        )
        lay.addWidget(self.ts)
        lay.addWidget(self.serve)
        self._poll = QTimer(self)
        self._poll.setInterval(4000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    def _browse_out(self):
        chosen = QFileDialog.getExistingDirectory(self, "Output folder", self.output.text())
        if chosen:
            self.output.setText(chosen)

    def _browse_cookie(self):
        path, _ = QFileDialog.getOpenFileName(self, "Cookie file", self.cookie.text(), "Text (*.txt);;All files (*.*)")
        if path:
            self.cookie.setText(path)

    def _save(self):
        write_settings({
            "output_dir": self.output.text().strip(),
            "cookie_file": self.cookie.text().strip(),
            "access_code": self.access.text().strip(),
            "remote_port": self.serve.current_port(),
        })
        self.web.access_code = self.access.text().strip()

    def _refresh(self):
        write_settings({"remote_port": self.serve.current_port()})

        def work():
            status = self.manager.container.tailscale_service.get_status()
            running = self.web.is_running()
            QTimer.singleShot(0, lambda: self._apply(status, running))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status, running):
        self.ts.apply_status(status)
        self.serve.apply_status(status, running)
