# music_player/remote_access_tab.py
#
# The "Settings" tab inside the Music Player page. Lets you stream your
# library to your phone over your own Tailscale network — same idea as
# Security Vault's Settings tab, just pointed at the music web server
# instead of the vault web server.
#
#   1. "Connect" joins your tailnet (`tailscale up`), same as running it
#      from a terminal. This is the SAME tailnet connection Security
#      Vault uses, if you also use that — connecting/disconnecting here
#      affects both.
#   2. "Start Remote Access" starts a small local-only web server
#      (127.0.0.1, never exposed on your LAN) and points Tailscale's
#      `serve` feature at it, so https://<this-device>.<tailnet>/ opens
#      a mobile library browser + player on your phone.
#   3. Because `tailscale serve` only forwards ONE thing at a time in
#      this app's simple wrapper, starting remote access here will take
#      over the address from Security Vault's remote access (or vice
#      versa) if both are turned on. Turning one off and the other on
#      is fine — you just can't have both reachable at once.
#
# The port is stored in the music library's own settings table (not
# Tailscale's shared config file) so it never collides with the Security
# Vault's separate "web_port" setting.

import threading

import customtkinter as ctk
from tkinter import messagebox

from core import theme

BG = theme.BG
PANEL = theme.PANEL
CARD = theme.PANEL_2
ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
TEXT = theme.TEXT
MUTED = theme.MUTED
SUCCESS = theme.SUCCESS
DANGER = theme.DANGER
DANGER_BG = theme.DANGER_BG
DANGER_HOVER = theme.DANGER_HOVER

STATUS_POLL_MS = 4000
DEFAULT_PORT = 8766  # Security Vault defaults to 8765 — kept distinct so
                      # both can be configured without a port clash even
                      # though only one can be *served* at a time.


