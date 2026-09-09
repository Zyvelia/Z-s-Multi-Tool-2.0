"""Qt Game Stats & News — headlines, feeds, weather, stats, encrypted keys."""

from __future__ import annotations

import threading
import webbrowser
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.News_Tracker import crypto_store
from modules.News_Tracker import game_providers
from modules.News_Tracker import news
from modules.News_Tracker import storage
from modules.News_Tracker import weather

REFRESH_INTERVAL_OPTIONS = {
    "Off": 0,
    "Every 5 minutes": 5,
    "Every 15 minutes": 15,
    "Every 30 minutes": 30,
    "Every hour": 60,
}

KEY_PROVIDER_ORDER = ["fortnite", "steam", "clash_of_clans", "clash_royale", "brawl_stars", "newsapi", "custom"]
KEY_PROVIDER_INFO = dict(game_providers.PROVIDERS)
KEY_PROVIDER_INFO["newsapi"] = {
    "name": "News (NewsAPI.org)",
    "icon": "📰",
    "id_label": None,
    "key_help": "Optional — without a key, headlines come from Google News RSS automatically.",
    "key_url": "https://newsapi.org/register",
    "needs_extra": False,
}
GAME_PROVIDER_ORDER = ["fortnite", "steam", "clash_of_clans", "clash_royale", "brawl_stars", "custom"]


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _scroll(layout) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    inner = QWidget()
    inner.setLayout(layout)
    scroll.setWidget(inner)
    return scroll


