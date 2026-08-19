"""Game Stats & News module settings — feeds, preferences, and data."""

from __future__ import annotations

import customtkinter as ctk
from tkinter import messagebox

from core import theme

from . import crypto_store
from . import storage
from .ui import REFRESH_INTERVAL_OPTIONS, _get_news_page


class GameStatsNewsSettingsPanel(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self.settings = storage.get_settings()

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="x")
        content.grid_columnconfigure(0, weight=1)

        self._build_feeds_section(content)
        self._build_preferences_section(content)
        self._build_data_section(content)

    def _reload_settings(self):
        self.settings = storage.get_settings()

    def _build_feeds_section(self, parent):
        feeds_section = ctk.CTkFrame(parent, fg_color=theme.PANEL_2, corner_radius=10)
        feeds_section.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        feeds_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            feeds_section, text="Custom Feeds",
            font=theme.font(15, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5), columnspan=3)

        add_row = ctk.CTkFrame(feeds_section, fg_color="transparent")
        add_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=15, pady=(0, 10))
        add_row.grid_columnconfigure(0, weight=1)
        add_row.grid_columnconfigure(1, weight=1)

        self.new_feed_name_entry = ctk.CTkEntry(add_row, placeholder_text="Feed name (e.g. F1)")
        self.new_feed_name_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.new_feed_query_entry = ctk.CTkEntry(add_row, placeholder_text="Keywords (e.g. Formula 1)")
        self.new_feed_query_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5))
        self.new_feed_query_entry.bind("<Return>", lambda e: self._add_feed())

        ctk.CTkButton(add_row, text="Add Feed", width=90, command=self._add_feed).grid(
            row=0, column=2
        )

        self.feeds_list_frame = ctk.CTkFrame(feeds_section, fg_color="transparent")
        self.feeds_list_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=15, pady=(0, 15))
        self.feeds_list_frame.grid_columnconfigure(0, weight=1)

        self._render_feed_list()

    def _build_preferences_section(self, parent):
        prefs_section = ctk.CTkFrame(parent, fg_color=theme.PANEL_2, corner_radius=10)
        prefs_section.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        prefs_section.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            prefs_section, text="Preferences",
            font=theme.font(15, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 10), columnspan=2)

        ctk.CTkLabel(prefs_section, text="Headline country code").grid(
            row=1, column=0, sticky="w", padx=15, pady=6
        )
        self.country_entry = ctk.CTkEntry(prefs_section, width=100)
        self.country_entry.insert(0, self.settings.get("country", "us"))
        self.country_entry.grid(row=1, column=1, sticky="w", padx=15, pady=6)
        self.country_entry.bind("<FocusOut>", lambda e: self._on_country_changed())
        self.country_entry.bind("<Return>", lambda e: self._on_country_changed())

        ctk.CTkLabel(prefs_section, text="Headlines per feed").grid(
            row=2, column=0, sticky="w", padx=15, pady=6
        )
        self.page_size_entry = ctk.CTkEntry(prefs_section, width=100)
        self.page_size_entry.insert(0, str(self.settings.get("page_size", 15)))
        self.page_size_entry.grid(row=2, column=1, sticky="w", padx=15, pady=6)
        self.page_size_entry.bind("<FocusOut>", lambda e: self._on_page_size_changed())
        self.page_size_entry.bind("<Return>", lambda e: self._on_page_size_changed())

        ctk.CTkLabel(prefs_section, text="Auto-refresh").grid(
            row=3, column=0, sticky="w", padx=15, pady=(6, 15)
        )
        current_minutes = self.settings.get("refresh_interval_minutes", 0)
        current_label = next(
            (label for label, mins in REFRESH_INTERVAL_OPTIONS.items() if mins == current_minutes),
            "Off",
        )
        self.refresh_interval_menu = ctk.CTkOptionMenu(
            prefs_section, values=list(REFRESH_INTERVAL_OPTIONS.keys()),
            command=self._on_refresh_interval_changed,
        )
        self.refresh_interval_menu.set(current_label)
        self.refresh_interval_menu.grid(row=3, column=1, sticky="w", padx=15, pady=(6, 15))

    def _build_data_section(self, parent):
        data_section = ctk.CTkFrame(parent, fg_color=theme.PANEL_2, corner_radius=10)
        data_section.grid(row=2, column=0, sticky="ew")
        data_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            data_section, text="Your Data",
            font=theme.font(15, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            data_section,
            text=f"Feeds, saved articles, and preferences:\n{storage.storage_path()}\n\n"
                 f"Encrypted API keys:\n{crypto_store.storage_path()}",
            text_color=theme.MUTED, justify="left", wraplength=640, anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=15, pady=(0, 10))

        btn_row = ctk.CTkFrame(data_section, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="w", padx=15, pady=(0, 15))

        ctk.CTkButton(
            btn_row, text="Clear saved articles",
            fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
            command=self._clear_saved,
        ).grid(row=0, column=0, padx=(0, 10))

        ctk.CTkButton(
            btn_row, text="Reset all data",
            fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
            command=self._reset_all_confirm,
        ).grid(row=0, column=1)

    def _clear_frame(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def _render_feed_list(self):
        self._clear_frame(self.feeds_list_frame)
        feeds = storage.get_custom_feeds()

        if not feeds:
            ctk.CTkLabel(
                self.feeds_list_frame, text="No custom feeds yet.", text_color=theme.MUTED
            ).grid(row=0, column=0, sticky="w")
            return

        for i, feed in enumerate(feeds):
            row = ctk.CTkFrame(self.feeds_list_frame, fg_color=theme.PANEL_2)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row, text=f"{feed['name']}  —  \"{feed['query']}\"", anchor="w"
            ).grid(row=0, column=0, sticky="w", padx=10, pady=8)

            ctk.CTkButton(
                row, text="Remove", width=80,
                fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
                command=lambda name=feed["name"]: self._remove_feed(name),
            ).grid(row=0, column=1, padx=10, pady=8)

    def _add_feed(self):
        name = self.new_feed_name_entry.get().strip()
        query = self.new_feed_query_entry.get().strip()
        if not name or not query:
            messagebox.showwarning("Add Feed", "Please enter both a feed name and keywords.")
            return
        storage.add_custom_feed(name, query)
        self.new_feed_name_entry.delete(0, "end")
        self.new_feed_query_entry.delete(0, "end")
        self._render_feed_list()
        page = _get_news_page(self.manager)
        if page is not None:
            page._render_feeds_tab()

    def _remove_feed(self, name):
        storage.remove_custom_feed(name)
        page = _get_news_page(self.manager)
        if page is not None and page._active_feed_name == name:
            page._active_feed_name = None
        self._render_feed_list()
        if page is not None:
            page._render_feeds_tab()

    def _on_country_changed(self):
        value = self.country_entry.get().strip().lower() or "us"
        self.settings = storage.update_setting("country", value)
        page = _get_news_page(self.manager)
        if page is not None:
            page.settings = self.settings

    def _on_page_size_changed(self):
        raw = self.page_size_entry.get().strip()
        try:
            value = max(1, min(50, int(raw)))
        except ValueError:
            value = self.settings.get("page_size", 15)
        self.page_size_entry.delete(0, "end")
        self.page_size_entry.insert(0, str(value))
        self.settings = storage.update_setting("page_size", value)
        page = _get_news_page(self.manager)
        if page is not None:
            page.settings = self.settings

    def _on_refresh_interval_changed(self, label):
        minutes = REFRESH_INTERVAL_OPTIONS.get(label, 0)
        self.settings = storage.update_setting("refresh_interval_minutes", minutes)
        page = _get_news_page(self.manager)
        if page is not None:
            page.settings = self.settings
            page._schedule_auto_refresh()

    def _clear_saved(self):
        page = _get_news_page(self.manager)
        if page is not None:
            page._clear_saved_confirm()
            return
        if not storage.get_saved_articles():
            return
        if messagebox.askyesno("Clear saved articles", "Remove all saved articles? This cannot be undone."):
            storage.clear_saved_articles()

    def _reset_all_confirm(self):
        if not messagebox.askyesno(
            "Reset all data",
            "This will remove all custom feeds, saved articles, and preferences "
            "(API keys are stored separately and are not affected). Continue?",
        ):
            return

        storage.clear_all_data()
        self._reload_settings()

        page = _get_news_page(self.manager)
        if page is not None:
            page.settings = self.settings
            page._active_feed_name = None
            page._render_feeds_tab()
            page._render_saved_tab()
            page._schedule_auto_refresh()

        self._render_feed_list()
        self.country_entry.delete(0, "end")
        self.country_entry.insert(0, self.settings.get("country", "us"))
        self.page_size_entry.delete(0, "end")
        self.page_size_entry.insert(0, str(self.settings.get("page_size", 15)))
        self.refresh_interval_menu.set("Off")
