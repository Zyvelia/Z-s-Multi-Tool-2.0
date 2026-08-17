import threading
import customtkinter as ctk

from .scanner import NetworkScanner, NetworkScannerError
from .port_scanner import PortScanner, PortScannerError
from .threat_report import ThreatReporter
from core import theme

# ── Palette (matches app-wide theme) ─────────────────────
BG      = theme.BG
PANEL   = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT  = theme.ACCENT
DANGER  = theme.DANGER
TEXT    = theme.TEXT
MUTED   = theme.MUTED
BORDER  = theme.BORDER
FONT    = theme.FONT_FAMILY
# ─────────────────────────────────────────────────────────

# Severity → color mapping
SEVERITY_COLORS = {
    "critical": "#ff4444",
    "high":     "#ff8c42",
    "medium":   "#f5c542",
    "low":      "#4ea1ff",
    "info":     "#9aa4b2",
}


class NetworkAuditorUI(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager
        self.scanner = NetworkScanner()
        self.port_scanner = PortScanner()
        self.threat_reporter = ThreatReporter()
        self.devices = []
        self.selected_device = None
        self.build_ui()
        self.auto_detect_network()
        self._check_nmap_available()

    # ── widget helpers ───────────────────────────────────

    def _btn(self, parent, text, cmd=None, width=120,
             fg=ACCENT, hover="#2f7fd6", tc=BG, **kw):
        return ctk.CTkButton(
            parent, text=text, command=cmd, width=width,
            fg_color=fg, hover_color=hover, text_color=tc,
            corner_radius=6, font=(FONT, 12, "bold"), **kw
        )

    def _ghost_btn(self, parent, text, cmd=None, width=100, **kw):
        return ctk.CTkButton(
            parent, text=text, command=cmd, width=width,
            fg_color=PANEL_2, hover_color=BORDER,
            text_color=MUTED, border_width=0,
            corner_radius=6, font=(FONT, 12), **kw
        )

    def _label(self, parent, text, size=13, weight="normal",
               color=MUTED, **kw):
        return ctk.CTkLabel(
            parent, text=text, text_color=color,
            font=(FONT, size, weight), **kw
        )

    def _section_label(self, parent, text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            row, text=text.upper(),
            text_color=MUTED, font=(FONT, 9, "bold")
        ).pack(side="left")
        ctk.CTkFrame(row, height=1, fg_color=BORDER).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

    # ── layout ───────────────────────────────────────────

    def build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_main()
        self._build_status_bar()

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(
            fill="x", side="bottom")

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=12)

        ctk.CTkLabel(
            inner, text="Network Auditor",
            text_color=TEXT, font=(FONT, 20, "bold")
        ).pack(side="left", padx=14)

        # Right: network entry + controls
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")

        self.network_entry = ctk.CTkEntry(
            right, width=200,
            placeholder_text="e.g. 192.168.1.0/24",
            fg_color=PANEL_2, border_color=BORDER,
            text_color=TEXT, placeholder_text_color=MUTED,
            font=(FONT, 12)
        )
        self.network_entry.pack(side="left", padx=(0, 8))

        self._ghost_btn(
            right, "⟳  Auto Detect", width=120,
            cmd=self.auto_detect_network
        ).pack(side="left", padx=(0, 8))

        self._btn(
            right, "🔍  Discover", width=110,
            cmd=self.discover_devices
        ).pack(side="left")

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=BG)
        main.grid(row=1, column=0, sticky="nsew", padx=14, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(0, weight=1)

        self._build_left(main)
        self._build_right(main)

    # ── left: device list ────────────────────────────────

    def _build_left(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL,
                             corner_radius=10, border_width=1,
                             border_color=BORDER)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self._label(panel, "Devices",
                    size=15, weight="bold", color=TEXT).pack(
            anchor="w", padx=16, pady=(16, 2))
        self._label(panel, "Discovered devices on the network.",
                    size=11).pack(anchor="w", padx=16)

        self._section_label(panel, "Select device")

        self.device_dropdown = ctk.CTkOptionMenu(
            panel, values=["No Devices Found"],
            fg_color=PANEL_2, button_color=PANEL_2,
            button_hover_color=BORDER,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=PANEL_2,
            text_color=TEXT, font=(FONT, 12)
        )
        self.device_dropdown.pack(fill="x", padx=16, pady=(0, 10))

        self._btn(
            panel, "⟳  Scan Device",
            cmd=self.scan_selected
        ).pack(fill="x", padx=16, pady=(0, 16))

        # Device count badge
        self._section_label(panel, "Summary")

        self.device_count_label = self._label(
            panel, "No devices discovered yet.", size=11)
        self.device_count_label.pack(anchor="w", padx=16, pady=(0, 16))

    # ── right: results ───────────────────────────────────

    def _build_right(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=PANEL,
                             corner_radius=10, border_width=1,
                             border_color=BORDER)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        self._label(panel, "Scan Results",
                    size=15, weight="bold", color=TEXT).pack(
            anchor="w", padx=16, pady=(16, 2))
        self._label(panel, "Open ports and threat analysis for the selected device.",
                    size=11).pack(anchor="w", padx=16)

        # Scrollable results area
        self.results_scroll = ctk.CTkScrollableFrame(
            panel, fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT
        )
        self.results_scroll.pack(fill="both", expand=True,
                                 padx=12, pady=(8, 12))

        self._render_placeholder()

    def _render_placeholder(self):
        for w in self.results_scroll.winfo_children():
            w.destroy()
        self._label(
            self.results_scroll,
            "Select a device and click  ⟳ Scan Device  to begin.",
            size=12
        ).pack(pady=40)

    def _render_results(self, ports, threats):
        for w in self.results_scroll.winfo_children():
            w.destroy()

        # ── Open Ports ───────────────────────────────────
        self._section_label(self.results_scroll, "Open Ports")

        if not ports:
            self._label(self.results_scroll,
                        "No open ports found.", size=12).pack(
                anchor="w", padx=4, pady=(0, 8))
        else:
            for port in ports:
                row = ctk.CTkFrame(
                    self.results_scroll, fg_color=PANEL_2,
                    corner_radius=6, border_width=1, border_color=BORDER
                )
                row.pack(fill="x", padx=4, pady=3)

                ctk.CTkLabel(
                    row, text=str(port.port),
                    text_color=ACCENT, font=(FONT, 12, "bold"),
                    width=60, anchor="center",
                    fg_color=BG, corner_radius=4
                ).pack(side="left", padx=(8, 10), pady=8)

                ctk.CTkLabel(
                    row, text=port.service,
                    text_color=TEXT, font=(FONT, 12),
                    anchor="w"
                ).pack(side="left", fill="x", expand=True, pady=8)

        # ── Threat Report ─────────────────────────────────
        self._section_label(self.results_scroll, "Threat Report")

        if not threats:
            row = ctk.CTkFrame(
                self.results_scroll, fg_color=PANEL_2,
                corner_radius=6, border_width=1, border_color=BORDER
            )
            row.pack(fill="x", padx=4, pady=3)
            ctk.CTkLabel(
                row, text="✓  No threats detected.",
                text_color="#34d399", font=(FONT, 12, "bold")
            ).pack(anchor="w", padx=14, pady=12)
        else:
            for threat in threats:
                sev = threat.severity.lower()
                color = SEVERITY_COLORS.get(sev, MUTED)

                card = ctk.CTkFrame(
                    self.results_scroll, fg_color=PANEL_2,
                    corner_radius=8, border_width=1, border_color=BORDER
                )
                card.pack(fill="x", padx=4, pady=5)

                # Colored top strip per severity
                ctk.CTkFrame(card, height=3, fg_color=color,
                             corner_radius=0).pack(fill="x")

                body = ctk.CTkFrame(card, fg_color="transparent")
                body.pack(fill="x", padx=14, pady=(8, 12))

                title_row = ctk.CTkFrame(body, fg_color="transparent")
                title_row.pack(fill="x")

                ctk.CTkLabel(
                    title_row, text=threat.title,
                    text_color=TEXT, font=(FONT, 13, "bold"),
                    anchor="w"
                ).pack(side="left")

                ctk.CTkLabel(
                    title_row,
                    text=threat.severity.upper(),
                    text_color=color,
                    fg_color=BG, corner_radius=4,
                    font=(FONT, 9, "bold"),
                    padx=7, pady=2
                ).pack(side="right")

                ctk.CTkLabel(
                    body, text=threat.description,
                    text_color=MUTED, font=(FONT, 11),
                    anchor="w", wraplength=380, justify="left"
                ).pack(fill="x", pady=(4, 0))

    # ── status bar ───────────────────────────────────────

    def _build_status_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        bar.grid(row=2, column=0, sticky="ew")
        ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(
            fill="x", side="top")

        self.status = ctk.CTkLabel(
            bar, text="Ready",
            text_color=MUTED, font=(FONT, 11)
        )
        self.status.pack(side="left", padx=18, pady=8)

    # ── network detection & discovery ────────────────────

    def auto_detect_network(self):
        network = self.scanner.auto_detect_network()
        self.network_entry.delete(0, "end")
        self.network_entry.insert(0, network)

    def _check_nmap_available(self):
        if not PortScanner.is_nmap_available():
            self.status.configure(
                text="Nmap not found — port scanning is disabled until it's installed (nmap.org)."
            )

    def discover_devices(self):
        threading.Thread(
            target=self._discover_thread, daemon=True).start()

    def _discover_thread(self):
        self.after(0, lambda: self.status.configure(
            text="Scanning network…"))
        network = self.network_entry.get().strip() or "192.168.1.0/24"
        try:
            devices = self.scanner.discover(network)
        except NetworkScannerError as e:
            self.after(0, lambda: self.status.configure(text=str(e)))
            return
        self.after(0, lambda: self._update_devices(devices))

    def _update_devices(self, devices):
        self.devices = devices
        names = [f"{d.vendor}  ({d.ip})" for d in devices]

        if names:
            self.device_dropdown.configure(values=names)
            self.device_dropdown.set(names[0])
            self.device_count_label.configure(
                text=f"{len(devices)} device{'s' if len(devices) != 1 else ''} found.")
        else:
            self.device_dropdown.configure(values=["No Devices Found"])
            self.device_dropdown.set("No Devices Found")
            self.device_count_label.configure(text="No devices discovered yet.")

        self.status.configure(text=f"Found {len(devices)} devices")

    # ── port scan ────────────────────────────────────────

    def scan_selected(self):
        if not self.devices:
            self.status.configure(text="No devices found — run Discover first.")
            return

        selected = self.device_dropdown.get()
        device = next((d for d in self.devices if d.ip in selected), None)

        if not device:
            self.status.configure(text="No device selected.")
            return

        threading.Thread(
            target=self._scan_thread,
            args=(device.ip,), daemon=True
        ).start()

    def _scan_thread(self, ip):
        self.after(0, lambda: self.status.configure(
            text=f"Scanning {ip}…"))
        try:
            ports = self.port_scanner.scan(ip)
        except PortScannerError as e:
            self.after(0, lambda: self.status.configure(text=str(e)))
            return
        threats = self.threat_reporter.analyze(ports)
        self.after(0, lambda: self._update_results(ports, threats))

    def _update_results(self, ports, threats):
        self._render_results(ports, threats)
        threat_count = len(threats)
        self.status.configure(
            text=f"Scan complete — {len(ports)} open port{'s' if len(ports) != 1 else ''}, "
                 f"{threat_count} threat{'s' if threat_count != 1 else ''} found."
        )
