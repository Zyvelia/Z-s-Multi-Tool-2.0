"""Qt System Monitor — live metrics, progress bars, process table."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modules.System.system_monitor.colors import metric_colors
from modules.System.system_monitor.metrics import (
    IP_MASK_TEXT,
    REFRESH_MS,
    MetricsSampler,
    fmt_pct,
    fmt_rate,
    fmt_temp,
)


def _bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    return bar


class SystemMonitorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self._sampler = MetricsSampler()
        self._busy = False
        self._ip_revealed = False
        self._local_ip = "—"
        self._core_bars: list[QProgressBar] = []
        self._core_labels: list[QLabel] = []

        root = QVBoxLayout(self)
        title = QLabel("System Monitor")
        title.setObjectName("AccentTitle")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        body = QVBoxLayout(host)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        live = QFrame()
        live.setObjectName("Panel")
        lg = QGridLayout(live)
        live_title = QLabel("LIVE")
        live_title.setObjectName("CardTitle")
        lg.addWidget(live_title, 0, 0, 1, 4)

        self.cpu_val, self.cpu_bar, self.cpu_detail = self._metric_cell("CPU")
        self.ram_val, self.ram_bar, self.ram_detail = self._metric_cell("MEMORY")
        self.disk_val, self.disk_bar, self.disk_detail = self._metric_cell("DISK")
        self.swap_val, self.swap_bar, self.swap_detail = self._metric_cell("SWAP")
        for i, widgets in enumerate((
            (self.cpu_val, self.cpu_bar, self.cpu_detail),
            (self.ram_val, self.ram_bar, self.ram_detail),
            (self.disk_val, self.disk_bar, self.disk_detail),
            (self.swap_val, self.swap_bar, self.swap_detail),
        )):
            cell = QWidget()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(4, 4, 4, 4)
            for w in widgets:
                cl.addWidget(w)
            lg.addWidget(cell, 1, i)

        self.net_down = QLabel("NET ↓ —")
        self.net_up = QLabel("NET ↑ —")
        self.disk_read = QLabel("DISK READ —")
        self.disk_write = QLabel("DISK WRITE —")
        lg.addWidget(self.net_down, 2, 0)
        lg.addWidget(self.net_up, 2, 1)
        lg.addWidget(self.disk_read, 2, 2)
        lg.addWidget(self.disk_write, 2, 3)

        self.gpu_name = QLabel("GPU — not detected")
        self.gpu_name.setObjectName("Muted")
        self.gpu_util, self.gpu_util_bar, self.gpu_util_detail = self._metric_cell("GPU LOAD")
        self.gpu_vram, self.gpu_vram_bar, self.gpu_vram_detail = self._metric_cell("VRAM")
        lg.addWidget(self.gpu_name, 3, 0, 1, 4)
        gpu_row = QWidget()
        gr = QHBoxLayout(gpu_row)
        gr.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        left.addWidget(self.gpu_util)
        left.addWidget(self.gpu_util_bar)
        left.addWidget(self.gpu_util_detail)
        right = QVBoxLayout()
        right.addWidget(self.gpu_vram)
        right.addWidget(self.gpu_vram_bar)
        right.addWidget(self.gpu_vram_detail)
        gr.addLayout(left, 1)
        gr.addLayout(right, 1)
        lg.addWidget(gpu_row, 4, 0, 1, 4)
        body.addWidget(live)

        core_panel = QFrame()
        core_panel.setObjectName("Panel")
        cl = QVBoxLayout(core_panel)
        core_head = QHBoxLayout()
        ct = QLabel("PER-CORE")
        ct.setObjectName("CardTitle")
        self.core_summary = QLabel("—")
        self.core_summary.setObjectName("Muted")
        core_head.addWidget(ct)
        core_head.addStretch(1)
        core_head.addWidget(self.core_summary)
        cl.addLayout(core_head)
        self.core_grid = QGridLayout()
        cl.addLayout(self.core_grid)
        body.addWidget(core_panel)

        bottom = QHBoxLayout()
        info = QFrame()
        info.setObjectName("Panel")
        il = QVBoxLayout(info)
        it = QLabel("SYSTEM INFO")
        it.setObjectName("CardTitle")
        il.addWidget(it)
        self.info = {}
        for key in (
            "OS", "Hostname", "CPU", "Cores / Threads", "Total RAM",
            "Local IP", "Uptime", "Battery", "Network (↑ / ↓)", "Processes", "GPU",
        ):
            row = QHBoxLayout()
            k = QLabel(key)
            k.setObjectName("Muted")
            v = QLabel("—")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(k)
            row.addWidget(v, 1)
            il.addLayout(row)
            self.info[key] = v
        ip_btn = QPushButton("Show / hide IP")
        ip_btn.clicked.connect(self._toggle_ip)
        il.addWidget(ip_btn)
        il.addStretch(1)
        bottom.addWidget(info, 1)

        proc = QFrame()
        proc.setObjectName("Panel")
        pl = QVBoxLayout(proc)
        pt = QLabel("TOP PROCESSES (by CPU)")
        pt.setObjectName("CardTitle")
        pl.addWidget(pt)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "PID", "CPU%", "MEM%"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        pl.addWidget(self.table, 1)
        bottom.addWidget(proc, 1)
        body.addLayout(bottom)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def _metric_cell(self, label: str):
        name = QLabel(label)
        name.setObjectName("Muted")
        value = QLabel("—")
        bar = _bar()
        detail = QLabel("")
        detail.setObjectName("Muted")
        return value, bar, detail

    def on_hide(self):
        self._timer.stop()

    def on_show(self):
        if not self._timer.isActive():
            self._timer.start()
        self._tick()

    def _toggle_ip(self):
        self._ip_revealed = not self._ip_revealed
        self._refresh_ip()

    def _refresh_ip(self):
        if self._ip_revealed:
            self.info["Local IP"].setText(self._local_ip)
        else:
            self.info["Local IP"].setText(IP_MASK_TEXT)

    def _ensure_cores(self, count: int):
        if len(self._core_bars) == count:
            return
        while self.core_grid.count():
            item = self.core_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._core_bars = []
        self._core_labels = []
        cols = min(count, 8) or 1
        for i in range(count):
            wrap = QWidget()
            vl = QVBoxLayout(wrap)
            vl.setContentsMargins(2, 2, 2, 2)
            lbl = QLabel(f"{i:02d} —")
            lbl.setObjectName("Muted")
            bar = _bar()
            vl.addWidget(lbl)
            vl.addWidget(bar)
            r, c = divmod(i, cols)
            self.core_grid.addWidget(wrap, r, c)
            self._core_labels.append(lbl)
            self._core_bars.append(bar)

    def _tick(self):
        if self._busy:
            return
        self._busy = True

        def work():
            try:
                snap = self._sampler.take()
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._failed(str(exc)))
                return
            QTimer.singleShot(0, lambda: self._apply(snap))

        threading.Thread(target=work, daemon=True).start()

    def _failed(self, err: str):
        self._busy = False
        self.status.setObjectName("Danger")
        self.status.setText(err)

    def _apply(self, snap: dict):
        self._busy = False
        self.cpu_val.setText(fmt_pct(snap["cpu"]))
        self.cpu_bar.setValue(int(snap["cpu"]))
        self.cpu_detail.setText(snap["cpu_detail"])
        self.ram_val.setText(fmt_pct(snap["ram"]))
        self.ram_bar.setValue(int(snap["ram"]))
        self.ram_detail.setText(snap["ram_detail"])
        self.disk_val.setText(fmt_pct(snap["disk"]))
        self.disk_bar.setValue(int(snap["disk"]))
        self.disk_detail.setText(snap["disk_detail"])
        self.swap_val.setText(fmt_pct(snap["swap"]))
        self.swap_bar.setValue(int(snap["swap"]))
        self.swap_detail.setText(snap["swap_detail"])
        self.net_down.setText(f"NET ↓ {fmt_rate(snap['net_down'])}")
        self.net_up.setText(f"NET ↑ {fmt_rate(snap['net_up'])}")
        self.disk_read.setText(f"DISK READ {fmt_rate(snap['disk_read'])}")
        self.disk_write.setText(f"DISK WRITE {fmt_rate(snap['disk_write'])}")

        gpu = snap.get("gpu")
        if gpu:
            self.gpu_name.setText(f"GPU — {gpu['name'][:42]}")
            self.gpu_util.setText(fmt_pct(gpu["util"]))
            self.gpu_util_bar.setValue(int(gpu["util"]))
            self.gpu_util_detail.setText(fmt_temp(gpu["temp"]) if gpu.get("temp") is not None else "")
            self.gpu_vram.setText(fmt_pct(gpu["mem_pct"]))
            self.gpu_vram_bar.setValue(int(gpu["mem_pct"]))
            self.gpu_vram_detail.setText(gpu["mem_detail"])
            gpu_line = f"{gpu['name'][:36]} · {fmt_pct(gpu['util'])}"
            if gpu.get("temp") is not None:
                gpu_line += f" · {fmt_temp(gpu['temp'])}"
            self.info["GPU"].setText(gpu_line)
        else:
            self.gpu_name.setText("GPU — not detected")
            self.info["GPU"].setText("Not detected")

        cores = snap.get("per_core") or []
        self._ensure_cores(len(cores))
        for i, pct in enumerate(cores):
            self._core_labels[i].setText(f"{i:02d} {fmt_pct(pct)}")
            self._core_bars[i].setValue(int(pct))
        if cores:
            avg = sum(cores) / len(cores)
            peak = max(cores)
            self.core_summary.setText(f"avg {fmt_pct(avg)} · peak {fmt_pct(peak)}")

        self._local_ip = snap["local_ip"]
        self.info["OS"].setText(snap["os"])
        self.info["Hostname"].setText(snap["hostname"])
        self.info["CPU"].setText(snap["cpu_model"])
        self.info["Cores / Threads"].setText(snap["cores"])
        self.info["Total RAM"].setText(snap["total_ram"])
        self._refresh_ip()
        self.info["Uptime"].setText(snap["uptime"])
        self.info["Battery"].setText(snap["battery"])
        self.info["Network (↑ / ↓)"].setText(
            f"↑ {fmt_rate(snap['net_up'])} · ↓ {fmt_rate(snap['net_down'])}"
        )
        self.info["Processes"].setText(snap["process_count"])

        rows = snap.get("processes") or []
        self.table.setRowCount(len(rows))
        for r, proc in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(str(proc["name"])))
            self.table.setItem(r, 1, QTableWidgetItem(str(proc["pid"])))
            self.table.setItem(r, 2, QTableWidgetItem(f"{proc['cpu']:.1f}"))
            self.table.setItem(r, 3, QTableWidgetItem(f"{proc['mem']:.1f}"))
        _ = metric_colors()
        self.status.setText("")
