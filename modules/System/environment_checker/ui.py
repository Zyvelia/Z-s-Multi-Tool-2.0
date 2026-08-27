"""One-screen health check for app dependencies."""

import customtkinter as ctk

from core import theme
from core.services.environment_checker import run_all_checks


class EnvironmentCheckerPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager
        self._rows: list[ctk.CTkFrame] = []
        self._build_ui()
        self.run_checks()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.pack(fill="x", padx=12, pady=(12, 8))

        ctk.CTkLabel(
            header, text="🩺  Environment Checker",
            font=theme.font(22, "bold"), text_color=theme.TEXT,
        ).pack(anchor="w", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            header,
            text=(
                "This module only reads your system — it does not change anything. "
                "Each row is something Z's Multi Tool uses; green means ready, red means "
                "a feature may be broken until you install the fix."
            ),
            font=theme.font(12), text_color=theme.MUTED, anchor="w", justify="left", wraplength=720,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        btn_row = ctk.CTkFrame(header, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkButton(
            btn_row, text="Re-check", width=120, height=34,
            command=self.run_checks, **theme.primary_button_style(),
        ).pack(side="left")

        self._summary = ctk.CTkLabel(
            btn_row, text="", font=theme.font(12, "bold"), text_color=theme.TEXT,
        )
        self._summary.pack(side="left", padx=(16, 0))

        self._list = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        self._list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._list.grid_columnconfigure(0, weight=1)

    def run_checks(self):
        for w in self._list.winfo_children():
            w.destroy()
        self._rows.clear()

        results = run_all_checks()
        passed = sum(1 for r in results if r["ok"])
        total = len(results)
        self._summary.configure(
            text=f"{passed}/{total} checks passed",
            text_color=theme.SUCCESS if passed == total else "#f1c40f" if passed >= total - 2 else theme.ERROR,
        )

        for item in results:
            self._add_row(item)

    def _add_row(self, item: dict):
        row = ctk.CTkFrame(self._list, fg_color=theme.PANEL_2, corner_radius=theme.RADIUS_SM)
        row.pack(fill="x", padx=8, pady=6)
        row.grid_columnconfigure(1, weight=1)

        icon = "✓" if item["ok"] else "✗"
        color = theme.SUCCESS if item["ok"] else theme.ERROR
        ctk.CTkLabel(row, text=icon, font=theme.font(16, "bold"), text_color=color, width=28).grid(
            row=0, column=0, rowspan=2, padx=(12, 8), pady=12,
        )
        ctk.CTkLabel(
            row, text=item["name"], font=theme.font(13, "bold"), text_color=theme.TEXT, anchor="w",
        ).grid(row=0, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(
            row, text=item["detail"], font=theme.font(11), text_color=theme.MUTED, anchor="w", justify="left",
        ).grid(row=1, column=1, sticky="w", pady=(2, 10))
        if item.get("fix") and not item["ok"]:
            ctk.CTkLabel(
                row, text=f"Fix: {item['fix']}", font=theme.font(10), text_color=theme.FAINT,
                anchor="w", justify="left", wraplength=560,
            ).grid(row=2, column=1, sticky="w", padx=(0, 12), pady=(0, 10))
