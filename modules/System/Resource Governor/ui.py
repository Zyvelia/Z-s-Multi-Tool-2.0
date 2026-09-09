"""Qt Resource Governor — parked shell around existing budget checks."""

from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.services import resource_governor as gov


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class ResourceGovernorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        cfg = gov.load()

        root = QVBoxLayout(self)
        title = QLabel("Resource Governor")
        title.setObjectName("AccentTitle")
        root.addWidget(title)
        sub = QLabel(
            "One budget for this PC. Over the line, new game-server starts are blocked. Nothing is killed."
        )
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.strip = QLabel("")
        root.addWidget(self.strip)

        toggles = QHBoxLayout()
        self.on_box = QCheckBox("Enabled")
        self.on_box.setChecked(bool(cfg.get("enabled")))
        self.block_box = QCheckBox("Block new game-server starts when over budget")
        self.block_box.setChecked(bool(cfg.get("block_server_starts")))
        toggles.addWidget(self.on_box)
        toggles.addWidget(self.block_box)
        toggles.addStretch(1)
        root.addLayout(toggles)

        budgets = QHBoxLayout()
        ram_lab = QLabel("Max RAM %")
        ram_lab.setObjectName("Muted")
        self.ram = QSpinBox()
        self.ram.setRange(20, 99)
        self.ram.setValue(int(cfg.get("max_ram_percent", 85)))
        cpu_lab = QLabel("Max CPU %")
        cpu_lab.setObjectName("Muted")
        self.cpu = QSpinBox()
        self.cpu.setRange(20, 99)
        self.cpu.setValue(int(cfg.get("max_cpu_percent", 90)))
        save = QPushButton("Save")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        budgets.addWidget(ram_lab)
        budgets.addWidget(self.ram)
        budgets.addWidget(cpu_lab)
        budgets.addWidget(self.cpu)
        budgets.addWidget(save)
        budgets.addWidget(refresh)
        budgets.addStretch(1)
        root.addLayout(budgets)

        hog_title = QLabel("Known hogs")
        hog_title.setObjectName("CardTitle")
        root.addWidget(hog_title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.hogs = QVBoxLayout(host)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        QTimer.singleShot(200, self.refresh)

    def _save(self):
        gov.save({
            "enabled": self.on_box.isChecked(),
            "block_server_starts": self.block_box.isChecked(),
            "max_ram_percent": self.ram.value(),
            "max_cpu_percent": self.cpu.value(),
        })
        self.refresh()

    def refresh(self):
        def work():
            snap = gov.snapshot()
            QTimer.singleShot(0, lambda: self._apply(snap))

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, snap: dict):
        over = snap.get("over_budget")
        self.strip.setText(
            f"CPU {snap['cpu_percent']:.0f}%   RAM {snap['ram_percent']:.0f}% "
            f"({snap['ram_used_gb']:.1f} / {snap['ram_total_gb']:.1f} GB)"
            + ("   OVER BUDGET" if over else "   ok")
        )
        self.strip.setObjectName("Danger" if over else "Success")
        self.strip.style().unpolish(self.strip)
        self.strip.style().polish(self.strip)
        _ok, reason = gov.allow_start("game_server")
        if reason:
            self.strip.setText(self.strip.text() + "\n" + reason)
        _clear(self.hogs)
        rows = snap.get("hogs") or []
        if not rows:
            empty = QLabel("Nothing matching Ollama / VLC / ffmpeg / running game servers.")
            empty.setObjectName("Muted")
            self.hogs.addWidget(empty)
            self.hogs.addStretch(1)
            return
        for hog in rows:
            card = QFrame()
            card.setObjectName("Panel")
            cl = QVBoxLayout(card)
            name = QLabel(f"{hog.get('name')}   {hog.get('rss_mb', 0)} MB")
            name.setObjectName("CardTitle")
            cl.addWidget(name)
            self.hogs.addWidget(card)
        self.hogs.addStretch(1)
