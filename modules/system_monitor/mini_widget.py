# modules/system_monitor/mini_widget.py
#
# A compact, self-updating CPU/RAM readout meant to live INSIDE a catalog
# tool card (see core/tool_registry.py's optional "widget" key), as opposed
# to system_monitor/ui.py's full-page gauges opened via "Open".

import customtkinter as ctk
import psutil

from core import theme

REFRESH_MS = 1500


class SystemMonitorMiniWidget(ctk.CTkFrame):

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        self._cpu_bar = self._build_row(0, "CPU")
        self._ram_bar = self._build_row(1, "RAM")

        self._tick()

    def _build_row(self, row, label):
        ctk.CTkLabel(
            self,
            text=label,
            font=theme.font(10, "bold"),
            text_color=theme.FAINT,
            width=32,
            anchor="w"
        ).grid(row=row, column=0, sticky="w", pady=2)

        bar = ctk.CTkProgressBar(
            self,
            height=8,
            corner_radius=4,
            fg_color=theme.PANEL_2,
            progress_color=theme.ACCENT
        )
        bar.set(0)
        bar.grid(row=row, column=1, sticky="ew", padx=8, pady=2)

        pct_label = ctk.CTkLabel(
            self,
            text="—",
            font=theme.mono(10),
            text_color=theme.MUTED,
            width=32,
            anchor="e"
        )
        pct_label.grid(row=row, column=2, sticky="e", pady=2)

        # stash the label on the bar so _tick() can update both together
        bar.pct_label = pct_label
        return bar

    def _tick(self):
        # Guard against the app closing / this widget being destroyed by a
        # catalog re-render (hide, search, category switch) while a
        # scheduled .after() callback is still pending — without this,
        # Tkinter raises "invalid command name" trying to touch a dead
        # widget.
        if not self.winfo_exists():
            return

        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent

            self._cpu_bar.set(cpu / 100)
            self._cpu_bar.pct_label.configure(text=f"{cpu:.0f}%")

            self._ram_bar.set(ram / 100)
            self._ram_bar.pct_label.configure(text=f"{ram:.0f}%")

            for bar, val in ((self._cpu_bar, cpu), (self._ram_bar, ram)):
                bar.configure(
                    progress_color=theme.DANGER if val >= 85 else theme.ACCENT
                )
        except Exception:
            pass

        self.after(REFRESH_MS, self._tick)


def build(parent, manager=None):
    return SystemMonitorMiniWidget(parent)
