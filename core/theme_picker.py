"""Reusable theme card picker (catalog + module settings)."""

import customtkinter as ctk

from core import theme as app_theme


class ThemePickerRow(ctk.CTkFrame):
    """Clickable theme preview cards — single row or wrapped grid."""

    def __init__(
        self,
        parent,
        themes,
        selected_id: str,
        on_select,
        *,
        card_width: int = 210,
        card_height: int = 108,
        use_app_theme: bool = True,
        wrap_after: int = 0,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._on_select = on_select
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._selected_id = selected_id
        self._use_app = use_app_theme
        self._t = app_theme
        self._wrap_after = max(0, wrap_after)
        self._card_width = card_width
        self._card_height = card_height

        if self._wrap_after:
            self._grid_container = ctk.CTkFrame(self, fg_color="transparent")
            self._grid_container.pack(fill="x", anchor="w")
        else:
            self._grid_container = self

        for i, bundle in enumerate(themes):
            self._add_card(bundle, card_width, card_height, index=i)

        self.refresh_selection(selected_id)

    def _accent(self):
        return self._t.ACCENT if self._use_app else getattr(self, "_panel_accent", self._t.ACCENT)

    def _border(self):
        return self._t.BORDER if self._use_app else getattr(self, "_panel_border", self._t.BORDER)

    def set_panel_theme(self, panel_theme):
        """Style selection borders with the module's own palette."""
        self._use_app = False
        self._panel_accent = panel_theme.ACCENT
        self._panel_border = panel_theme.BORDER
        self._t = panel_theme
        self.refresh_selection(self._selected_id)

    def _add_card(self, bundle, width, height, index: int = 0):
        card = ctk.CTkFrame(
            self._grid_container,
            fg_color=self._t.PANEL_2,
            corner_radius=self._t.RADIUS_SM,
            border_width=1,
            border_color=self._border(),
            width=width,
            height=height,
            cursor="hand2",
        )
        if self._wrap_after:
            row, col = divmod(index, self._wrap_after)
            card.grid(row=row, column=col, padx=(0, 10), pady=4, sticky="nw")
            for c in range(self._wrap_after):
                self._grid_container.grid_columnconfigure(c, weight=0)
        else:
            card.pack(side="left", padx=(0, 10), pady=4)
        card.pack_propagate(False)
        self._cards[bundle.id] = card

        swatch_row = ctk.CTkFrame(card, fg_color="transparent")
        swatch_row.pack(anchor="w", padx=10, pady=(10, 6))
        for color in (bundle.t.BG, bundle.t.ACCENT, bundle.t.TEXT):
            ctk.CTkFrame(
                swatch_row,
                width=30,
                height=14,
                fg_color=color,
                corner_radius=4,
            ).pack(side="left", padx=(0, 5))

        ctk.CTkLabel(
            card,
            text=bundle.name,
            font=self._t.font(13, "bold"),
            text_color=self._t.TEXT,
        ).pack(anchor="w", padx=10)

        ctk.CTkLabel(
            card,
            text=bundle.description,
            font=self._t.font(10),
            text_color=self._t.MUTED,
            wraplength=width - 22,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(2, 8))

        def on_click(_event=None, theme_id=bundle.id):
            self._selected_id = theme_id
            self._on_select(theme_id)
            self.refresh_selection(theme_id)

        self._bind_click_recursive(card, on_click)

    def _bind_click_recursive(self, widget, callback):
        widget.bind("<Button-1>", callback)
        for child in widget.winfo_children():
            self._bind_click_recursive(child, callback)

    def refresh_selection(self, selected_id: str):
        self._selected_id = selected_id
        for theme_id, card in self._cards.items():
            selected = theme_id == selected_id
            card.configure(
                border_width=2 if selected else 1,
                border_color=self._accent() if selected else self._border(),
            )
