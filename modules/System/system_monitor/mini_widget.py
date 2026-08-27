# modules/system_monitor/mini_widget.py
#
# A compact, self-updating CPU/RAM readout meant to live INSIDE a catalog
# tool card (see core/tool_registry.py's optional "widget" key), as opposed
# to system_monitor/ui.py's full-page gauges opened via "Open".

import customtkinter as ctk
import psutil

from core import theme

try:
    from .colors import metric_color
except ImportError:  # pragma: no cover
    from ._theme import METRIC_COLORS

    def metric_color(key: str) -> str:
        return METRIC_COLORS[key]

REFRESH_MS = 1500


class SystemMonitorMiniWidget(ctk.CTkFrame):

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)

        self._cpu_label = self._build_row(0, "CPU", metric_color("cpu"))
        self._ram_label = self._build_row(1, "RAM", metric_color("ram"))

        self._tick()

    def _build_row(self, row, label, color):
        ctk.CTkLabel(
            self,
            text=label,
            font=theme.font(10, "bold"),
            text_color=theme.FAINT,
            width=32,
            anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=2)

        pct_label = ctk.CTkLabel(
            self,
            text="—",
            font=theme.mono(11, "bold"),
            text_color=color,
            anchor="e",
        )
        pct_label.grid(row=row, column=1, sticky="e", pady=2)
        pct_label.base_color = color
        return pct_label

    def _tick(self):
        if not self.winfo_exists():
            return

        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent

            self._cpu_label.configure(
                text=f"{cpu:.1f}%",
                text_color=theme.DANGER if cpu >= 85 else self._cpu_label.base_color,
            )
            self._ram_label.configure(
                text=f"{ram:.1f}%",
                text_color=theme.DANGER if ram >= 85 else self._ram_label.base_color,
            )
        except Exception:
            pass

        self.after(REFRESH_MS, self._tick)


def build(parent, manager=None):
    return SystemMonitorMiniWidget(parent)
