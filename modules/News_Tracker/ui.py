"""
ui.py
CustomTkinter UI for the Game Stats & News plugin.

Tabs:
    Home       -> Top headlines, full width. Each headline can be
                  "kept" (bookmarked) with one click.
    My Feeds   -> User-defined keyword/topic feeds (e.g. "AI", "F1",
                  "hometown team") that fetch their own headlines.
    Game Stats -> Look up a player's stats using a stored API key —
                  built-in support for Fortnite and Steam, plus a
                  generic path for any other game's REST API.
    API Keys   -> Add, view (masked), and remove API keys. Keys are
                  encrypted at rest via crypto_store.py.
    Saved      -> Every headline the user has kept, across all feeds.

Module ⚙ settings -> Custom feeds, country, headline count,
                  auto-refresh interval, and stored data management.

API calls run on background threads so the UI never freezes; results are
marshalled back to the main thread via `after()`.
"""

import threading
import webbrowser
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

from . import news
from . import storage
from . import crypto_store
from . import game_providers
from core import theme

REFRESH_INTERVAL_OPTIONS = {
    "Off": 0,
    "Every 5 minutes": 5,
    "Every 15 minutes": 15,
    "Every 30 minutes": 30,
    "Every hour": 60,
}

# Providers offered in the "Add API Key" form. Includes everything in
# game_providers.PROVIDERS (used for actual game-stat lookups) plus
# "newsapi", which isn't a game but reuses the same encrypted-key UI so
# there's one consistent place to manage every key this plugin uses.
KEY_PROVIDER_ORDER = ["fortnite", "steam", "clash_of_clans", "clash_royale", "brawl_stars", "newsapi", "custom"]
KEY_PROVIDER_INFO = dict(game_providers.PROVIDERS)
KEY_PROVIDER_INFO["newsapi"] = {
    "name": "News (NewsAPI.org)",
    "icon": "📰",
    "id_label": None,
    "key_help": "Optional — without a key, headlines come from Google News RSS automatically, no key required.",
    "key_url": "https://newsapi.org/register",
    "needs_extra": False,
}

# Providers selectable for an actual stats lookup (excludes "newsapi",
# which isn't a game).
GAME_PROVIDER_ORDER = ["fortnite", "steam", "clash_of_clans", "clash_royale", "brawl_stars", "custom"]


def _get_news_page(manager):
    if manager is None:
        return None
    current = getattr(manager, "current", None)
    if current is None:
        return None
    inner = getattr(current, "_inner", current)
    if inner.__class__.__name__ == "WeatherNewsUI":
        return inner
    return None


