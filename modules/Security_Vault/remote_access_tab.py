# modules/password_vault/remote_access_tab.py
#
# The "Settings" tab inside the Vault page. Lets you reach your
# passwords + authenticator codes from your phone over your own
# Tailscale network:
#
#   1. "Connect" joins your tailnet (`tailscale up`), same as running
#      it from a terminal.
#   2. "Start Remote Access" starts a small local-only web server
#      (127.0.0.1, never exposed on your LAN) and points Tailscale's
#      `serve` feature at it, so https://<this-device>.<tailnet>/
#      shows a mobile-friendly vault + authenticator view, protected
#      by your master password, reachable only from your own devices.
#   3. Auto-off closes remote access again after N minutes so it isn't
#      left open indefinitely.
#
# Everything here is editable and persisted via TailscaleService's
# settings.json (hostname, auth key, port, auto-off minutes, etc).

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
BORDER = theme.BORDER

STATUS_POLL_MS = 4000
COUNTDOWN_TICK_MS = 1000


class RemoteAccessTab(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")

        self.manager = manager
        self.tailscale = manager.container.tailscale_service
        self.web_server = manager.container.vault_web_server

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._poll_job = None
        self._countdown_job = None

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        self._build_tailscale_panel(scroll)
        self._build_remote_access_panel(scroll)
        self._build_config_panel(scroll)

        self._load_config_into_fields()
        self._refresh_status()
        self._start_polling()

    def destroy(self):
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        if self._countdown_job:
            try:
                self.after_cancel(self._countdown_job)
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

    def _open_install_page(self):
        import webbrowser
        webbrowser.open("https://tailscale.com/download")

    def _on_connect_clicked(self):
        cfg = self._config_from_fields()
        self.tailscale.save_config(cfg)
        self.ts_connect_btn.configure(state="disabled", text="Connecting…")

        def work():
            ok, msg = self.tailscale.connect(
                hostname=cfg["hostname"] or None,
                auth_key=cfg["auth_key"] or None,
                accept_routes=cfg["accept_routes"],
            )
            self.after(0, lambda: self._after_connect(ok, msg))

        import threading
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
                "Remote access is currently running. Disconnecting Tailscale will also "
                "stop it. Continue?",
            ):
                return
        self.tailscale.cancel_auto_off_timer()
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
            panel, text="Remote access (view on phone)", font=("Segoe UI", 16, "bold"), text_color=TEXT
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

        ctk.CTkButton(
            panel, text="🔍 Diagnose", fg_color=CARD, hover_color=PANEL,
            text_color=TEXT, command=self._on_diagnose_clicked,
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 8))

        self.ra_countdown_label = ctk.CTkLabel(
            panel, text="", font=("Segoe UI", 12), text_color=MUTED, anchor="w",
        )
        self.ra_countdown_label.grid(row=4, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 15))

    def _on_diagnose_clicked(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Diagnostics")
        popup.geometry("640x480")
        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            popup, text="Raw output from the Tailscale CLI — copy/paste this if you need help.",
            font=("Segoe UI", 12), text_color=MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))

        box = ctk.CTkTextbox(popup, wrap="word")
        box.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        box.insert("1.0", "Running diagnostics…")
        box.configure(state="disabled")

        def work():
            text = self.tailscale.diagnostics()
            def apply():
                if not popup.winfo_exists():
                    return
                box.configure(state="normal")
                box.delete("1.0", "end")
                box.insert("1.0", text)
                box.configure(state="disabled")
            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def _on_start_remote_access(self):
        cfg = self._config_from_fields()
        self.tailscale.save_config(cfg)

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
            ok, msg = self.web_server.start(cfg["web_port"])
            if ok:
                ok2, msg2 = self.tailscale.enable_serve(cfg["web_port"])
                if not ok2:
                    ok, msg = ok2, msg2
            self.after(0, lambda: self._after_start_remote_access(ok, msg, cfg))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _after_start_remote_access(self, ok, msg, cfg):
        self.ra_start_btn.configure(state="normal", text="▶ Start Remote Access")
        if not ok:
            messagebox.showerror("Couldn't start remote access", msg)
            self._refresh_status()
            return

        if cfg["auto_off_enabled"] and cfg["auto_off_minutes"] > 0:
            self.tailscale.start_auto_off_timer(cfg["auto_off_minutes"], self._auto_off_triggered)

        self._refresh_status()

    def _auto_off_triggered(self):
        # Fires on a background thread — hop back to the Tk thread.
        self.after(0, self._on_stop_remote_access)

    def _on_stop_remote_access(self):
        self.tailscale.cancel_auto_off_timer()
        self.tailscale.disable_serve()
        self.web_server.stop()
        self._refresh_status()

    # =====================================================
    # CONFIG PANEL (editable fields)
    # =====================================================

    def _build_config_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL)
        panel.grid(row=2, column=0, sticky="ew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel, text="Settings", font=("Segoe UI", 16, "bold"), text_color=TEXT
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 4))

        ctk.CTkLabel(panel, text="Device name (optional)", font=("Segoe UI", 12), text_color=MUTED).grid(
            row=1, column=0, sticky="w", padx=(15, 5)
        )
        self.hostname_entry = ctk.CTkEntry(panel, placeholder_text="e.g. my-desktop")
        self.hostname_entry.grid(row=2, column=0, sticky="ew", padx=(15, 5), pady=(0, 10))

        ctk.CTkLabel(panel, text="Local port", font=("Segoe UI", 12), text_color=MUTED).grid(
            row=1, column=1, sticky="w", padx=(5, 15)
        )
        self.port_entry = ctk.CTkEntry(panel, placeholder_text="8765")
        self.port_entry.grid(row=2, column=1, sticky="ew", padx=(5, 15), pady=(0, 10))

        ctk.CTkLabel(
            panel, text="Auth key (optional — for unattended reconnects)",
            font=("Segoe UI", 12), text_color=MUTED
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=15)
        self.authkey_entry = ctk.CTkEntry(panel, placeholder_text="tskey-auth-…", show="•")
        self.authkey_entry.grid(row=4, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 10))

        self.accept_routes_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            panel, text="Accept subnet routes from tailnet", variable=self.accept_routes_var,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 10))

        auto_off_row = ctk.CTkFrame(panel, fg_color="transparent")
        auto_off_row.grid(row=6, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 10))
        auto_off_row.grid_columnconfigure(1, weight=1)

        self.auto_off_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            auto_off_row, text="Auto turn off remote access after", variable=self.auto_off_var,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        ).grid(row=0, column=0, sticky="w")

        self.auto_off_minutes_entry = ctk.CTkEntry(auto_off_row, width=70, placeholder_text="30")
        self.auto_off_minutes_entry.grid(row=0, column=1, sticky="w", padx=(10, 5))

        ctk.CTkLabel(auto_off_row, text="minutes", font=("Segoe UI", 12), text_color=MUTED).grid(
            row=0, column=2, sticky="w"
        )

        ctk.CTkButton(
            panel, text="💾 Save Settings", fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#0b0d10", command=self._on_save_settings,
        ).grid(row=7, column=0, columnspan=2, sticky="ew", padx=15, pady=(4, 15))

        ctk.CTkLabel(
            panel,
            text="Remote access uses Tailscale's own HTTPS proxy — it's reachable only from "
                 "devices signed into your tailnet, never from the open internet. Logging in "
                 "from your phone uses the same master password as this app, and unlocks the "
                 "same vault.",
            font=("Segoe UI", 11), text_color=MUTED, anchor="w", justify="left", wraplength=560,
        ).grid(row=8, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 15))

    def _on_save_settings(self):
        cfg = self._config_from_fields()
        self.tailscale.save_config(cfg)
        messagebox.showinfo("Saved", "Settings saved.")

    def _config_from_fields(self):
        try:
            port = int(self.port_entry.get().strip() or 8765)
        except ValueError:
            port = 8765

        try:
            minutes = int(self.auto_off_minutes_entry.get().strip() or 30)
        except ValueError:
            minutes = 30

        return {
            "hostname": self.hostname_entry.get().strip(),
            "auth_key": self.authkey_entry.get().strip(),
            "accept_routes": self.accept_routes_var.get(),
            "web_port": port,
            "auto_off_enabled": self.auto_off_var.get(),
            "auto_off_minutes": minutes,
        }

    def _load_config_into_fields(self):
        cfg = self.tailscale.load_config()
        self.hostname_entry.insert(0, cfg.get("hostname", ""))
        self.authkey_entry.insert(0, cfg.get("auth_key", ""))
        self.port_entry.insert(0, str(cfg.get("web_port", 8765)))
        self.accept_routes_var.set(cfg.get("accept_routes", True))
        self.auto_off_var.set(cfg.get("auto_off_enabled", False))
        self.auto_off_minutes_entry.insert(0, str(cfg.get("auto_off_minutes", 30)))

    # =====================================================
    # STATUS POLLING
    # =====================================================

    def _start_polling(self):
        self._poll_job = self.after(STATUS_POLL_MS, self._poll_tick)
        self._countdown_job = self.after(COUNTDOWN_TICK_MS, self._countdown_tick)

    def _poll_tick(self):
        self._refresh_status()
        self._poll_job = self.after(STATUS_POLL_MS, self._poll_tick)

    def _countdown_tick(self):
        remaining = self.tailscale.auto_off_remaining_seconds()
        if remaining is None:
            self.ra_countdown_label.configure(text="")
        else:
            mins, secs = divmod(remaining, 60)
            self.ra_countdown_label.configure(
                text=f"Auto turn-off in {mins:02d}:{secs:02d}"
            )
        self._countdown_job = self.after(COUNTDOWN_TICK_MS, self._countdown_tick)

    def _refresh_status(self):
        """
        Fetches status + serving state and updates the UI. This does two
        `tailscale` subprocess calls under the hood (via get_status()),
        so it's run on a background thread — this used to run directly
        on the Tk UI thread from the 4-second poll timer, freezing the
        whole app for the duration of both subprocess launches on every
        single poll tick.
        """
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