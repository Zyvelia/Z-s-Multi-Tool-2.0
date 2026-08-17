# modules/Network/port_forward_helper/ui.py
#
# UPnP port forwarding UI: detects the router, lists its current NAT
# port-mapping table, and lets you add/remove mappings without touching
# the router's web admin page.

import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from core import theme
from . import upnp_client
from .upnp_client import UPnPError


class PortForwardHelperUI(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager

        self.device = None          # upnp_client.IGDDevice | None
        self.mappings = []          # list[upnp_client.PortMapping]
        self.local_ip = upnp_client.get_local_ip()
        self._busy = False

        self._build_ui()
        self.after(150, self.detect_router)

    # =====================================================
    # LAYOUT
    # =====================================================

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.pack(fill="x", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))

        ctk.CTkLabel(
            header, text="🔀  Port Forward Helper", font=theme.font(22, "bold"),
            text_color=theme.TEXT
        ).pack(side="left", padx=theme.PAD_LG, pady=14)

        ctk.CTkButton(
            header, text="⟳ Rescan Router", width=140, height=32,
            command=self.detect_router, **theme.secondary_button_style()
        ).pack(side="right", padx=(0, theme.PAD_LG), pady=14)

        # ── router status strip ─────────────────────────
        status_panel = ctk.CTkFrame(self, **theme.panel_style())
        status_panel.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD))
        status_panel.grid_columnconfigure(0, weight=1)
        status_panel.grid_columnconfigure(1, weight=1)
        status_panel.grid_columnconfigure(2, weight=1)

        self.router_label = self._stat(status_panel, 0, "ROUTER", "Detecting…")
        self.external_ip_label = self._stat(status_panel, 1, "EXTERNAL IP", "—")
        self.local_ip_label = self._stat(status_panel, 2, "THIS PC (LAN)", self.local_ip)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        # ── add-mapping form ────────────────────────────
        self._build_add_form(body)

        # ── mapping table ────────────────────────────────
        table_panel = ctk.CTkFrame(body, **theme.panel_style())
        table_panel.grid(row=1, column=0, sticky="nsew")
        table_panel.grid_rowconfigure(1, weight=1)
        table_panel.grid_columnconfigure(0, weight=1)

        head_row = ctk.CTkFrame(table_panel, fg_color="transparent")
        head_row.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD, 4))

        ctk.CTkLabel(
            head_row, text="CURRENT PORT MAPPINGS", font=theme.font(10, "bold"),
            text_color=theme.FAINT, anchor="w"
        ).pack(side="left")

        self.mapping_count_label = ctk.CTkLabel(
            head_row, text="", font=theme.font(10), text_color=theme.FAINT
        )
        self.mapping_count_label.pack(side="right")

        self.table_frame = ctk.CTkScrollableFrame(table_panel, fg_color="transparent")
        self.table_frame.grid(row=1, column=0, sticky="nsew", padx=(6, 6), pady=(0, theme.PAD))
        self.table_frame.grid_columnconfigure(0, weight=1)

        self._render_placeholder("Detecting your router…")

    def _stat(self, parent, col, label, value):
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=0, column=col, sticky="ew", padx=theme.PAD_LG, pady=12)

        ctk.CTkLabel(
            cell, text=label, font=theme.font(10, "bold"), text_color=theme.FAINT, anchor="w"
        ).pack(anchor="w")

        value_label = ctk.CTkLabel(
            cell, text=value, font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w"
        )
        value_label.pack(anchor="w")
        return value_label

    def _build_add_form(self, parent):
        panel = ctk.CTkFrame(parent, **theme.panel_style())
        panel.grid(row=0, column=0, sticky="ew", pady=(0, theme.PAD))

        ctk.CTkLabel(
            panel, text="ADD PORT FORWARD", font=theme.font(10, "bold"),
            text_color=theme.FAINT, anchor="w"
        ).pack(anchor="w", padx=theme.PAD_LG, pady=(theme.PAD, 4))

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=theme.PAD_LG, pady=(0, theme.PAD))

        self.ext_port_entry = self._labeled_entry(row, "External Port", "e.g. 25565", width=110)
        self.int_port_entry = self._labeled_entry(row, "Internal Port", "e.g. 25565", width=110)

        proto_wrap = ctk.CTkFrame(row, fg_color="transparent")
        proto_wrap.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            proto_wrap, text="Protocol", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.protocol_menu = ctk.CTkOptionMenu(
            proto_wrap, values=["TCP", "UDP"], width=90,
            fg_color=theme.PANEL_2, button_color=theme.PANEL_2,
            button_hover_color=theme.PANEL_HOVER, dropdown_fg_color=theme.PANEL,
            text_color=theme.TEXT, font=theme.font(12)
        )
        self.protocol_menu.pack()

        ip_wrap = ctk.CTkFrame(row, fg_color="transparent")
        ip_wrap.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            ip_wrap, text="Internal Client (LAN IP)", font=theme.font(10),
            text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.internal_ip_entry = ctk.CTkEntry(
            ip_wrap, width=140, height=32, placeholder_text=self.local_ip,
            fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
        )
        self.internal_ip_entry.pack()

        desc_wrap = ctk.CTkFrame(row, fg_color="transparent")
        desc_wrap.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkLabel(
            desc_wrap, text="Description", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        self.desc_entry = ctk.CTkEntry(
            desc_wrap, height=32, placeholder_text="e.g. Minecraft Server",
            fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
        )
        self.desc_entry.pack(fill="x")

        self.add_btn = ctk.CTkButton(
            row, text="+ Add", width=90, height=32,
            command=self.add_mapping, **theme.primary_button_style()
        )
        self.add_btn.pack(side="left", pady=(16, 0))

    def _labeled_entry(self, parent, label, placeholder, width=100):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            wrap, text=label, font=theme.font(10), text_color=theme.MUTED, anchor="w"
        ).pack(anchor="w")
        entry = ctk.CTkEntry(
            wrap, width=width, height=32, placeholder_text=placeholder,
            fg_color=theme.PANEL_2, border_width=0, text_color=theme.TEXT
        )
        entry.pack()
        return entry

    # =====================================================
    # TABLE RENDERING
    # =====================================================

    def _clear_table(self):
        for w in self.table_frame.winfo_children():
            w.destroy()

    def _render_placeholder(self, text):
        self._clear_table()
        ctk.CTkLabel(
            self.table_frame, text=text, font=theme.font(12), text_color=theme.FAINT
        ).pack(pady=40)
        self.mapping_count_label.configure(text="")

    def _render_mappings(self):
        self._clear_table()

        if not self.mappings:
            ctk.CTkLabel(
                self.table_frame, text="No port mappings on this router yet.",
                font=theme.font(12), text_color=theme.FAINT
            ).pack(pady=40)
            self.mapping_count_label.configure(text="")
            return

        self.mapping_count_label.configure(
            text=f"{len(self.mappings)} mapping{'s' if len(self.mappings) != 1 else ''}"
        )

        for m in self.mappings:
            row = ctk.CTkFrame(self.table_frame, fg_color=theme.PANEL_2, corner_radius=theme.RADIUS_SM)
            row.pack(fill="x", padx=4, pady=3)
            row.grid_columnconfigure(4, weight=1)

            ctk.CTkLabel(
                row, text=str(m.external_port), font=theme.mono(13, "bold"),
                text_color=theme.ACCENT, width=70, anchor="w"
            ).grid(row=0, column=0, padx=(theme.PAD, 4), pady=10, sticky="w")

            ctk.CTkLabel(
                row, text="→", font=theme.font(12), text_color=theme.FAINT
            ).grid(row=0, column=1, padx=2)

            ctk.CTkLabel(
                row, text=f"{m.internal_client}:{m.internal_port}", font=theme.mono(12),
                text_color=theme.TEXT, width=150, anchor="w"
            ).grid(row=0, column=2, padx=4, sticky="w")

            ctk.CTkLabel(
                row, text=m.protocol, font=theme.font(11, "bold"),
                text_color=theme.MUTED, fg_color=theme.PANEL, corner_radius=6,
                width=50
            ).grid(row=0, column=3, padx=8)

            ctk.CTkLabel(
                row, text=m.description or "—", font=theme.font(12),
                text_color=theme.MUTED, anchor="w"
            ).grid(row=0, column=4, padx=4, sticky="ew")

            if not m.enabled:
                ctk.CTkLabel(
                    row, text="disabled", font=theme.font(10),
                    text_color=theme.ERROR
                ).grid(row=0, column=5, padx=4)

            ctk.CTkButton(
                row, text="Remove", width=80, height=28,
                command=lambda mm=m: self.remove_mapping(mm),
                **theme.danger_button_style()
            ).grid(row=0, column=6, padx=(4, theme.PAD), pady=6)

    # =====================================================
    # ROUTER DETECTION
    # =====================================================

    def detect_router(self):
        if self._busy:
            return
        self._busy = True
        self.router_label.configure(text="Detecting…")
        self._render_placeholder("Detecting your router…")
        threading.Thread(target=self._detect_thread, daemon=True).start()

    def _detect_thread(self):
        try:
            device = upnp_client.discover()
            ip = upnp_client.get_external_ip(device)
            mappings = upnp_client.list_mappings(device)
        except UPnPError as e:
            self.after(0, lambda: self._detect_failed(str(e)))
            return
        except Exception as e:
            self.after(0, lambda: self._detect_failed(f"Unexpected error: {e}"))
            return

        self.after(0, lambda: self._detect_succeeded(device, ip, mappings))

    def _detect_failed(self, message):
        self._busy = False
        self.device = None
        self.router_label.configure(text="Not found")
        self.external_ip_label.configure(text="—")
        self._render_placeholder(message)

    def _detect_succeeded(self, device, external_ip, mappings):
        self._busy = False
        self.device = device
        self.mappings = mappings
        self.router_label.configure(text=device.friendly_name)
        self.external_ip_label.configure(text=external_ip)
        self._render_mappings()

    def refresh_mappings(self):
        if not self.device or self._busy:
            return
        self._busy = True
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _refresh_thread(self):
        try:
            mappings = upnp_client.list_mappings(self.device)
            ip = upnp_client.get_external_ip(self.device)
        except UPnPError as e:
            self.after(0, lambda: self._refresh_failed(str(e)))
            return
        self.after(0, lambda: self._refresh_succeeded(mappings, ip))

    def _refresh_failed(self, message):
        self._busy = False
        messagebox.showerror("Couldn't Refresh", message)

    def _refresh_succeeded(self, mappings, external_ip):
        self._busy = False
        self.mappings = mappings
        self.external_ip_label.configure(text=external_ip)
        self._render_mappings()

    # =====================================================
    # ADD / REMOVE
    # =====================================================

    def add_mapping(self):
        if not self.device:
            messagebox.showwarning("No Router", "No router detected yet — click Rescan Router first.")
            return

        ext_raw = self.ext_port_entry.get().strip()
        int_raw = self.int_port_entry.get().strip() or ext_raw
        protocol = self.protocol_menu.get()
        internal_ip = self.internal_ip_entry.get().strip() or self.local_ip
        description = self.desc_entry.get().strip() or "Z's Multi Tool"

        if not ext_raw.isdigit() or not int_raw.isdigit():
            messagebox.showwarning("Invalid Port", "External/Internal port must be numbers.")
            return

        ext_port, int_port = int(ext_raw), int(int_raw)
        if not (1 <= ext_port <= 65535) or not (1 <= int_port <= 65535):
            messagebox.showwarning("Invalid Port", "Ports must be between 1 and 65535.")
            return

        self.add_btn.configure(state="disabled", text="Adding…")
        threading.Thread(
            target=self._add_thread,
            args=(ext_port, int_port, internal_ip, protocol, description),
            daemon=True
        ).start()

    def _add_thread(self, ext_port, int_port, internal_ip, protocol, description):
        try:
            upnp_client.add_mapping(
                self.device, ext_port, int_port, internal_ip,
                protocol=protocol, description=description
            )
            mappings = upnp_client.list_mappings(self.device)
        except UPnPError as e:
            self.after(0, lambda: self._add_failed(str(e)))
            return
        self.after(0, lambda: self._add_succeeded(mappings))

    def _add_failed(self, message):
        self.add_btn.configure(state="normal", text="+ Add")
        messagebox.showerror("Couldn't Add Mapping", message)

    def _add_succeeded(self, mappings):
        self.add_btn.configure(state="normal", text="+ Add")
        self.mappings = mappings
        self._render_mappings()
        self.ext_port_entry.delete(0, "end")
        self.int_port_entry.delete(0, "end")
        self.desc_entry.delete(0, "end")

    def remove_mapping(self, mapping):
        if not self.device:
            return
        if not messagebox.askyesno(
            "Remove Port Mapping",
            f"Remove the forward for external port {mapping.external_port}/{mapping.protocol}?"
        ):
            return
        threading.Thread(target=self._remove_thread, args=(mapping,), daemon=True).start()

    def _remove_thread(self, mapping):
        try:
            upnp_client.delete_mapping(self.device, mapping.external_port, mapping.protocol)
            mappings = upnp_client.list_mappings(self.device)
        except UPnPError as e:
            self.after(0, lambda: self._remove_failed(str(e)))
            return
        self.after(0, lambda: self._remove_succeeded(mappings))

    def _remove_failed(self, message):
        messagebox.showerror("Couldn't Remove Mapping", message)

    def _remove_succeeded(self, mappings):
        self.mappings = mappings
        self._render_mappings()