class WeatherNewsUI(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.settings = storage.get_settings()
        self._active_feed_name = None
        self._gs_key_options = []
        self._gs_selected_key_id = None
        self._add_key_provider_id = "fortnite"
        self._key_visible = False

        root = QVBoxLayout(self)
        title = QLabel("Game Stats & News")
        title.setObjectName("AccentTitle")
        root.addWidget(title)

        self.weather_strip = QLabel("Weather: loading…")
        self.weather_strip.setObjectName("Muted")
        self.weather_strip.setWordWrap(True)
        root.addWidget(self.weather_strip)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_home(), "Home")
        self.tabs.addTab(self._build_feeds(), "My Feeds")
        self.tabs.addTab(self._build_game_stats(), "Game Stats")
        self.tabs.addTab(self._build_saved(), "Saved")
        root.addWidget(self.tabs, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_auto_refresh_tick)

        self.refresh_home()
        self._render_saved()
        self._refresh_gs_keys()
        self._load_weather()
        self._schedule_auto_refresh()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _NewsSettings(parent, manager)

    def _build_home(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        header = QHBoxLayout()
        h = QLabel("Top Headlines")
        h.setObjectName("CardTitle")
        self.updated = QLabel("Last updated: —")
        self.updated.setObjectName("Muted")
        header.addWidget(h)
        header.addStretch(1)
        header.addWidget(self.updated)
        lay.addLayout(header)
        search = QHBoxLayout()
        self.news_search = QLineEdit()
        self.news_search.setPlaceholderText("Search headlines by keyword…")
        self.news_search.returnPressed.connect(self.refresh_home)
        go = QPushButton("Search")
        go.setObjectName("Primary")
        go.clicked.connect(self.refresh_home)
        self.home_refresh = QPushButton("Refresh")
        self.home_refresh.clicked.connect(self.refresh_home)
        search.addWidget(self.news_search, 1)
        search.addWidget(go)
        search.addWidget(self.home_refresh)
        lay.addLayout(search)
        self.home_list = QVBoxLayout()
        lay.addWidget(_scroll(self.home_list), 1)
        return page

    def _build_feeds(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        t = QLabel("My Custom Feeds")
        t.setObjectName("CardTitle")
        hint = QLabel("Add feeds in module settings, then pick one below.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.feed_pick = QComboBox()
        self.feed_pick.currentTextChanged.connect(self._on_feed_selected)
        self.feed_refresh = QPushButton("Refresh")
        self.feed_refresh.clicked.connect(self.refresh_feed)
        row.addWidget(self.feed_pick, 1)
        row.addWidget(self.feed_refresh)
        lay.addLayout(row)
        self.feed_list = QVBoxLayout()
        lay.addWidget(_scroll(self.feed_list), 1)
        self._reload_feed_picker()
        return page

    def _build_game_stats(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        t = QLabel("Game Stats")
        t.setObjectName("CardTitle")
        lay.addWidget(t)
        bar = QFrame()
        bar.setObjectName("Panel")
        bl = QHBoxLayout(bar)
        self.gs_key = QComboBox()
        self.gs_key.currentIndexChanged.connect(self._on_gs_key)
        self.gs_id = QLineEdit()
        self.gs_id.setPlaceholderText("Player identifier")
        self.gs_id.returnPressed.connect(self._lookup_stats)
        self.gs_btn = QPushButton("Look up")
        self.gs_btn.setObjectName("Primary")
        self.gs_btn.clicked.connect(self._lookup_stats)
        bl.addWidget(QLabel("Key"))
        bl.addWidget(self.gs_key, 1)
        bl.addWidget(self.gs_id, 1)
        bl.addWidget(self.gs_btn)
        lay.addWidget(bar)
        self.gs_list = QVBoxLayout()
        lay.addWidget(_scroll(self.gs_list), 1)
        return page

    def _build_saved(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        header = QHBoxLayout()
        t = QLabel("Saved Articles")
        t.setObjectName("CardTitle")
        clear = QPushButton("Clear all")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_saved_confirm)
        header.addWidget(t)
        header.addStretch(1)
        header.addWidget(clear)
        lay.addLayout(header)
        self.saved_list = QVBoxLayout()
        lay.addWidget(_scroll(self.saved_list), 1)
        return page

    def on_show(self):
        self.settings = storage.get_settings()
        self._reload_feed_picker()
        self._refresh_gs_keys()
        self._schedule_auto_refresh()

    def _load_weather(self):
        def work():
            try:
                data = weather.get_weather(unit=self.settings.get("temp_unit", "C"))
                err = None
            except weather.WeatherError as exc:
                data, err = None, str(exc)
            except Exception as exc:
                data, err = None, str(exc)
            QTimer.singleShot(0, lambda: self._apply_weather(data, err))

        threading.Thread(target=work, daemon=True).start()

    def _apply_weather(self, data, err):
        if err or not data:
            self.weather_strip.setText(f"Weather unavailable: {err or 'no data'}")
            return
        unit = data.get("unit", "C")
        bits = [
            f"{data.get('icon', '')} {data.get('location', '')}",
            f"{data.get('temperature')}°{unit}",
            data.get("condition", ""),
            f"wind {data.get('windspeed')}",
        ]
        forecast = data.get("forecast") or []
        if forecast:
            bits.append(" · ".join(f"{h['time']} {h['icon']} {h['temp']}°" for h in forecast[:4]))
        self.weather_strip.setText("  ·  ".join(str(b) for b in bits if b))

    def refresh_home(self):
        query = self.news_search.text().strip() or None
        self._fetch_news(query, self.home_list, self.home_refresh, self._touch_timestamp)

    def _reload_feed_picker(self):
        feeds = storage.get_custom_feeds()
        names = [f["name"] for f in feeds]
        self.feed_pick.blockSignals(True)
        self.feed_pick.clear()
        if not names:
            self.feed_pick.addItem("(no feeds — add in settings)")
            self._active_feed_name = None
        else:
            self.feed_pick.addItems(names)
            if self._active_feed_name not in names:
                self._active_feed_name = names[0]
            self.feed_pick.setCurrentText(self._active_feed_name)
        self.feed_pick.blockSignals(False)
        if names:
            self.refresh_feed()

    def _on_feed_selected(self, name):
        if name.startswith("("):
            return
        self._active_feed_name = name
        self.refresh_feed()

    def refresh_feed(self):
        feeds = {f["name"]: f["query"] for f in storage.get_custom_feeds()}
        if not self._active_feed_name or self._active_feed_name not in feeds:
            return
        self._fetch_news(feeds[self._active_feed_name], self.feed_list, self.feed_refresh)

    def _fetch_news(self, query, layout, btn, extra=None):
        btn.setEnabled(False)
        btn.setText("Loading…")
        _clear(layout)
        loading = QLabel("Loading headlines…")
        loading.setObjectName("Muted")
        layout.addWidget(loading)
        layout.addStretch(1)
        country = self.settings.get("country", "us")
        page_size = self.settings.get("page_size", 15)

        def work():
            try:
                data = news.get_headlines(query=query, country=country, page_size=page_size)
                error = None
            except Exception as exc:
                data, error = None, str(exc)
            QTimer.singleShot(0, lambda: self._render_headlines(data, error, layout, btn, extra))

        threading.Thread(target=work, daemon=True).start()

    def _touch_timestamp(self):
        self.updated.setText(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")

    def _render_headlines(self, data, error, layout, btn, extra=None):
        btn.setEnabled(True)
        btn.setText("Refresh")
        _clear(layout)
        if extra:
            extra()
        if error:
            err = QLabel(error)
            err.setObjectName("Danger")
            layout.addWidget(err)
            layout.addStretch(1)
            return
        articles = data or []
        if not articles:
            empty = QLabel("No headlines.")
            empty.setObjectName("Muted")
            layout.addWidget(empty)
            layout.addStretch(1)
            return
        for article in articles:
            layout.addWidget(self._headline_card(article))
        layout.addStretch(1)

    def _headline_card(self, article):
        card = QFrame()
        card.setObjectName("Panel")
        lay = QHBoxLayout(card)
        col = QVBoxLayout()
        title = QPushButton(article.get("title") or "(untitled)")
        title.setStyleSheet("text-align: left;")
        title.clicked.connect(lambda _=False, u=article.get("url"): self._open(u))
        src = QLabel(article.get("source") or "")
        src.setObjectName("Muted")
        col.addWidget(title)
        col.addWidget(src)
        lay.addLayout(col, 1)
        saved = storage.is_article_saved(article.get("url"))
        star = QPushButton("★" if saved else "☆")
        star.clicked.connect(lambda _=False, a=article, b=star: self._toggle_save(a, b))
        lay.addWidget(star)
        return card

    def _toggle_save(self, article, btn):
        url = article.get("url")
        if storage.is_article_saved(url):
            storage.remove_saved_article(url)
            btn.setText("☆")
        else:
            storage.save_article(article)
            btn.setText("★")
        self._render_saved()

    def _open(self, url):
        if url:
            webbrowser.open(url)

    def _refresh_gs_keys(self):
        keys = [k for k in crypto_store.list_keys() if k["provider"] in GAME_PROVIDER_ORDER]
        self._gs_key_options = keys
        self.gs_key.blockSignals(True)
        self.gs_key.clear()
        if not keys:
            self.gs_key.addItem("No API keys yet — add in settings")
            self.gs_id.setEnabled(False)
            self.gs_btn.setEnabled(False)
            self._gs_selected_key_id = None
        else:
            for k in keys:
                info = game_providers.PROVIDERS.get(k["provider"], {})
                self.gs_key.addItem(f"{info.get('icon', '🔑')} {info.get('name', k['provider'])} — {k['label']}", k["id"])
            self.gs_id.setEnabled(True)
            self.gs_btn.setEnabled(True)
            self._gs_selected_key_id = keys[0]["id"]
            self._update_gs_placeholder(keys[0]["provider"])
        self.gs_key.blockSignals(False)

    def _on_gs_key(self, idx):
        if idx < 0 or idx >= len(self._gs_key_options):
            return
        k = self._gs_key_options[idx]
        self._gs_selected_key_id = k["id"]
        self._update_gs_placeholder(k["provider"])

    def _update_gs_placeholder(self, provider):
        info = game_providers.PROVIDERS.get(provider, {})
        self.gs_id.setPlaceholderText(info.get("id_label", "Player identifier"))

    def _lookup_stats(self):
        if not self._gs_selected_key_id:
            return
        identifier = self.gs_id.text().strip()
        entry = crypto_store.get_entry(self._gs_selected_key_id)
        if not entry or not entry.get("token"):
            self._gs_message("Couldn't read that key — try removing and re-adding it in settings.")
            return
        self.gs_btn.setEnabled(False)
        self.gs_btn.setText("Looking up…")
        self._gs_message("Looking up player…")
        provider, token, extra = entry["provider"], entry["token"], entry.get("extra", {})

        def work():
            try:
                result = game_providers.fetch_stats(provider, identifier, token, extra)
                error = None
            except game_providers.GameStatsError as exc:
                result, error = None, str(exc)
            except Exception as exc:
                result, error = None, f"Unexpected error: {exc}"
            QTimer.singleShot(0, lambda: self._gs_result(result, error))

        threading.Thread(target=work, daemon=True).start()

    def _gs_message(self, text):
        _clear(self.gs_list)
        lbl = QLabel(text)
        lbl.setObjectName("Muted")
        lbl.setWordWrap(True)
        self.gs_list.addWidget(lbl)
        self.gs_list.addStretch(1)

    def _gs_result(self, result, error):
        self.gs_btn.setEnabled(True)
        self.gs_btn.setText("Look up")
        if error or not result:
            self._gs_message(error or "No result.")
            return
        _clear(self.gs_list)
        card = QFrame()
        card.setObjectName("Panel")
        cl = QVBoxLayout(card)
        player = QLabel(result.get("player", "—"))
        player.setObjectName("CardTitle")
        cl.addWidget(player)
        for label, value in result.get("rows", []):
            row = QHBoxLayout()
            k = QLabel(str(label))
            k.setObjectName("Muted")
            v = QLabel(str(value))
            row.addWidget(k)
            row.addWidget(v, 1)
            cl.addLayout(row)
        self.gs_list.addWidget(card)
        self.gs_list.addStretch(1)

    def _render_saved(self):
        _clear(self.saved_list)
        saved = storage.get_saved_articles()
        if not saved:
            empty = QLabel("Nothing kept yet. Click ☆ next to any headline to save it here.")
            empty.setObjectName("Muted")
            self.saved_list.addWidget(empty)
            self.saved_list.addStretch(1)
            return
        for item in saved:
            card = QFrame()
            card.setObjectName("Panel")
            lay = QHBoxLayout(card)
            col = QVBoxLayout()
            btn = QPushButton(item.get("title") or "(untitled)")
            btn.setStyleSheet("text-align: left;")
            btn.clicked.connect(lambda _=False, u=item.get("url"): self._open(u))
            src = QLabel(item.get("source") or "Unknown")
            src.setObjectName("Muted")
            col.addWidget(btn)
            col.addWidget(src)
            lay.addLayout(col, 1)
            rm = QPushButton("Remove")
            rm.setObjectName("Danger")
            rm.clicked.connect(lambda _=False, u=item.get("url"): self._remove_saved(u))
            lay.addWidget(rm)
            self.saved_list.addWidget(card)
        self.saved_list.addStretch(1)

    def _remove_saved(self, url):
        storage.remove_saved_article(url)
        self._render_saved()

    def _clear_saved_confirm(self):
        if not storage.get_saved_articles():
            return
        if QMessageBox.question(
            self, "Clear saved articles",
            "Remove all saved articles? This cannot be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        storage.clear_saved_articles()
        self._render_saved()

    def _schedule_auto_refresh(self):
        self._refresh_timer.stop()
        minutes = self.settings.get("refresh_interval_minutes", 0)
        if minutes and minutes > 0:
            self._refresh_timer.start(minutes * 60 * 1000)

    def _on_auto_refresh_tick(self):
        self.refresh_home()
        if storage.get_custom_feeds():
            self.refresh_feed()
        self._load_weather()
        self._schedule_auto_refresh()


def _news_page(manager):
    if manager is None:
        return None
    current = getattr(manager, "current", None)
    if current is None:
        return None
    inner = getattr(current, "_inner", current)
    if isinstance(inner, WeatherNewsUI):
        return inner
    return None


class _NewsSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.settings = storage.get_settings()
        lay = QVBoxLayout(self)

        feeds_t = QLabel("Custom feeds")
        feeds_t.setObjectName("CardTitle")
        lay.addWidget(feeds_t)
        add = QHBoxLayout()
        self.feed_name = QLineEdit()
        self.feed_name.setPlaceholderText("Feed name (e.g. F1)")
        self.feed_query = QLineEdit()
        self.feed_query.setPlaceholderText("Keywords (e.g. Formula 1)")
        add_btn = QPushButton("Add feed")
        add_btn.setObjectName("Primary")
        add_btn.clicked.connect(self._add_feed)
        add.addWidget(self.feed_name)
        add.addWidget(self.feed_query, 1)
        add.addWidget(add_btn)
        lay.addLayout(add)
        self.feed_host = QVBoxLayout()
        lay.addLayout(self.feed_host)

        prefs = QLabel("Preferences")
        prefs.setObjectName("CardTitle")
        lay.addWidget(prefs)
        row = QHBoxLayout()
        row.addWidget(QLabel("Headline country"))
        self.country = QLineEdit(self.settings.get("country", "us"))
        self.country.editingFinished.connect(self._save_country)
        row.addWidget(self.country)
        row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Headlines per feed"))
        self.page_size = QLineEdit(str(self.settings.get("page_size", 15)))
        self.page_size.editingFinished.connect(self._save_page_size)
        row2.addWidget(self.page_size)
        row2.addStretch(1)
        lay.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Auto-refresh"))
        self.refresh = QComboBox()
        for label, mins in REFRESH_INTERVAL_OPTIONS.items():
            self.refresh.addItem(label, mins)
        current = self.settings.get("refresh_interval_minutes", 0)
        idx = self.refresh.findData(current)
        self.refresh.setCurrentIndex(idx if idx >= 0 else 0)
        self.refresh.currentIndexChanged.connect(self._save_refresh)
        row3.addWidget(self.refresh)
        row3.addStretch(1)
        lay.addLayout(row3)

        keys_t = QLabel("API keys (encrypted)")
        keys_t.setObjectName("CardTitle")
        hint = QLabel(
            "Keys are encrypted at rest via crypto_store — they are never written as plaintext. "
            f"Stored at {crypto_store.storage_path()}"
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(keys_t)
        lay.addWidget(hint)
        self.keys_host = QVBoxLayout()
        lay.addLayout(self.keys_host)

        form = QFrame()
        form.setObjectName("Panel")
        fl = QVBoxLayout(form)
        self.provider = QComboBox()
        for p in KEY_PROVIDER_ORDER:
            info = KEY_PROVIDER_INFO[p]
            self.provider.addItem(f"{info['icon']} {info['name']}", p)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.key_help = QLabel("")
        self.key_help.setObjectName("Muted")
        self.key_help.setWordWrap(True)
        self.key_label = QLineEdit()
        self.key_label.setPlaceholderText("Label (optional)")
        self.key_value = QLineEdit()
        self.key_value.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_value.setPlaceholderText("API key")
        show = QPushButton("Show")
        show.clicked.connect(self._toggle_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_value, 1)
        key_row.addWidget(show)
        self.custom_url = QLineEdit()
        self.custom_url.setPlaceholderText("Base URL (custom APIs — may include {id})")
        self.custom_header = QLineEdit()
        self.custom_header.setPlaceholderText("Auth header name")
        self.custom_prefix = QLineEdit()
        self.custom_prefix.setPlaceholderText("Prefix (e.g. Bearer )")
        self.custom_param = QLineEdit()
        self.custom_param.setPlaceholderText("ID query param if URL has no {id}")
        save_key = QPushButton("Save key")
        save_key.setObjectName("Primary")
        save_key.clicked.connect(self._save_key)
        fl.addWidget(self.provider)
        fl.addWidget(self.key_help)
        fl.addWidget(self.key_label)
        fl.addLayout(key_row)
        fl.addWidget(self.custom_url)
        fl.addWidget(self.custom_header)
        fl.addWidget(self.custom_prefix)
        fl.addWidget(self.custom_param)
        fl.addWidget(save_key)
        lay.addWidget(form)

        data_t = QLabel("Your data")
        data_t.setObjectName("CardTitle")
        path = QLabel(f"Feeds & articles: {storage.storage_path()}")
        path.setObjectName("Muted")
        path.setWordWrap(True)
        lay.addWidget(data_t)
        lay.addWidget(path)
        danger = QHBoxLayout()
        clear = QPushButton("Clear saved articles")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_saved)
        reset = QPushButton("Reset all data")
        reset.setObjectName("Danger")
        reset.clicked.connect(self._reset_all)
        danger.addWidget(clear)
        danger.addWidget(reset)
        danger.addStretch(1)
        lay.addLayout(danger)
        lay.addStretch(1)

        self._render_feeds()
        self._render_keys()
        self._provider_changed()

    def _page(self):
        return _news_page(self.manager)

    def _render_feeds(self):
        _clear(self.feed_host)
        feeds = storage.get_custom_feeds()
        if not feeds:
            empty = QLabel("No custom feeds yet.")
            empty.setObjectName("Muted")
            self.feed_host.addWidget(empty)
            return
        for feed in feeds:
            row = QHBoxLayout()
            lbl = QLabel(f"{feed['name']}  —  \"{feed['query']}\"")
            rm = QPushButton("Remove")
            rm.setObjectName("Danger")
            rm.clicked.connect(lambda _=False, n=feed["name"]: self._remove_feed(n))
            wrap = QWidget()
            row.addWidget(lbl, 1)
            row.addWidget(rm)
            wrap.setLayout(row)
            self.feed_host.addWidget(wrap)

    def _add_feed(self):
        name = self.feed_name.text().strip()
        query = self.feed_query.text().strip()
        if not name or not query:
            QMessageBox.warning(self, "Add feed", "Please enter both a feed name and keywords.")
            return
        storage.add_custom_feed(name, query)
        self.feed_name.clear()
        self.feed_query.clear()
        self._render_feeds()
        page = self._page()
        if page:
            page._reload_feed_picker()

    def _remove_feed(self, name):
        storage.remove_custom_feed(name)
        page = self._page()
        if page is not None and page._active_feed_name == name:
            page._active_feed_name = None
        self._render_feeds()
        if page:
            page._reload_feed_picker()

    def _save_country(self):
        value = self.country.text().strip().lower() or "us"
        self.settings = storage.update_setting("country", value)
        page = self._page()
        if page:
            page.settings = self.settings

    def _save_page_size(self):
        try:
            value = max(1, min(50, int(self.page_size.text().strip())))
        except ValueError:
            value = self.settings.get("page_size", 15)
        self.page_size.setText(str(value))
        self.settings = storage.update_setting("page_size", value)
        page = self._page()
        if page:
            page.settings = self.settings

    def _save_refresh(self):
        minutes = int(self.refresh.currentData() or 0)
        self.settings = storage.update_setting("refresh_interval_minutes", minutes)
        page = self._page()
        if page:
            page.settings = self.settings
            page._schedule_auto_refresh()

    def _toggle_key(self):
        self._key_visible = not getattr(self, "_key_visible", False)
        self.key_value.setEchoMode(
            QLineEdit.EchoMode.Normal if self._key_visible else QLineEdit.EchoMode.Password
        )

    def _provider_changed(self):
        provider = self.provider.currentData() or "fortnite"
        info = KEY_PROVIDER_INFO[provider]
        hint = info.get("key_help", "")
        if info.get("key_url"):
            hint += f"  ({info['key_url']})"
        self.key_help.setText(hint)
        extra = bool(info.get("needs_extra"))
        self.custom_url.setVisible(extra)
        self.custom_header.setVisible(extra)
        self.custom_prefix.setVisible(extra)
        self.custom_param.setVisible(extra)

    def _save_key(self):
        provider = self.provider.currentData() or "fortnite"
        extra = {}
        if KEY_PROVIDER_INFO[provider].get("needs_extra"):
            base_url = self.custom_url.text().strip()
            if not base_url:
                QMessageBox.warning(self, "Add API key", "Custom providers need a base URL.")
                return
            extra = {
                "base_url": base_url,
                "header_name": self.custom_header.text().strip(),
                "header_prefix": self.custom_prefix.text().strip(),
                "id_param": self.custom_param.text().strip(),
            }
        try:
            crypto_store.add_key(provider, self.key_label.text().strip(), self.key_value.text().strip(), extra=extra)
        except ValueError as exc:
            QMessageBox.warning(self, "Add API key", str(exc))
            return
        self.key_label.clear()
        self.key_value.clear()
        self.custom_url.clear()
        self.custom_header.clear()
        self.custom_prefix.clear()
        self.custom_param.clear()
        self._render_keys()
        page = self._page()
        if page:
            page._refresh_gs_keys()

    def _render_keys(self):
        _clear(self.keys_host)
        keys = crypto_store.list_keys()
        if not keys:
            empty = QLabel("No keys added yet.")
            empty.setObjectName("Muted")
            self.keys_host.addWidget(empty)
            return
        for k in keys:
            info = KEY_PROVIDER_INFO.get(k["provider"], {"icon": "🔑", "name": k["provider"]})
            card = QFrame()
            card.setObjectName("Panel")
            hl = QHBoxLayout(card)
            col = QVBoxLayout()
            name = QLabel(f"{info['icon']} {info['name']}  —  {k['label']}")
            name.setObjectName("CardTitle")
            preview = QLabel(k["preview"])
            preview.setObjectName("Muted")
            col.addWidget(name)
            col.addWidget(preview)
            hl.addLayout(col, 1)
            rm = QPushButton("Remove")
            rm.setObjectName("Danger")
            rm.clicked.connect(lambda _=False, kid=k["id"]: self._remove_key(kid))
            hl.addWidget(rm)
            self.keys_host.addWidget(card)

    def _remove_key(self, key_id):
        crypto_store.remove_key(key_id)
        self._render_keys()
        page = self._page()
        if page:
            page._refresh_gs_keys()

    def _clear_saved(self):
        page = self._page()
        if page is not None:
            page._clear_saved_confirm()
            return
        if not storage.get_saved_articles():
            return
        if QMessageBox.question(self, "Clear saved articles", "Remove all saved articles?") != QMessageBox.StandardButton.Yes:
            return
        storage.clear_saved_articles()

    def _reset_all(self):
        if QMessageBox.question(
            self, "Reset all data",
            "This will remove all custom feeds, saved articles, and preferences "
            "(API keys are stored separately and are not affected). Continue?",
        ) != QMessageBox.StandardButton.Yes:
            return
        storage.clear_all_data()
        self.settings = storage.get_settings()
        page = self._page()
        if page is not None:
            page.settings = self.settings
            page._active_feed_name = None
            page._reload_feed_picker()
            page._render_saved()
            page._schedule_auto_refresh()
        self._render_feeds()
        self.country.setText(self.settings.get("country", "us"))
        self.page_size.setText(str(self.settings.get("page_size", 15)))
        self.refresh.setCurrentIndex(0)
