"""SSH (paramiko) and serial (pyserial) sessions. GUI-free."""

from __future__ import annotations

import threading
from typing import Callable

OnBytes = Callable[[str], None]


class SessionError(Exception):
    pass


class SSHSession:
    def __init__(self):
        self._client = None
        self._chan = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def connected(self) -> bool:
        return self._chan is not None and not self._chan.closed

    def connect(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str = "",
        key_path: str = "",
        on_data: OnBytes | None = None,
    ) -> None:
        try:
            import paramiko
        except ImportError as e:
            raise SessionError("Install paramiko:  pip install paramiko") from e

        self.close()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": hostname,
            "port": int(port or 22),
            "username": username,
            "timeout": 15,
            "allow_agent": True,
            "look_for_keys": True,
        }
        if key_path:
            kwargs["key_filename"] = key_path
        if password:
            kwargs["password"] = password
        try:
            client.connect(**kwargs)
            chan = client.invoke_shell(term="xterm", width=120, height=36)
            chan.settimeout(0.2)
        except Exception as e:
            try:
                client.close()
            except Exception:
                pass
            raise SessionError(str(e)) from e

        self._client = client
        self._chan = chan
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop, args=(on_data,), daemon=True,
        )
        self._thread.start()

    def send(self, text: str) -> None:
        if not self.connected:
            raise SessionError("Not connected.")
        self._chan.send(text)

    def close(self) -> None:
        self._stop.set()
        chan, client = self._chan, self._client
        self._chan = None
        self._client = None
        try:
            if chan:
                chan.close()
        except Exception:
            pass
        try:
            if client:
                client.close()
        except Exception:
            pass

    def _read_loop(self, on_data: OnBytes | None) -> None:
        while not self._stop.is_set() and self._chan is not None:
            try:
                if self._chan.recv_ready():
                    raw = self._chan.recv(4096)
                    if not raw:
                        break
                    text = raw.decode("utf-8", errors="replace")
                    if on_data:
                        on_data(text)
                else:
                    self._stop.wait(0.05)
            except Exception:
                if self._stop.is_set():
                    break


class SerialSession:
    def __init__(self):
        self._ser = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def connected(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    def connect(self, port: str, baud: int, on_data: OnBytes | None = None) -> None:
        try:
            import serial
        except ImportError as e:
            raise SessionError("Install pyserial:  pip install pyserial") from e

        self.close()
        try:
            ser = serial.Serial(port=port, baudrate=int(baud), timeout=0.2)
        except Exception as e:
            raise SessionError(str(e)) from e
        self._ser = ser
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_loop, args=(on_data,), daemon=True,
        )
        self._thread.start()

    def send(self, text: str) -> None:
        if not self.connected:
            raise SessionError("Not connected.")
        self._ser.write(text.encode("utf-8", errors="replace"))

    def close(self) -> None:
        self._stop.set()
        ser = self._ser
        self._ser = None
        try:
            if ser:
                ser.close()
        except Exception:
            pass

    def _read_loop(self, on_data: OnBytes | None) -> None:
        while not self._stop.is_set() and self._ser is not None:
            try:
                raw = self._ser.read(512)
                if raw and on_data:
                    on_data(raw.decode("utf-8", errors="replace"))
                else:
                    self._stop.wait(0.03)
            except Exception:
                if self._stop.is_set():
                    break


def list_com_ports() -> list[str]:
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []
