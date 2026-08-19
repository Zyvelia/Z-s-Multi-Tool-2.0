"""
Wraps every tool module with a gear-button settings view + theme picker.

Each module gets the same layout as the catalog page's relationship to
Settings: main content, plus a dedicated settings screen with Back.
"""

from __future__ import annotations

import customtkinter as ctk

from core.module_themes import (
    get_saved_module_theme,
    list_module_themes,
    resolve_module_theme,
    save_module_theme,
)
from core.theme_picker import ThemePickerRow

_GEAR_SIZE = 40
_GEAR_BAR_H = 44


def open_module(manager, module_id: str, page_class):
    """Standard entry point for plugin `open` handlers."""
    return ModuleShell(manager.container, manager, module_id, page_class)


def find_module_shell(widget):
    """Walk up the widget tree to the enclosing ModuleShell, if any."""
    w = widget
    while w is not None:
        if w.__class__.__name__ == "ModuleShell":
            return w
        w = getattr(w, "master", None)
    return None


class ModuleSettingsView(ctk.CTkFrame):
    """In-module settings panel (theme swap + back)."""

    def __init__(self, parent, shell: "ModuleShell"):
        self.shell = shell
        self._t = shell._t
        super().__init__(parent, fg_color=self._t.BG)

        header = ctk.CTkFrame(
            self,
            fg_color=self._t.PANEL,
            corner_radius=self._t.RADIUS,
            border_width=1,
            border_color=self._t.BORDER,
        )
        header.pack(fill="x", padx=self._t.PAD_LG, pady=(self._t.PAD_LG, self._t.PAD))

        ctk.CTkButton(
            header,
            text="←  Back",
            width=110,
            height=36,
            command=shell.show_main,
            fg_color=self._t.PANEL_2,
            hover_color=self._t.PANEL_HOVER,
            text_color=self._t.TEXT,
            border_width=1,
            border_color=self._t.BORDER,
            corner_radius=self._t.RADIUS_SM,
            font=self._t.font(13),
        ).pack(side="left", padx=self._t.PAD_LG, pady=self._t.PAD)

        ctk.CTkLabel(
            header,
            text=f"⚙  {shell.module_id} Settings",
            font=self._t.font(22, "bold"),
            text_color=self._t.TEXT,
        ).pack(side="left", padx=self._t.PAD, pady=self._t.PAD)

        self._body = ctk.CTkScrollableFrame(
            self,
            fg_color=self._t.PANEL,
            corner_radius=self._t.RADIUS,
            border_width=1,
            border_color=self._t.BORDER,
        )
        self._body.pack(fill="both", expand=True, padx=self._t.PAD_LG, pady=(0, self._t.PAD_LG))

        self._extra_slot = ctk.CTkFrame(self._body, fg_color="transparent")
        self._extra_mounted = False

        ctk.CTkLabel(
            self._body,
            text="APPEARANCE",
            font=self._t.mono(10, "bold"),
            text_color=self._t.ACCENT,
            anchor="w",
        ).pack(anchor="w", padx=self._t.PAD_LG, pady=(self._t.PAD, 4))

        ctk.CTkLabel(
            self._body,
            text="Pick a color theme for this module. The module reloads when you switch.",
            font=self._t.font(12),
            text_color=self._t.MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=self._t.PAD_LG, pady=(0, 10))

        picker_wrap = ctk.CTkFrame(self._body, fg_color="transparent")
        picker_wrap.pack(fill="x", padx=self._t.PAD_LG, pady=(0, self._t.PAD))

        current = get_saved_module_theme(shell.settings, shell.module_id)
        self.picker = ThemePickerRow(
            picker_wrap,
            list_module_themes(),
            current,
            shell.apply_theme,
            use_app_theme=False,
            wrap_after=2,
        )
        self.picker.pack(fill="x", anchor="w")
        self.picker.set_panel_theme(self._t)
        self.after(50, self._enable_settings_scroll)

    def _enable_settings_scroll(self):
        """Bind mouse wheel anywhere in settings so CTkScrollableFrame actually scrolls."""
        canvas = getattr(self._body, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(yscrollincrement=1)
        except Exception:
            pass
        self._scroll_canvas = canvas
        self._bind_wheel_recursive(self._body)

    def _bind_wheel_recursive(self, widget):
        widget.bind("<MouseWheel>", self._on_settings_wheel, add="+")
        widget.bind("<Button-4>", self._on_settings_wheel, add="+")
        widget.bind("<Button-5>", self._on_settings_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_wheel_recursive(child)

    def _on_settings_wheel(self, event):
        canvas = getattr(self, "_scroll_canvas", None)
        if canvas is None:
            return
        num = getattr(event, "num", None)
        if num == 4:
            canvas.yview_scroll(-3, "units")
        elif num == 5:
            canvas.yview_scroll(3, "units")
        else:
            canvas.yview_scroll(int(-event.delta / 40), "units")
        return "break"

    def mount_extra_settings(self, page_class, manager):
        """Module-specific settings (e.g. remote access) below the theme picker."""
        if self._extra_mounted:
            return
        builder = getattr(page_class, "build_module_settings", None)
        if not callable(builder):
            return
        self._extra_mounted = True

        section = getattr(page_class, "MODULE_SETTINGS_TITLE", "Options")
        ctk.CTkLabel(
            self._body,
            text=str(section).upper(),
            font=self._t.mono(10, "bold"),
            text_color=self._t.ACCENT,
            anchor="w",
        ).pack(anchor="w", padx=self._t.PAD_LG, pady=(self._t.PAD, 4))

        self._extra_slot.pack(
            fill="x",
            padx=self._t.PAD_LG,
            pady=(0, self._t.PAD),
        )
        panel = builder(self._extra_slot, manager)
        panel.pack(fill="x")
        self.after(50, self._enable_settings_scroll)

    def apply_theme(self, theme_bundle):
        self._t = theme_bundle.t
        self.configure(fg_color=self._t.BG)
        self._body.configure(
            fg_color=self._t.PANEL,
            border_color=self._t.BORDER,
        )
        self.picker.set_panel_theme(self._t)


class ModuleShell(ctk.CTkFrame):
    """Hosts module content + optional settings sub-page."""

    def __init__(self, parent, manager, module_id: str, page_class):
        self.manager = manager
        self.module_id = module_id
        self.page_class = page_class
        self.settings = getattr(parent, "settings", manager.container.settings)

        self._load_theme(None)
        super().__init__(parent, fg_color=self._t.BG)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._main_frame.grid(row=0, column=0, sticky="nsew")

        self._gear_bar = ctk.CTkFrame(self._main_frame, fg_color="transparent", height=_GEAR_BAR_H)
        self._gear_bar.pack(side="top", fill="x")
        self._gear_bar.pack_propagate(False)

        self._content_host = ctk.CTkFrame(self._main_frame, fg_color="transparent")
        self._content_host.pack(fill="both", expand=True)

        self._settings_frame = ModuleSettingsView(self, self)
        self._settings_frame.grid(row=0, column=0, sticky="nsew")
        self._settings_frame.grid_remove()

        self._push_runtime_theme()
        self._inner = page_class(self._content_host, manager)
        self._inner.pack(fill="both", expand=True)

        self._gear_btn = ctk.CTkButton(
            self._gear_bar,
            text="⚙",
            width=_GEAR_SIZE,
            height=_GEAR_SIZE,
            corner_radius=_GEAR_SIZE // 2,
            command=self.show_settings,
            fg_color=self._t.PANEL_2,
            hover_color=self._t.PANEL_HOVER,
            text_color=self._t.TEXT,
            border_width=1,
            border_color=self._t.BORDER,
            font=self._t.font(15),
        )
        self._gear_btn.place(relx=0.5, rely=0.5, anchor="center")

    def _push_runtime_theme(self):
        try:
            from core.theme import apply_theme_tokens
            apply_theme_tokens(self._t)
        except Exception:
            pass

    def _load_theme(self, theme_id):
        bundle = resolve_module_theme(
            theme_id if theme_id is not None else get_saved_module_theme(self.settings, self.module_id)
        )
        self._theme_id = bundle.id
        self._t = bundle.t
        self._on_accent = bundle.on_accent

    def open_vault_dashboard(self, page_class):
        """Secure Vault: swap lock screen for the unlocked dashboard in-place."""
        try:
            self._inner.destroy()
        except Exception:
            pass
        self._inner = page_class(self._content_host, self.manager)
        self._inner.pack(fill="both", expand=True)

    def show_settings(self):
        self._settings_frame.mount_extra_settings(self.page_class, self.manager)
        self._main_frame.grid_remove()
        self._settings_frame.grid()
        self._settings_frame.tkraise()
        self._settings_frame.after(50, self._settings_frame._enable_settings_scroll)

    def show_main(self):
        self._settings_frame.grid_remove()
        self._main_frame.grid()
        self._main_frame.tkraise()

    def apply_theme(self, theme_id: str):
        if theme_id == self._theme_id:
            return

        save_module_theme(self.settings, self.module_id, theme_id)
        self._load_theme(theme_id)
        self._push_runtime_theme()

        self.configure(fg_color=self._t.BG)
        self._gear_btn.configure(
            fg_color=self._t.PANEL_2,
            hover_color=self._t.PANEL_HOVER,
            text_color=self._t.TEXT,
            border_color=self._t.BORDER,
        )

        if hasattr(self, "_settings_frame"):
            self._settings_frame.apply_theme(resolve_module_theme(theme_id))

        if hasattr(self._inner, "apply_theme") and callable(self._inner.apply_theme):
            self._inner.apply_theme(theme_id)
        elif hasattr(self._inner, "apply_module_theme") and callable(self._inner.apply_module_theme):
            self._inner.apply_module_theme(theme_id)
        else:
            self._rebuild_inner()

        try:
            self.winfo_toplevel().configure(fg_color=self._t.BG)
        except Exception:
            pass

    def _rebuild_inner(self):
        inner_cls = type(self._inner) if getattr(self, "_inner", None) else self.page_class
        try:
            self._inner.destroy()
        except Exception:
            pass
        self._push_runtime_theme()
        if inner_cls.__name__ == "PasswordVaultPage":
            self.open_vault_dashboard(inner_cls)
        else:
            self._inner = self.page_class(self._content_host, self.manager)
            self._inner.pack(fill="both", expand=True)

    def on_show(self):
        saved = get_saved_module_theme(self.settings, self.module_id)
        if saved != self._theme_id:
            self.apply_theme(saved)
            return
        self._push_runtime_theme()
        if hasattr(self._inner, "on_show") and callable(self._inner.on_show):
            try:
                self._inner.on_show()
            except Exception as e:
                print(f"[ModuleShell] on_show failed for {self.module_id}: {e}")
        try:
            self.winfo_toplevel().configure(fg_color=self._t.BG)
        except Exception:
            pass
