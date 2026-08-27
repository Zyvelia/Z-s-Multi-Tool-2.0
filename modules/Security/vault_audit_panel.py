"""Vault audit panel for Security Center (merged breach + vault audit)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from core import theme


def _load_audit_tab_class():
    path = Path(__file__).resolve().parent / "Secure Vault" / "audit_tab.py"
    spec = importlib.util.spec_from_file_location("security_center_audit_tab", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.SecurityAuditTab


class _VaultAuditHost:
    """Minimal stand-in for PasswordVaultPage so SecurityAuditTab can run here."""

    def __init__(self, manager, panel: "VaultAuditPanel"):
        self.manager = manager
        self.vault = manager.container.vault_service
        self._panel = panel
        self._breach_cache: dict[str, int] = {}

    def open_edit_dialog(self, entry):
        messagebox.showinfo(
            "Edit in Secure Vault",
            f"Open Secure Vault to edit “{entry.get('site', 'entry')}”.",
        )
        self._panel.open_secure_vault()

    def set_breach_cache(self, cache: dict):
        self._breach_cache = dict(cache or {})

    def render(self):
        pass


class VaultAuditPanel(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self.auth = manager.container.auth_service
        self._audit_host: _VaultAuditHost | None = None
        self._audit_tab = None
        self._build()

    def _build(self):
        if not self.auth.is_initialized():
            self._placeholder(
                "No vault yet",
                "Create a master password in Secure Vault first, then return here to audit saved passwords.",
                show_vault_btn=True,
            )
            return

        if self.auth.is_locked():
            self._placeholder(
                "Vault is locked",
                "Unlock Secure Vault to scan weak, reused, and breached saved passwords.",
                show_vault_btn=True,
            )
            return

        try:
            AuditTab = _load_audit_tab_class()
        except Exception as exc:
            self._placeholder("Could not load audit", str(exc), show_vault_btn=False)
            return

        self._audit_host = _VaultAuditHost(self.manager, self)
        self._audit_tab = AuditTab(self, self._audit_host)
        self._audit_tab.pack(fill="both", expand=True)

    def _placeholder(self, title: str, body: str, *, show_vault_btn: bool):
        box = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        box.pack(fill="both", expand=True, padx=4, pady=4)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(expand=True, padx=24, pady=32)
        ctk.CTkLabel(inner, text=title, font=theme.font(16, "bold"), text_color=theme.TEXT).pack(pady=(0, 8))
        ctk.CTkLabel(
            inner, text=body, font=theme.font(12), text_color=theme.MUTED,
            wraplength=480, justify="center",
        ).pack(pady=(0, 16))
        if show_vault_btn:
            ctk.CTkButton(
                inner, text="Open Secure Vault", height=38, width=200,
                command=self.open_secure_vault, **theme.primary_button_style(),
            ).pack()

    def open_secure_vault(self):
        catalog = self.manager.pages.get("catalog")
        if not catalog:
            return
        for tool in catalog.plugin_manager.get_tools():
            if tool.get("name") == "Secure Vault":
                catalog.open_tool(tool)
                return

    def on_show(self):
        if self._audit_tab and hasattr(self._audit_tab, "refresh"):
            self._audit_tab.refresh()