class WeatherNewsUI(ctk.CTkFrame):

    MODULE_SETTINGS_TITLE = "Feeds & preferences"

    @staticmethod
    def build_module_settings(parent, manager):
        from .settings_panel import GameStatsNewsSettingsPanel
        return GameStatsNewsSettingsPanel(parent, manager)

    def __init__(self, master, manager=None):
        super().__init__(master, fg_color=theme.BG)
        self.manager = manager

        self._home_news_data = None
        self._feed_news_data = None
        self._active_feed_name = None
        self._auto_refresh_job = None

        self._gs_key_options = []       # [{"id", "label", "provider", ...}]
        self._gs_selected_key_id = None
        self._add_key_provider_id = "fortnite"
        self._add_key_value_visible = False

        self.settings = storage.get_settings()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.tab_home = self.tabview.add("Home")
        self.tab_feeds = self.tabview.add("My Feeds")
        self.tab_game_stats = self.tabview.add("Game Stats")
        self.tab_api_keys = self.tabview.add("API Keys")
        self.tab_saved = self.tabview.add("Saved")

        self._build_home_tab()
        self._build_feeds_tab()
        self._build_game_stats_tab()
        self._build_api_keys_tab()
        self._build_saved_tab()

        # Initial load
        self.refresh_home()
        self._render_saved_tab()
        self._render_api_keys_list()
        self._refresh_game_stats_key_menu()
        self._schedule_auto_refresh()

    # ------------------------------------------------------------------
    # HOME TAB
    # ------------------------------------------------------------------

    def _build_home_tab(self):
        tab = self.tab_home
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="📰  Top Headlines",
            font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        self.last_updated_label = ctk.CTkLabel(
            header, text="Last updated: —",
            font=ctk.CTkFont(size=12), text_color=theme.MUTED
        )
        self.last_updated_label.grid(row=0, column=1, sticky="e")

        search_row = ctk.CTkFrame(tab, fg_color="transparent")
        search_row.grid(row=1, column=0, sticky="ew", padx=5, pady=(10, 5))
        search_row.grid_columnconfigure(0, weight=1)

        self.news_search_entry = ctk.CTkEntry(
            search_row, placeholder_text="Search headlines by keyword…", height=36
        )
        self.news_search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.news_search_entry.bind("<Return>", lambda e: self.refresh_home())

        ctk.CTkButton(
            search_row, text="Search", width=90, height=36,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self.refresh_home
        ).grid(row=0, column=1, padx=(0, 8))

        self.home_news_refresh_btn = ctk.CTkButton(
            search_row, text="🔄 Refresh", width=100, height=36,
            command=self.refresh_home
        )
        self.home_news_refresh_btn.grid(row=0, column=2)

        self.home_news_scroll = ctk.CTkScrollableFrame(tab, label_text="", fg_color="transparent")
        self.home_news_scroll.grid(row=2, column=0, sticky="nsew", padx=5, pady=(5, 5))
        self.home_news_scroll.grid_columnconfigure(0, weight=1)

        self.home_news_status_label = ctk.CTkLabel(
            self.home_news_scroll, text="Loading headlines…", justify="left", anchor="w"
        )
        self.home_news_status_label.grid(row=0, column=0, sticky="ew", pady=10)

    def refresh_home(self):
        query = self.news_search_entry.get().strip() or None
        self._fetch_news_into(
            query=query,
            scroll_frame=self.home_news_scroll,
            refresh_btn=self.home_news_refresh_btn,
            on_loaded=self._on_home_news_loaded,
        )

    def _on_home_news_loaded(self, data, error):
        self._home_news_data = data
        self._render_headline_list(
            data, error, self.home_news_scroll, self.home_news_refresh_btn, "🔄 Refresh"
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
            top, text="📌  My Custom Feeds", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            tab,
            text="Track any topic — a company, a hobby, a hometown team. Add feeds in "
                 "⚙ settings, then pick one below to see the latest headlines.",
            text_color=theme.MUTED, justify="left", wraplength=700, anchor="w"
        ).grid(row=1, column=0, sticky="ew", padx=5, pady=(4, 10))

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
                text="No custom feeds yet. Open ⚙ settings → Custom Feeds to add one "
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

        self.feed_news_scroll = ctk.CTkScrollableFrame(self.feeds_body, label_text="", fg_color="transparent")
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
    # GAME STATS TAB
    # ------------------------------------------------------------------

    def _build_game_stats_tab(self):
        tab = self.tab_game_stats
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 0))
        ctk.CTkLabel(
            header, text="🕹️  Game Stats", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        # -- lookup bar -----------------------------------------------
        bar = ctk.CTkFrame(tab, fg_color=theme.PANEL_2, corner_radius=10)
        bar.grid(row=1, column=0, sticky="ew", padx=5, pady=(12, 10))
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(bar, text="Key").grid(row=0, column=0, padx=(15, 8), pady=15)

        self.gs_key_menu = ctk.CTkOptionMenu(
            bar, values=["No API keys yet"], command=self._on_gs_key_selected, width=220
        )
        self.gs_key_menu.grid(row=0, column=1, sticky="w", pady=15)

        self.gs_identifier_entry = ctk.CTkEntry(bar, placeholder_text="Player identifier", width=200)
        self.gs_identifier_entry.grid(row=0, column=2, padx=(10, 10), pady=15)
        self.gs_identifier_entry.bind("<Return>", lambda e: self._on_game_stats_lookup())

        self.gs_lookup_btn = ctk.CTkButton(
            bar, text="Look Up", width=100, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_game_stats_lookup
        )
        self.gs_lookup_btn.grid(row=0, column=3, padx=(0, 15), pady=15)

        # -- results ----------------------------------------------------
        self.gs_results_scroll = ctk.CTkScrollableFrame(tab, label_text="", fg_color="transparent")
        self.gs_results_scroll.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.gs_results_scroll.grid_columnconfigure(0, weight=1)

        self._render_gs_placeholder(
            "No API keys added yet. Head to the API Keys tab to add one — "
            "Fortnite and Steam work out of the box, or add a custom API for any other game."
        )

    def _render_gs_placeholder(self, text):
        self._clear_frame(self.gs_results_scroll)
        ctk.CTkLabel(
            self.gs_results_scroll, text=text, text_color=theme.MUTED,
            justify="left", wraplength=700, anchor="w"
        ).grid(row=0, column=0, sticky="ew", pady=20, padx=5)

    def _refresh_game_stats_key_menu(self):
        keys = [k for k in crypto_store.list_keys() if k["provider"] in GAME_PROVIDER_ORDER]
        self._gs_key_options = keys

        if not keys:
            self.gs_key_menu.configure(values=["No API keys yet"], state="disabled")
            self.gs_key_menu.set("No API keys yet")
            self.gs_identifier_entry.configure(state="disabled")
            self.gs_lookup_btn.configure(state="disabled")
            self._gs_selected_key_id = None
            return

        labels = []
        for k in keys:
            info = game_providers.PROVIDERS.get(k["provider"], {})
            icon = info.get("icon", "🔑")
            name = info.get("name", k["provider"])
            labels.append(f"{icon} {name} — {k['label']}")

        self.gs_key_menu.configure(values=labels, state="normal")
        self.gs_key_menu.set(labels[0])
        self.gs_identifier_entry.configure(state="normal")
        self.gs_lookup_btn.configure(state="normal")
        self._gs_selected_key_id = keys[0]["id"]
        self._update_gs_identifier_placeholder(keys[0]["provider"])

    def _on_gs_key_selected(self, label):
        for i, k in enumerate(self._gs_key_options):
            info = game_providers.PROVIDERS.get(k["provider"], {})
            candidate = f"{info.get('icon', '🔑')} {info.get('name', k['provider'])} — {k['label']}"
            if candidate == label:
                self._gs_selected_key_id = k["id"]
                self._update_gs_identifier_placeholder(k["provider"])
                return

    def _update_gs_identifier_placeholder(self, provider):
        info = game_providers.PROVIDERS.get(provider, {})
        self.gs_identifier_entry.configure(placeholder_text=info.get("id_label", "Player identifier"))

    def _on_game_stats_lookup(self):
        if not self._gs_selected_key_id:
            return
        identifier = self.gs_identifier_entry.get().strip()

        entry = crypto_store.get_entry(self._gs_selected_key_id)
        if not entry or not entry.get("token"):
            self._render_gs_placeholder("⚠️ Couldn't read that key — try removing and re-adding it in API Keys.")
            return

        self.gs_lookup_btn.configure(state="disabled", text="Looking up…")
        self._render_gs_placeholder("Looking up player…")

        provider = entry["provider"]
        token = entry["token"]
        extra = entry.get("extra", {})

        def worker():
            try:
                result = game_providers.fetch_stats(provider, identifier, token, extra)
                error = None
            except game_providers.GameStatsError as exc:
                result = None
                error = str(exc)
            except Exception as exc:  # noqa: BLE001
                result = None
                error = f"Unexpected error: {exc}"
            self.after(0, lambda: self._on_gs_result(result, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_gs_result(self, result, error):
        self.gs_lookup_btn.configure(state="normal", text="Look Up")

        if error or not result:
            self._render_gs_placeholder(f"⚠️ {error or 'No result.'}")
            return

        self._clear_frame(self.gs_results_scroll)

        card = ctk.CTkFrame(self.gs_results_scroll, fg_color=theme.PANEL_2, corner_radius=10)
        card.grid(row=0, column=0, sticky="ew", pady=5, padx=5)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=result.get("player", "—"),
            font=ctk.CTkFont(size=17, weight="bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 10))

        rows = result.get("rows", [])
        for i, (label, value) in enumerate(rows):
            row_frame = ctk.CTkFrame(card, fg_color="transparent")
            row_frame.grid(row=i + 1, column=0, sticky="ew", padx=18, pady=4)
            row_frame.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row_frame, text=str(label), text_color=theme.MUTED, anchor="w", width=160).grid(
                row=0, column=0, sticky="w"
            )
            ctk.CTkLabel(row_frame, text=str(value), anchor="w", font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=1, sticky="w"
            )

        ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=len(rows) + 1, column=0)

    # ------------------------------------------------------------------
    # API KEYS TAB
    # ------------------------------------------------------------------

    def _build_api_keys_tab(self):
        tab = self.tab_api_keys
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(tab, label_text="", fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            scroll, text="🔑  API Keys", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        ctk.CTkLabel(
            scroll,
            text="Keys are encrypted before they're written to disk, and decrypted only in memory "
                 "right before a request goes out. (They can't be hashed instead — a hashed key "
                 "can't be sent back to the API to authenticate, since hashing can't be reversed.)",
            text_color=theme.MUTED, justify="left", wraplength=760, anchor="w"
        ).grid(row=1, column=0, sticky="ew", pady=(0, 15))

        # -- existing keys ----------------------------------------------
        self.keys_list_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self.keys_list_frame.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        self.keys_list_frame.grid_columnconfigure(0, weight=1)

        # -- add-key form -------------------------------------------------
        form = ctk.CTkFrame(scroll, fg_color=theme.PANEL_2, corner_radius=10)
        form.grid(row=3, column=0, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            form, text="Add a Key", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=18, pady=(16, 10))

        ctk.CTkLabel(form, text="Provider").grid(row=1, column=0, sticky="w", padx=18, pady=6)
        provider_labels = [
            f"{KEY_PROVIDER_INFO[p]['icon']} {KEY_PROVIDER_INFO[p]['name']}" for p in KEY_PROVIDER_ORDER
        ]
        self.add_key_provider_menu = ctk.CTkOptionMenu(
            form, values=provider_labels, command=self._on_add_key_provider_changed, width=220
        )
        self.add_key_provider_menu.set(provider_labels[0])
        self.add_key_provider_menu.grid(row=1, column=1, sticky="w", padx=18, pady=6)

        self.add_key_hint_label = ctk.CTkLabel(
            form, text="", text_color=theme.MUTED, justify="left", wraplength=650, anchor="w"
        )
        self.add_key_hint_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 8))

        ctk.CTkLabel(form, text="Label").grid(row=3, column=0, sticky="w", padx=18, pady=6)
        self.add_key_label_entry = ctk.CTkEntry(
            form, placeholder_text="e.g. my main account (optional)", width=300
        )
        self.add_key_label_entry.grid(row=3, column=1, sticky="w", padx=18, pady=6)

        ctk.CTkLabel(form, text="Key").grid(row=4, column=0, sticky="w", padx=18, pady=6)
        key_value_row = ctk.CTkFrame(form, fg_color="transparent")
        key_value_row.grid(row=4, column=1, sticky="w", padx=18, pady=6)

        self.add_key_value_entry = ctk.CTkEntry(key_value_row, width=300, show="•")
        self.add_key_value_entry.grid(row=0, column=0, padx=(0, 6))

        self.add_key_show_btn = ctk.CTkButton(
            key_value_row, text="👁", width=32, command=self._toggle_add_key_visibility
        )
        self.add_key_show_btn.grid(row=0, column=1)

        # -- custom-provider-only extra fields ---------------------------
        self.add_key_custom_frame = ctk.CTkFrame(form, fg_color="transparent")
        self.add_key_custom_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self.add_key_custom_frame, text="Base URL").grid(row=0, column=0, sticky="w", pady=4)
        self.custom_base_url_entry = ctk.CTkEntry(
            self.add_key_custom_frame,
            placeholder_text="https://api.example.com/stats/{id}  (or ?name= is added automatically)",
            width=420
        )
        self.custom_base_url_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=4)

        ctk.CTkLabel(self.add_key_custom_frame, text="Auth header").grid(row=1, column=0, sticky="w", pady=4)
        header_row = ctk.CTkFrame(self.add_key_custom_frame, fg_color="transparent")
        header_row.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=4)
        self.custom_header_name_entry = ctk.CTkEntry(header_row, placeholder_text="Header name (e.g. Authorization)", width=220)
        self.custom_header_name_entry.grid(row=0, column=0, padx=(0, 6))
        self.custom_header_prefix_entry = ctk.CTkEntry(header_row, placeholder_text="Prefix (e.g. \"Bearer \")", width=140)
        self.custom_header_prefix_entry.grid(row=0, column=1)

        ctk.CTkLabel(self.add_key_custom_frame, text="ID query param").grid(row=2, column=0, sticky="w", pady=4)
        self.custom_id_param_entry = ctk.CTkEntry(
            self.add_key_custom_frame, placeholder_text="name  (only used if the URL has no {id})", width=220
        )
        self.custom_id_param_entry.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=4)

        ctk.CTkButton(
            form, text="Save Key", fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_save_key
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=18, pady=(14, 18))

        self._on_add_key_provider_changed(provider_labels[0])

    def _provider_id_from_label(self, label):
        for p in KEY_PROVIDER_ORDER:
            if f"{KEY_PROVIDER_INFO[p]['icon']} {KEY_PROVIDER_INFO[p]['name']}" == label:
                return p
        return KEY_PROVIDER_ORDER[0]

    def _on_add_key_provider_changed(self, label):
        provider = self._provider_id_from_label(label)
        self._add_key_provider_id = provider
        info = KEY_PROVIDER_INFO[provider]

        hint = info.get("key_help", "")
        if info.get("key_url"):
            hint += f"  ({info['key_url']})"
        self.add_key_hint_label.configure(text=hint)

        if info.get("needs_extra"):
            self.add_key_custom_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=18, pady=(4, 4))
        else:
            self.add_key_custom_frame.grid_forget()

    def _toggle_add_key_visibility(self):
        self._add_key_value_visible = not self._add_key_value_visible
        self.add_key_value_entry.configure(show="" if self._add_key_value_visible else "•")
        self.add_key_show_btn.configure(text="🙈" if self._add_key_value_visible else "👁")

    def _on_save_key(self):
        provider = self._add_key_provider_id
        label = self.add_key_label_entry.get().strip()
        value = self.add_key_value_entry.get().strip()

        extra = {}
        if KEY_PROVIDER_INFO[provider].get("needs_extra"):
            base_url = self.custom_base_url_entry.get().strip()
            if not base_url:
                messagebox.showwarning("Add API Key", "Custom providers need a base URL.")
                return
            extra = {
                "base_url": base_url,
                "header_name": self.custom_header_name_entry.get().strip(),
                "header_prefix": self.custom_header_prefix_entry.get().strip(),
                "id_param": self.custom_id_param_entry.get().strip(),
            }

        try:
            crypto_store.add_key(provider, label, value, extra=extra)
        except ValueError as exc:
            messagebox.showwarning("Add API Key", str(exc))
            return

        self.add_key_label_entry.delete(0, "end")
        self.add_key_value_entry.delete(0, "end")
        self.custom_base_url_entry.delete(0, "end")
        self.custom_header_name_entry.delete(0, "end")
        self.custom_header_prefix_entry.delete(0, "end")
        self.custom_id_param_entry.delete(0, "end")

        self._render_api_keys_list()
        self._refresh_game_stats_key_menu()

    def _render_api_keys_list(self):
        self._clear_frame(self.keys_list_frame)
        keys = crypto_store.list_keys()

        if not keys:
            ctk.CTkLabel(
                self.keys_list_frame, text="No keys added yet.", text_color=theme.MUTED
            ).grid(row=0, column=0, sticky="w")
            return

        for i, k in enumerate(keys):
            info = KEY_PROVIDER_INFO.get(k["provider"], {"icon": "🔑", "name": k["provider"]})
            row = ctk.CTkFrame(self.keys_list_frame, fg_color=theme.PANEL_2, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(row, text=info["icon"], font=ctk.CTkFont(size=18)).grid(
                row=0, column=0, rowspan=2, padx=(15, 10), pady=10
            )

            ctk.CTkLabel(
                row, text=f"{info['name']}  —  {k['label']}", anchor="w",
                font=ctk.CTkFont(weight="bold")
            ).grid(row=0, column=1, sticky="w", pady=(10, 0))

            ctk.CTkLabel(
                row, text=k["preview"], anchor="w", text_color=theme.MUTED,
                font=ctk.CTkFont(family="Consolas", size=12)
            ).grid(row=1, column=1, sticky="w", pady=(0, 10))

            ctk.CTkButton(
                row, text="Remove", width=80, fg_color=theme.DANGER_BG,
                hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
                command=lambda kid=k["id"]: self._remove_key(kid)
            ).grid(row=0, column=2, rowspan=2, padx=15, pady=10)

    def _remove_key(self, key_id):
        crypto_store.remove_key(key_id)
        self._render_api_keys_list()
        self._refresh_game_stats_key_menu()

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
            top, text="⭐  Saved Articles", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            top, text="Clear all", width=90, fg_color=theme.DANGER_BG, hover_color=theme.DANGER_HOVER, text_color=theme.DANGER,
            command=self._clear_saved_confirm
        ).grid(row=0, column=1, sticky="e")

        self.saved_scroll = ctk.CTkScrollableFrame(tab, label_text="", fg_color="transparent")
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
            row_frame = ctk.CTkFrame(self.saved_scroll, fg_color=theme.PANEL_2, corner_radius=8)
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
        row_frame = ctk.CTkFrame(parent, fg_color=theme.PANEL_2, corner_radius=8)
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
                self.home_news_refresh_btn, "🔄 Refresh"
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
