"""CTk-free system snapshots for System Monitor (psutil + optional nvidia-smi)."""

from __future__ import annotations

import ctypes
import os
import platform
import socket
import subprocess
import time

import psutil

REFRESH_MS = 750
TOP_PROCESS_COUNT = 10
IP_MASK_TEXT = "•••.•••.•••.•••"
WARN_THRESHOLD = 80


def fmt_pct(pct: float) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    if pct >= 100.0:
        return "100%"
    if pct >= 10.0:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"


def fmt_count(n: int) -> str:
    return f"{int(n):,}"


def byte_unit_size(n: float) -> tuple[float, str, float]:
    n = max(0.0, float(n))
    units = (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024), ("B", 1))
    for label, div in units:
        if n >= div or label == "B":
            return n / div, label, float(div)
    return n, "B", 1.0


def fmt_bytes(n: float) -> str:
    val, unit, _ = byte_unit_size(n)
    if unit == "B":
        return f"{int(val)} B"
    if val >= 100:
        return f"{val:.0f} {unit}"
    if val >= 10:
        return f"{val:.1f} {unit}"
    return f"{val:.2f} {unit}"


def fmt_bytes_pair(used: float, total: float) -> str:
    _, unit, div = byte_unit_size(max(total, used, 1))
    u = used / div
    t = total / div
    if unit == "B":
        return f"{int(u)} / {int(t)} B"
    if t >= 100:
        return f"{u:.0f} / {t:.0f} {unit}"
    if t >= 10:
        return f"{u:.1f} / {t:.1f} {unit}"
    return f"{u:.2f} / {t:.2f} {unit}"


def fmt_rate(bytes_per_sec: float) -> str:
    rate = max(0.0, float(bytes_per_sec))
    val, unit, _ = byte_unit_size(rate)
    if unit == "B":
        return f"{int(val)} B/s"
    if val >= 100:
        return f"{val:.0f} {unit}/s"
    if val >= 10:
        return f"{val:.1f} {unit}/s"
    return f"{val:.2f} {unit}/s"


def fmt_mhz(mhz: float) -> str:
    mhz = max(0.0, float(mhz))
    if mhz >= 1000:
        ghz = mhz / 1000
        if ghz >= 10:
            return f"{ghz:.1f} GHz"
        return f"{ghz:.2f} GHz"
    return f"{mhz:.0f} MHz"


def fmt_temp(celsius: float) -> str:
    return f"{float(celsius):.0f}°C"


def system_uptime_seconds() -> int:
    if platform.system() == "Windows":
        try:
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        except Exception:
            pass
    return max(0, int(time.time() - psutil.boot_time()))


def fmt_uptime(total_s: int) -> str:
    total_s = max(0, int(total_s))
    days, rem = divmod(total_s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    clock = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if days:
        return f"{days}d {clock}"
    return clock


def system_drive() -> str:
    if platform.system() == "Windows":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "—"


def cpu_model() -> str:
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


def query_nvidia_gpu() -> dict | None:
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
            "mem_detail": fmt_bytes_pair(mem_used * 1024 * 1024, mem_total * 1024 * 1024),
            "temp": temp,
        }
    except Exception:
        return None


class MetricsSampler:
    """Stateful psutil sampler — call `take()` off the UI thread."""

    def __init__(self):
        self.drive = system_drive()
        self.cpu_name = cpu_model()
        self._prev_net = psutil.net_io_counters()
        self._prev_net_time = time.monotonic()
        self._prev_disk = psutil.disk_io_counters()
        self._prev_disk_time = time.monotonic()
        self._proc_cpu_ready = False
        self._gpu_sample_counter = 0
        self._gpu = query_nvidia_gpu()
        self._last_up = 0.0
        self._last_down = 0.0
        self._last_read = 0.0
        self._last_write = 0.0

    def take(self) -> dict:
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage(self.drive)
        swap = psutil.swap_memory()
        per_core = psutil.cpu_percent(percpu=True)
        freq = psutil.cpu_freq()

        cpu_detail = f"{psutil.cpu_count(logical=True)} threads"
        if freq and freq.current:
            cpu_detail = f"{fmt_mhz(freq.current)} · {cpu_detail}"

        now = time.monotonic()
        current_net = psutil.net_io_counters()
        elapsed = max(now - self._prev_net_time, 0.001)
        up_rate = (current_net.bytes_sent - self._prev_net.bytes_sent) / elapsed
        down_rate = (current_net.bytes_recv - self._prev_net.bytes_recv) / elapsed
        self._last_up = up_rate
        self._last_down = down_rate
        self._prev_net = current_net
        self._prev_net_time = now

        current_disk = psutil.disk_io_counters()
        if current_disk is not None:
            if self._prev_disk is not None:
                disk_elapsed = max(now - self._prev_disk_time, 0.001)
                self._last_read = (current_disk.read_bytes - self._prev_disk.read_bytes) / disk_elapsed
                self._last_write = (current_disk.write_bytes - self._prev_disk.write_bytes) / disk_elapsed
            self._prev_disk = current_disk
            self._prev_disk_time = now

        self._gpu_sample_counter += 1
        if self._gpu_sample_counter >= 2:
            self._gpu_sample_counter = 0
            gpu = query_nvidia_gpu()
            if gpu:
                self._gpu = gpu

        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None
        if battery is None:
            battery_text = "No battery"
        else:
            state = "charging" if battery.power_plugged else "on battery"
            battery_text = f"{fmt_pct(battery.percent)} ({state})"

        return {
            "cpu": cpu,
            "cpu_detail": cpu_detail,
            "ram": ram.percent,
            "ram_detail": fmt_bytes_pair(ram.used, ram.total),
            "disk": disk.percent,
            "disk_detail": fmt_bytes_pair(disk.used, disk.total),
            "disk_label": f"DISK ({self.drive.rstrip(chr(92))})",
            "swap": swap.percent if swap.total > 0 else 0.0,
            "swap_detail": fmt_bytes_pair(swap.used, swap.total) if swap.total > 0 else "No swap configured",
            "per_core": list(per_core),
            "net_up": up_rate,
            "net_down": down_rate,
            "disk_read": self._last_read,
            "disk_write": self._last_write,
            "gpu": self._gpu,
            "os": f"{platform.system()} {platform.release()}",
            "hostname": socket.gethostname(),
            "cpu_model": self.cpu_name,
            "cores": f"{psutil.cpu_count(logical=False)} cores · {psutil.cpu_count(logical=True)} threads",
            "total_ram": fmt_bytes(ram.total),
            "local_ip": local_ip(),
            "uptime": fmt_uptime(system_uptime_seconds()),
            "battery": battery_text,
            "process_count": fmt_count(len(psutil.pids())),
            "processes": self._top_processes(),
        }

    def _top_processes(self) -> list[dict]:
        if not self._proc_cpu_ready:
            for p in psutil.process_iter():
                try:
                    p.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self._proc_cpu_ready = True
            return []

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
        top = []
        for info in procs[:TOP_PROCESS_COUNT]:
            top.append({
                "pid": info.get("pid"),
                "name": (info.get("name") or "?")[:32],
                "cpu": float(info.get("cpu_percent") or 0.0),
                "mem": float(info.get("memory_percent") or 0.0),
            })
        return top
