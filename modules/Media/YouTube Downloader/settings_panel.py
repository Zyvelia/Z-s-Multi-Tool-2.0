"""YouTube Downloader module settings — paths, cookies, and remote access."""

from __future__ import annotations

import os
import threading

import customtkinter as ctk
from tkinter import filedialog

try:
    import yt_dlp as youtube_dl
except ImportError:
    try:
        import youtube_dl
    except ImportError:
        youtube_dl = None

from core import theme

from .ui import (
    DEFAULT_REMOTE_PORT,
    SETTINGS_FILE,
    _COOKIE_BROWSERS,
    _make_btn,
    _read_all_settings,
    _resolve_cookie_browser,
    _set_entry,
    _write_settings,
    log_to_yt_page,
)

class YTDownloaderSettingsPanel(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self.tailscale = manager.container.tailscale_service
        self.web_server = getattr(manager, "yt_web_server", None)
        self._phone_poll_job = None

        self._build_paths_section(self)
        self._build_remote_section(self)
        self._build_phone_section(self)

        self._load_settings()
        self._refresh_remote_status()
        self._refresh_phone_status()
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, _event=None):
        if self._phone_poll_job:
            try:
                self.after_cancel(self._phone_poll_job)
            except Exception:
                pass
            self._phone_poll_job = None

    def _load_settings(self):
        s = _read_all_settings()
        self._set_entry(self._out_entry, s.get("output_dir", os.path.expanduser("~")))
        self._set_entry(self._cookie_entry, s.get("cookie_file", ""))
        self._remote_port_entry.delete(0, "end")
        self._remote_port_entry.insert(0, str(s.get("remote_port", DEFAULT_REMOTE_PORT)))
        self._autostart_var.set(bool(s.get("auto_start_remote", False)))
        self._access_code_entry.delete(0, "end")
        self._access_code_entry.insert(0, s.get("access_code", ""))
        if self.web_server is not None:
            self.web_server.access_code = s.get("access_code", "")

    def _save_settings(self):
        _write_settings({
            "output_dir": self._out_entry.get(),
            "cookie_file": self._cookie_entry.get(),
            "remote_port": self._current_remote_port(),
            "auto_start_remote": bool(self._autostart_var.get()),
            "access_code": self._access_code_entry.get().strip(),
        })
        if self.web_server is not None:
            self.web_server.access_code = self._access_code_entry.get().strip()

    def _build_paths_section(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            panel, text="Output & cookies",
            font=("Segoe UI", 16, "bold"), text_color=theme.TEXT,
        ).pack(anchor="w", padx=12, pady=(12, 4))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=(0, 12))

        out_col = ctk.CTkFrame(inner, fg_color="transparent")
        out_col.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(out_col, text="Output folder", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 4))

        out_row = ctk.CTkFrame(out_col, fg_color="transparent")
        out_row.pack(fill="x")

        self._out_entry = ctk.CTkEntry(
            out_row, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2, corner_radius=8, state="readonly")
        self._out_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        _make_btn(out_row, "Browse", self._browse_output, width=80).pack(side="left")

        cookie_col = ctk.CTkFrame(inner, fg_color="transparent")
        cookie_col.pack(fill="x")

        ctk.CTkLabel(cookie_col, text="Cookie file (optional)", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 4))

        cookie_row = ctk.CTkFrame(cookie_col, fg_color="transparent")
        cookie_row.pack(fill="x")

        self._cookie_entry = ctk.CTkEntry(
            cookie_row, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2, corner_radius=8, state="readonly")
        self._cookie_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        _make_btn(cookie_row, "Browse", self._browse_cookie, width=80).pack(side="left")
        _make_btn(cookie_row, "✕", self._clear_cookie, width=36).pack(side="left", padx=(4, 0))

        cookie_refresh_row = ctk.CTkFrame(cookie_col, fg_color="transparent")
        cookie_refresh_row.pack(fill="x", pady=(4, 0))

        self._cookie_browser_var = ctk.StringVar(value="opera_gx")
        ctk.CTkOptionMenu(
            cookie_refresh_row, values=list(_COOKIE_BROWSERS.keys()),
            variable=self._cookie_browser_var, fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.ACCENT, text_color=theme.TEXT, width=110,
        ).pack(side="left", padx=(0, 6))

        _make_btn(cookie_refresh_row, "Refresh from Browser",
                  self._refresh_cookie_from_browser).pack(side="left", fill="x", expand=True)

    def _build_remote_section(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", pady=(0, 8))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(top, text="Browser extension",
                     font=("Segoe UI", 13, "bold"), text_color=theme.TEXT).pack(side="left")

        self._remote_status_lbl = ctk.CTkLabel(top, text="Off", text_color=theme.MUTED)
        self._remote_status_lbl.pack(side="right")

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 6))

        self._remote_start_btn = _make_btn(row, "Start", self._start_remote_access, width=90)
        self._remote_start_btn.pack(side="left")

        self._remote_stop_btn = _make_btn(row, "Stop", self._stop_remote_access,
                                          **theme.danger_button_kwargs(), width=90)
        self._remote_stop_btn.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(row, text="Local port", text_color=theme.MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))
        self._remote_port_entry = ctk.CTkEntry(
            row, width=80, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2, corner_radius=8)
        self._remote_port_entry.pack(side="left")

        self._autostart_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            row, text="Auto-start with the app", variable=self._autostart_var,
            text_color=theme.MUTED, font=("Segoe UI", 12), fg_color=theme.ACCENT, hover_color="#2f7fd6",
            command=self._save_settings,
        ).pack(side="left", padx=(20, 0))

        ctk.CTkLabel(
            panel,
            text="Loopback server for the Zs Multi Tool Companion browser extension. "
                 "Downloads use the output folder and format/quality set on the main page.",
            text_color=theme.MUTED, font=("Segoe UI", 11), anchor="w", justify="left", wraplength=640,
        ).pack(fill="x", padx=12, pady=(0, 12))

    def _build_phone_section(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", pady=(0, 8))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(top, text="Phone access (Tailscale)",
                     font=("Segoe UI", 13, "bold"), text_color=theme.TEXT).pack(side="left")

        self._phone_status_lbl = ctk.CTkLabel(top, text="Off", text_color=theme.MUTED)
        self._phone_status_lbl.pack(side="right")

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 6))

        self._phone_stop_btn = _make_btn(row, "Stop", self._stop_phone_access,
                                         **theme.danger_button_kwargs(), width=90)
        self._phone_stop_btn.pack(side="left")

        ctk.CTkLabel(row, text="Access code (optional)", text_color=theme.MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))
        self._access_code_entry = ctk.CTkEntry(
            row, width=110, show="•", fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2, corner_radius=8)
        self._access_code_entry.pack(side="left")
        self._access_code_entry.bind("<KeyRelease>", self._on_access_code_changed)

        ctk.CTkLabel(
            panel,
            text="Started from Remote Hub's Go Live button. Uses the same local port as "
                 "the browser extension above. Optional access code is required to queue "
                 "downloads from the mobile page and extension.",
            text_color=theme.MUTED, font=("Segoe UI", 11), anchor="w", justify="left", wraplength=640,
        ).pack(fill="x", padx=12, pady=(0, 12))

    def _current_remote_port(self):
        try:
            return int(self._remote_port_entry.get().strip() or DEFAULT_REMOTE_PORT)
        except ValueError:
            return DEFAULT_REMOTE_PORT

    def _browse_output(self):
        d = filedialog.askdirectory(initialdir=self._out_entry.get() or os.path.expanduser("~"))
        if d:
            self._set_entry(self._out_entry, d)
            self._save_settings()

    def _browse_cookie(self):
        f = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if f:
            self._set_entry(self._cookie_entry, f)
            self._save_settings()

    def _clear_cookie(self):
        self._set_entry(self._cookie_entry, "")
        self._save_settings()

    def _refresh_cookie_from_browser(self):
        if youtube_dl is None:
            log_to_yt_page(self.manager, "yt-dlp not installed. Run: pip install yt-dlp")
            return

        browser_key = self._cookie_browser_var.get()
        out_path = os.path.join(os.path.dirname(SETTINGS_FILE), "cookies.txt")

        def _do():
            try:
                browser_name, profile = _resolve_cookie_browser(browser_key)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                jar = youtube_dl.cookies.extract_cookies_from_browser(browser_name, profile)
                jar.filename = out_path
                jar.save(ignore_discard=True, ignore_expires=True)
                count = len(jar)
                log_to_yt_page(
                    self.manager,
                    f"Pulled {count} cookie(s) from {browser_key} -> {out_path}",
                )
                self.after(0, lambda: (self._set_entry(self._cookie_entry, out_path), self._save_settings()))
            except Exception as e:
                log_to_yt_page(self.manager, f"Couldn't read cookies from {browser_key}: {e}")
                log_to_yt_page(self.manager, "Tip: close the browser fully first — it locks its cookie DB while running.")

        threading.Thread(target=_do, daemon=True).start()

    def _start_remote_access(self):
        if self.web_server is None:
            return
        port = self._current_remote_port()

        def work():
            ok, msg = self.web_server.start(port)
            self.after(0, lambda: self._after_start_remote_access(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_start_remote_access(self, ok, msg):
        if ok:
            log_to_yt_page(self.manager, f"Browser-extension server started — {msg}")
        else:
            log_to_yt_page(self.manager, f"Couldn't start browser-extension server: {msg}")
        self._save_settings()
        self._refresh_remote_status()

    def _stop_remote_access(self):
        if self.web_server is None:
            return
        self.web_server.stop()
        log_to_yt_page(self.manager, "Browser-extension server stopped.")
        self._refresh_remote_status()

    def _refresh_remote_status(self):
        if not self.winfo_exists() or self.web_server is None:
            return
        if self.web_server.is_running():
            self._remote_status_lbl.configure(
                text=f"On — 127.0.0.1:{self.web_server.port}", text_color=theme.SUCCESS)
            self._remote_stop_btn.configure(state="normal")
            self._remote_start_btn.configure(state="disabled")
        else:
            self._remote_status_lbl.configure(text="Off", text_color=theme.MUTED)
            self._remote_stop_btn.configure(state="disabled")
            self._remote_start_btn.configure(state="normal")

    def _on_access_code_changed(self, _event=None):
        self._save_settings()

    def _stop_phone_access(self):
        self.tailscale.disable_app_serve("yt")
        self._refresh_phone_status()

    def _refresh_phone_status(self):
        if self._phone_poll_job:
            try:
                self.after_cancel(self._phone_poll_job)
            except Exception:
                pass

        def work():
            status = self.tailscale.get_status()
            live = status["running"] and self.tailscale.is_app_serving("yt")
            self.after(0, lambda: self._apply_phone_status(status, live))

        threading.Thread(target=work, daemon=True).start()
        self._phone_poll_job = self.after(4000, self._refresh_phone_status)

    def _apply_phone_status(self, status, live):
        if not self.winfo_exists():
            return
        if live:
            hostname = status.get("hostname") or "this-device"
            self._phone_status_lbl.configure(
                text=f"https://{hostname}:8445/", text_color=theme.SUCCESS
            )
        else:
            self._phone_status_lbl.configure(text="Off", text_color=theme.MUTED)

    @staticmethod
    def _set_entry(entry, value: str):
        _set_entry(entry, value)
