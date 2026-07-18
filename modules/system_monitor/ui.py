"""
System Monitor — main page.

Clean, flat-card layout using the shared app theme (core.theme) instead of
a standalone palette — matches mini_widget.py's existing look rather than
introducing a second visual style for the same module.
"""

import time
import socket
import platform
from collections import deque

import customtkinter as ctk
import psutil

try:
    from core import theme
except ImportError:  # pragma: no cover - fallback for standalone use/testing
    class theme:  # type: ignore
        BG = "#0f1115"
        PANEL = "#151922"
        PANEL_2 = "#1b2030"
        ACCENT = "#4ea1ff"
        DANGER = "#ff5c5c"
        OK = "#3ddc84"
        MUTED = "#7d8494"
        FAINT = "#565d6e"
        TEXT = "#e8edf5"

        @staticmethod
        def font(size, weight="normal"):
            return ctk.CTkFont(size=size, weight=weight)

        @staticmethod
        def mono(size):
            return ctk.CTkFont(family="Consolas", size=size)


REFRESH_MS = 1000
HISTORY_LEN = 60          # ~60s of sparkline history at 1s refresh
WARN_THRESHOLD = 80       # usage % at which a bar/gauge turns danger-colored
TOP_PROCESS_COUNT = 8


def _usage_color(pct: float) -> str:
    return theme.DANGER if pct >= WARN_THRESHOLD else theme.ACCENT


def _bytes_to_human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ------------------------------------------------------------- sparkline

import tkinter as tk


class Sparkline(tk.Canvas):
    """Minimal line-history strip — shows trend, not just a point-in-time
    percentage. Cheap: a deque of floats and a polyline redraw."""

    def __init__(self, parent, width=220, height=32, color=None):
        super().__init__(parent, width=width, height=height,
                          bg=theme.PANEL_2, highlightthickness=0)
        self._w = width
        self._h = height
        self._color = color or theme.ACCENT
        self._history: deque[float] = deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN)
        self._line_id = None

    def push(self, value: float) -> None:
        self._history.append(value)
        self._redraw()

    def _redraw(self) -> None:
        if self._line_id is not None:
            self.delete(self._line_id)
        pts = []
        n = len(self._history)
        for i, v in enumerate(self._history):
            x = (i / max(n - 1, 1)) * self._w
            y = self._h - (min(v, 100) / 100) * self._h
            pts.extend((x, y))
        if len(pts) >= 4:
            color = _usage_color(self._history[-1])
            self._line_id = self.create_line(*pts, fill=color, width=1.6, smooth=True)


# --------------------------------------------------------------- metric card

class MetricCard(ctk.CTkFrame):
    """A single stat: label, big percentage, progress bar, and a sparkline
    showing recent history."""

    def __init__(self, parent, label: str):
        super().__init__(parent, fg_color=theme.PANEL, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top, text=label, font=theme.font(12, "bold"), text_color=theme.MUTED,
        ).grid(row=0, column=0, sticky="w")

        self.pct_label = ctk.CTkLabel(
            top, text="0%", font=theme.font(20, "bold"), text_color=theme.ACCENT,
        )
        self.pct_label.grid(row=0, column=1, sticky="e")

        self.bar = ctk.CTkProgressBar(
            self, height=8, corner_radius=4,
            fg_color=theme.PANEL_2, progress_color=theme.ACCENT,
        )
        self.bar.set(0)
        self.bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))

        self.sparkline = Sparkline(self, width=220, height=28)
        self.sparkline.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))

        self.detail_label = ctk.CTkLabel(
            self, text="", font=theme.mono(10), text_color=theme.FAINT, anchor="w",
        )
        self.detail_label.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 12))

    def set_value(self, pct: float, detail: str = "") -> None:
        color = _usage_color(pct)
        self.pct_label.configure(text=f"{pct:.0f}%", text_color=color)
        self.bar.set(pct / 100)
        self.bar.configure(progress_color=color)
        self.sparkline.push(pct)
        if detail:
            self.detail_label.configure(text=detail)


# ------------------------------------------------------------------- info row

def _info_row(parent, row: int, key: str, col_offset: int = 0):
    base_col = col_offset * 2
    ctk.CTkLabel(
        parent, text=key, font=theme.font(11), text_color=theme.MUTED, anchor="w",
    ).grid(row=row, column=base_col, padx=(16, 10), pady=5, sticky="w")

    val = ctk.CTkLabel(
        parent, text="—", font=theme.mono(11), text_color=theme.TEXT, anchor="w",
    )
    val.grid(row=row, column=base_col + 1, padx=(0, 20), pady=5, sticky="w")
    return val


# ------------------------------------------------------------------- main page

class SystemMonitorPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager

        self._prev_net = psutil.net_io_counters()
        self._prev_net_time = time.monotonic()

        self._build_ui()
        self._update_stats()

    # ------------------------------------------------------------- layout

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="System Monitor",
            font=theme.font(20, "bold"), text_color=theme.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        # ---- metric cards row: CPU / RAM / Disk / Swap ----
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.grid(row=1, column=0, sticky="ew", padx=16)
        for i in range(4):
            cards_row.grid_columnconfigure(i, weight=1, uniform="cards")

        self.cpu_card = MetricCard(cards_row, "CPU")
        self.cpu_card.grid(row=0, column=0, padx=(0, 8), pady=(0, 12), sticky="nsew")

        self.ram_card = MetricCard(cards_row, "MEMORY")
        self.ram_card.grid(row=0, column=1, padx=8, pady=(0, 12), sticky="nsew")

        self.disk_card = MetricCard(cards_row, "DISK (C:)")
        self.disk_card.grid(row=0, column=2, padx=8, pady=(0, 12), sticky="nsew")

        self.swap_card = MetricCard(cards_row, "SWAP")
        self.swap_card.grid(row=0, column=3, padx=(8, 0), pady=(0, 12), sticky="nsew")

        # ---- per-core CPU row ----
        core_panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        core_panel.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        core_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            core_panel, text="PER-CORE USAGE", font=theme.font(11, "bold"),
            text_color=theme.MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 6))

        self._core_bar_frame = ctk.CTkFrame(core_panel, fg_color="transparent")
        self._core_bar_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._core_bars: list[ctk.CTkProgressBar] = []
        self._core_labels: list[ctk.CTkLabel] = []
        self._build_core_bars(psutil.cpu_count(logical=True) or 1)

        # ---- two-column bottom section: system info + top processes ----
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # -- system info --
        info_panel = ctk.CTkFrame(bottom, fg_color=theme.PANEL, corner_radius=10)
        info_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ctk.CTkLabel(
            info_panel, text="SYSTEM INFO", font=theme.font(11, "bold"),
            text_color=theme.MUTED, anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))

        info_grid = ctk.CTkFrame(info_panel, fg_color="transparent")
        info_grid.pack(fill="x", pady=(0, 12))

        self._os_val = _info_row(info_grid, 0, "OS")
        self._host_val = _info_row(info_grid, 1, "Hostname")
        self._cores_val = _info_row(info_grid, 2, "Cores / Threads")
        self._mem_val = _info_row(info_grid, 3, "Total RAM")
        self._up_val = _info_row(info_grid, 4, "Uptime")
        self._battery_val = _info_row(info_grid, 5, "Battery")
        self._net_val = _info_row(info_grid, 6, "Network (↑ / ↓)")
        self._proc_count_val = _info_row(info_grid, 7, "Processes")

        # -- top processes --
        proc_panel = ctk.CTkFrame(bottom, fg_color=theme.PANEL, corner_radius=10)
        proc_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        proc_panel.grid_columnconfigure(0, weight=1)
        proc_panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            proc_panel, text=f"TOP PROCESSES (by CPU)", font=theme.font(11, "bold"),
            text_color=theme.MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        self._proc_list_frame = ctk.CTkScrollableFrame(
            proc_panel, fg_color="transparent",
        )
        self._proc_list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 12))
        self._proc_list_frame.grid_columnconfigure(0, weight=1)
        self._proc_row_labels: list[tuple[ctk.CTkLabel, ctk.CTkLabel, ctk.CTkLabel]] = []
        self._build_proc_rows(TOP_PROCESS_COUNT)

    def _build_core_bars(self, count: int) -> None:
        cols = min(count, 8)  # wrap after 8 to keep bars a readable width
        for i in range(count):
            r, c = divmod(i, cols)
            self._core_bar_frame.grid_columnconfigure(c, weight=1, uniform="cores")

            cell = ctk.CTkFrame(self._core_bar_frame, fg_color="transparent")
            cell.grid(row=r, column=c, sticky="ew", padx=4, pady=4)
            cell.grid_columnconfigure(0, weight=1)

            lbl = ctk.CTkLabel(
                cell, text=f"{i}", font=theme.mono(9), text_color=theme.FAINT,
            )
            lbl.grid(row=0, column=0, sticky="w")

            bar = ctk.CTkProgressBar(
                cell, height=6, corner_radius=3,
                fg_color=theme.PANEL_2, progress_color=theme.ACCENT,
            )
            bar.set(0)
            bar.grid(row=1, column=0, sticky="ew")

            self._core_bars.append(bar)
            self._core_labels.append(lbl)

    def _build_proc_rows(self, count: int) -> None:
        header = ctk.CTkFrame(self._proc_list_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="NAME", font=theme.font(9, "bold"), text_color=theme.FAINT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header, text="CPU%", font=theme.font(9, "bold"), text_color=theme.FAINT, width=48,
        ).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            header, text="MEM%", font=theme.font(9, "bold"), text_color=theme.FAINT, width=48,
        ).grid(row=0, column=2, sticky="e", padx=(8, 4))

        for i in range(count):
            row = ctk.CTkFrame(self._proc_list_frame, fg_color="transparent")
            row.grid(row=i + 1, column=0, sticky="ew", padx=4, pady=2)
            row.grid_columnconfigure(0, weight=1)

            name_lbl = ctk.CTkLabel(
                row, text="—", font=theme.mono(10), text_color=theme.TEXT,
                anchor="w",
            )
            name_lbl.grid(row=0, column=0, sticky="ew")

            cpu_lbl = ctk.CTkLabel(
                row, text="—", font=theme.mono(10), text_color=theme.MUTED, width=48,
            )
            cpu_lbl.grid(row=0, column=1, sticky="e")

            mem_lbl = ctk.CTkLabel(
                row, text="—", font=theme.mono(10), text_color=theme.MUTED, width=48,
            )
            mem_lbl.grid(row=0, column=2, sticky="e", padx=(8, 4))

            self._proc_row_labels.append((name_lbl, cpu_lbl, mem_lbl))

    # ------------------------------------------------------------- update

    def _update_stats(self):
        if not self.winfo_exists():
            return

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        swap = psutil.swap_memory()
        per_core = psutil.cpu_percent(percpu=True)

        self.cpu_card.set_value(cpu, f"{psutil.cpu_count(logical=True)} threads")
        self.ram_card.set_value(
            ram.percent,
            f"{_bytes_to_human(ram.used)} / {_bytes_to_human(ram.total)}",
        )
        self.disk_card.set_value(
            disk.percent,
            f"{_bytes_to_human(disk.used)} / {_bytes_to_human(disk.total)}",
        )
        if swap.total > 0:
            self.swap_card.set_value(
                swap.percent, f"{_bytes_to_human(swap.used)} / {_bytes_to_human(swap.total)}",
            )
        else:
            self.swap_card.set_value(0, "no swap configured")

        for i, pct in enumerate(per_core):
            if i < len(self._core_bars):
                self._core_bars[i].set(pct / 100)
                self._core_bars[i].configure(progress_color=_usage_color(pct))

        # -- system info --
        self._os_val.configure(text=f"{platform.system()} {platform.release()}")
        self._host_val.configure(text=socket.gethostname())
        self._cores_val.configure(
            text=f"{psutil.cpu_count(logical=False)} / {psutil.cpu_count(logical=True)}"
        )
        self._mem_val.configure(text=_bytes_to_human(ram.total))

        uptime_s = int(time.time() - psutil.boot_time())
        d, rem = divmod(uptime_s, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        self._up_val.configure(text=f"{d}d {h:02d}h {m:02d}m")

        self._proc_count_val.configure(text=str(len(psutil.pids())))

        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery is None:
            self._battery_val.configure(text="No battery")
        else:
            state = "charging" if battery.power_plugged else "on battery"
            self._battery_val.configure(text=f"{battery.percent:.0f}% ({state})")

        # -- live network throughput (delta since last tick, not cumulative) --
        now = time.monotonic()
        current_net = psutil.net_io_counters()
        elapsed = max(now - self._prev_net_time, 0.001)
        up_rate = (current_net.bytes_sent - self._prev_net.bytes_sent) / elapsed
        down_rate = (current_net.bytes_recv - self._prev_net.bytes_recv) / elapsed
        self._net_val.configure(
            text=f"{_bytes_to_human(up_rate)}/s / {_bytes_to_human(down_rate)}/s"
        )
        self._prev_net = current_net
        self._prev_net_time = now

        # -- top processes by CPU --
        self._update_top_processes()

        self.after(REFRESH_MS, self._update_stats)

    def _update_top_processes(self) -> None:
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda info: info.get("cpu_percent") or 0, reverse=True)
        top = procs[:TOP_PROCESS_COUNT]

        for i, (name_lbl, cpu_lbl, mem_lbl) in enumerate(self._proc_row_labels):
            if i < len(top):
                info = top[i]
                name = (info.get("name") or "?")[:26]
                cpu_pct = info.get("cpu_percent") or 0.0
                mem_pct = info.get("memory_percent") or 0.0
                name_lbl.configure(text=name)
                cpu_lbl.configure(text=f"{cpu_pct:.0f}", text_color=_usage_color(cpu_pct))
                mem_lbl.configure(text=f"{mem_pct:.0f}")
            else:
                name_lbl.configure(text="—")
                cpu_lbl.configure(text="—", text_color=theme.MUTED)
                mem_lbl.configure(text="—")
