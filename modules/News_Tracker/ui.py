"""
ui.py
CustomTkinter UI for the Weather & News Tracker plugin.

Tabs:
    Home       -> Weather panel (left) + top headlines (right), each
                  headline can be "kept" (bookmarked) with one click.
    My Feeds   -> User-defined keyword/topic feeds (e.g. "AI", "F1",
                  "hometown team") that fetch their own headlines.
    Saved      -> Every headline the user has kept, across all feeds.
    Settings   -> Manage custom feeds, temperature unit, country,
                  headline count, auto-refresh interval, and stored data
                  (all persisted to disk via storage.py).

API calls run on background threads so the UI never freezes; results are
marshalled back to the main thread via `after()`.
"""

import threading
import webbrowser
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

from . import weather
from . import news
from . import storage
from core import theme

REFRESH_INTERVAL_OPTIONS = {
    "Off": 0,
    "Every 5 minutes": 5,
    "Every 15 minutes": 15,
    "Every 30 minutes": 30,
    "Every hour": 60,
}


class WeatherNewsUI(ctk.CTkFrame):
    def __init__(self, master, manager=None):
        super().__init__(master, fg_color=theme.BG)
        self.manager = manager

        self._weather_data = None
        self._home_news_data = None
        self._feed_news_data = None
        self._active_feed_name = None
        self._auto_refresh_job = None

        self.settings = storage.get_settings()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.tab_home = self.tabview.add("Home")
        self.tab_feeds = self.tabview.add("My Feeds")
        self.tab_saved = self.tabview.add("Saved")
        self.tab_settings = self.tabview.add("Settings")

        self._build_home_tab()
        self._build_feeds_tab()
        self._build_saved_tab()
        self._build_settings_tab()

        # Initial load
        self.refresh_home()
        self._render_saved_tab()
        self._schedule_auto_refresh()

    # ------------------------------------------------------------------
    # HOME TAB
    # ------------------------------------------------------------------

    def _build_home_tab(self):
        tab = self.tab_home
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=(5, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="🌦️  Weather & News Tracker",
            font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        self.last_updated_label = ctk.CTkLabel(
            header, text="Last updated: —",
            font=ctk.CTkFont(size=12), text_color=theme.MUTED
        )
        self.last_updated_label.grid(row=0, column=1, sticky="e")

        # Weather panel
        panel = ctk.CTkFrame(tab)
        panel.grid(row=1, column=0, sticky="nsew", padx=(0, 5), pady=10)
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel, text="Weather", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        self.weather_scroll = ctk.CTkScrollableFrame(panel, label_text="")
        self.weather_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.weather_scroll.grid_columnconfigure(0, weight=1)

        self.weather_status_label = ctk.CTkLabel(
            self.weather_scroll, text="Loading weather…", justify="left", anchor="w"
        )
        self.weather_status_label.grid(row=0, column=0, sticky="ew", pady=10)

        self.weather_refresh_btn = ctk.CTkButton(
            panel, text="🔄 Refresh Weather", command=self.refresh_weather
        )
        self.weather_refresh_btn.grid(row=2, column=0, sticky="ew", padx=15, pady=(5, 15))

        # News panel
        news_panel = ctk.CTkFrame(tab)
        news_panel.grid(row=1, column=1, sticky="nsew", padx=(5, 0), pady=10)
        news_panel.grid_rowconfigure(2, weight=1)
        news_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            news_panel, text="Top Headlines", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        search_row = ctk.CTkFrame(news_panel, fg_color="transparent")
        search_row.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 5))
        search_row.grid_columnconfigure(0, weight=1)

        self.news_search_entry = ctk.CTkEntry(
            search_row, placeholder_text="Search headlines by keyword…"
        )
        self.news_search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.news_search_entry.bind("<Return>", lambda e: self.refresh_home())

        ctk.CTkButton(
            search_row, text="Search", width=80, command=self.refresh_home
        ).grid(row=0, column=1)

        self.home_news_scroll = ctk.CTkScrollableFrame(news_panel, label_text="")
        self.home_news_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        self.home_news_scroll.grid_columnconfigure(0, weight=1)

        self.home_news_status_label = ctk.CTkLabel(
            self.home_news_scroll, text="Loading headlines…", justify="left", anchor="w"
        )
        self.home_news_status_label.grid(row=0, column=0, sticky="ew", pady=10)

        self.home_news_refresh_btn = ctk.CTkButton(
            news_panel, text="🔄 Refresh News", command=self.refresh_home
        )
        self.home_news_refresh_btn.grid(row=3, column=0, sticky="ew", padx=15, pady=(5, 15))

    def refresh_home(self):
        """Refresh both weather and home headlines."""
        self.refresh_weather()
        query = self.news_search_entry.get().strip() or None
        self._fetch_news_into(
            query=query,
            scroll_frame=self.home_news_scroll,
            refresh_btn=self.home_news_refresh_btn,
            on_loaded=self._on_home_news_loaded,
        )

    def refresh_weather(self):
        self.weather_refresh_btn.configure(state="disabled", text="Loading…")
        self._clear_frame(self.weather_scroll)
        ctk.CTkLabel(self.weather_scroll, text="Loading weather…").grid(row=0, column=0, pady=10)

        unit = self.settings.get("temp_unit", "C")

        def worker():
            try:
                data = weather.get_weather(unit=unit)
                error = None
            except weather.WeatherError as exc:
                data = None
                error = str(exc)
            except Exception as exc:  # noqa: BLE001 - surface any unexpected error safely
                data = None
                error = f"Unexpected error: {exc}"
            self.after(0, lambda: self._on_weather_loaded(data, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_weather_loaded(self, data, error):
        self.weather_refresh_btn.configure(state="normal", text="🔄 Refresh Weather")
        self._clear_frame(self.weather_scroll)

        if error or not data:
            ctk.CTkLabel(
                self.weather_scroll,
                text=f"⚠️ Could not load weather.\n{error or 'Unknown error'}",
                text_color="#e06c75", justify="left"
            ).grid(row=0, column=0, sticky="w", pady=10)
            self._touch_timestamp()
            return

        self._weather_data = data
        unit_label = data.get("unit", "C")
        row = 0

        ctk.CTkLabel(
            self.weather_scroll, text=f"📍 {data['location']}",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w", justify="left"
        ).grid(row=row, column=0, sticky="w", pady=(0, 8)); row += 1

        ctk.CTkLabel(
            self.weather_scroll,
            text=f"{data['icon']}  {data['temperature']}°{unit_label} — {data['condition']}",
            font=ctk.CTkFont(size=22, weight="bold"), anchor="w", justify="left"
        ).grid(row=row, column=0, sticky="w", pady=(0, 4)); row += 1

        wind_unit = "mph" if unit_label == "F" else "km/h"
        ctk.CTkLabel(
            self.weather_scroll, text=f"💨 Wind: {data['windspeed']} {wind_unit}",
            anchor="w", justify="left"
        ).grid(row=row, column=0, sticky="w", pady=(0, 12)); row += 1

        if data.get("forecast"):
            ctk.CTkLabel(
                self.weather_scroll, text="Upcoming",
                font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
            ).grid(row=row, column=0, sticky="w", pady=(0, 4)); row += 1

            for item in data["forecast"]:
                frame = ctk.CTkFrame(self.weather_scroll, fg_color=theme.PANEL_2)
                frame.grid(row=row, column=0, sticky="ew", pady=3)
                frame.grid_columnconfigure(1, weight=1)

                ctk.CTkLabel(frame, text=item["time"], width=60, anchor="w").grid(
                    row=0, column=0, padx=(10, 5), pady=6
                )
                ctk.CTkLabel(
                    frame, text=f"{item['icon']} {item['condition']}", anchor="w"
                ).grid(row=0, column=1, sticky="w", pady=6)
                ctk.CTkLabel(frame, text=f"{item['temp']}°{unit_label}", anchor="e", width=50).grid(
                    row=0, column=2, padx=(5, 10), pady=6
                )
                row += 1

        self._touch_timestamp()

    def _on_home_news_loaded(self, data, error):
        self._home_news_data = data
        self._render_headline_list(
            data, error, self.home_news_scroll, self.home_news_refresh_btn, "🔄 Refresh News"
        )
        self._touch_timestamp()

    # ------------------------------------------------------------------
    # MY FEEDS TAB
    # ------------------------------------------------------------------

    def _build_feeds_tab(self):
        tab = self.tab_feeds
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 0))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top, text="My Custom Feeds", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            tab,
            text="Track any topic — a company, a hobby, a hometown team. Add feeds in Settings, "
                 "then pick one below to see the latest headlines.",
            text_color=theme.MUTED, justify="left", wraplength=700, anchor="w"
        ).grid(row=1, column=0, sticky="ew", padx=5, pady=(2, 10))

        self.feeds_body = ctk.CTkFrame(tab, fg_color="transparent")
        self.feeds_body.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.feeds_body.grid_rowconfigure(1, weight=1)
        self.feeds_body.grid_columnconfigure(0, weight=1)

        self._render_feeds_tab()

    def _render_feeds_tab(self):
        """Rebuild the feed picker + headline list (called after feeds change)."""
        self._clear_frame(self.feeds_body)
        feeds = storage.get_custom_feeds()

        if not feeds:
            ctk.CTkLabel(
                self.feeds_body,
                text="No custom feeds yet. Go to Settings → Custom Feeds to add one "
                     "(e.g. name: \"F1\", keywords: \"Formula 1\").",
                justify="left", wraplength=700, anchor="w"
            ).grid(row=0, column=0, sticky="w", pady=10)
            return

        picker_row = ctk.CTkFrame(self.feeds_body, fg_color="transparent")
        picker_row.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        names = [f["name"] for f in feeds]
        if self._active_feed_name not in names:
            self._active_feed_name = names[0]

        self.feed_selector = ctk.CTkSegmentedButton(
            picker_row, values=names, command=self._on_feed_selected
        )
        self.feed_selector.set(self._active_feed_name)
        self.feed_selector.grid(row=0, column=0, sticky="w")

        self.feed_refresh_btn = ctk.CTkButton(
            picker_row, text="🔄 Refresh", width=90, command=self.refresh_feed
        )
        self.feed_refresh_btn.grid(row=0, column=1, padx=(10, 0))

        self.feed_news_scroll = ctk.CTkScrollableFrame(self.feeds_body, label_text="")
        self.feed_news_scroll.grid(row=1, column=0, sticky="nsew")
        self.feed_news_scroll.grid_columnconfigure(0, weight=1)

        self.refresh_feed()

    def _on_feed_selected(self, name):
        self._active_feed_name = name
        self.refresh_feed()

    def refresh_feed(self):
        feeds = {f["name"]: f["query"] for f in storage.get_custom_feeds()}
        if not self._active_feed_name or self._active_feed_name not in feeds:
            return
        query = feeds[self._active_feed_name]

        self._fetch_news_into(
            query=query,
            scroll_frame=self.feed_news_scroll,
            refresh_btn=self.feed_refresh_btn,
            on_loaded=self._on_feed_news_loaded,
        )

    def _on_feed_news_loaded(self, data, error):
        self._feed_news_data = data
        self._render_headline_list(
            data, error, self.feed_news_scroll, self.feed_refresh_btn, "🔄 Refresh"
        )

    # ------------------------------------------------------------------
    # SAVED TAB
    # ------------------------------------------------------------------

    def _build_saved_tab(self):
        tab = self.tab_saved
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 5))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top, text="Saved Articles", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            top, text="Clear all", width=90, fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
            command=self._clear_saved_confirm
        ).grid(row=0, column=1, sticky="e")

        self.saved_scroll = ctk.CTkScrollableFrame(tab, label_text="")
        self.saved_scroll.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.saved_scroll.grid_columnconfigure(0, weight=1)

    def _render_saved_tab(self):
        self._clear_frame(self.saved_scroll)
        saved = storage.get_saved_articles()

        if not saved:
            ctk.CTkLabel(
                self.saved_scroll,
                text="Nothing kept yet. Click the ☆ next to any headline to save it here.",
                justify="left"
            ).grid(row=0, column=0, sticky="w", pady=10)
            return

        for i, item in enumerate(saved):
            row_frame = ctk.CTkFrame(self.saved_scroll, fg_color=theme.PANEL_2)
            row_frame.grid(row=i, column=0, sticky="ew", pady=3)
            row_frame.grid_columnconfigure(0, weight=1)

            title_btn = ctk.CTkButton(
                row_frame, text=item["title"], anchor="w",
                fg_color="transparent", hover_color=("gray80", "gray25"),
                text_color=("black", "white"), font=ctk.CTkFont(size=13),
                command=lambda url=item.get("url"): self._open_link(url)
            )
            title_btn.grid(row=0, column=0, sticky="ew", padx=(5, 5), pady=(6, 0))

            remove_btn = ctk.CTkButton(
                row_frame, text="🗑", width=30, fg_color="transparent",
                hover_color=("gray80", "gray25"), text_color=("black", "white"),
                command=lambda url=item.get("url"): self._remove_saved(url)
            )
            remove_btn.grid(row=0, column=1, rowspan=2, padx=(0, 8))

            ctk.CTkLabel(
                row_frame, text=item.get("source", "Unknown"),
                font=ctk.CTkFont(size=11), text_color=theme.MUTED, anchor="w"
            ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))

    def _remove_saved(self, url):
        storage.remove_saved_article(url)
        self._render_saved_tab()
        # Refresh star states wherever this article might currently be shown
        self._refresh_save_buttons()

    def _clear_saved_confirm(self):
        if not storage.get_saved_articles():
            return
        if messagebox.askyesno("Clear saved articles", "Remove all saved articles? This cannot be undone."):
            storage.clear_saved_articles()
            self._render_saved_tab()
            self._refresh_save_buttons()

    # ------------------------------------------------------------------
    # SETTINGS TAB
    # ------------------------------------------------------------------

    def _build_settings_tab(self):
        tab = self.tab_settings
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(tab, label_text="")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        # --- Custom feeds management ---------------------------------
        feeds_section = ctk.CTkFrame(scroll)
        feeds_section.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        feeds_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            feeds_section, text="Custom Feeds", font=ctk.CTkFont(size=15, weight="bold")
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

        self._render_settings_feed_list()

        # --- Preferences -----------------------------------------------
        prefs_section = ctk.CTkFrame(scroll)
        prefs_section.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        prefs_section.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            prefs_section, text="Preferences", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 10), columnspan=2)

        ctk.CTkLabel(prefs_section, text="Temperature unit").grid(
            row=1, column=0, sticky="w", padx=15, pady=6
        )
        self.unit_switch = ctk.CTkSegmentedButton(
            prefs_section, values=["C", "F"], command=self._on_unit_changed
        )
        self.unit_switch.set(self.settings.get("temp_unit", "C"))
        self.unit_switch.grid(row=1, column=1, sticky="w", padx=15, pady=6)

        ctk.CTkLabel(prefs_section, text="Headline country code").grid(
            row=2, column=0, sticky="w", padx=15, pady=6
        )
        self.country_entry = ctk.CTkEntry(prefs_section, width=100)
        self.country_entry.insert(0, self.settings.get("country", "us"))
        self.country_entry.grid(row=2, column=1, sticky="w", padx=15, pady=6)
        self.country_entry.bind("<FocusOut>", lambda e: self._on_country_changed())
        self.country_entry.bind("<Return>", lambda e: self._on_country_changed())

        ctk.CTkLabel(prefs_section, text="Headlines per feed").grid(
            row=3, column=0, sticky="w", padx=15, pady=6
        )
        self.page_size_entry = ctk.CTkEntry(prefs_section, width=100)
        self.page_size_entry.insert(0, str(self.settings.get("page_size", 15)))
        self.page_size_entry.grid(row=3, column=1, sticky="w", padx=15, pady=6)
        self.page_size_entry.bind("<FocusOut>", lambda e: self._on_page_size_changed())
        self.page_size_entry.bind("<Return>", lambda e: self._on_page_size_changed())

        ctk.CTkLabel(prefs_section, text="Auto-refresh").grid(
            row=4, column=0, sticky="w", padx=15, pady=(6, 15)
        )
        current_minutes = self.settings.get("refresh_interval_minutes", 0)
        current_label = next(
            (label for label, mins in REFRESH_INTERVAL_OPTIONS.items() if mins == current_minutes),
            "Off",
        )
        self.refresh_interval_menu = ctk.CTkOptionMenu(
            prefs_section, values=list(REFRESH_INTERVAL_OPTIONS.keys()),
            command=self._on_refresh_interval_changed
        )
        self.refresh_interval_menu.set(current_label)
        self.refresh_interval_menu.grid(row=4, column=1, sticky="w", padx=15, pady=(6, 15))

        # --- Data management --------------------------------------------
        data_section = ctk.CTkFrame(scroll)
        data_section.grid(row=2, column=0, sticky="ew")
        data_section.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            data_section, text="Your Data", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            data_section,
            text=f"Feeds, saved articles, and preferences are stored locally at:\n{storage.storage_path()}",
            text_color=theme.MUTED, justify="left", wraplength=700, anchor="w"
        ).grid(row=1, column=0, sticky="w", padx=15, pady=(0, 10))

        btn_row = ctk.CTkFrame(data_section, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="w", padx=15, pady=(0, 15))

        ctk.CTkButton(
            btn_row, text="Clear saved articles", fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
            command=self._clear_saved_confirm
        ).grid(row=0, column=0, padx=(0, 10))

        ctk.CTkButton(
            btn_row, text="Reset all data", fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
            command=self._reset_all_confirm
        ).grid(row=0, column=1)

    # -- Feed management callbacks --

    def _render_settings_feed_list(self):
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
                row, text="Remove", width=80, fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
                command=lambda name=feed["name"]: self._remove_feed(name)
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
        self._render_settings_feed_list()
        self._render_feeds_tab()

    def _remove_feed(self, name):
        storage.remove_custom_feed(name)
        if self._active_feed_name == name:
            self._active_feed_name = None
        self._render_settings_feed_list()
        self._render_feeds_tab()

    # -- Preference callbacks --

    def _on_unit_changed(self, value):
        self.settings = storage.update_setting("temp_unit", value)
        self.refresh_weather()

    def _on_country_changed(self):
        value = self.country_entry.get().strip().lower() or "us"
        self.settings = storage.update_setting("country", value)

    def _on_page_size_changed(self):
        raw = self.page_size_entry.get().strip()
        try:
            value = max(1, min(50, int(raw)))
        except ValueError:
            value = self.settings.get("page_size", 15)
        self.page_size_entry.delete(0, "end")
        self.page_size_entry.insert(0, str(value))
        self.settings = storage.update_setting("page_size", value)

    def _on_refresh_interval_changed(self, label):
        minutes = REFRESH_INTERVAL_OPTIONS.get(label, 0)
        self.settings = storage.update_setting("refresh_interval_minutes", minutes)
        self._schedule_auto_refresh()

    def _reset_all_confirm(self):
        if messagebox.askyesno(
            "Reset all data",
            "This will remove all custom feeds, saved articles, and preferences. Continue?"
        ):
            storage.clear_all_data()
            self.settings = storage.get_settings()
            self._active_feed_name = None
            self._render_settings_feed_list()
            self._render_feeds_tab()
            self._render_saved_tab()
            self.unit_switch.set(self.settings.get("temp_unit", "C"))
            self.country_entry.delete(0, "end")
            self.country_entry.insert(0, self.settings.get("country", "us"))
            self.page_size_entry.delete(0, "end")
            self.page_size_entry.insert(0, str(self.settings.get("page_size", 15)))
            self.refresh_interval_menu.set("Off")
            self.refresh_weather()

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------

    def _schedule_auto_refresh(self):
        if self._auto_refresh_job is not None:
            self.after_cancel(self._auto_refresh_job)
            self._auto_refresh_job = None

        minutes = self.settings.get("refresh_interval_minutes", 0)
        if minutes and minutes > 0:
            self._auto_refresh_job = self.after(minutes * 60 * 1000, self._on_auto_refresh_tick)

    def _on_auto_refresh_tick(self):
        self.refresh_home()
        if storage.get_custom_feeds():
            self.refresh_feed()
        self._schedule_auto_refresh()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _fetch_news_into(self, query, scroll_frame, refresh_btn, on_loaded):
        refresh_btn.configure(state="disabled", text="Loading…")
        self._clear_frame(scroll_frame)
        ctk.CTkLabel(scroll_frame, text="Loading headlines…").grid(row=0, column=0, pady=10)

        country = self.settings.get("country", "us")
        page_size = self.settings.get("page_size", 15)

        def worker():
            try:
                data = news.get_headlines(query=query, country=country, page_size=page_size)
                error = None
            except news.NewsError as exc:
                data = None
                error = str(exc)
            except Exception as exc:  # noqa: BLE001
                data = None
                error = f"Unexpected error: {exc}"
            self.after(0, lambda: on_loaded(data, error))

        threading.Thread(target=worker, daemon=True).start()

    def _render_headline_list(self, data, error, scroll_frame, refresh_btn, refresh_btn_text):
        refresh_btn.configure(state="normal", text=refresh_btn_text)
        self._clear_frame(scroll_frame)

        if error or data is None:
            ctk.CTkLabel(
                scroll_frame,
                text=f"⚠️ Could not load headlines.\n{error or 'Unknown error'}",
                text_color="#e06c75", justify="left"
            ).grid(row=0, column=0, sticky="w", pady=10)
            return

        if not data:
            ctk.CTkLabel(scroll_frame, text="No headlines found.").grid(
                row=0, column=0, pady=10
            )
            return

        for i, item in enumerate(data):
            self._build_headline_row(scroll_frame, i, item)

    def _build_headline_row(self, parent, row_index, item):
        row_frame = ctk.CTkFrame(parent, fg_color=theme.PANEL_2)
        row_frame.grid(row=row_index, column=0, sticky="ew", pady=3)
        row_frame.grid_columnconfigure(0, weight=1)

        title_btn = ctk.CTkButton(
            row_frame, text=item["title"], anchor="w",
            fg_color="transparent", hover_color=("gray80", "gray25"),
            text_color=("black", "white"), font=ctk.CTkFont(size=13),
            command=lambda url=item.get("url"): self._open_link(url)
        )
        title_btn.grid(row=0, column=0, sticky="ew", padx=(5, 5), pady=(6, 0))

        is_saved = storage.is_article_saved(item.get("url"))
        save_btn = ctk.CTkButton(
            row_frame, text=("★" if is_saved else "☆"), width=30,
            fg_color="transparent", hover_color=("gray80", "gray25"),
            text_color=("#e0b03e" if is_saved else ("black", "white")),
            command=lambda i=item: self._toggle_save(i)
        )
        save_btn.grid(row=0, column=1, rowspan=2, padx=(0, 8))

        ctk.CTkLabel(
            row_frame, text=item.get("source", "Unknown"),
            font=ctk.CTkFont(size=11), text_color=theme.MUTED, anchor="w"
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))

    def _toggle_save(self, item):
        url = item.get("url")
        if storage.is_article_saved(url):
            storage.remove_saved_article(url)
        else:
            storage.save_article(item)
        self._render_saved_tab()
        self._refresh_save_buttons()

    def _refresh_save_buttons(self):
        """Re-render any currently visible headline lists so ☆/★ stays in sync."""
        if self._home_news_data is not None:
            self._render_headline_list(
                self._home_news_data, None, self.home_news_scroll,
                self.home_news_refresh_btn, "🔄 Refresh News"
            )
        if self._feed_news_data is not None and hasattr(self, "feed_news_scroll"):
            self._render_headline_list(
                self._feed_news_data, None, self.feed_news_scroll,
                self.feed_refresh_btn, "🔄 Refresh"
            )

    def _open_link(self, url):
        if url:
            webbrowser.open(url)

    def _clear_frame(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def _touch_timestamp(self):
        now = datetime.now().strftime("%H:%M:%S")
        self.last_updated_label.configure(text=f"Last updated: {now}")
