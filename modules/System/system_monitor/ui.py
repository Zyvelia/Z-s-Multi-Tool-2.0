"""
System Monitor — main page.

Clean, flat-card layout using the shared app theme (core.theme) instead of
a standalone palette — matches mini_widget.py's existing look rather than
introducing a second visual style for the same module.
"""

import os
import subprocess
import sys
import time
import socket
import platform
import ctypes

import customtkinter as ctk
import psutil

from core import theme
from .colors import core_color, metric_colors


REFRESH_MS = 500
ANIM_MS = 20
SMOOTH_RATE = 0.16
PROC_RESORT_SAMPLES = 4
WARN_THRESHOLD = 80
TOP_PROCESS_COUNT = 10
IP_MASK_TEXT = "•••.•••.•••.•••"
SMOOTH_SCROLL_PX = 48     # pixels per mouse-wheel notch
SMOOTH_SCROLL_MS = 12     # animation frame interval (~83 fps)
SMOOTH_SCROLL_FRICTION = 0.88
SMOOTH_SCROLL_VEL_CAP = 0.09


def _usage_color(pct: float, base: str = None) -> str:
    """Danger-red past the warning threshold, otherwise `base` (each
    metric card / core bar passes its own base color instead of every
    bar sharing the one shared ACCENT)."""
    return theme.DANGER if pct >= WARN_THRESHOLD else (base or theme.ACCENT)


def _fmt_pct(pct: float) -> str:
    """Stable percent label — one decimal, no width jump at 10/100."""
    pct = max(0.0, min(100.0, float(pct)))
    if pct >= 100.0:
        return "100%"
    if pct >= 10.0:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"


def _fmt_count(n: int) -> str:
    return f"{int(n):,}"


def _byte_unit_size(n: float) -> tuple[float, str, float]:
    """Return (display value, unit label, divisor) for `n` bytes."""
    n = max(0.0, float(n))
    units = (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024), ("B", 1))
    for label, div in units:
        if n >= div or label == "B":
            return n / div, label, float(div)
    return n, "B", 1.0


def _fmt_bytes(n: float) -> str:
    """Human bytes with tidy decimals (no 12.0 MB when 12 MB reads cleaner)."""
    val, unit, _ = _byte_unit_size(n)
    if unit == "B":
        return f"{int(val)} B"
    if val >= 100:
        return f"{val:.0f} {unit}"
    if val >= 10:
        return f"{val:.1f} {unit}"
    return f"{val:.2f} {unit}"


def _fmt_bytes_pair(used: float, total: float) -> str:
    """Used / total in the same unit so the line doesn't swap KB↔MB."""
    _, unit, div = _byte_unit_size(max(total, used, 1))
    u = used / div
    t = total / div
    if unit == "B":
        return f"{int(u)} / {int(t)} B"
    if t >= 100:
        return f"{u:.0f} / {t:.0f} {unit}"
    if t >= 10:
        return f"{u:.1f} / {t:.1f} {unit}"
    return f"{u:.2f} / {t:.2f} {unit}"


def _fmt_rate(bytes_per_sec: float, *, sticky: dict | None = None) -> str:
    """Throughput label; optional `sticky` dict keeps the unit between refreshes."""
    rate = max(0.0, float(bytes_per_sec))
    if sticky is not None:
        div = sticky.get("divisor", 1024.0)
        unit = sticky.get("unit", "KB")
        if rate >= div * 768:
            while rate >= div * 768 and div < 1024 ** 3:
                div *= 1024
                unit = {"KB": "MB", "MB": "GB", "GB": "TB"}.get(unit, unit)
        elif rate < div * 0.75 and div > 1:
            div /= 1024
            unit = {"MB": "KB", "GB": "MB", "TB": "GB"}.get(unit, unit)
        sticky["divisor"] = div
        sticky["unit"] = unit
        val = rate / div
    else:
        val, unit, _ = _byte_unit_size(rate)
    if unit == "B":
        return f"{int(val)} B/s"
    if val >= 100:
        return f"{val:.0f} {unit}/s"
    if val >= 10:
        return f"{val:.1f} {unit}/s"
    return f"{val:.2f} {unit}/s"


def _fmt_mhz(mhz: float) -> str:
    mhz = max(0.0, float(mhz))
    if mhz >= 1000:
        ghz = mhz / 1000
        if ghz >= 10:
            return f"{ghz:.1f} GHz"
        return f"{ghz:.2f} GHz"
    return f"{mhz:.0f} MHz"


