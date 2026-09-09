"""Reusable Qt Tailscale + app-serve settings used by Vault, Music, etc."""

from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

STATUS_POLL_MS = 4000


class TailscalePanel(QWidget):
    def __init__(self, parent, tailscale):
        super().__init__(parent)
        self.tailscale = tailscale
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("Panel")
        cl = QVBoxLayout(card)
        title = QLabel("Tailscale network")
        title.setObjectName("CardTitle")
        self.status = QLabel("Checking…")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setObjectName("Danger")
        self.disconnect_btn.clicked.connect(self._disconnect)
        install = QPushButton("Install Tailscale…")
        install.clicked.connect(lambda: webbrowser.open("https://tailscale.com/download"))
        row.addWidget(self.connect_btn)
        row.addWidget(self.disconnect_btn)
        row.addWidget(install)
        cl.addWidget(title)
        cl.addWidget(self.status)
        cl.addLayout(row)
        lay.addWidget(card)

    def apply_status(self, status):
        if not status.get("installed"):
            self.status.setText("Tailscale isn't installed on this device.")
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(False)
            return
        if status.get("running"):
            ip_bit = f"  ·  {status['tailscale_ip']}" if status.get("tailscale_ip") else ""
            self.status.setText(f"Connected as {status.get('hostname') or 'this device'}{ip_bit}")
            self.status.setObjectName("Success")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Reconnect")
            self.disconnect_btn.setEnabled(True)
        else:
            self.status.setText("Not connected.")
            self.status.setObjectName("Muted")
            self.connect_btn.setEnabled(True)
            self.connect_btn.setText("Connect")
            self.disconnect_btn.setEnabled(False)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _connect(self):
        cfg = self.tailscale.load_config()
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Connecting…")

        def work():
            ok, msg = self.tailscale.connect(
                hostname=cfg.get("hostname") or None,
                auth_key=cfg.get("auth_key") or None,
                accept_routes=cfg.get("accept_routes", True),
            )
            QTimer.singleShot(0, lambda: self._after_connect(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_connect(self, ok, msg):
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Connect")
        if not ok:
            QMessageBox.warning(
                self,
                "Couldn't connect",
                f"{msg}\n\nIf this is the first time, Tailscale may have opened a browser "
                "tab to approve login — finish that and click Connect again.",
            )

    def _disconnect(self):
        ok, msg = self.tailscale.disconnect()
        if not ok:
            QMessageBox.warning(self, "Couldn't disconnect", msg)


class AppServePanel(QWidget):
    """Start/stop a local web server and map it onto the tailnet."""

    def __init__(self, parent, *, tailscale, get_server, app_key, default_port, title, hint):
        super().__init__(parent)
        self.tailscale = tailscale
        self.get_server = get_server
        self.app_key = app_key
        self.default_port = default_port
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("Panel")
        cl = QVBoxLayout(card)
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        self.status = QLabel("Off")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        row = QHBoxLayout()
        self.start_btn = QPushButton("Start remote access")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop remote access")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.clicked.connect(self._stop)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Local port"))
        self.port = QLineEdit(str(default_port))
        self.port.setMaximumWidth(90)
        port_row.addWidget(self.port)
        port_row.addStretch(1)
        note = QLabel(hint)
        note.setObjectName("Muted")
        note.setWordWrap(True)
        cl.addWidget(heading)
        cl.addWidget(self.status)
        cl.addLayout(row)
        cl.addLayout(port_row)
        cl.addWidget(note)
        lay.addWidget(card)

    def current_port(self):
        try:
            return int((self.port.text() or "").strip() or self.default_port)
        except ValueError:
            return self.default_port

    def apply_status(self, status, running):
        server = self.get_server()
        if running:
            port = getattr(server, "port", None) or self.current_port()
            hostname = status.get("hostname") or "this-device"
            self.status.setText(
                f"On — phone can reach this over the tailnet. Serving locally on 127.0.0.1:{port} "
                f"({hostname})."
            )
            self.status.setObjectName("Success")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status.setText("Off.")
            self.status.setObjectName("Muted")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _start(self):
        server = self.get_server()
        port = self.current_port()
        status = self.tailscale.get_status()
        if not status.get("installed"):
            QMessageBox.warning(self, "Tailscale", "Install Tailscale first.")
            return
        if not status.get("running"):
            if QMessageBox.question(
                self, "Not connected", "Connect to Tailscale now, then start remote access?"
            ) != QMessageBox.StandardButton.Yes:
                return
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Starting…")

        def work():
            ok, msg = server.start(port)
            if ok:
                ok2, msg2 = self.tailscale.enable_app_serve(self.app_key, port)
                if not ok2:
                    ok, msg = ok2, msg2
            QTimer.singleShot(0, lambda: self._after_start(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_start(self, ok, msg):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Start remote access")
        if not ok:
            QMessageBox.warning(self, "Couldn't start remote access", str(msg))

    def _stop(self):
        self.tailscale.disable_app_serve(self.app_key)
        self.get_server().stop()


class VaultRemoteSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.tailscale = manager.container.tailscale_service
        self.web_server = manager.container.vault_web_server
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.ts = TailscalePanel(self, self.tailscale)
        self.serve = AppServePanel(
            self,
            tailscale=self.tailscale,
            get_server=lambda: self.web_server,
            app_key="vault",
            default_port=8765,
            title="Remote access (view on phone)",
            hint=(
                "Uses Tailscale HTTPS — reachable only from devices on your tailnet. "
                "Phone unlock uses the same master password."
            ),
        )
        lay.addWidget(self.ts)
        lay.addWidget(self.serve)

        cfg_card = QFrame()
        cfg_card.setObjectName("Panel")
        form = QFormLayout(cfg_card)
        self.hostname = QLineEdit()
        self.auth_key = QLineEdit()
        self.auth_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.accept_routes = QCheckBox("Accept subnet routes from tailnet")
        self.auto_off = QCheckBox("Auto turn off remote access after")
        self.auto_off_minutes = QLineEdit("30")
        self.auto_off_minutes.setMaximumWidth(70)
        minutes_row = QHBoxLayout()
        minutes_row.addWidget(self.auto_off)
        minutes_row.addWidget(self.auto_off_minutes)
        minutes_row.addWidget(QLabel("minutes"))
        minutes_row.addStretch(1)
        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        diagnose = QPushButton("Diagnose")
        diagnose.clicked.connect(self._diagnose)
        form.addRow("Device name (optional)", self.hostname)
        form.addRow("Auth key (optional)", self.auth_key)
        form.addRow(self.accept_routes)
        form.addRow(minutes_row)
        btn_row = QHBoxLayout()
        btn_row.addWidget(save)
        btn_row.addWidget(diagnose)
        form.addRow(btn_row)
        self.countdown = QLabel("")
        self.countdown.setObjectName("Muted")
        form.addRow(self.countdown)
        lay.addWidget(cfg_card)
        self._load_config()

        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._countdown)
        self._tick.start()
        self._refresh()

    def _load_config(self):
        cfg = self.tailscale.load_config()
        self.hostname.setText(cfg.get("hostname", "") or "")
        self.auth_key.setText(cfg.get("auth_key", "") or "")
        self.serve.port.setText(str(cfg.get("web_port", 8765)))
        self.accept_routes.setChecked(bool(cfg.get("accept_routes", True)))
        self.auto_off.setChecked(bool(cfg.get("auto_off_enabled", False)))
        self.auto_off_minutes.setText(str(cfg.get("auto_off_minutes", 30)))

    def _config(self):
        try:
            minutes = int((self.auto_off_minutes.text() or "30").strip())
        except ValueError:
            minutes = 30
        return {
            "hostname": self.hostname.text().strip(),
            "auth_key": self.auth_key.text().strip(),
            "accept_routes": self.accept_routes.isChecked(),
            "web_port": self.serve.current_port(),
            "auto_off_enabled": self.auto_off.isChecked(),
            "auto_off_minutes": minutes,
        }

    def _save(self):
        self.tailscale.save_config(self._config())
        QMessageBox.information(self, "Saved", "Settings saved.")

    def _diagnose(self):
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText("Running diagnostics…")
        dlg_host = QWidget(self)
        dlg_host.setWindowTitle("Diagnostics")
        vl = QVBoxLayout(dlg_host)
        vl.addWidget(box)
        dlg_host.resize(640, 420)
        dlg_host.show()

        def work():
            text = self.tailscale.diagnostics()
            QTimer.singleShot(0, lambda: box.setPlainText(text))

        threading.Thread(target=work, daemon=True).start()

    def _countdown(self):
        remaining = self.tailscale.auto_off_remaining_seconds()
        if remaining is None:
            self.countdown.setText("")
            return
        mins, secs = divmod(int(remaining), 60)
        self.countdown.setText(f"Auto turn-off in {mins:02d}:{secs:02d}")

    def _refresh(self):
        def work():
            status = self.tailscale.get_status()
            running = self.web_server.is_running()
            QTimer.singleShot(0, lambda: self._apply(status, running))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status, running):
        self.ts.apply_status(status)
        self.serve.apply_status(status, running)
        cfg = self._config()
        if running and cfg["auto_off_enabled"] and cfg["auto_off_minutes"] > 0:
            if self.tailscale.auto_off_remaining_seconds() is None:
                self.tailscale.start_auto_off_timer(
                    cfg["auto_off_minutes"],
                    lambda: QTimer.singleShot(0, self.serve._stop),
                )


class MusicRemoteSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.tailscale = manager.container.tailscale_service
        self.db = getattr(manager, "music_db", None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.ts = TailscalePanel(self, self.tailscale)
        self.serve = AppServePanel(
            self,
            tailscale=self.tailscale,
            get_server=self._server,
            app_key="music",
            default_port=8766,
            title="Remote access (listen on phone)",
            hint=(
                "Opens a mobile library browser on your tailnet address. "
                "The phone streams from this PC's library."
            ),
        )
        self.autostart = QCheckBox("Auto-start the local music server when the app opens")
        if self.db is not None:
            port = self.db.get_setting("remote_port", "8766")
            self.serve.port.setText(str(port))
            self.autostart.setChecked(self.db.get_setting("auto_start_server", "0") == "1")
        self.autostart.toggled.connect(self._autostart)
        lay.addWidget(self.ts)
        lay.addWidget(self.serve)
        lay.addWidget(self.autostart)
        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    def _server(self):
        web = getattr(self.manager, "music_web_server", None)
        if web is None:
            import importlib
            web_mod = importlib.import_module("modules.Media.Media Player.web_server")
            web = web_mod.MusicWebServer(
                library=getattr(self.manager, "music_db", None),
                engine=getattr(self.manager, "music_engine", None),
            )
            self.manager.music_web_server = web
        return web

    def _autostart(self, on):
        if self.db is not None:
            self.db.set_setting("auto_start_server", "1" if on else "0")
            self.db.set_setting("remote_port", str(self.serve.current_port()))

    def _refresh(self):
        if self.db is not None:
            self.db.set_setting("remote_port", str(self.serve.current_port()))

        def work():
            status = self.tailscale.get_status()
            running = self._server().is_running()
            QTimer.singleShot(0, lambda: self._apply(status, running))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status, running):
        self.ts.apply_status(status)
        self.serve.apply_status(status, running)


def ensure_manager_server(manager, attr: str, factory):
    web = getattr(manager, attr, None)
    if web is None:
        web = factory()
        setattr(manager, attr, web)
    return web


class SimpleRemoteSettings(QWidget):
    """Tailscale + app-serve block for modules that only need remote access."""

    def __init__(self, parent, manager, *, get_server, app_key, default_port, title, hint):
        super().__init__(parent)
        self.manager = manager
        self.tailscale = manager.container.tailscale_service
        self._get_server = get_server
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.ts = TailscalePanel(self, self.tailscale)
        self.serve = AppServePanel(
            self,
            tailscale=self.tailscale,
            get_server=get_server,
            app_key=app_key,
            default_port=default_port,
            title=title,
            hint=hint,
        )
        lay.addWidget(self.ts)
        lay.addWidget(self.serve)
        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._refresh()

    def _refresh(self):
        def work():
            status = self.tailscale.get_status()
            running = self._get_server().is_running()
            QTimer.singleShot(0, lambda: self._apply(status, running))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, status, running):
        self.ts.apply_status(status)
        self.serve.apply_status(status, running)
