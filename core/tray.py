# core/tray.py
#
# System tray ("hidden icons") support.
#
# - Minimizing the window hides it and shows a tray icon instead, so the
#   app keeps running in the background without a taskbar entry.
# - Left-click / "Open" on the tray icon restores the window.
# - "Quit" on the tray icon fully closes the app (same as the window's X).
# - The X button on the window itself still fully quits — it does NOT
#   minimize to tray. Only the minimize button does that.
#
# pystray runs its own icon thread; Tkinter is not thread-safe, so every
# callback that touches the window schedules itself back onto the main
# thread with `app.after(0, ...)` instead of calling Tk methods directly.

import threading

import pystray
from PIL import Image

from core import paths


class TrayIcon:

    def __init__(self, app):
        self.app = app
        self._icon = None
        self._thread = None

    # =====================================================
    # SHOW / HIDE
    # =====================================================

    def show(self):
        """Hide the window and show the tray icon (called on minimize)."""
        if self._icon is not None:
            return  # already showing

        self.app.withdraw()

        image = Image.open(paths.resource_path("assets", "icon.ico"))

        menu = pystray.Menu(
            pystray.MenuItem("Open Z's Multi Tool", self._on_open, default=True),
            pystray.MenuItem("Quit", self._on_quit),
        )

        self._icon = pystray.Icon("zs_multi_tool", image, "Z's Multi Tool", menu)

        # pystray blocks in .run(), so it needs its own thread.
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def hide(self):
        """Remove the tray icon (called on restore or quit)."""
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

    # =====================================================
    # TRAY MENU CALLBACKS (run on pystray's thread — hop back to Tk's)
    # =====================================================

    def _on_open(self, icon=None, item=None):
        self.app.after(0, self._restore_window)

    def _on_quit(self, icon=None, item=None):
        self.app.after(0, self.app.quit_app)

    def _restore_window(self):
        self.hide()

        # Prevent the brief white "flash" that happens when Tk deiconifies
        # a withdrawn window: the OS shows the frame with a plain white
        # background for a frame before the dark theme repaints onto it.
        # Fix: stay fully transparent, force Tk to finish painting while
        # still invisible, THEN reveal the window.
        self.app.attributes("-alpha", 0)
        self.app.deiconify()
        self.app.state("normal")
        self.app.update_idletasks()
        self.app.update()
        self.app.lift()
        self.app.focus_force()
        self.app.attributes("-alpha", 1)
