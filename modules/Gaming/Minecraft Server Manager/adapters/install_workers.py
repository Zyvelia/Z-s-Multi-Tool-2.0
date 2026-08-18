"""Minecraft and SteamCMD install worker factories."""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from .. import backend as mc
from ..core.events import DownloadEvent
from .steamcmd_install import SteamCmdInstallWorker


def create_minecraft_java_install_worker(
    server_dir: Path,
    version: mc.MCVersion,
) -> threading.Thread:
    class _Starter(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue[DownloadEvent] = queue.Queue()

        def run(self) -> None:
            info, error = mc.get_server_download_info(version)
            if error or info is None:
                self.events.put(DownloadEvent(kind="error", message=error or "No download info."))
                return
            worker = mc.ServerDownloadWorker(info, server_dir)
            worker.events = self.events
            worker.run()

    return _Starter()


def create_minecraft_bedrock_install_worker(
    server_dir: Path,
    preview: bool = False,
) -> threading.Thread:
    class _Starter(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue[DownloadEvent] = queue.Queue()
            self.version = ""

        def run(self) -> None:
            info, error = mc.get_bedrock_download_info(preview=preview)
            if error or info is None:
                self.events.put(DownloadEvent(kind="error", message=error or "No download info."))
                return
            self.version = info.version
            worker = mc.BedrockDownloadWorker(info, server_dir)
            worker.events = self.events
            worker.run()

    return _Starter()


def create_steamcmd_install_worker(server_dir: Path, app_id: str) -> SteamCmdInstallWorker:
    return SteamCmdInstallWorker(server_dir, app_id)
