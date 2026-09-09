"""Qt Media Player — artist/folder browser, virtual track table, sticky bar."""

from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import importlib

from core.module_themes import get_saved_module_theme, resolve_module_theme
from core.qt.module_shell import find_qt_module_shell
from core.qt.remote_common import MusicRemoteSettings

_db = importlib.import_module("modules.Media.Media Player.db")
_player = importlib.import_module("modules.Media.Media Player.player")
_types = importlib.import_module("modules.Media.Media Player.media_types")
_index = importlib.import_module("modules.Media.Media Player.auto_index")
Library = _db.Library
FilteredPlaylist = _player.FilteredPlaylist
VLCMusicEngine = _player.VLCMusicEngine
file_dialog_video_types = _types.file_dialog_video_types
AutoIndexer = _index.AutoIndexer

REPEAT_MODES = ("off", "one", "all")
UNKNOWN = "(Unknown)"


def _qss_for_music(bundle):
    t = bundle.t
    accent_bg = getattr(t, "ACCENT_GLOW", None) or getattr(t, "ACCENT_MUTED", t.PANEL_2)
    return f"""
QWidget#MPRoot {{
    background-color: {t.BG};
    color: {t.TEXT};
}}
QWidget#MPRoot QPushButton {{
    background-color: {t.PANEL_2};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
}}
QWidget#MPRoot QPushButton:hover {{
    background-color: {t.PANEL_HOVER};
}}
QWidget#MPRoot QPushButton:disabled {{
    color: {t.MUTED};
    background-color: {t.PANEL};
    border: 1px solid {t.BORDER};
}}
QWidget#MPRoot QPushButton#MPPlayBtn {{
    background-color: {accent_bg};
    color: {t.ACCENT};
    border: 1px solid {t.ACCENT};
    border-radius: 10px;
    padding: 0;
}}
QWidget#MPRoot QPushButton#MPPlayBtn:hover {{
    background-color: {t.ACCENT};
}}
QWidget#MPRoot QPushButton#MPTransportBtn {{
    background-color: transparent;
    border: 1px solid {t.BORDER};
    border-radius: 10px;
    color: {t.ACCENT};
    padding: 0;
}}
QWidget#MPRoot QPushButton#MPTransportBtn:hover {{
    border: 1px solid {t.ACCENT};
}}
QWidget#MPRoot QPushButton#MPPillBtn {{
    background-color: transparent;
    border: 1px solid {t.BORDER};
    border-radius: 16px;
    padding: 0 12px;
    color: {t.MUTED};
    font-size: 12px;
}}
QWidget#MPRoot QPushButton#MPPillBtn:checked {{
    background-color: {t.ACCENT};
    border: 1px solid {t.ACCENT};
    color: {t.PANEL};
    font-weight: 700;
}}
QWidget#MPRoot QPushButton#MPPillBtn:checked:hover {{
    background-color: {t.ACCENT};
}}
QWidget#MPRoot QTableView {{
    background-color: {t.PANEL};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    gridline-color: {t.BORDER};
    outline: none;
}}
QWidget#MPRoot QTableView::item:selected {{
    background: {accent_bg};
    color: {t.ACCENT};
}}
QWidget#MPRoot QHeaderView::section {{
    background-color: {t.PANEL_2};
    color: {t.MUTED};
    border: none;
    border-right: 1px solid {t.BORDER};
    padding: 6px 8px;
    font-weight: 700;
}}
QWidget#MPRoot QListWidget {{
    background-color: {t.PANEL};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    outline: none;
}}
QWidget#MPRoot QListWidget::item:selected {{
    background: {accent_bg};
    color: {t.ACCENT};
}}
QWidget#MPRoot QLabel#MPNowPlaying {{
    color: {t.TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QWidget#MPRoot QWidget#MPBar {{
    background-color: {t.PANEL};
    border-top: 1px solid {t.BORDER};
}}
QWidget#MPRoot QSlider::groove:horizontal {{
    height: 4px;
    background: {t.BORDER};
    border-radius: 2px;
}}
QWidget#MPRoot QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -4px 0;
    background: {t.ACCENT};
    border-radius: 6px;
}}
QWidget#MPRoot QSlider::sub-page:horizontal {{
    background: {t.ACCENT};
    border-radius: 2px;
}}
QWidget#MPRoot QLabel#MPStatus {{
    color: {t.MUTED};
    font-size: 12px;
    padding-top: 6px;
}}
"""