class RemoteAccessTab(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")

        self.manager = manager
        self.tailscale = manager.container.tailscale_service
        self.web_server = manager.music_web_server
        self.db = manager.music_db

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._poll_job = None

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        self._build_tailscale_panel(scroll)
        self._build_remote_access_panel(scroll)

        self._load_port_field()
        self._refresh_status()
        self._start_polling()

    def destroy(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        super().destroy()

    # =====================================================
    # TAILSCALE PANEL
    # =====================================================

    def _build_tailscale_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL)
        panel.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel, text="Tailscale network", font=("Segoe UI", 16, "bold"), text_color=TEXT
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=15, pady=(15, 4))

        self.ts_status_label = ctk.CTkLabel(
            panel, text="Checking…", font=("Segoe UI", 13), text_color=MUTED, anchor="w", justify="left"
        )
        self.ts_status_label.grid(row=1, column=0, columnspan=3, sticky="ew", padx=15, pady=(0, 10))

        self.ts_connect_btn = ctk.CTkButton(
            panel, text="Connect", fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#0b0d10", command=self._on_connect_clicked,
        )
        self.ts_connect_btn.grid(row=2, column=0, sticky="ew", padx=(15, 5), pady=(0, 15))

        self.ts_disconnect_btn = ctk.CTkButton(
            panel, text="Disconnect", fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            text_color=DANGER, command=self._on_disconnect_clicked,
        )
        self.ts_disconnect_btn.grid(row=2, column=1, sticky="ew", padx=5, pady=(0, 15))

        ctk.CTkButton(
            panel, text="Install Tailscale…", fg_color=CARD, hover_color=PANEL,
            text_color=TEXT, command=self._open_install_page,
        ).grid(row=2, column=2, sticky="ew", padx=(5, 15), pady=(0, 15))

        ctk.CTkLabel(
            panel,
            text="This is the same tailnet connection used by Security Vault, if you "
                 "have that module too — connecting or disconnecting here affects both.",
            font=("Segoe UI", 11), text_color=MUTED, anchor="w", justify="left", wraplength=560,
        ).grid(row=3, column=0, columnspan=3, sticky="ew", padx=15, pady=(0, 15))

    def _open_install_page(self):
        import webbrowser
        webbrowser.open("https://tailscale.com/download")

    def _on_connect_clicked(self):
        cfg = self.tailscale.load_config()
        self.ts_connect_btn.configure(state="disabled", text="Connecting…")

        def work():
            ok, msg = self.tailscale.connect(
                hostname=cfg.get("hostname") or None,
                auth_key=cfg.get("auth_key") or None,
                accept_routes=cfg.get("accept_routes", True),
            )
            self.after(0, lambda: self._after_connect(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_connect(self, ok, msg):
        self.ts_connect_btn.configure(state="normal", text="Connect")
        if not ok:
            messagebox.showerror(
                "Couldn't connect",
                f"{msg}\n\nIf this is the first time connecting this device, Tailscale "
                "may have opened a browser tab for you to approve the login — finish that "
                "and click Connect again.",
            )
        self._refresh_status()

    def _on_disconnect_clicked(self):
        if self.web_server.is_running():
            if not messagebox.askyesno(
                "Remote access is on",
                "Music remote access is currently running. Disconnecting Tailscale will "
                "also stop it. Continue?",
            ):
                return
        self.web_server.stop()
        ok, msg = self.tailscale.disconnect()
        if not ok:
            messagebox.showerror("Couldn't disconnect", msg)
        self._refresh_status()

    # =====================================================
    # REMOTE ACCESS PANEL
    # =====================================================

    def _build_remote_access_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL)
        panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel, text="Remote access (listen on phone)", font=("Segoe UI", 16, "bold"), text_color=TEXT
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 4))

        self.ra_status_label = ctk.CTkLabel(
            panel, text="Off", font=("Segoe UI", 13), text_color=MUTED, anchor="w", justify="left", wraplength=520,
        )
        self.ra_status_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 10))

        self.ra_start_btn = ctk.CTkButton(
            panel, text="▶ Start Remote Access", fg_color=SUCCESS, hover_color="#33b57d",
            text_color="#0b0d10", command=self._on_start_remote_access,
        )
        self.ra_start_btn.grid(row=2, column=0, sticky="ew", padx=(15, 5), pady=(0, 8))

        self.ra_stop_btn = ctk.CTkButton(
            panel, text="■ Stop Remote Access", fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            text_color=DANGER, command=self._on_stop_remote_access,
        )
        self.ra_stop_btn.grid(row=2, column=1, sticky="ew", padx=(5, 15), pady=(0, 8))

        port_row = ctk.CTkFrame(panel, fg_color="transparent")
        port_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 8))
        ctk.CTkLabel(port_row, text="Local port", font=("Segoe UI", 12), text_color=MUTED).pack(side="left")
        self.port_entry = ctk.CTkEntry(port_row, width=90, placeholder_text=str(DEFAULT_PORT))
        self.port_entry.pack(side="left", padx=(10, 0))

        self.autostart_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            panel, text="Auto-start the local server when the app opens (music only — "
                        "doesn't apply to Security Vault)",
            variable=self.autostart_var, font=("Segoe UI", 12), text_color=MUTED,
            command=self._on_autostart_toggled,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 8))

        ctk.CTkLabel(
            panel,
            text="Opens a mobile library browser + player at your Tailscale address, "
                 "reachable only from devices signed into your own tailnet — never the "
                 "open internet. Your phone streams straight from this PC's library; it "
                 "doesn't control the desktop app's playback.",
            font=("Segoe UI", 11), text_color=MUTED, anchor="w", justify="left", wraplength=560,
        ).grid(row=5, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 15))

    def _load_port_field(self):
        port = self.db.get_setting("remote_port", str(DEFAULT_PORT))
        self.port_entry.insert(0, str(port))
        self.autostart_var.set(self.db.get_setting("auto_start_server", "0") == "1")

    def _on_autostart_toggled(self):
        self.db.set_setting("auto_start_server", "1" if self.autostart_var.get() else "0")

    def _current_port(self):
        try:
            port = int(self.port_entry.get().strip() or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        self.db.set_setting("remote_port", str(port))
        return port

    def _on_start_remote_access(self):
        port = self._current_port()

        status = self.tailscale.get_status()
        if not status["installed"]:
            messagebox.showwarning("Tailscale not installed", "Install Tailscale first.")
            return
        if not status["running"]:
            if not messagebox.askyesno(
                "Not connected",
                "You're not connected to Tailscale yet. Connect now, then start remote access?",
            ):
                return
            self._on_connect_clicked()

        self.ra_start_btn.configure(state="disabled", text="Starting…")

        def work():
            ok, msg = self.web_server.start(port)
            if ok:
                ok2, msg2 = self.tailscale.enable_serve(port)
                if not ok2:
                    ok, msg = ok2, msg2
            self.after(0, lambda: self._after_start_remote_access(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_start_remote_access(self, ok, msg):
        self.ra_start_btn.configure(state="normal", text="▶ Start Remote Access")
        if not ok:
            messagebox.showerror("Couldn't start remote access", msg)
        self._refresh_status()

    def _on_stop_remote_access(self):
        self.tailscale.disable_serve()
        self.web_server.stop()
        self._refresh_status()

    # =====================================================
    # STATUS POLLING
    # =====================================================

    def _start_polling(self):
        self._poll_job = self.after(STATUS_POLL_MS, self._poll_tick)

    def _poll_tick(self):
        self._refresh_status()
        self._poll_job = self.after(STATUS_POLL_MS, self._poll_tick)

    def _refresh_status(self):
        def work():
            status = self.tailscale.get_status()
            serving = self.web_server.is_running()
            self.after(0, lambda: self._apply_status(status, serving))

        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, status, web_server_running):
        if not self.winfo_exists():
            return

        if not status["installed"]:
            self.ts_status_label.configure(
                text="Tailscale isn't installed on this device.", text_color=MUTED
            )
            self.ts_connect_btn.configure(state="disabled")
            self.ts_disconnect_btn.configure(state="disabled")
        elif status["running"]:
            ip_bit = f"  ·  {status['tailscale_ip']}" if status["tailscale_ip"] else ""
            self.ts_status_label.configure(
                text=f"🟢 Connected as {status['hostname'] or 'this device'}{ip_bit}",
                text_color=SUCCESS,
            )
            self.ts_connect_btn.configure(state="normal", text="Reconnect")
            self.ts_disconnect_btn.configure(state="normal")
        else:
            self.ts_status_label.configure(text="⚪ Not connected.", text_color=MUTED)
            self.ts_connect_btn.configure(state="normal", text="Connect")
            self.ts_disconnect_btn.configure(state="disabled")

        if web_server_running:
            port = self.web_server.port
            hostname = status.get("hostname") or "this-device"
            self.ra_status_label.configure(
                text=(
                    f"🟢 On — open https://{hostname}/ on your phone (must be signed into "
                    f"the same tailnet). Serving locally on 127.0.0.1:{port}."
                ),
                text_color=SUCCESS,
            )
            self.ra_start_btn.configure(state="disabled")
            self.ra_stop_btn.configure(state="normal")
        else:
            self.ra_status_label.configure(text="⚪ Off.", text_color=MUTED)
            self.ra_start_btn.configure(state="normal")
            self.ra_stop_btn.configure(state="disabled")
