# Embedded browser panel for the Video Player tab — Windows only.
#
# WebView2 (the Edge Chromium engine) has no "give me a widget to embed"
# API the way VLC does with set_hwnd/set_xwindow. pywebview creates it as
# its own real top-level OS window. To get it living inside a CTk frame
# instead of floating as a separate window, this module does the same
# raw-HWND trick video_player.py already uses for VLC: grab the native
# window handle and reparent it, then keep it resized to match its host
# frame on every resize.
#
# This is inherently a bit fragile (WebView2 wasn't designed to be
# embedded this way) — expect occasional resize flicker, and note the
# Windows-only dependency below.
#
# Requires (Windows only):
#     pip install pywebview pywin32
#     WebView2 Runtime (preinstalled on Windows 11 and most Windows 10
#     machines; Microsoft Edge itself satisfies this).
#
# Network-request interception (used by "Find Stream Here") is NOT
# available through pywebview's WebView2 backend, so that button re-opens
# the current URL in a separate, hidden headless browser via
# stream_finder.find_m3u8_sync() rather than watching the live embedded
# session's traffic. Practically: pages that need you to be logged in
# (and you only logged in inside the embedded browser) won't resolve,
# since the headless scan starts with a fresh, cookie-less session.

from __future__ import annotations

import threading
import urllib.parse

import customtkinter as ctk

from core import theme
from ._buttons import cool_button_kwargs
# Unique-enough window title so we can find this exact webview window
# via EnumWindows without grabbing some unrelated Edge/Chromium window
# that happens to be open on the user's desktop.
_WINDOW_TITLE = "__zmt_embedded_browser__"


