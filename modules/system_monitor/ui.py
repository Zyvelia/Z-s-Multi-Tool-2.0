import customtkinter as ctk
import tkinter as tk
import psutil
import platform
import socket
import time
import math

# ── Palette ──────────────────────────────────────────────
BG      = "#07090f"   # near-black base
PANEL   = "#0d1120"   # card background
BORDER  = "#1a2540"   # subtle border / track
ACCENT  = "#00d9ff"   # cyan glow — the signature colour
ACCENT2 = "#0099cc"   # darker cyan for arc track
WARN    = "#ff6b6b"   # high-usage alert
OK      = "#00d9ff"   # normal usage

TEXT    = "#e8edf5"   # primary text
MUTED   = "#4a5878"   # dimmed labels
MONO    = ("Consolas", 11)   # monospaced data face
HEAD    = ("Segoe UI", 11, "bold")

# Threshold above which the arc turns red
WARN_THRESHOLD = 80


def _arc_color(pct: float) -> str:
    return WARN if pct >= WARN_THRESHOLD else ACCENT


# ── Circular arc gauge ────────────────────────────────────

class ArcGauge(tk.Canvas):
    """A self-contained circular gauge drawn with tk.Canvas arcs."""

    SIZE   = 130          # canvas width & height
    RADIUS = 50           # arc radius from centre
    WIDTH  = 12           # stroke width of both track and arc

    def __init__(self, parent, label: str):
        super().__init__(
            parent,
            width=self.SIZE,
            height=self.SIZE,
            bg=PANEL,
            highlightthickness=0,
        )
        self._label  = label
        self._pct    = 0.0
        self._cx     = self.SIZE / 2
        self._cy     = self.SIZE / 2 - 6   # shift up slightly so label fits

        # Track (full circle, muted)
        self._draw_arc(0, 360, BORDER, tag="track")

        # Live arc (starts empty)
        self._arc_id = None
        self._draw_filled_arc(0)

        # Centre percentage text
        self._val_id = self.create_text(
            self._cx, self._cy,
            text="0%",
            fill=ACCENT,
            font=("Consolas", 18, "bold"),
        )

        # Bottom label
        self.create_text(
            self._cx, self.SIZE - 10,
            text=label.upper(),
            fill=MUTED,
            font=("Segoe UI", 8, "bold"),
        )

    # ── internal helpers ──────────────────────────────────

    def _bbox(self):
        r = self.RADIUS
        return (
            self._cx - r, self._cy - r,
            self._cx + r, self._cy + r,
        )

    def _draw_arc(self, start, extent, color, tag=None):
        kw = dict(
            outline=color,
            style="arc",
            width=self.WIDTH,
            start=start,
            extent=extent,
        )
        if tag:
            kw["tags"] = tag
        self.create_arc(*self._bbox(), **kw)

    def _draw_filled_arc(self, pct: float):
        if self._arc_id:
            self.delete(self._arc_id)
        if pct <= 0:
            self._arc_id = None
            return
        extent = (pct / 100) * 359.9   # avoid full-circle collapse
        color  = _arc_color(pct)
        self._arc_id = self.create_arc(
            *self._bbox(),
            outline=color,
            style="arc",
            width=self.WIDTH,
            start=90,           # top of circle
            extent=-extent,     # clockwise
        )

    # ── public ───────────────────────────────────────────

    def set_value(self, pct: float):
        self._pct = pct
        self._draw_filled_arc(pct)
        color = _arc_color(pct)
        self.itemconfig(self._val_id, text=f"{pct:.0f}%", fill=color)


# ── Info row helper ───────────────────────────────────────

def _info_row(parent, row: int, icon: str, key: str, col_offset: int = 0):
    """Create a key/value pair and return the value label."""
    base_col = col_offset * 3  # each column block occupies 3 grid columns

    # Icon
    tk.Label(
        parent,
        text=icon,
        bg=PANEL,
        fg=MUTED,
        font=("Segoe UI", 12),
    ).grid(row=row, column=base_col, padx=(18, 4), pady=6, sticky="w")

    # Key
    tk.Label(
        parent,
        text=key,
        bg=PANEL,
        fg=MUTED,
        font=("Segoe UI", 10),
    ).grid(row=row, column=base_col + 1, padx=(0, 8), pady=6, sticky="w")

    # Value (returned so caller can update it)
    val = tk.Label(
        parent,
        text="—",
        bg=PANEL,
        fg=TEXT,
        font=MONO,
        anchor="w",
    )
    val.grid(row=row, column=base_col + 2, padx=(0, 24), pady=6, sticky="w")
    return val


# ── Main page ─────────────────────────────────────────────

class SystemMonitorPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.configure(fg_color=BG)
        self.build_ui()
        self.update_stats()

    # ── build ─────────────────────────────────────────────

    def build_ui(self):
        # ── Header ──────────────────────────────────────
        hdr = tk.Frame(self, bg=PANEL, height=56)
        hdr.pack(fill="x", padx=16, pady=(16, 0))
        hdr.pack_propagate(False)

        # Thin cyan accent line at top of header
        accent_bar = tk.Frame(self, bg=ACCENT, height=2)
        accent_bar.pack(fill="x", padx=16)

        tk.Label(
            hdr,
            text="SYSTEM  MONITOR",
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left", padx=6)

        # Live dot
        self._dot_canvas = tk.Canvas(hdr, width=10, height=10, bg=PANEL, highlightthickness=0)
        self._dot_canvas.pack(side="left", padx=4, pady=0)
        self._dot = self._dot_canvas.create_oval(1, 1, 9, 9, fill=ACCENT, outline="")
        self._dot_visible = True

        # ── Gauge row ────────────────────────────────────
        gauge_frame = tk.Frame(self, bg=BG)
        gauge_frame.pack(fill="x", padx=16, pady=12)
        gauge_frame.columnconfigure((0, 1, 2), weight=1)

        self.cpu_gauge  = self._make_gauge(gauge_frame, "CPU",  0)
        self.ram_gauge  = self._make_gauge(gauge_frame, "RAM",  1)
        self.disk_gauge = self._make_gauge(gauge_frame, "DISK", 2)

        # ── Divider ──────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(0, 12))

        # ── System info grid ─────────────────────────────
        info_outer = tk.Frame(self, bg=PANEL, bd=0, relief="flat")
        info_outer.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Section label
        tk.Label(
            info_outer,
            text="  SYSTEM INFO",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(10, 4))

        tk.Frame(info_outer, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(0, 6))

        grid = tk.Frame(info_outer, bg=PANEL)
        grid.pack(fill="both", expand=True)

        # Left column
        self._os_val     = _info_row(grid, 0, "🖥", "OS",           col_offset=0)
        self._host_val   = _info_row(grid, 1, "📡", "Hostname",     col_offset=0)
        self._cores_val  = _info_row(grid, 2, "⚙️", "CPU Cores",    col_offset=0)
        self._thread_val = _info_row(grid, 3, "🔀", "CPU Threads",  col_offset=0)

        # Vertical divider between columns
        tk.Frame(grid, bg=BORDER, width=1).grid(
            row=0, column=3, rowspan=5, padx=4, pady=8, sticky="ns"
        )

        # Right column
        self._mem_val  = _info_row(grid, 0, "🧠", "Total RAM",      col_offset=1)
        self._up_val   = _info_row(grid, 1, "⏱", "Uptime",          col_offset=1)
        self._sent_val = _info_row(grid, 2, "↑", "Net Sent",         col_offset=1)
        self._recv_val = _info_row(grid, 3, "↓", "Net Received",     col_offset=1)

    def _make_gauge(self, parent, label: str, col: int) -> ArcGauge:
        card = tk.Frame(parent, bg=PANEL, bd=0)
        card.grid(row=0, column=col, padx=6, pady=4, sticky="nsew")

        gauge = ArcGauge(card, label)
        gauge.pack(padx=20, pady=16)
        return gauge

    # ── update ────────────────────────────────────────────

    def update_stats(self):
        # Usage
        cpu  = psutil.cpu_percent()
        ram  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        self.cpu_gauge.set_value(cpu)
        self.ram_gauge.set_value(ram.percent)
        self.disk_gauge.set_value(disk.percent)

        # System info
        self._os_val.config(
            text=f"{platform.system()} {platform.release()}"
        )
        self._host_val.config(text=socket.gethostname())
        self._cores_val.config(text=str(psutil.cpu_count(logical=False)))
        self._thread_val.config(text=str(psutil.cpu_count(logical=True)))
        self._mem_val.config(
            text=f"{round(ram.total / (1024**3), 1)} GB"
        )

        uptime_s = int(time.time() - psutil.boot_time())
        d = uptime_s // 86400
        h = (uptime_s % 86400) // 3600
        m = (uptime_s % 3600) // 60
        self._up_val.config(text=f"{d}d {h:02d}h {m:02d}m")

        net = psutil.net_io_counters()
        self._sent_val.config(text=f"{net.bytes_sent / 1024**3:.2f} GB")
        self._recv_val.config(text=f"{net.bytes_recv / 1024**3:.2f} GB")

        # Blink the live dot
        self._dot_visible = not self._dot_visible
        color = ACCENT if self._dot_visible else PANEL
        self._dot_canvas.itemconfig(self._dot, fill=color)

        self.after(1000, self.update_stats)
