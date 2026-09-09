"""Now — live war room as a Qt page (optional, not home)."""

from __future__ import annotations

import importlib
import os
import threading
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.services import activity_log

REFRESH_MS = 2500


class NowView(QWidget):
    def __init__(self, settings, plugin_manager, page_manager, parent=None):
        super().__init__(parent)
        self.setObjectName("NowRoot")
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.page_manager = page_manager
        self._hub_busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(20, 16, 20, 20)
        self._body.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self._build_header()
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self.servers_box, self.servers_list = self._make_card("Servers")
        self.hub_box, self.hub_body = self._make_card("Remote Hub")
        row1.addWidget(self.servers_box, 1)
        row1.addWidget(self.hub_box, 1)
        self._body.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.media_box, self.media_body = self._make_card("Now playing")
        self.notice_box, self.notice_list = self._make_card("Notifications")
        row2.addWidget(self.media_box, 1)
        row2.addWidget(self.notice_box, 1)
        self._body.addLayout(row2)

        self._build_watchdog()
        self._body.addStretch(1)
        activity_log.subscribe(lambda _e: QTimer.singleShot(0, self._refresh_notices))

    def on_show(self):
        self.refresh()
        self._timer.start()

    def on_hide(self):
        self._timer.stop()

    def _build_header(self):
        header = QFrame()
        header.setObjectName("Panel")
        lay = QVBoxLayout(header)
        lay.setContentsMargins(20, 14, 20, 14)
        title = QLabel("NOW")
        title.setObjectName("AccentTitle")
        self.strip = QLabel("Reading live state…")
        self.strip.setObjectName("Muted")
        lay.addWidget(title)
        lay.addWidget(self.strip)
        self._body.addWidget(header)

    def _make_card(self, title):
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        lay.addWidget(label)
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(6)
        inner.setLayout(inner_lay)
        lay.addWidget(inner, 1)
        return frame, inner

    def _build_watchdog(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        title = QLabel("Watchdog + agent")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        hint = QLabel(
            "Crash restart uses the retry count. Agent writes ask first when confirm is on."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.watch_box = QCheckBox("Crash watchdog")
        self.watch_box.setChecked(self.settings.get("watchdog_enabled") is not False)
        self.watch_box.toggled.connect(
            lambda on: self.settings.set("watchdog_enabled", bool(on))
        )
        self.confirm_box = QCheckBox("Confirm agent writes")
        self.confirm_box.setChecked(self.settings.get("agent_confirm_writes") is not False)
        self.confirm_box.toggled.connect(
            lambda on: self.settings.set("agent_confirm_writes", bool(on))
        )
        row.addWidget(self.watch_box)
        row.addWidget(self.confirm_box)
        retries_label = QLabel("Retries")
        retries_label.setObjectName("Muted")
        row.addWidget(retries_label)
        self.retry_box = QComboBox()
        self.retry_box.addItems(["0", "1", "2", "3"])
        current = str(int(self.settings.get("watchdog_retries") or 2))
        idx = self.retry_box.findText(current)
        self.retry_box.setCurrentIndex(idx if idx >= 0 else 2)
        self.retry_box.currentTextChanged.connect(self._save_retries)
        row.addWidget(self.retry_box)
        row.addStretch(1)
        lay.addLayout(row)
        self._body.addWidget(frame)

    def _save_retries(self, value):
        try:
            self.settings.set("watchdog_retries", int(value))
        except ValueError:
            pass

    def refresh(self):
        servers = self._servers()
        hub = self._hub_status()
        playing = self._now_playing()
        up = sum(1 for s in servers if s.get("running"))
        live_n = sum(1 for v in (hub.get("live_apps") or {}).values() if v)
        unread = activity_log.unread_count()
        bits = [
            f"{up} server{'s' if up != 1 else ''} up" if servers else "no servers",
            "Hub live" if live_n else "Hub offline",
            playing.get("label") or "nothing playing",
        ]
        if unread:
            bits.append(f"{unread} new")
        self.strip.setText("  ·  ".join(bits))
        self._render_servers(servers)
        self._render_hub(hub, live_n)
        self._render_media(playing)
        self._refresh_notices()

    def _servers(self):
        try:
            api = importlib.import_module("modules.Gaming.Game Server Manager.agent_api")
            return api.load_servers_safe()
        except Exception:
            return []

    def _hub_status(self):
        try:
            api = importlib.import_module("modules.Network.remote_hub.agent_api")
            return api.status()
        except Exception as e:
            return {"error": str(e), "live_apps": {}, "running": False}

    def _now_playing(self):
        engine = getattr(self.page_manager, "music_engine", None)
        if engine is None:
            return {"label": "", "state": "idle"}
        try:
            playing = bool(engine.is_playing())
            paused = bool(engine.is_paused()) if hasattr(engine, "is_paused") else False
            meta = engine.get_current_meta() if hasattr(engine, "get_current_meta") else None
            path = None
            if getattr(engine, "playlist", None) and getattr(engine, "index", -1) >= 0:
                try:
                    path = engine.playlist[engine.index]
                except Exception:
                    path = None
            if meta:
                title = meta.get("title") or os.path.basename(meta.get("path") or path or "?")
                artist = meta.get("artist")
                label = f"{artist} — {title}" if artist else title
            elif path:
                label = os.path.basename(str(path))
            else:
                label = ""
            state = "playing" if playing else ("paused" if paused or label else "idle")
            return {"label": label, "state": state}
        except Exception:
            return {"label": "", "state": "idle"}

    def _clear_inner(self, widget):
        lay = widget.layout()
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            child = item.layout()
            if child is not None:
                while child.count():
                    citem = child.takeAt(0)
                    cw = citem.widget()
                    if cw is not None:
                        cw.deleteLater()

    def _muted(self, parent_lay, text):
        lab = QLabel(text)
        lab.setObjectName("Muted")
        lab.setWordWrap(True)
        parent_lay.addWidget(lab)
        return lab

    def _render_servers(self, servers):
        self._clear_inner(self.servers_list)
        lay = self.servers_list.layout()
        if not servers:
            self._muted(lay, "No servers saved yet.")
            btn = QPushButton("Open Game Server Manager")
            btn.clicked.connect(lambda: self._open("Game Server Manager"))
            lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
            lay.addStretch(1)
            return
        for srv in servers:
            row = QFrame()
            row.setObjectName("Panel")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(10, 8, 10, 8)
            left = QVBoxLayout()
            name = QLabel(srv.get("name") or "Server")
            name.setObjectName("CardTitle")
            running = bool(srv.get("running"))
            ready = bool(srv.get("ready"))
            players = srv.get("players") or []
            state = "ready" if ready else ("up" if running else "down")
            who = ", ".join(players) if players else "nobody on"
            meta = QLabel(f"{state}  ·  {who}  ·  {srv.get('game_type') or ''}")
            meta.setObjectName("Success" if running else "Muted")
            left.addWidget(name)
            left.addWidget(meta)
            row_lay.addLayout(left, 1)
            action = QPushButton("Stop" if running else "Start")
            if running:
                action.setObjectName("Danger")
                action.clicked.connect(lambda _=False, s=srv: self._stop_server(s))
            else:
                action.setObjectName("Primary")
                action.clicked.connect(lambda _=False, s=srv: self._start_server(s))
            row_lay.addWidget(action)
            lay.addWidget(row)
        open_btn = QPushButton("Open Game Server Manager")
        open_btn.clicked.connect(lambda: self._open("Game Server Manager"))
        lay.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)

    def _render_hub(self, hub, live_n):
        self._clear_inner(self.hub_body)
        lay = self.hub_body.layout()
        if hub.get("error"):
            err = QLabel(str(hub["error"]))
            err.setObjectName("Error")
            err.setWordWrap(True)
            lay.addWidget(err)
            lay.addStretch(1)
            return
        installed = bool(hub.get("installed"))
        running = bool(hub.get("running"))
        url = hub.get("hub_url") or ""
        status = "Tailscale up" if running else ("installed, offline" if installed else "Tailscale missing")
        status_lab = QLabel(status)
        status_lab.setObjectName("Success" if running else "Muted")
        lay.addWidget(status_lab)
        if url:
            url_lab = QLabel(url)
            url_lab.setObjectName("AccentTitle")
            url_lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(url_lab)
        live = hub.get("live_apps") or {}
        names = [k for k, v in live.items() if v]
        self._muted(
            lay,
            ("Live: " + ", ".join(names)) if names else "No apps exposed on the tailnet.",
        )
        row = QHBoxLayout()
        live_btn = QPushButton("Go Live")
        live_btn.setObjectName("Primary")
        live_btn.setEnabled(not self._hub_busy)
        live_btn.clicked.connect(self._hub_live)
        off_btn = QPushButton("Go Offline")
        off_btn.setEnabled(not self._hub_busy)
        off_btn.clicked.connect(self._hub_offline)
        hub_btn = QPushButton("Hub")
        hub_btn.clicked.connect(lambda: self._open("Remote Hub"))
        row.addWidget(live_btn)
        row.addWidget(off_btn)
        row.addWidget(hub_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._muted(
            lay,
            "Remote sessions: devices on your tailnet hitting the live apps above. "
            "Per-request history is not logged yet — this is who is exposed right now.",
        )
        lay.addStretch(1)

    def _render_media(self, playing):
        self._clear_inner(self.media_body)
        lay = self.media_body.layout()
        label = playing.get("label") or "Nothing playing"
        state = playing.get("state") or "idle"
        title = QLabel(label)
        title.setObjectName("CardTitle" if playing.get("label") else "Muted")
        title.setWordWrap(True)
        lay.addWidget(title)
        self._muted(lay, state)
        btn = QPushButton("Open Media Player")
        btn.clicked.connect(lambda: self._open("Media Player"))
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)

    def _refresh_notices(self):
        if not hasattr(self, "notice_list"):
            return
        self._clear_inner(self.notice_list)
        lay = self.notice_list.layout()
        events = activity_log.recent(12)
        if not events:
            self._muted(lay, "No activity yet. Agent calls and crashes show up here.")
            lay.addStretch(1)
            return
        colors = {
            "error": "Error",
            "warn": "Warn",
            "ok": "Success",
            "info": "Muted",
        }
        for event in events:
            when = datetime.fromtimestamp(event.get("ts", 0)).strftime("%H:%M:%S")
            line = QLabel(f"{when}  {event.get('title') or event.get('kind')}")
            line.setObjectName(colors.get(event.get("level"), "Muted"))
            lay.addWidget(line)
            if event.get("detail"):
                self._muted(lay, event["detail"])
        mark = QPushButton("Mark read")
        mark.clicked.connect(self._mark_read)
        lay.addWidget(mark, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)

    def _mark_read(self):
        activity_log.mark_all_read()
        self._refresh_notices()

    def _open(self, name: str):
        for tool in self.plugin_manager.get_tools():
            if tool.get("name") == name:
                self.page_manager.show_page(name)
                return
        QMessageBox.information(self, "Now", f"{name} isn't loaded.")

    def _start_server(self, srv: dict):
        def work():
            api = importlib.import_module("modules.Gaming.Game Server Manager.agent_api")
            result = api.start_server(srv)
            activity_log.add(
                "notify",
                f"Start {srv.get('name')}",
                "" if result.get("ok") else str(result.get("error") or ""),
                "ok" if result.get("ok") else "error",
            )
            QTimer.singleShot(0, self.refresh)

        threading.Thread(target=work, daemon=True).start()

    def _stop_server(self, srv: dict):
        def work():
            api = importlib.import_module("modules.Gaming.Game Server Manager.agent_api")
            api.stop_server(srv)
            QTimer.singleShot(0, self.refresh)

        threading.Thread(target=work, daemon=True).start()

    def _hub_live(self):
        self._hub_busy = True
        self.refresh()

        def work():
            try:
                api = importlib.import_module("modules.Network.remote_hub.agent_api")
                result = api.go_live()
                activity_log.add(
                    "hub",
                    "Hub went live" if result.get("ok") else "Hub live failed",
                    result.get("hub_url") or result.get("error") or "",
                    "ok" if result.get("ok") else "error",
                )
            except Exception as e:
                activity_log.add("hub", "Hub live failed", str(e), "error")
            self._hub_busy = False
            QTimer.singleShot(0, self.refresh)

        threading.Thread(target=work, daemon=True).start()

    def _hub_offline(self):
        self._hub_busy = True

        def work():
            try:
                api = importlib.import_module("modules.Network.remote_hub.agent_api")
                api.go_offline()
                activity_log.add("hub", "Hub offline", "", "info")
            except Exception as e:
                activity_log.add("hub", "Hub offline failed", str(e), "error")
            self._hub_busy = False
            QTimer.singleShot(0, self.refresh)

        threading.Thread(target=work, daemon=True).start()