class BrowserPanel(ctk.CTkFrame):
    """Address bar + embedded WebView2 browser + a 'Find Stream Here'
    button that scans whatever page is currently loaded for an .m3u8
    HLS manifest and hands it back via on_stream_found(stream_url, page_url).
    """

    def __init__(self, parent, on_stream_found=None, start_url="https://www.google.com"):
        super().__init__(parent, fg_color=theme.PANEL, corner_radius=10,
                          border_width=1, border_color=theme.BORDER)
        self.on_stream_found = on_stream_found

        self._webview_window = None   # pywebview window object
        self._webview_hwnd = None     # native HWND once reparented
        self._started = False
        self._current_url = start_url

        self._build_ui()

    # =====================================================
    # UI
    # =====================================================

    def _build_ui(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(side="top", fill="x", padx=8, pady=(8, 4))

        nav_kw = cool_button_kwargs(width=36)
        ctk.CTkButton(bar, text="◀", command=self.go_back, **nav_kw).pack(side="left", padx=(0, 4))
        ctk.CTkButton(bar, text="▶", command=self.go_forward, **nav_kw).pack(side="left", padx=(0, 4))
        ctk.CTkButton(bar, text="⟳", command=self.reload, **nav_kw).pack(side="left", padx=(0, 8))

        self.address_entry = ctk.CTkEntry(bar, placeholder_text="Enter a URL and press Enter…")
        self.address_entry.insert(0, self._current_url)
        self.address_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.address_entry.bind("<Return>", lambda _e: self.navigate(self.address_entry.get().strip()))

        go_kw = cool_button_kwargs(width=60)
        ctk.CTkButton(
            bar, text="Go", command=lambda: self.navigate(self.address_entry.get().strip()), **go_kw,
        ).pack(side="left", padx=(0, 8))

        find_kw = theme.primary_button_kwargs()
        find_kw["font"] = ("Segoe UI", 13, "bold")
        self.find_stream_btn = ctk.CTkButton(
            bar, text="🕵 Find Stream Here", command=self.find_stream_on_current_page, **find_kw,
        )
        self.find_stream_btn.pack(side="left")

        self.status_label = ctk.CTkLabel(
            self, text="", text_color=theme.MUTED, font=("Segoe UI", 11), anchor="w",
        )
        self.status_label.pack(side="top", fill="x", padx=12)

        # The real WebView2 window gets reparented/resized to sit exactly
        # inside this frame — see _reparent()/_resize_browser_to_host().
        self.browser_host = ctk.CTkFrame(self, fg_color="black", corner_radius=6, height=460)
        self.browser_host.pack(side="top", fill="both", expand=True, padx=8, pady=(4, 8))
        self.browser_host.pack_propagate(False)

        self.placeholder_label = ctk.CTkLabel(
            self.browser_host, text="Enter a URL above and press Go to start browsing",
            text_color=theme.MUTED,
        )
        self.placeholder_label.place(relx=0.5, rely=0.5, anchor="center")

        self.browser_host.bind("<Configure>", lambda _e: self._resize_browser_to_host())

    # =====================================================
    # NAVIGATION / LIFECYCLE
    # =====================================================

    def navigate(self, url):
        url = (url or "").strip()
        if not url:
            return
        if not urllib.parse.urlparse(url).scheme:
            url = "https://" + url
        self._current_url = url
        self.address_entry.delete(0, "end")
        self.address_entry.insert(0, url)

        if not self._started:
            self._start_webview(url)
        else:
            try:
                self._webview_window.load_url(url)
            except Exception as exc:
                self.status_label.configure(text=f"⚠ Navigation error: {exc}")

    def _start_webview(self, url):
        if self._started:
            return
        self._started = True
        self.placeholder_label.configure(text="Starting embedded browser…")

        def run():
            # pywebview refuses to start unless the calling thread's NAME
            # is "MainThread" (it only checks the name, not actual thread
            # identity - see r0x0r/pywebview#1251). CTk already owns the
            # real main thread via mainloop(), so webview.start() has to
            # run here in the background instead; renaming this thread
            # satisfies pywebview's check without restructuring the app
            # around webview owning the main loop.
            threading.current_thread().name = "MainThread"

            try:
                import webview  # pywebview
            except ImportError:
                self.after(0, lambda: self.status_label.configure(
                    text="⚠ pywebview not installed — run: pip install pywebview pywin32"))
                self._started = False
                return

            try:
                self._webview_window = webview.create_window(
                    _WINDOW_TITLE, url=url, width=960, height=600,
                )
                # gui='edgechromium' pins it to WebView2 (the only sane
                # choice on Windows); runs its own message loop here, so
                # this must stay on a background thread since CTk already
                # owns the main thread's mainloop().
                webview.start(gui="edgechromium", debug=False)
            except Exception as exc:
                self.after(0, lambda exc=exc: self.status_label.configure(
                    text=f"⚠ Couldn't start embedded browser: {exc}"))
                self._started = False

        threading.Thread(target=run, daemon=True).start()
        self.after(200, lambda: self._try_embed(attempts=0))

    def _try_embed(self, attempts):
        if not self.winfo_exists():
            return
        if self._webview_window is None:
            if attempts > 100:  # ~20s
                self.status_label.configure(text="⚠ Embedded browser didn't start in time")
                return
            self.after(200, lambda: self._try_embed(attempts + 1))
            return

        hwnd = self._find_hwnd()
        if not hwnd:
            self.after(200, lambda: self._try_embed(attempts + 1))
            return

        self._webview_hwnd = hwnd
        try:
            self._reparent(hwnd)
        except Exception as exc:
            self.status_label.configure(text=f"⚠ Couldn't embed browser window: {exc}")
            return
        self.placeholder_label.place_forget()
        self.status_label.configure(text="")

    def _find_hwnd(self):
        try:
            import win32gui
        except ImportError:
            self.status_label.configure(text="⚠ pywin32 not installed — run: pip install pywin32")
            return None

        matches = []

        def enum_handler(hwnd, _):
            if win32gui.GetWindowText(hwnd) == _WINDOW_TITLE:
                matches.append(hwnd)

        win32gui.EnumWindows(enum_handler, None)
        return matches[0] if matches else None

    def _reparent(self, hwnd):
        import win32con
        import win32gui

        host_hwnd = self.browser_host.winfo_id()

        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = (style & ~win32con.WS_POPUP) | win32con.WS_CHILD
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        win32gui.SetParent(hwnd, host_hwnd)

        self._resize_browser_to_host()

    def _resize_browser_to_host(self):
        if not self._webview_hwnd:
            return
        try:
            import win32gui
            w = self.browser_host.winfo_width()
            h = self.browser_host.winfo_height()
            if w > 1 and h > 1:
                win32gui.MoveWindow(self._webview_hwnd, 0, 0, w, h, True)
        except Exception:
            pass

    def go_back(self):
        if self._webview_window:
            try:
                self._webview_window.evaluate_js("history.back()")
            except Exception:
                pass

    def go_forward(self):
        if self._webview_window:
            try:
                self._webview_window.evaluate_js("history.forward()")
            except Exception:
                pass

    def reload(self):
        if self._webview_window:
            try:
                self._webview_window.evaluate_js("location.reload()")
            except Exception:
                pass

    # =====================================================
    # STREAM SCAN
    # =====================================================

    def find_stream_on_current_page(self):
        """Re-opens the current URL in a hidden headless browser and scans
        it for an .m3u8 manifest (see module docstring for why this can't
        just watch the live embedded session's own traffic)."""
        page_url = self._current_url
        if not page_url:
            self.status_label.configure(text="⚠ Load a page first")
            return

        self.status_label.configure(text="🕵 Scanning current page for stream…")
        self.find_stream_btn.configure(state="disabled")

        def worker():
            stream_url = None
            error = None
            try:
                stream_url = find_m3u8_sync(page_url, timeout=30.0)
            except Exception as exc:
                error = str(exc)

            def apply():
                if not self.winfo_exists():
                    return
                self.find_stream_btn.configure(state="normal")
                if stream_url:
                    self.status_label.configure(text="🎯 Stream found and added to playlist")
                    if self.on_stream_found:
                        self.on_stream_found(stream_url, page_url)
                else:
                    self.status_label.configure(text=f"⚠ {error}")

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # =====================================================
    # TEARDOWN
    # =====================================================

    def destroy(self):
        if self._webview_window is not None:
            try:
                import webview
                webview.destroy_window(self._webview_window)
            except Exception:
                pass
        super().destroy()