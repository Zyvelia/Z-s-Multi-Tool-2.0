from .ui import SystemMonitorPage
from .mini_widget import build as build_mini_widget


def open_system_monitor(manager):

    return SystemMonitorPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "System Monitor",
            "category": "System",
            "desc": "Live system statistics",
            "icon": "🖥️",
            "open": open_system_monitor,
            "widget": build_mini_widget
        }
    )


def run():
    """Launch System Monitor as its own standalone window (no Zs Multi Tool
    manager required). This is what main.py calls."""
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")

    root = ctk.CTk()
    root.title("System Monitor")
    root.geometry("980x680")
    root.minsize(760, 560)
    root.configure(fg_color="#0f1115")

    page = SystemMonitorPage(root, manager=None)
    page.pack(fill="both", expand=True)

    root.mainloop()