def _fmt_temp(celsius: float) -> str:
    return f"{float(celsius):.0f}°C"


def _system_uptime_seconds() -> int:
    """Seconds since last boot — GetTickCount64 on Windows avoids clock skew."""
    if platform.system() == "Windows":
        try:
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        except Exception:
            pass
    return max(0, int(time.time() - psutil.boot_time()))


def _fmt_uptime(total_s: int) -> str:
    total_s = max(0, int(total_s))
    days, rem = divmod(total_s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    clock = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if days:
        return f"{days}d {clock}"
    return clock


def _bytes_to_human(n: float) -> str:
    return _fmt_bytes(n)


class SmoothScalar:
    """Display value eases toward `target` each frame — no hard jumps."""

    __slots__ = ("display", "target", "rate", "cap")

    def __init__(self, initial: float = 0.0, *, rate: float = SMOOTH_RATE, cap: float | None = 100.0):
        self.display = float(initial)
        self.target = float(initial)
        self.rate = rate
        self.cap = cap

    def snap(self, value: float) -> None:
        if self.cap is not None:
            value = max(0.0, min(self.cap, float(value)))
        else:
            value = max(0.0, float(value))
        self.display = self.target = value

    def set_target(self, value: float) -> None:
        if self.cap is not None:
            self.target = max(0.0, min(self.cap, float(value)))
        else:
            self.target = max(0.0, float(value))

    def step(self) -> float:
        diff = self.target - self.display
        if abs(diff) < 0.04:
            self.display = self.target
        else:
            self.display += diff * self.rate
        return self.display


def _system_drive() -> str:
    if platform.system() == "Windows":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "—"


def _cpu_model() -> str:
    name = (platform.processor() or "").strip()
    if platform.system() == "Windows":
        try:
            flags = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            flags = 0
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "name"],
                text=True, timeout=2, creationflags=flags,
            )
            lines = [ln.strip() for ln in out.splitlines() if ln.strip() and ln.strip().lower() != "name"]
            if lines:
                return lines[0][:48]
        except Exception:
            pass
    if name and "family" not in name.lower():
        return name[:48]
    return "—"


def _query_nvidia_gpu() -> dict | None:
    try:
        flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    except AttributeError:
        flags = 0
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,name,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=2, creationflags=flags,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        parts = [p.strip() for p in out.stdout.strip().split(",")]
        if len(parts) < 4:
            return None
        util = float(parts[0])
        mem_used = float(parts[1])
        mem_total = float(parts[2])
        name = parts[3]
        temp = float(parts[4]) if len(parts) > 4 and parts[4] else None
        mem_pct = (mem_used / mem_total * 100) if mem_total else 0.0
        return {
            "name": name,
            "util": util,
            "mem_pct": mem_pct,
            "mem_detail": _fmt_bytes_pair(mem_used * 1024 * 1024, mem_total * 1024 * 1024),
            "temp": temp,
        }
    except Exception:
        return None


# --------------------------------------------------------------- stat row

class StatRow(ctk.CTkFrame):
    """Label + live number (+ optional detail). No bars or charts."""

    def __init__(self, parent, label: str, color: str = None, fg_color=theme.PANEL):
        super().__init__(parent, fg_color=fg_color, corner_radius=10)
        self.grid_columnconfigure(0, weight=1)
        self._color = color or theme.ACCENT

        ctk.CTkLabel(
            self, text=label, font=theme.font(11, "bold"), text_color=theme.MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))

        self.value_label = ctk.CTkLabel(
            self, text="—", font=theme.mono(22, "bold"), text_color=self._color, anchor="w",
        )
        self.value_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 2))

        self.detail_label = ctk.CTkLabel(
            self, text="", font=theme.mono(10), text_color=theme.FAINT, anchor="w",
        )
        self.detail_label.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 10))

        self._smooth = SmoothScalar()
        self._pending_detail = ""
        self._format_value = _fmt_pct

    def set_target(self, value: float, detail: str = "") -> None:
        self._smooth.set_target(value)
        if detail:
            self._pending_detail = detail

    def apply_smooth(self) -> None:
        value = self._smooth.step()
        color = _usage_color(value, self._color)
        self.value_label.configure(text=self._format_value(value), text_color=color)
        if self._pending_detail:
            self.detail_label.configure(text=self._pending_detail)
            self._pending_detail = ""


