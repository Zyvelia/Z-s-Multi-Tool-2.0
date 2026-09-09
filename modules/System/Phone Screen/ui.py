"""Qt Phone Screen — ADB mirror with tap/swipe, optional scrcpy, and native
window embedding for local emulators. Supports multiple independent docks
so you can run several mirrors/emulator windows side by side.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QWheelEvent, QKeyEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

backend = importlib.import_module("modules.System.Phone Screen.backend")

_IS_WINDOWS = sys.platform == "win32"


class _ScreenLabel(QLabel):
    """ADB-mirror display surface — forwards mouse/keyboard to the owning dock."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setText("Connect a phone (USB debugging) or start an emulator, then Refresh.")
        self.setObjectName("Muted")

    def mousePressEvent(self, event: QMouseEvent):
        self._owner._on_press(event)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._owner._on_release(event)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        self._owner._on_wheel(event)

    def keyPressEvent(self, event: QKeyEvent):
        self._owner._on_key(event)


class _EmbedContainer(QWidget):
    """Native-window host for Window Embed mode. A real emulator window gets
    reparented on top of this widget and resized to fill it."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self.setMinimumSize(240, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #000;")
        self._shown_once = False

    def resizeEvent(self, event):
        self._owner._on_embed_resize(self.width(), self.height())
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            QTimer.singleShot(0, self._owner._on_embed_container_ready)


class _MirrorDock(QFrame):
    """One self-contained phone/emulator mirror — device picker, controls, and
    the live screen. Either polls ADB screencaps, or (for local emulators)
    embeds the emulator's real window directly."""

    _devices_ready = Signal(list, object)
    _tcp_connect_ready = Signal(object, object)
    _tcp_disconnect_ready = Signal()
    _mirror_ready = Signal(str, tuple, object)
    _frame_ready = Signal(object, object)
    _nav_error_ready = Signal(str)
    _embed_windows_ready = Signal(list, object)
    _embed_done = Signal(object)

    def __init__(self, parent, dock_num: int, on_close):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.dock_num = dock_num
        self._on_close = on_close

        self.mode = "adb"
        self._devices = []
        self._serial = ""
        self._dev_w = 1080
        self._dev_h = 1920
        self._disp_w = 1
        self._disp_h = 1
        self._mirroring = False
        self._busy_frame = False
        self._press = None
        self._scrcpy = None

        self._embed_windows: list = []
        self._embed_state = None  # backend.EmbedState while embedded
        self._embed_hwnd = 0

        self._devices_ready.connect(self._devices_done)
        self._tcp_connect_ready.connect(self._tcp_done)
        self._tcp_disconnect_ready.connect(self._refresh_devices)
        self._mirror_ready.connect(self._start_mirror)
        self._frame_ready.connect(self._show_frame)
        self._nav_error_ready.connect(lambda err: QMessageBox.warning(self, "Phone Screen", err))
        self._embed_windows_ready.connect(self._embed_windows_done)
        self._embed_done.connect(self._embed_finished)

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel(f"Screen {dock_num}")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        header.addStretch(1)
        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(28)
        close_btn.setToolTip("Remove this screen")
        close_btn.clicked.connect(self._request_close)
        header.addWidget(close_btn)
        root.addLayout(header)

        mode_row = QHBoxLayout()
        self.adb_mode_btn = QPushButton("ADB Mirror")
        self.adb_mode_btn.setCheckable(True)
        self.adb_mode_btn.setChecked(True)
        self.embed_mode_btn = QPushButton("Embed Window (local emulator)")
        self.embed_mode_btn.setCheckable(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.adb_mode_btn)
        self._mode_group.addButton(self.embed_mode_btn)
        self.adb_mode_btn.clicked.connect(lambda: self._set_mode("adb"))
        self.embed_mode_btn.clicked.connect(lambda: self._set_mode("embed"))
        mode_row.addWidget(self.adb_mode_btn)
        mode_row.addWidget(self.embed_mode_btn)
        if not _IS_WINDOWS:
            self.embed_mode_btn.setEnabled(False)
            self.embed_mode_btn.setToolTip("Window embedding is Windows-only.")
        root.addLayout(mode_row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        body = QHBoxLayout()
        side = QFrame()
        side.setObjectName("Panel")
        sl = QVBoxLayout(side)

        dt = QLabel("Devices")
        dt.setObjectName("CardTitle")
        sl.addWidget(dt)
        self.device = QComboBox()
        sl.addWidget(self.device)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_devices)
        sl.addWidget(refresh)
        diag = QPushButton("Diagnostics")
        diag.clicked.connect(self._show_diagnostics)
        sl.addWidget(diag)
        tcp_l = QLabel("Wireless ADB (ip:port)")
        tcp_l.setObjectName("Muted")
        sl.addWidget(tcp_l)
        self.tcp = QLineEdit()
        self.tcp.setPlaceholderText("127.0.0.1:5555 or 192.168.1.20:5555")
        sl.addWidget(self.tcp)
        tcp_row = QHBoxLayout()
        conn = QPushButton("Connect")
        conn.clicked.connect(self._tcp_connect)
        disc = QPushButton("Disconnect")
        disc.clicked.connect(self._tcp_disconnect)
        tcp_row.addWidget(conn)
        tcp_row.addWidget(disc)
        sl.addLayout(tcp_row)
        self.awake = QCheckBox("Keep phone awake while mirrored")
        self.awake.setChecked(True)
        sl.addWidget(self.awake)
        self.mirror_btn = QPushButton("Start mirror")
        self.mirror_btn.setObjectName("Primary")
        self.mirror_btn.clicked.connect(self._toggle_mirror)
        sl.addWidget(self.mirror_btn)
        scrcpy = QPushButton("HD window (scrcpy)")
        scrcpy.clicked.connect(self._open_scrcpy)
        sl.addWidget(scrcpy)
        self._adb_widgets = [self.mirror_btn, scrcpy, self.awake]

        embed_l = QLabel("Emulator windows")
        embed_l.setObjectName("Muted")
        sl.addWidget(embed_l)
        self.embed_combo = QComboBox()
        sl.addWidget(self.embed_combo)
        embed_row = QHBoxLayout()
        embed_refresh = QPushButton("Scan windows")
        embed_refresh.clicked.connect(self._refresh_embed_windows)
        self.embed_btn = QPushButton("Embed")
        self.embed_btn.setObjectName("Primary")
        self.embed_btn.clicked.connect(self._toggle_embed)
        embed_row.addWidget(embed_refresh)
        embed_row.addWidget(self.embed_btn)
        sl.addLayout(embed_row)
        self._embed_widgets = [embed_l, self.embed_combo, embed_refresh, self.embed_btn]

        nav = QHBoxLayout()
        for label, key in (("Back", "4"), ("Home", "3"), ("Recents", "187"), ("Power", "26")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, k=key: self._nav(k))
            nav.addWidget(btn)
        sl.addLayout(nav)
        note = QLabel(
            "ADB Mirror: click/type on the picture for real taps and keys.\n"
            "Embed Window: shows the emulator's actual live window, full speed — "
            "click it like any normal window. Local emulators only."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        sl.addWidget(note)
        sl.addStretch(1)
        body.addWidget(side)

        stage = QFrame()
        stage.setObjectName("Panel")
        st = QVBoxLayout(stage)
        self.screen = _ScreenLabel(self)
        self.embed_container = _EmbedContainer(self)
        self.embed_container.hide()
        st.addWidget(self.screen, 1)
        st.addWidget(self.embed_container, 1)
        body.addWidget(stage, 1)
        root.addLayout(body, 1)

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(140)
        self._frame_timer.timeout.connect(self._grab_frame)
        # Stagger the first scan per dock — adding several screens back to
        # back used to fire every dock's adb scan at once, which could
        # overwhelm the adb server/process table. _ADB_LOCK in backend.py
        # now serializes the actual adb calls too, but staggering keeps the
        # UI responsive while several scans queue up.
        QTimer.singleShot(200 + (dock_num - 1) * 400, self._refresh_devices)
        self._set_status()
        self._apply_mode_visibility()

    # -- lifecycle ---------------------------------------------------------

    def cleanup(self):
        """Called before this dock is removed or the page closes."""
        self._stop_mirror()
        self._stop_scrcpy()
        self._detach_embed()

    def on_hide(self):
        if self._mirroring:
            self._frame_timer.stop()

    def on_show(self):
        if self._mirroring and not self._frame_timer.isActive():
            self._frame_timer.start()

    def _request_close(self):
        self._on_close(self)

    # -- mode switching ------------------------------------------------

    def _set_mode(self, mode: str):
        if mode == self.mode:
            return
        if mode == "embed" and self._mirroring:
            self._stop_mirror()
        if mode == "adb" and self._embed_state is not None:
            self._detach_embed()
        self.mode = mode
        self._apply_mode_visibility()

    def _apply_mode_visibility(self):
        adb_on = self.mode == "adb"
        self.screen.setVisible(adb_on)
        self.embed_container.setVisible(not adb_on)
        for w in self._adb_widgets:
            w.setEnabled(adb_on)
        for w in self._embed_widgets:
            w.setEnabled(not adb_on)
        self.embed_btn.setText("Detach" if self._embed_state is not None else "Embed")

    # -- status --------------------------------------------------------

    def _set_status(self, extra: str = ""):
        adb = backend.find_adb()
        scrcpy = backend.find_scrcpy()
        parts = [
            f"adb: {adb}" if adb else "adb: not found (install Android platform-tools)",
            f"scrcpy: {scrcpy}" if scrcpy else "scrcpy: not installed (optional — winget install Genymobile.scrcpy)",
        ]
        if extra:
            parts.append(extra)
        self.status.setObjectName("Success" if adb else "Danger")
        self.status.setText(" · ".join(parts))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # -- ADB device list -------------------------------------------------

    def _selected_serial(self) -> str:
        label = self.device.currentText()
        for device in self._devices:
            if device.label == label and device.state == "device":
                return device.serial
        if len(self._devices) == 1 and self._devices[0].state == "device":
            return self._devices[0].serial
        return ""

    def _refresh_devices(self):
        def work():
            err = None
            devices = []
            try:
                devices = backend.list_devices()
            except backend.AdbError as e:
                err = str(e)
            self._devices_ready.emit(devices, err)

        threading.Thread(target=work, daemon=True).start()

    def _devices_done(self, devices, err):
        if err:
            self._devices = []
            QMessageBox.warning(self, "Phone Screen", err)
            self._set_status()
            return
        self._devices = devices
        labels = [d.label for d in self._devices] or ["(none)"]
        current = self.device.currentText()
        self.device.clear()
        self.device.addItems(labels)
        if current in labels:
            self.device.setCurrentText(current)
        extra = f"{len(self._devices)} device(s)"
        note = backend.emulator_status_note(device_count=len(self._devices))
        if note:
            extra = f"{extra} · {note}"
        self._set_status(extra)

    def _show_diagnostics(self):
        box = QMessageBox(self)
        box.setWindowTitle("Phone Screen — Scan diagnostics")
        box.setText(
            "Trace of the last device scan (Refresh). Shows exactly which "
            "ports were tried, whether they were open, and what adb said."
        )
        box.setDetailedText(backend.get_scan_log())
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _tcp_connect(self):
        address = self.tcp.text().strip()
        if not address:
            QMessageBox.information(self, "Phone Screen", "Enter the phone IP (and port, default 5555).")
            return

        def work():
            err = result = None
            try:
                result = backend.connect_tcp(address)
            except backend.AdbError as e:
                err = str(e)
            self._tcp_connect_ready.emit(result, err)

        threading.Thread(target=work, daemon=True).start()

    def _tcp_done(self, result, err):
        if err:
            QMessageBox.warning(self, "Phone Screen", err)
            return
        self._set_status(result or "")
        self._refresh_devices()

    def _tcp_disconnect(self):
        address = self.tcp.text().strip()
        if not address:
            return

        def work():
            try:
                backend.disconnect_tcp(address)
            except backend.AdbError:
                pass
            self._tcp_disconnect_ready.emit()

        threading.Thread(target=work, daemon=True).start()

    # -- ADB mirror ------------------------------------------------------

    def _toggle_mirror(self):
        if self._mirroring:
            self._stop_mirror()
            return
        serial = self._selected_serial()
        if not serial:
            QMessageBox.information(
                self, "Phone Screen",
                "No device ready. Plug in USB, start BlueStacks, or Connect wireless, then Refresh.",
            )
            return

        def work():
            err = None
            size = (1080, 1920)
            try:
                size = backend.wm_size(serial)
            except backend.AdbError as e:
                err = str(e)
            self._mirror_ready.emit(serial, size, err)

        threading.Thread(target=work, daemon=True).start()

    def _start_mirror(self, serial, size, err):
        if err:
            QMessageBox.warning(self, "Phone Screen", err)
            return
        self._dev_w, self._dev_h = size
        self._serial = serial
        self._mirroring = True
        self.mirror_btn.setText("Stop mirror")
        if self.awake.isChecked():
            def stay():
                try:
                    backend.stay_awake(serial, True)
                except backend.AdbError:
                    pass
            threading.Thread(target=stay, daemon=True).start()
        self.screen.setFocus()
        self._frame_timer.start()
        self._grab_frame()

    def _stop_mirror(self):
        was = self._mirroring
        self._mirroring = False
        self._frame_timer.stop()
        serial = self._serial
        self.mirror_btn.setText("Start mirror")
        if was and serial and self.awake.isChecked():
            def stay():
                try:
                    backend.stay_awake(serial, False)
                except backend.AdbError:
                    pass
            threading.Thread(target=stay, daemon=True).start()

    def _grab_frame(self):
        if not self._mirroring or self._busy_frame:
            return
        serial = self._serial
        self._busy_frame = True

        def work():
            err = None
            data = None
            try:
                data = backend.screencap(serial)
            except Exception as e:
                err = str(e)
            self._frame_ready.emit(data, err)

        threading.Thread(target=work, daemon=True).start()

    def _show_frame(self, data, err):
        self._busy_frame = False
        if not self._mirroring:
            return
        if err:
            self._mirror_failed(err)
            return
        image = QImage.fromData(data, "PNG")
        if image.isNull():
            self._mirror_failed("screencap did not return a PNG.")
            return
        self._dev_w, self._dev_h = image.width(), image.height()
        pix = QPixmap.fromImage(image)
        scaled = pix.scaled(
            self.screen.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._disp_w, self._disp_h = scaled.width(), scaled.height()
        self.screen.setPixmap(scaled)
        self.screen.setText("")

    def _mirror_failed(self, err: str):
        self._stop_mirror()
        QMessageBox.warning(self, "Phone Screen", err)

    def _to_device(self, event) -> tuple[int, int] | None:
        if self._disp_w <= 1 or self._disp_h <= 1:
            return None
        off_x = max(0, (self.screen.width() - self._disp_w) / 2)
        off_y = max(0, (self.screen.height() - self._disp_h) / 2)
        local_x = event.position().x() - off_x
        local_y = event.position().y() - off_y
        if local_x < 0 or local_y < 0 or local_x > self._disp_w or local_y > self._disp_h:
            return None
        x = int(local_x / self._disp_w * self._dev_w)
        y = int(local_y / self._disp_h * self._dev_h)
        x = max(0, min(self._dev_w - 1, x))
        y = max(0, min(self._dev_h - 1, y))
        return x, y

    def _on_press(self, event: QMouseEvent):
        self.screen.setFocus()
        if event.button() == Qt.MouseButton.RightButton:
            self._nav("4")
            return
        pt = self._to_device(event)
        if pt:
            self._press = (pt[0], pt[1], time.monotonic())

    def _on_release(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._mirroring or not self._serial:
            return
        end = self._to_device(event)
        start = self._press
        self._press = None
        if not end or not start:
            return
        x1, y1, t0 = start
        x2, y2 = end
        dt = max(0.05, time.monotonic() - t0)
        dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        serial = self._serial

        def work():
            try:
                if dist < 18:
                    backend.tap(serial, x2, y2)
                else:
                    backend.swipe(serial, x1, y1, x2, y2, int(dt * 1000))
            except backend.AdbError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_wheel(self, event: QWheelEvent):
        if not self._mirroring or not self._serial:
            return
        mid_x = self._dev_w // 2
        mid_y = self._dev_h // 2
        delta = 280 if event.angleDelta().y() > 0 else -280
        serial = self._serial

        def work():
            try:
                backend.swipe(serial, mid_x, mid_y, mid_x, mid_y + delta, 120)
            except backend.AdbError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_key(self, event: QKeyEvent):
        if not self._mirroring or not self._serial:
            return
        serial = self._serial
        special = {
            Qt.Key.Key_Return: "66",
            Qt.Key.Key_Enter: "66",
            Qt.Key.Key_Backspace: "67",
            Qt.Key.Key_Delete: "67",
            Qt.Key.Key_Escape: "4",
            Qt.Key.Key_Tab: "61",
            Qt.Key.Key_Up: "19",
            Qt.Key.Key_Down: "20",
            Qt.Key.Key_Left: "21",
            Qt.Key.Key_Right: "22",
            Qt.Key.Key_Space: "62",
        }
        key = special.get(event.key())
        char = event.text() if event.text() and event.text().isprintable() else ""

        def work():
            try:
                if key:
                    backend.keyevent(serial, key)
                elif char:
                    backend.type_text(serial, char)
            except backend.AdbError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _nav(self, key: str):
        serial = self._serial or self._selected_serial()
        if not serial:
            return

        def work():
            err = None
            try:
                backend.keyevent(serial, key)
            except backend.AdbError as e:
                err = str(e)
            if err:
                self._nav_error_ready.emit(err)

        threading.Thread(target=work, daemon=True).start()

    def _open_scrcpy(self):
        serial = self._selected_serial() or self._serial
        if not serial:
            QMessageBox.information(self, "Phone Screen", "Pick a device first.")
            return
        if not backend.find_scrcpy():
            QMessageBox.information(
                self, "Phone Screen",
                "scrcpy is not installed. The in-app mirror already has tap/swipe.\n\n"
                "For a sharper separate window:\n  winget install Genymobile.scrcpy",
            )
            return
        try:
            self._stop_scrcpy()
            self._scrcpy = backend.start_scrcpy(serial, f"ZsPhone {serial}")
        except backend.AdbError as e:
            QMessageBox.warning(self, "Phone Screen", str(e))

    def _stop_scrcpy(self):
        proc = self._scrcpy
        self._scrcpy = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    # -- Window embed mode -------------------------------------------------

    def _refresh_embed_windows(self):
        def work():
            err, windows = None, []
            try:
                windows = backend.list_emulator_windows()
            except backend.EmbedError as e:
                err = str(e)
            self._embed_windows_ready.emit(windows, err)

        threading.Thread(target=work, daemon=True).start()

    def _embed_windows_done(self, windows, err):
        if err:
            QMessageBox.warning(self, "Phone Screen", err)
            return
        self._embed_windows = windows
        self.embed_combo.clear()
        if not windows:
            self.embed_combo.addItem("(no BlueStacks/MuMu window found — start one, then Scan)")
            return
        self.embed_combo.addItems([w.label for w in windows])

    def _toggle_embed(self):
        if self._embed_state is not None:
            self._detach_embed()
            return
        if not self._embed_windows:
            QMessageBox.information(self, "Phone Screen", "Scan windows first, then pick one.")
            return
        idx = self.embed_combo.currentIndex()
        if idx < 0 or idx >= len(self._embed_windows):
            return
        target = self._embed_windows[idx]

        def work():
            err = None
            state = None
            try:
                container_hwnd = int(self.embed_container.winId())
                state = backend.embed_window(target.hwnd, container_hwnd)
                backend.resize_embedded(
                    target.hwnd, self.embed_container.width(), self.embed_container.height()
                )
            except backend.EmbedError as e:
                err = str(e)
            self._embed_hwnd = target.hwnd if not err else 0
            self._embed_done.emit((state, err))

        threading.Thread(target=work, daemon=True).start()

    def _embed_finished(self, payload):
        state, err = payload
        if err:
            QMessageBox.warning(self, "Phone Screen", err)
            return
        self._embed_state = state
        self.embed_btn.setText("Detach")

    def _on_embed_resize(self, width: int, height: int):
        if self._embed_state is not None:
            backend.resize_embedded(self._embed_state.hwnd, width, height)

    def _on_embed_container_ready(self):
        # Placeholder hook — nothing to do until the user clicks Embed, but
        # kept so a future "auto-embed on show" option has somewhere to live.
        pass

    def _detach_embed(self):
        state = self._embed_state
        self._embed_state = None
        self._embed_hwnd = 0
        self.embed_btn.setText("Embed")
        if state is not None:
            def work():
                backend.unembed_window(state)
            threading.Thread(target=work, daemon=True).start()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)


class PhoneScreenPage(QWidget):
    """Container that manages any number of independent _MirrorDock screens,
    arranged in a grid of drag-resizable splitters so you can size each
    screen yourself (both its width and its height)."""

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._docks: list[_MirrorDock] = []
        self._next_num = 1
        self._columns = 2

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel("Phone Screen")
        title.setObjectName("AccentTitle")
        top.addWidget(title)
        top.addStretch(1)
        cols_l = QLabel("Columns")
        cols_l.setObjectName("Muted")
        top.addWidget(cols_l)
        self.cols_combo = QComboBox()
        self.cols_combo.addItems(["1", "2", "3", "4"])
        self.cols_combo.setCurrentText(str(self._columns))
        self.cols_combo.currentTextChanged.connect(self._on_columns_changed)
        top.addWidget(self.cols_combo)
        add_btn = QPushButton("+ Add Screen")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(self._add_dock)
        top.addWidget(add_btn)
        root.addLayout(top)

        hint = QLabel(
            "Android on USB, wireless ADB, BlueStacks, or MuMu Player. Add as many screens "
            "as you like, arranged in a grid — drag the thin bars between screens to resize "
            "them yourself. ADB Mirror polls a screenshot and forwards clicks as taps. Embed "
            "Window shows a local emulator's real window directly, at full speed, with native "
            "clicks."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        root.addWidget(self._scroll, 1)

        # Outer splitter stacks rows vertically; each row is its own
        # horizontal splitter holding up to `self._columns` docks. Rebuilt
        # (cheaply — docks are reparented, not recreated) whenever a dock is
        # added/removed or the column count changes.
        self._grid = QSplitter(Qt.Orientation.Vertical)
        self._grid.setChildrenCollapsible(False)
        self._scroll.setWidget(self._grid)

        self._add_dock()

    def _add_dock(self):
        dock = _MirrorDock(self, self._next_num, on_close=self._remove_dock)
        self._next_num += 1
        dock.setMinimumSize(320, 360)
        self._docks.append(dock)
        self._rebuild_grid()

    def _remove_dock(self, dock: _MirrorDock):
        if len(self._docks) <= 1:
            QMessageBox.information(self, "Phone Screen", "At least one screen has to stay open.")
            return
        dock.cleanup()
        self._docks.remove(dock)
        dock.setParent(None)
        dock.deleteLater()
        self._rebuild_grid()

    def _on_columns_changed(self, text: str):
        try:
            self._columns = max(1, int(text))
        except ValueError:
            self._columns = 2
        self._rebuild_grid()

    def _rebuild_grid(self):
        """Re-lay-out self._docks into a grid of splitters, `self._columns`
        wide. Docks are reparented into fresh splitters (cheap — no
        recreation, no loss of state) and the old splitter tree is torn down."""
        old_grid = self._grid
        new_grid = QSplitter(Qt.Orientation.Vertical)
        new_grid.setChildrenCollapsible(False)

        for start in range(0, len(self._docks), self._columns):
            row_docks = self._docks[start:start + self._columns]
            row = QSplitter(Qt.Orientation.Horizontal)
            row.setChildrenCollapsible(False)
            for dock in row_docks:
                row.addWidget(dock)  # reparents automatically
            new_grid.addWidget(row)

        self._scroll.setWidget(new_grid)
        self._grid = new_grid
        # QScrollArea.setWidget() already deletes the previous widget for us —
        # calling setParent/deleteLater on old_grid here would double-delete
        # it and crash.

    def closeEvent(self, event):
        for dock in self._docks:
            dock.cleanup()
        super().closeEvent(event)

    def on_hide(self):
        for dock in self._docks:
            dock.on_hide()

    def on_show(self):
        for dock in self._docks:
            dock.on_show()