def _fmt_time(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _disk_folders(root):
    if not root or not os.path.isdir(root):
        return []
    out = []
    try:
        for name in sorted(os.listdir(root), key=str.lower):
            path = os.path.join(root, name)
            if os.path.isdir(path) and not name.startswith("."):
                out.append((name, os.path.normpath(path)))
    except OSError:
        pass
    return out[:400]


class TransportButton(QPushButton):
    """Painted prev / play / pause / next — no font-dependent media glyphs."""

    def __init__(self, kind, primary=False, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._ink = QColor("#FFE6F2")
        self._ink_on_accent = QColor("#0a0006")
        self.setObjectName("MPPlayBtn" if primary else "MPTransportBtn")
        side = 40 if primary else 32
        self.setFixedSize(side, side)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip({"play": "Play", "pause": "Pause", "prev": "Previous", "next": "Next"}.get(kind, kind))

    def set_kind(self, kind):
        if kind == self._kind:
            return
        self._kind = kind
        self.setToolTip("Pause" if kind == "pause" else "Play" if kind == "play" else self.toolTip())
        self.update()

    def set_ink(self, color, on_accent=None):
        self._ink = QColor(color)
        if on_accent:
            self._ink_on_accent = QColor(on_accent)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse() and self.isEnabled()
        primary = self.objectName() == "MPPlayBtn"
        color = self._ink_on_accent if primary and hovered else self._ink
        if not self.isEnabled():
            color.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        pad = max(7.0, min(self.width(), self.height()) * 0.24)
        box = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        if self._kind == "play":
            path = QPainterPath()
            path.moveTo(box.left() + box.width() * 0.18, box.top())
            path.lineTo(box.right(), box.center().y())
            path.lineTo(box.left() + box.width() * 0.18, box.bottom())
            path.closeSubpath()
            painter.drawPath(path)
        elif self._kind == "pause":
            gap = box.width() * 0.22
            w = (box.width() - gap) / 2
            painter.drawRoundedRect(QRectF(box.left(), box.top(), w, box.height()), 1.5, 1.5)
            painter.drawRoundedRect(QRectF(box.right() - w, box.top(), w, box.height()), 1.5, 1.5)
        elif self._kind == "prev":
            mid = QPolygonF([
                QPointF(box.right(), box.top()),
                QPointF(box.left() + box.width() * 0.18, box.center().y()),
                QPointF(box.right(), box.bottom()),
            ])
            painter.drawPolygon(mid)
            painter.drawRoundedRect(QRectF(box.left(), box.top(), 2.4, box.height()), 1, 1)
        elif self._kind == "next":
            mid = QPolygonF([
                QPointF(box.left(), box.top()),
                QPointF(box.right() - box.width() * 0.18, box.center().y()),
                QPointF(box.left(), box.bottom()),
            ])
            painter.drawPolygon(mid)
            painter.drawRoundedRect(QRectF(box.right() - 2.4, box.top(), 2.4, box.height()), 1, 1)
        painter.end()


class TrackTableModel(QAbstractTableModel):
    HEADERS = ("Title", "Artist", "Album", "Time")
    CHUNK = 250

    def __init__(self, db):
        super().__init__()
        self.db = db
        self.query = ""
        self.artist = None
        self.folder = None
        self._total = 0
        self._rows = {}

    def set_filter(self, query="", artist=None, folder=None):
        self.beginResetModel()
        self.query = query or ""
        self.artist = artist
        self.folder = folder
        self._rows.clear()
        self._total = self.db.browse_count(
            query=self.query, artist=self.artist, folder=self.folder
        )
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return self._total

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._row(index.row())
        if not row:
            return None
        if role == Qt.ItemDataRole.UserRole:
            return row.get("id")
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        col = index.column()
        if col == 0:
            return row.get("title") or os.path.basename(row.get("path") or "?")
        if col == 1:
            return row.get("artist") or ""
        if col == 2:
            return row.get("album") or ""
        if col == 3:
            return _fmt_time(row.get("duration"))
        return None

    def song_id_at(self, row):
        data = self._row(row)
        return data.get("id") if data else None

    def _row(self, i):
        if i < 0 or i >= self._total:
            return None
        cached = self._rows.get(i)
        if cached is not None:
            return cached
        start = (i // self.CHUNK) * self.CHUNK
        chunk = self.db.browse_rows(
            query=self.query, artist=self.artist, folder=self.folder,
            offset=start, limit=self.CHUNK,
        )
        for j, row in enumerate(chunk):
            self._rows[start + j] = row
        if len(self._rows) > self.CHUNK * 10:
            lo, hi = max(0, start - self.CHUNK), start + self.CHUNK * 2
            self._rows = {k: v for k, v in self._rows.items() if lo <= k < hi}
        return self._rows.get(i)


class MusicPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.db = getattr(manager, "music_db", None) or Library()
        manager.music_db = self.db
        self.engine = getattr(manager, "music_engine", None)
        self._video = None
        self._seeking = False
        self._scan_busy = False
        self._artist = None
        self._folder = None
        self._bundle = None
        self._watch_note = ""
        self._watch_busy = False
        self._watch_t0 = 0.0
        self._shown_song_id = None
        self._status_tick = QTimer(self)
        self._status_tick.setInterval(1000)
        self._status_tick.timeout.connect(self._paint_status)

        self.setObjectName("MPRoot")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_sidebar())
        split.addWidget(self._build_table())
        split.setStretchFactor(1, 1)
        split.setSizes([240, 900])
        root.addWidget(split, 1)
        root.addWidget(self._build_bar())

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._apply_filter)

        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._update_now)

        self.apply_theme()
        self._restore_last()
        QTimer.singleShot(0, self._after_first_paint)

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return MusicRemoteSettings(parent, manager)

    def _build_sidebar(self):
        side = QWidget()
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 10, 8, 10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search library…")
        self.search.textChanged.connect(lambda: self._search_timer.start())
        self.search.returnPressed.connect(self._apply_filter)
        lay.addWidget(self.search)

        all_btn = QPushButton("All tracks")
        all_btn.clicked.connect(self._clear_filters)
        lay.addWidget(all_btn)

        artists_lab = QLabel("Artists")
        artists_lab.setObjectName("Muted")
        lay.addWidget(artists_lab)
        self.artists = QListWidget()
        self.artists.itemClicked.connect(self._pick_artist)
        lay.addWidget(self.artists, 3)

        folders_lab = QLabel("Folders")
        folders_lab.setObjectName("Muted")
        lay.addWidget(folders_lab)
        self.folders = QListWidget()
        self.folders.itemClicked.connect(self._pick_folder_item)
        lay.addWidget(self.folders, 2)

        self.folder = QLineEdit(self.db.get_setting("music_folder") or "")
        self.folder.setPlaceholderText("Music folder")
        lay.addWidget(self.folder)
        row = QHBoxLayout()
        browse = QPushButton("Folder")
        browse.clicked.connect(self._pick_root)
        scan = QPushButton("Rescan")
        scan.clicked.connect(self._rescan)
        row.addWidget(browse)
        row.addWidget(scan)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("MPStatus")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(36)
        lay.addWidget(self.status)
        return side

    def _build_table(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 10, 10, 8)
        self.count_lab = QLabel("")
        self.count_lab.setObjectName("Muted")
        lay.addWidget(self.count_lab)
        self.model = TrackTableModel(self.db)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.doubleClicked.connect(self._play_index)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.table, 1)
        return host

    def _build_bar(self):
        bar = QWidget()
        bar.setObjectName("MPBar")
        bar.setFixedHeight(120)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(6)
        self.now = QLabel("Nothing playing")
        self.now.setObjectName("MPNowPlaying")
        lay.addWidget(self.now)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        self.time_lab = QLabel("0:00")
        self.time_lab.setObjectName("Muted")
        self.time_lab.setFixedWidth(40)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setFixedHeight(18)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.len_lab = QLabel("0:00")
        self.len_lab.setObjectName("Muted")
        self.len_lab.setFixedWidth(40)
        seek_row.addWidget(self.time_lab)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.len_lab)
        lay.addLayout(seek_row)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        transport.setContentsMargins(0, 0, 0, 0)
        self.shuffle_btn = QPushButton("Shuffle")
        self.shuffle_btn.setObjectName("MPPillBtn")
        self.shuffle_btn.setCheckable(True)
        self.shuffle_btn.setFixedHeight(32)
        self.shuffle_btn.setChecked(bool(getattr(self.engine, "shuffle", False)))
        self.shuffle_btn.toggled.connect(self._toggle_shuffle)
        self.prev_btn = TransportButton("prev")
        self.play_btn = TransportButton("play", primary=True)
        self.next_btn = TransportButton("next")
        self.repeat_btn = QPushButton(self._repeat_label())
        self.repeat_btn.setObjectName("MPPillBtn")
        self.repeat_btn.setFixedHeight(32)
        self.prev_btn.clicked.connect(self._prev)
        self.play_btn.clicked.connect(self._play_pause)
        self.next_btn.clicked.connect(self._next)
        self.repeat_btn.clicked.connect(self._cycle_repeat)
        video = QPushButton("Video")
        video.setFixedHeight(32)
        video.clicked.connect(self._open_video)
        transport.addWidget(self.shuffle_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        transport.addWidget(self.prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        transport.addWidget(self.play_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        transport.addWidget(self.next_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        transport.addWidget(self.repeat_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        transport.addSpacing(12)
        vol_lab = QLabel("Volume")
        vol_lab.setObjectName("Muted")
        transport.addWidget(vol_lab, 0, Qt.AlignmentFlag.AlignVCenter)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 200)
        self.vol.setFixedWidth(120)
        self.vol.setFixedHeight(18)
        self.vol.setValue(int((getattr(self.engine, "volume", 0.8) or 0.8) * 100))
        self.vol.valueChanged.connect(self._set_volume)
        transport.addWidget(self.vol, 0, Qt.AlignmentFlag.AlignVCenter)
        transport.addStretch(1)
        transport.addWidget(video, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(transport)
        return bar

    def apply_theme(self, theme_id=None):
        shell = find_qt_module_shell(self)
        if shell is not None and getattr(shell, "_bundle", None) is not None:
            bundle = shell._bundle
        else:
            settings = getattr(self.manager, "settings", None)
            saved = get_saved_module_theme(settings, "Media Player") if settings else theme_id
            bundle = resolve_module_theme(theme_id or saved)
        self._bundle = bundle
        self.setStyleSheet(_qss_for_music(bundle))
        ink = bundle.t.ACCENT
        on = getattr(bundle, "on_accent", "#0a0006")
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.set_ink(ink, on)

    def _after_first_paint(self):
        self._apply_filter()
        self._paint_status()
        self._refresh_sidebar_async()
        QTimer.singleShot(0, self._ensure_engine)
        self._start_indexer()
        if not self._tick.isActive():
            self._tick.start()

    def _folder_label(self):
        raw = self.folder.text().strip().rstrip("\\/")
        return os.path.basename(raw) or raw or "library"

    def _paint_status(self):
        try:
            total = self.db.count()
        except Exception:
            total = self.model.rowCount()
        head = f"{total:,} tracks in {self._folder_label()}"
        note = self._watch_note
        if self._watch_busy:
            sec = max(0, int(time.monotonic() - self._watch_t0))
            note = f"Setting up live updates… {sec}s — you can play now"
        self.status.setText(f"{head}\n{note}" if note else head)

    def _on_indexer_status(self, text):
        text = (text or "").strip()
        if text.startswith("Starting library watch"):
            self._watch_busy = True
            self._watch_t0 = time.monotonic()
            self._watch_note = "Setting up live updates… — you can play now"
            if not self._status_tick.isActive():
                self._status_tick.start()
            self._paint_status()
            return
        self._watch_busy = False
        self._status_tick.stop()
        if text.startswith("Watching for changes"):
            self._watch_note = "Live folder updates on"
        elif text.startswith("Auto-indexing"):
            self._watch_note = "Background refresh on"
        else:
            self._watch_note = text
        self._paint_status()

    def _ensure_engine(self):
        if self.engine is not None:
            return
        existing = getattr(self.manager, "music_engine", None)
        if existing is not None:
            self.engine = existing
            return
        self.engine = VLCMusicEngine()
        self.manager.music_engine = self.engine

    def on_hide(self):
        self._tick.stop()

    def on_show(self):
        if not self._tick.isActive():
            self._tick.start()
        self._update_now()

    def _restore_last(self):
        raw = self.db.get_setting("last_song_id")
        if not raw:
            return
        try:
            song = self.db.get_song(int(raw))
        except (TypeError, ValueError):
            return
        if song:
            self._set_now_text(song)

    def _set_now_text(self, meta):
        title = (meta or {}).get("title") or os.path.basename((meta or {}).get("path") or "?")
        artist = (meta or {}).get("artist")
        self.now.setText(f"{artist} — {title}" if artist else title)

    def _playlist(self):
        return FilteredPlaylist(
            self.db, query=self.search.text().strip(),
            artist=self._artist, folder=self._folder,
        )

    def _bind_queue(self, start_row=None, song_id=None):
        self._ensure_engine()
        playlist = self._playlist()
        self.engine.playlist = playlist
        self.engine.db = self.db
        if start_row is not None:
            self.engine.index = start_row
            return playlist
        if song_id is not None and hasattr(playlist, "index_of"):
            found = playlist.index_of(song_id)
            if found >= 0:
                self.engine.index = found
                return playlist
        if getattr(self.engine, "index", -1) < 0 and playlist:
            self.engine.index = 0
        return playlist

    def _apply_filter(self):
        self.model.set_filter(
            query=self.search.text().strip(),
            artist=self._artist,
            folder=self._folder,
        )
        self.count_lab.setText(f"{self.model.rowCount():,} tracks")
        # The filter changed, so a row we previously highlighted may no
        # longer be at the same position (or visible at all) — force
        # _follow_song to re-resolve the now-playing song against the
        # new view instead of assuming it's already showing correctly.
        self._shown_song_id = None

    def _clear_filters(self):
        self._artist = None
        self._folder = None
        self.artists.clearSelection()
        self.folders.clearSelection()
        self._apply_filter()

    def _pick_artist(self, item):
        name = item.data(Qt.ItemDataRole.UserRole)
        self._artist = name
        self._folder = None
        self.folders.clearSelection()
        self._apply_filter()

    def _pick_folder_item(self, item):
        self._folder = item.data(Qt.ItemDataRole.UserRole)
        self._artist = None
        self.artists.clearSelection()
        self._apply_filter()

    def _refresh_sidebar(self):
        self._refresh_sidebar_async()

    def _refresh_sidebar_async(self):
        root = self.folder.text().strip()

        def work():
            try:
                artists = self.db.list_artists()
            except Exception as exc:
                print(f"[MusicPage] artists: {exc}")
                artists = []
            folders = _disk_folders(root)
            QTimer.singleShot(0, lambda: self._fill_sidebar(artists, folders, root))

        threading.Thread(target=work, daemon=True).start()

    def _fill_sidebar(self, artists, folders, root):
        if self.folder.text().strip() != root:
            return
        self.artists.blockSignals(True)
        self.artists.clear()
        for name, n in artists:
            label = UNKNOWN if not name else name
            item = QListWidgetItem(f"{label}  ·  {n}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.artists.addItem(item)
        self.artists.blockSignals(False)

        self.folders.blockSignals(True)
        self.folders.clear()
        if root:
            here = QListWidgetItem("This folder")
            here.setData(Qt.ItemDataRole.UserRole, os.path.normpath(root))
            self.folders.addItem(here)
        for name, path in folders:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.folders.addItem(item)
        self.folders.blockSignals(False)

    def _start_indexer(self):
        folder = self.folder.text().strip()
        if not folder:
            return
        indexer = getattr(self.manager, "music_indexer", None)
        if indexer is None:
            indexer = AutoIndexer(self.db)
            self.manager.music_indexer = indexer
        if indexer.running and indexer.folder == os.path.normcase(os.path.normpath(folder)):
            return
        indexer.start(
            folder,
            status_cb=lambda text: QTimer.singleShot(0, lambda t=text: self._on_indexer_status(t)),
            scan_busy_cb=lambda: self._scan_busy,
        )

    def _pick_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Music folder", self.folder.text())
        if not chosen:
            return
        self.folder.setText(chosen)
        self.db.set_setting("music_folder", chosen)
        self._refresh_sidebar()
        self._start_indexer()
        self._rescan()

    def _rescan(self):
        folder = self.folder.text().strip()
        if not folder:
            return
        self._scan_busy = True
        self._watch_busy = False
        self._status_tick.stop()
        self._watch_note = "Scanning folder for new files…"
        self._paint_status()

        def work():
            try:
                self.db.scan(folder, full=True)
            except Exception as e:
                print(f"[MusicPage] scan: {e}")
            self._scan_busy = False
            QTimer.singleShot(0, self._after_scan)

        threading.Thread(target=work, daemon=True).start()

    def _after_scan(self):
        self._watch_note = "Scan finished"
        self._paint_status()
        self._refresh_sidebar()
        self._apply_filter()

    def _play_index(self, index):
        row = index.row()
        sid = self.model.song_id_at(row)
        playlist = self._bind_queue(start_row=row)
        if not playlist:
            return
        self.engine.play_at(row)
        if sid is not None:
            self.db.set_setting("last_song_id", str(sid))
        self._update_now()

    def _repeat_label(self):
        mode = getattr(self.engine, "repeat_mode", "off")
        return {"off": "Repeat: off", "one": "Repeat: one", "all": "Repeat: all"}.get(mode, "Repeat: off")

    def _set_volume(self, value):
        self._ensure_engine()
        self.engine.set_volume(value / 100.0)

    def _toggle_shuffle(self, on):
        self._ensure_engine()
        self.engine.shuffle = bool(on)

    def _cycle_repeat(self):
        self._ensure_engine()
        mode = getattr(self.engine, "repeat_mode", "off")
        nxt = REPEAT_MODES[(REPEAT_MODES.index(mode) + 1) % len(REPEAT_MODES)] if mode in REPEAT_MODES else "off"
        self.engine.repeat_mode = nxt
        self.repeat_btn.setText(self._repeat_label())

    def _seek_released(self):
        if self.engine is None:
            self._seeking = False
            return
        length = 0
        try:
            length = self.engine.get_length() or 0
        except Exception:
            pass
        if length > 0:
            self.engine.seek((self.seek.value() / 1000.0) * length)
        self._seeking = False

    def _prev(self):
        if not getattr(self.engine, "playlist", None):
            self._bind_queue()
        self.engine.prev()
        self._update_now()

    def _next(self):
        if not getattr(self.engine, "playlist", None):
            self._bind_queue()
        self.engine.next()
        self._update_now()

    def _play_pause(self):
        if self.engine is not None and self.engine.is_playing():
            self.engine.pause()
        else:
            raw = self.db.get_setting("last_song_id")
            sid = int(raw) if raw and str(raw).isdigit() else None
            playlist = self._bind_queue(song_id=sid)
            if not playlist:
                return
            self.engine.play()
        self._update_now()

    def _open_video(self):
        if self._video is None:
            self._video = VideoWindow(self, self.manager)
        self._video.show()
        self._video.raise_()
        self._video.activateWindow()

    def _update_now(self):
        if self.engine is None:
            return
        try:
            meta = self.engine.get_current_meta() if hasattr(self.engine, "get_current_meta") else None
            playing = self.engine.is_playing()
            sid = None
            if meta:
                self._set_now_text(meta)
                sid = meta.get("id")
                if sid is not None:
                    self.db.set_setting("last_song_id", str(sid))
            elif not self.now.text() or self.now.text() == "Nothing playing":
                self.now.setText("Nothing playing")
            self.play_btn.set_kind("pause" if playing else "play")
            playlist = getattr(self.engine, "playlist", None)
            has_playlist = bool(playlist)
            can_move = has_playlist and len(playlist) > 0
            self.prev_btn.setEnabled(can_move)
            self.next_btn.setEnabled(can_move)
            self._follow_song(sid)
            pos = self.engine.get_time() if hasattr(self.engine, "get_time") else 0
            length = self.engine.get_length() if hasattr(self.engine, "get_length") else 0
            self.time_lab.setText(_fmt_time(pos))
            self.len_lab.setText(_fmt_time(length))
            if not self._seeking and length > 0:
                self.seek.blockSignals(True)
                self.seek.setValue(int((pos / length) * 1000))
                self.seek.blockSignals(False)
            self.repeat_btn.setText(self._repeat_label())
            self.shuffle_btn.blockSignals(True)
            self.shuffle_btn.setChecked(bool(getattr(self.engine, "shuffle", False)))
            self.shuffle_btn.blockSignals(False)
        except Exception as exc:
            print(f"[MusicPage] now playing: {exc}")

    def _follow_song(self, song_id):
        """
        Highlights the row for `song_id` in the *table's own* current
        filter/search view. engine.index is a position in whatever
        playlist was bound when playback started, which can be a
        completely different filtered set than what the table is
        showing right now (e.g. the user searched after hitting play) —
        so we look the song up by id against the table's own filter
        instead of trusting engine.index as a row number directly.
        """
        if song_id is None:
            return
        if song_id == self._shown_song_id:
            return
        try:
            row = self.db.browse_index_of(
                int(song_id), query=self.model.query,
                artist=self.model.artist, folder=self.model.folder,
            )
        except Exception:
            return
        if row is None or row < 0 or row >= self.model.rowCount():
            # Not visible under the current filter — leave whatever
            # was last shown alone rather than selecting the wrong row.
            return
        self._shown_song_id = song_id
        self.table.selectRow(row)
        self.table.scrollTo(self.model.index(row, 0))


class VideoWindow(QDialog):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.setWindowTitle("Video")
        self.resize(960, 640)
        self.manager = manager
        video = importlib.import_module("modules.Media.Media Player.video_engine")
        self._is_url = video.is_url
        self._url_display_name = video.url_display_name
        self.engine = getattr(manager, "media_engine", None)
        if self.engine is None:
            self.engine = video.VLCMediaEngine()
            manager.media_engine = self.engine
        self._seeking = False
        root = QVBoxLayout(self)
        self.surface = QWidget()
        self.surface.setMinimumHeight(240)
        self.surface.setStyleSheet("background: #000;")
        root.addWidget(self.surface, 3)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._play_item)
        root.addWidget(self.list, 1)
        seek_row = QHBoxLayout()
        self.time_lab = QLabel("0:00")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.len_lab = QLabel("0:00")
        seek_row.addWidget(self.time_lab)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.len_lab)
        root.addLayout(seek_row)
        row = QHBoxLayout()
        add = QPushButton("Add files")
        add.clicked.connect(self._add_files)
        add_url = QPushButton("Add URL")
        add_url.clicked.connect(self._add_url)
        row.addWidget(add)
        row.addWidget(add_url)
        row.addStretch(1)
        self.prev_btn = QPushButton("Prev")
        self.play_btn = QPushButton("Play")
        self.next_btn = QPushButton("Next")
        self.prev_btn.clicked.connect(self._prev)
        self.play_btn.clicked.connect(self._play_pause)
        self.next_btn.clicked.connect(self._next)
        row.addWidget(self.prev_btn)
        row.addWidget(self.play_btn)
        row.addWidget(self.next_btn)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(remove)
        root.addLayout(row)
        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._tick_ui)
        self._tick.start()
        self._refresh_list()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._attach_hwnd)

    def _attach_hwnd(self):
        handle = int(self.surface.winId())
        try:
            if sys.platform.startswith("win"):
                self.engine.player.set_hwnd(handle)
            elif sys.platform == "linux":
                self.engine.player.set_xwindow(handle)
            elif sys.platform == "darwin":
                self.engine.player.set_nsobject(handle)
        except Exception as e:
            print(f"[Video] video output: {e}")

    def _filters(self):
        parts = [f"{label} ({pattern})" for label, pattern in file_dialog_video_types()]
        return ";;".join(parts)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add video", "", self._filters())
        for path in paths:
            self.engine.add_track(path)
        self._refresh_list()

    def _add_url(self):
        from PySide6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, "Add URL", "http(s) video URL")
        if ok and url.strip():
            self.engine.add_track(url.strip())
            self._refresh_list()

    def _refresh_list(self):
        self.list.clear()
        for i, path in enumerate(self.engine.playlist):
            name = self._url_display_name(path) if self._is_url(path) else os.path.basename(path)
            mark = "> " if i == self.engine.index else ""
            item = QListWidgetItem(f"{mark}{name}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(item)
        self._update_transport()

    def _play_item(self, item):
        self._attach_hwnd()
        self.engine.play_at(item.data(Qt.ItemDataRole.UserRole))
        self._refresh_list()

    def _play_pause(self):
        if self.engine.is_playing():
            self.engine.pause()
        else:
            self._attach_hwnd()
            self.engine.play()
        self._refresh_list()

    def _next(self):
        self._attach_hwnd()
        self.engine.next()
        self._refresh_list()

    def _prev(self):
        self._attach_hwnd()
        self.engine.prev()
        self._refresh_list()

    def _update_transport(self):
        self.play_btn.setText("Pause" if self.engine.is_playing() else "Play")
        playlist = getattr(self.engine, "playlist", None)
        index = getattr(self.engine, "index", -1)
        self.prev_btn.setEnabled(bool(playlist) and index > 0)
        self.next_btn.setEnabled(bool(playlist) and index + 1 < len(playlist))

    def _remove(self):
        item = self.list.currentItem()
        if item is None:
            return
        self.engine.remove_track(item.data(Qt.ItemDataRole.UserRole))
        self._refresh_list()

    def _seek_released(self):
        length = self.engine.get_length() or 0
        if length > 0:
            self.engine.seek((self.seek.value() / 1000.0) * length)
        self._seeking = False

    def _tick_ui(self):
        pos = self.engine.get_time()
        length = self.engine.get_length()
        self.time_lab.setText(_fmt_time(pos))
        self.len_lab.setText(_fmt_time(length))
        if not self._seeking and length > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int((pos / length) * 1000))
            self.seek.blockSignals(False)
        self._update_transport()