class ThroughputRow(StatRow):
    """Network / disk rate as a plain number."""

    def __init__(self, parent, label: str, color: str = None):
        super().__init__(parent, label, color=color, fg_color="transparent")
        self._rate_sticky = {"unit": "KB", "divisor": 1024.0}
        self._smooth = SmoothScalar(cap=None)
        self.detail_label.grid_remove()

    def set_target_throughput(self, bytes_per_sec: float, detail: str = "") -> None:
        self._smooth.set_target(max(0.0, bytes_per_sec))
        if detail:
            self._pending_detail = detail

    def apply_smooth(self) -> None:
        rate = self._smooth.step()
        color = _usage_color(min(rate / 1_048_576 * 100, 100.0), self._color)
        self.value_label.configure(
            text=_fmt_rate(rate, sticky=self._rate_sticky), text_color=color,
        )


def _core_grid_columns(count: int) -> int:
    return min(count, 8) or 1


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


class SmoothScrollableFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame with momentum wheel scrolling (no cancel/restart stutter)."""

    def __init__(self, *args, scroll_px: float = SMOOTH_SCROLL_PX, **kwargs):
        super().__init__(*args, **kwargs)
        self._scroll_px = scroll_px
        self._scroll_velocity = 0.0
        self._scroll_anim_job = None
        self._scrolling = False

    def is_scrolling(self) -> bool:
        return self._scrolling

    def _wheel_pixels(self, event) -> float:
        if sys.platform.startswith("win"):
            return -event.delta / 120.0 * self._scroll_px
        if sys.platform == "darwin":
            return -event.delta * 2.0
        return -self._scroll_px if event.num == 4 else self._scroll_px

    def _scroll_metrics(self) -> tuple[float, float, float] | None:
        canvas = self._parent_canvas
        bbox = canvas.bbox("all")
        if not bbox:
            return None
        total_h = max(1, bbox[3] - bbox[1])
        view_h = max(1, canvas.winfo_height())
        if total_h <= view_h:
            return None
        max_top = max(0.0, 1.0 - (view_h / total_h))
        return canvas.yview()[0], max_top, total_h

    def _add_scroll_velocity(self, pixels: float) -> None:
        metrics = self._scroll_metrics()
        if metrics is None:
            return
        _, _, total_h = metrics
        self._scroll_velocity += pixels / total_h
        self._scroll_velocity = max(
            -SMOOTH_SCROLL_VEL_CAP,
            min(SMOOTH_SCROLL_VEL_CAP, self._scroll_velocity),
        )
        self._start_scroll_loop()

    def _start_scroll_loop(self) -> None:
        if self._scroll_anim_job is not None:
            return
        self._scrolling = True
        self._scroll_loop()

    def _scroll_loop(self) -> None:
        if not self.winfo_exists():
            self._scroll_anim_job = None
            self._scrolling = False
            return

        metrics = self._scroll_metrics()
        if metrics is None or abs(self._scroll_velocity) < 1e-5:
            self._scroll_velocity = 0.0
            self._scroll_anim_job = None
            self._scrolling = False
            return

        current, max_top, _ = metrics
        next_pos = current + self._scroll_velocity
        if next_pos <= 0.0:
            next_pos = 0.0
            self._scroll_velocity = 0.0
        elif next_pos >= max_top:
            next_pos = max_top
            self._scroll_velocity = 0.0
        else:
            self._scroll_velocity *= SMOOTH_SCROLL_FRICTION

        self._parent_canvas.yview_moveto(next_pos)
        self._scroll_anim_job = self.after(SMOOTH_SCROLL_MS, self._scroll_loop)

    def _mouse_wheel_all(self, event):
        if not self._check_if_valid_scroll(event.widget):
            return
        if self._shift_pressed and self._orientation == "vertical":
            return super()._mouse_wheel_all(event)
        self._add_scroll_velocity(self._wheel_pixels(event))


# ------------------------------------------------------------------- main page

class SystemMonitorPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager
        self._system_drive = _system_drive()

        self._prev_net = psutil.net_io_counters()
        self._prev_net_time = time.monotonic()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_disk_time = time.monotonic()
        self._proc_cpu_ready = False
        self._cpu_model = _cpu_model()
        self._gpu_info = _query_nvidia_gpu()
        self._gpu_sample_counter = 0
        self._core_smooth: list[SmoothScalar] = []
        self._proc_smooth: dict[int, tuple[SmoothScalar, SmoothScalar, str]] = {}
        self._proc_order: list[int] = []
        self._proc_resort_counter = 0
        self._last_up_rate = 0.0
        self._last_down_rate = 0.0
        self._ip_revealed = False
        self._local_ip_value: str | None = None
        self._uptime_shown = -1

        self._build_ui()
        self._update_stats()
        self._start_live_anim()

    # ------------------------------------------------------------- layout

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = SmoothScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=theme.PANEL_2,
            scrollbar_button_hover_color=theme.PANEL_HOVER,
        )
        body.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        body.grid_columnconfigure(0, weight=1)
        self._scroll_body = body

        ctk.CTkLabel(
            body, text="System Monitor",
            font=theme.font(20, "bold"), text_color=theme.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 12))

        colors = metric_colors()

        # ---- live stats (numbers only) ----
        live_panel = ctk.CTkFrame(body, fg_color=theme.PANEL, corner_radius=10)
        live_panel.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        for i in range(4):
            live_panel.grid_columnconfigure(i, weight=1, uniform="live")

        ctk.CTkLabel(
            live_panel, text="LIVE", font=theme.font(11, "bold"),
            text_color=theme.MUTED, anchor="w",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(10, 6))

        disk_label = f"DISK ({self._system_drive.rstrip('\\')})"
        self.cpu_row = StatRow(live_panel, "CPU", color=colors["cpu"], fg_color="transparent")
        self.cpu_row.grid(row=1, column=0, padx=(16, 8), pady=(0, 8), sticky="nsew")

        self.ram_row = StatRow(live_panel, "MEMORY", color=colors["ram"], fg_color="transparent")
        self.ram_row.grid(row=1, column=1, padx=8, pady=(0, 8), sticky="nsew")

        self.disk_row = StatRow(live_panel, disk_label, color=colors["disk"], fg_color="transparent")
        self.disk_row.grid(row=1, column=2, padx=8, pady=(0, 8), sticky="nsew")

        self.swap_row = StatRow(live_panel, "SWAP", color=colors["swap"], fg_color="transparent")
        self.swap_row.grid(row=1, column=3, padx=(8, 16), pady=(0, 8), sticky="nsew")

        self.net_down_row = ThroughputRow(live_panel, "NET ↓", color=colors["net_down"])
        self.net_down_row.grid(row=2, column=0, padx=(16, 8), pady=(0, 8), sticky="nsew")

        self.net_up_row = ThroughputRow(live_panel, "NET ↑", color=colors["net_up"])
        self.net_up_row.grid(row=2, column=1, padx=8, pady=(0, 8), sticky="nsew")

        self.disk_read_row = ThroughputRow(live_panel, "DISK READ", color=colors["disk_read"])
        self.disk_read_row.grid(row=2, column=2, padx=8, pady=(0, 8), sticky="nsew")

        self.disk_write_row = ThroughputRow(live_panel, "DISK WRITE", color=colors["disk_write"])
        self.disk_write_row.grid(row=2, column=3, padx=(8, 16), pady=(0, 12), sticky="nsew")

        self._gpu_util_row = None
        self._gpu_vram_row = None
        if self._gpu_info:
            ctk.CTkLabel(
                live_panel,
                text=f"GPU — {self._gpu_info['name'][:42]}",
                font=theme.font(10, "bold"),
                text_color=theme.FAINT,
                anchor="w",
            ).grid(row=3, column=0, columnspan=4, sticky="w", padx=16, pady=(4, 4))

            self._gpu_util_row = StatRow(
                live_panel, "GPU LOAD", color=colors["gpu"], fg_color="transparent",
            )
            self._gpu_util_row.grid(row=4, column=0, columnspan=2, padx=(16, 8), pady=(0, 12), sticky="ew")

            self._gpu_vram_row = StatRow(
                live_panel, "VRAM", color=colors["gpu"], fg_color="transparent",
            )
            self._gpu_vram_row.grid(row=4, column=2, columnspan=2, padx=(8, 16), pady=(0, 12), sticky="ew")

        # ---- per-core CPU row ----
        core_panel = ctk.CTkFrame(body, fg_color=theme.PANEL, corner_radius=10)
        core_panel.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        core_panel.grid_columnconfigure(0, weight=1)

        core_header = ctk.CTkFrame(core_panel, fg_color="transparent")
        core_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        core_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            core_header, text="PER-CORE", font=theme.font(11, "bold"),
            text_color=theme.MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._core_summary = ctk.CTkLabel(
            core_header, text="—", font=theme.mono(9),
            text_color=theme.FAINT, anchor="e",
        )
        self._core_summary.grid(row=0, column=1, sticky="e")

        self._core_grid = ctk.CTkFrame(core_panel, fg_color="transparent")
        self._core_grid.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        self._core_labels: list[ctk.CTkLabel] = []
        self._build_core_labels(psutil.cpu_count(logical=True) or 1)

        # ---- two-column bottom section: system info + top processes ----
        bottom = ctk.CTkFrame(body, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)

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
        self._cpu_model_val = _info_row(info_grid, 2, "CPU")
        self._cores_val = _info_row(info_grid, 3, "Cores / Threads")
        self._mem_val = _info_row(info_grid, 4, "Total RAM")
        self._ip_val = _info_row(info_grid, 5, "Local IP")
        self._ip_val.configure(cursor="hand2")
        self._ip_val.bind("<Button-1>", self._toggle_local_ip)
        self._refresh_ip_display()
        self._up_val = _info_row(info_grid, 6, "Uptime")
        self._battery_val = _info_row(info_grid, 7, "Battery")
        self._net_val = _info_row(info_grid, 8, "Network (↑ / ↓)")
        self._proc_count_val = _info_row(info_grid, 9, "Processes")
        self._gpu_val = _info_row(info_grid, 10, "GPU")

        # -- top processes --
        proc_panel = ctk.CTkFrame(bottom, fg_color=theme.PANEL, corner_radius=10)
        proc_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        proc_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            proc_panel, text=f"TOP PROCESSES (by CPU)", font=theme.font(11, "bold"),
            text_color=theme.MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        self._proc_list_frame = ctk.CTkFrame(proc_panel, fg_color="transparent")
        self._proc_list_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 12))
        self._proc_list_frame.grid_columnconfigure(0, weight=1)
        self._proc_row_labels: list[tuple[ctk.CTkLabel, ctk.CTkLabel, ctk.CTkLabel]] = []
        self._build_proc_rows(TOP_PROCESS_COUNT)

    def _build_core_labels(self, count: int) -> None:
        cols = _core_grid_columns(count)
        for i in range(count):
            r, c = divmod(i, cols)
            lbl = ctk.CTkLabel(
                self._core_grid,
                text=f"{i:02d} —",
                font=theme.mono(12),
                text_color=theme.MUTED,
                anchor="w",
                width=84,
            )
            lbl.grid(row=r, column=c, sticky="w", padx=(0, 6), pady=2)
            self._core_labels.append(lbl)
        self._core_smooth = [SmoothScalar() for _ in range(count)]

    def _build_proc_rows(self, count: int) -> None:
        header = ctk.CTkFrame(self._proc_list_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=4)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="NAME", font=theme.font(9, "bold"), text_color=theme.FAINT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header, text="CPU%", font=theme.font(9, "bold"), text_color=theme.FAINT, width=52,
        ).grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            header, text="MEM%", font=theme.font(9, "bold"), text_color=theme.FAINT, width=52,
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
                row, text="—", font=theme.mono(10), text_color=theme.MUTED, width=52,
            )
            cpu_lbl.grid(row=0, column=1, sticky="e")

            mem_lbl = ctk.CTkLabel(
                row, text="—", font=theme.mono(10), text_color=theme.MUTED, width=52,
            )
            mem_lbl.grid(row=0, column=2, sticky="e", padx=(8, 4))

            self._proc_row_labels.append((name_lbl, cpu_lbl, mem_lbl))

    # ------------------------------------------------------------- update

    def _toggle_local_ip(self, _event=None) -> None:
        self._ip_revealed = not self._ip_revealed
        if self._ip_revealed and self._local_ip_value is None:
            self._local_ip_value = _local_ip()
        self._refresh_ip_display()

    def _refresh_ip_display(self) -> None:
        if self._ip_revealed:
            ip = self._local_ip_value or _local_ip()
            self._local_ip_value = ip
            self._ip_val.configure(text=ip, text_color=theme.TEXT)
        else:
            self._ip_val.configure(text=IP_MASK_TEXT, text_color=theme.MUTED)

    def _refresh_uptime(self) -> None:
        uptime_s = _system_uptime_seconds()
        if uptime_s != self._uptime_shown:
            self._uptime_shown = uptime_s
            self._up_val.configure(text=_fmt_uptime(uptime_s))

    def _start_live_anim(self) -> None:
        self._animate_live()

    def _animate_live(self) -> None:
        if not self.winfo_exists():
            return

        self.cpu_row.apply_smooth()
        self.ram_row.apply_smooth()
        self.disk_row.apply_smooth()
        self.swap_row.apply_smooth()
        self.net_down_row.apply_smooth()
        self.net_up_row.apply_smooth()
        self.disk_read_row.apply_smooth()
        self.disk_write_row.apply_smooth()
        if self._gpu_util_row:
            self._gpu_util_row.apply_smooth()
        if self._gpu_vram_row:
            self._gpu_vram_row.apply_smooth()

        core_values: list[float] = []
        for i, smooth in enumerate(self._core_smooth):
            if i >= len(self._core_labels):
                break
            pct = smooth.step()
            self._core_labels[i].configure(
                text=f"{i:02d} {_fmt_pct(pct)}",
                text_color=_usage_color(pct, core_color(i)),
            )
            core_values.append(pct)

        if core_values:
            avg = sum(core_values) / len(core_values)
            peak = max(core_values)
            self._core_summary.configure(
                text=f"avg {_fmt_pct(avg)} · peak {_fmt_pct(peak)}",
            )

        self._refresh_uptime()
        self._apply_proc_smooth()
        self.after(ANIM_MS, self._animate_live)

    def _apply_proc_smooth(self) -> None:
        for i, (name_lbl, cpu_lbl, mem_lbl) in enumerate(self._proc_row_labels):
            if i >= len(self._proc_order):
                name_lbl.configure(text="—")
                cpu_lbl.configure(text="—", text_color=theme.MUTED)
                mem_lbl.configure(text="—")
                continue
            pid = self._proc_order[i]
            entry = self._proc_smooth.get(pid)
            if entry is None:
                name_lbl.configure(text="—")
                cpu_lbl.configure(text="—", text_color=theme.MUTED)
                mem_lbl.configure(text="—")
                continue
            cpu_s, mem_s, name = entry
            cpu_pct = cpu_s.step()
            mem_pct = mem_s.step()
            name_lbl.configure(text=name)
            cpu_lbl.configure(
                text=f"{cpu_pct:5.1f}",
                text_color=_usage_color(min(cpu_pct, 100.0), theme.MUTED),
            )
            mem_lbl.configure(text=f"{mem_pct:5.1f}")

    def _update_stats(self):
        if not self.winfo_exists():
            return
        if getattr(self, "_scroll_body", None) and self._scroll_body.is_scrolling():
            self.after(80, self._update_stats)
            return

        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage(self._system_drive)
        swap = psutil.swap_memory()
        per_core = psutil.cpu_percent(percpu=True)
        freq = psutil.cpu_freq()

        cpu_detail = f"{psutil.cpu_count(logical=True)} threads"
        if freq and freq.current:
            cpu_detail = f"{_fmt_mhz(freq.current)} · {cpu_detail}"
        self.cpu_row.set_target(cpu, cpu_detail)
        self.ram_row.set_target(ram.percent, _fmt_bytes_pair(ram.used, ram.total))
        self.disk_row.set_target(disk.percent, _fmt_bytes_pair(disk.used, disk.total))
        if swap.total > 0:
            self.swap_row.set_target(swap.percent, _fmt_bytes_pair(swap.used, swap.total))
        else:
            self.swap_row.set_target(0, "No swap configured")

        for i, pct in enumerate(per_core):
            if i < len(self._core_smooth):
                self._core_smooth[i].set_target(pct)

        # -- network + disk throughput --
        now = time.monotonic()
        current_net = psutil.net_io_counters()
        elapsed = max(now - self._prev_net_time, 0.001)
        up_rate = (current_net.bytes_sent - self._prev_net.bytes_sent) / elapsed
        down_rate = (current_net.bytes_recv - self._prev_net.bytes_recv) / elapsed
        self._last_up_rate = up_rate
        self._last_down_rate = down_rate
        self.net_down_row.set_target_throughput(down_rate)
        self.net_up_row.set_target_throughput(up_rate)
        self._prev_net = current_net
        self._prev_net_time = now

        current_disk = psutil.disk_io_counters()
        if current_disk is not None:
            if self._prev_disk is not None:
                disk_elapsed = max(now - self._prev_disk_time, 0.001)
                read_rate = (current_disk.read_bytes - self._prev_disk.read_bytes) / disk_elapsed
                write_rate = (current_disk.write_bytes - self._prev_disk.write_bytes) / disk_elapsed
                self.disk_read_row.set_target_throughput(read_rate)
                self.disk_write_row.set_target_throughput(write_rate)
            self._prev_disk = current_disk
            self._prev_disk_time = now

        gpu = None
        self._gpu_sample_counter += 1
        if self._gpu_sample_counter >= 2:
            self._gpu_sample_counter = 0
            gpu = _query_nvidia_gpu()
        if gpu and self._gpu_util_row and self._gpu_vram_row:
            temp_detail = _fmt_temp(gpu["temp"]) if gpu.get("temp") is not None else ""
            self._gpu_util_row.set_target(gpu["util"], temp_detail)
            self._gpu_vram_row.set_target(gpu["mem_pct"], gpu["mem_detail"])
            self._gpu_info = gpu

        # -- system info --
        self._os_val.configure(text=f"{platform.system()} {platform.release()}")
        self._host_val.configure(text=socket.gethostname())
        self._cpu_model_val.configure(text=self._cpu_model)
        self._cores_val.configure(
            text=f"{psutil.cpu_count(logical=False)} cores · {psutil.cpu_count(logical=True)} threads"
        )
        self._mem_val.configure(text=_fmt_bytes(ram.total))

        self._proc_count_val.configure(text=_fmt_count(len(psutil.pids())))

        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery is None:
            self._battery_val.configure(text="No battery")
        else:
            state = "charging" if battery.power_plugged else "on battery"
            self._battery_val.configure(text=f"{_fmt_pct(battery.percent)} ({state})")

        self._net_val.configure(
            text=f"↑ {_fmt_rate(self._last_up_rate)} · ↓ {_fmt_rate(self._last_down_rate)}"
        )

        gpu = self._gpu_info
        if gpu:
            gpu_line = f"{gpu['name'][:36]} · {_fmt_pct(gpu['util'])}"
            if gpu.get("temp") is not None:
                gpu_line += f" · {_fmt_temp(gpu['temp'])}"
            self._gpu_val.configure(text=gpu_line)
        else:
            self._gpu_val.configure(text="Not detected")

        # -- top processes by CPU --
        self._update_top_processes()

        self.after(REFRESH_MS, self._update_stats)

    def _update_top_processes(self) -> None:
        if not self._proc_cpu_ready:
            for p in psutil.process_iter():
                try:
                    p.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self._proc_cpu_ready = True
            return

        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_percent"]):
            try:
                info = p.info
                name = info.get("name") or "?"
                if name.lower() in {"system idle process", "idle"}:
                    continue
                cpu_pct = p.cpu_percent(None)
                if cpu_pct is None:
                    cpu_pct = 0.0
                info["cpu_percent"] = cpu_pct
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda info: info.get("cpu_percent") or 0, reverse=True)
        top = procs[:TOP_PROCESS_COUNT]

        self._proc_resort_counter += 1
        if self._proc_resort_counter >= PROC_RESORT_SAMPLES or not self._proc_order:
            self._proc_resort_counter = 0
            self._proc_order = [info["pid"] for info in top]

        seen_pids = set()
        for info in top:
            pid = info["pid"]
            seen_pids.add(pid)
            cpu_pct = info.get("cpu_percent") or 0.0
            mem_pct = info.get("memory_percent") or 0.0
            name = (info.get("name") or "?")[:26]
            if pid not in self._proc_smooth:
                cpu_s = SmoothScalar(cpu_pct)
                mem_s = SmoothScalar(mem_pct)
                self._proc_smooth[pid] = (cpu_s, mem_s, name)
            else:
                cpu_s, mem_s, _ = self._proc_smooth[pid]
                self._proc_smooth[pid] = (cpu_s, mem_s, name)
            cpu_s.set_target(cpu_pct)
            mem_s.set_target(mem_pct)

        for pid in list(self._proc_smooth):
            if pid not in seen_pids and pid not in self._proc_order:
                del self._proc_smooth[pid]
