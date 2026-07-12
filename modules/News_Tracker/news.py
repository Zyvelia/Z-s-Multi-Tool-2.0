"""
news.py
Headline fetching helper.

Primary source: Google News RSS (https://news.google.com/rss) — real, live
headlines, no API key required. This mirrors the "no key needed" approach
used for weather.py (Open-Meteo).

Optional source: NewsAPI (https://newsapi.org) — used automatically instead
of Google News RSS if a NEWSAPI_KEY environment variable is set.

If both sources fail (e.g. no internet access), a small offline notice is
returned instead of raising, so the UI always has something to display.
"""

import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"
GOOGLE_NEWS_TOP_URL = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
GOOGLE_NEWS_SEARCH_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

CACHE_TTL_SECONDS = 180  # 3 minutes
REQUEST_TIMEOUT = 8

_cache = {"key": None, "timestamp": 0, "data": None}

OFFLINE_NOTICE = [
    {"title": "Unable to reach any news source right now. Check your internet connection and refresh.",
     "source": "Offline", "url": ""},
]


class NewsError(Exception):
    """Raised when headlines cannot be retrieved from any source."""


def _get_api_key():
    return os.environ.get("NEWSAPI_KEY", "").strip()


def _fetch_from_newsapi(query, country, page_size):
    api_key = _get_api_key()
    if not api_key:
        return None

    params = {"apiKey": api_key, "pageSize": page_size}
    if query:
        params["q"] = query
    else:
        params["country"] = country

    try:
        resp = requests.get(NEWSAPI_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        articles = payload.get("articles", [])
        return [
            {
                "title": a.get("title") or "(untitled)",
                "source": (a.get("source") or {}).get("name", "Unknown"),
                "url": a.get("url", ""),
            }
            for a in articles
        ]
    except (requests.RequestException, ValueError):
        return None


def _fetch_from_google_news(query, page_size):
    url = GOOGLE_NEWS_SEARCH_URL.format(query=quote(query)) if query else GOOGLE_NEWS_TOP_URL

    try:
        resp = requests.get(
            url, timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (WeatherNewsTracker/1.0)"}
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError):
        return None

    headlines = []
    for item in root.findall(".//item")[:page_size]:
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")

        if source_el is not None and source_el.text:
            source_name = source_el.text.strip()
            title = raw_title
        elif " - " in raw_title:
            title, source_name = raw_title.rsplit(" - ", 1)
        else:
            title, source_name = raw_title, "Google News"

        if title:
            headlines.append({"title": title, "source": source_name, "url": link})

    return headlines or None


def get_headlines(query=None, country="us", page_size=15, use_cache=True):
    """
    Fetch top headlines, optionally filtered by a keyword query.

    Returns a list of dicts: [{"title": str, "source": str, "url": str}, ...]

    Order of attempts:
        1. NewsAPI, if NEWSAPI_KEY is set in the environment.
        2. Google News RSS (free, no key required) — the default path.
        3. Offline notice, if both network sources fail.
    """
    cache_key = f"{query}|{country}|{page_size}"
    now = time.time()
    if use_cache and _cache["key"] == cache_key and (now - _cache["timestamp"]) < CACHE_TTL_SECONDS:
        return _cache["data"]

    headlines = _fetch_from_newsapi(query, country, page_size)

    if headlines is None:
        headlines = _fetch_from_google_news(query, page_size)

    if headlines is None:
        headlines = list(OFFLINE_NOTICE)

    _cache["key"] = cache_key
    _cache["timestamp"] = now
    _cache["data"] = headlines

    return headlines
