"""Route Tk after() through Qt.

The Qt shell never runs Tk's mainloop — it only pumps update().
Worker threads that call widget.after() then hit:
    RuntimeError: main thread is not in main loop
QTimer.singleShot is safe from any thread and lands on the Qt loop.
"""

from __future__ import annotations

import threading
import tkinter as tk

from PySide6.QtCore import QTimer

_orig_after = None
_orig_after_idle = None
_orig_after_cancel = None
_installed = False
_lock = threading.Lock()
_seq = 0
_jobs: dict[str, dict] = {}


def schedule(ms, func, *args):
    """Run func on the Qt loop. Safe from worker threads."""
    global _seq
    with _lock:
        _seq += 1
        ident = f"qtafter-{_seq}"
        _jobs[ident] = {"cancelled": False}

    def fire(i=ident):
        with _lock:
            job = _jobs.pop(i, None)
        if not job or job.get("cancelled"):
            return
        try:
            if args:
                func(*args)
            else:
                func()
        except Exception:
            pass

    QTimer.singleShot(max(0, int(ms)), fire)
    return ident


def install() -> None:
    global _orig_after, _orig_after_idle, _orig_after_cancel, _installed
    if _installed:
        return
    _orig_after = tk.Misc.after
    _orig_after_idle = tk.Misc.after_idle
    _orig_after_cancel = tk.Misc.after_cancel
    tk.Misc.after = _after
    tk.Misc.after_idle = _after_idle
    tk.Misc.after_cancel = _after_cancel
    _installed = True


def _after(self, ms, func=None, *args):
    if func is None:
        if threading.current_thread() is threading.main_thread() and _orig_after:
            try:
                return _orig_after(self, ms)
            except Exception:
                pass
        return None
    return schedule(ms, func, *args)


def _after_idle(self, func, *args):
    return _after(self, 0, func, *args)


def _after_cancel(self, ident):
    if isinstance(ident, str) and ident.startswith("qtafter-"):
        with _lock:
            job = _jobs.get(ident)
            if job is not None:
                job["cancelled"] = True
        return
    if _orig_after_cancel is None:
        return
    try:
        return _orig_after_cancel(self, ident)
    except Exception:
        return
