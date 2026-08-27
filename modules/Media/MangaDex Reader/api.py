"""
Thin wrapper around the public MangaDex API (api.mangadex.org).
No auth required for search / feed / at-home endpoints used here.
"""
import threading
import time

import requests

API_BASE = "https://api.mangadex.org"
COVER_BASE = "https://uploads.mangadex.org/covers"

DEFAULT_RATINGS = ["safe", "suggestive", "erotica"]
ALL_RATINGS = ["safe", "suggestive", "erotica", "pornographic"]


class MangaDexError(Exception):
    pass


class MangaDexClient:
    """Session + simple rate limiter (MangaDex allows ~5 req/s globally)."""

    def __init__(self, min_interval=0.22):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MangaDexReader/1.0"})
        self._min_interval = min_interval
        self._last_call = 0.0
        self._lock = threading.Lock()

    def _throttle(self):
        with self._lock:
            wait = self._last_call + self._min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()

    def _get(self, path, params=None):
        self._throttle()
        resp = self.session.get(f"{API_BASE}{path}", params=params, timeout=20)
        if resp.status_code == 429:
            time.sleep(1.0)
            resp = self.session.get(f"{API_BASE}{path}", params=params, timeout=20)
        if not resp.ok:
            raise MangaDexError(f"{path} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    # ---------- search ----------

    def search_manga(self, title, limit=24, content_ratings=None):
        params = {
            "title": title,
            "limit": limit,
            "includes[]": ["cover_art"],
            "order[relevance]": "desc",
        }
        params["contentRating[]"] = content_ratings or DEFAULT_RATINGS
        data = self._get("/manga", params=params)
        return [self._parse_manga(m) for m in data.get("data", [])]

    BROWSE_SORTS = {
        "Popular": "followedCount",
        "Latest Updates": "latestUploadedChapter",
        "Recently Added": "createdAt",
        "Title (A-Z)": "title",
    }

    def browse_manga(self, sort="Popular", limit=24, offset=0, content_ratings=None):
        """List manga with no title filter, sorted by the given BROWSE_SORTS key."""
        order_field = self.BROWSE_SORTS.get(sort, "followedCount")
        params = {
            "limit": limit,
            "offset": offset,
            "includes[]": ["cover_art"],
            f"order[{order_field}]": "asc" if order_field == "title" else "desc",
        }
        params["contentRating[]"] = content_ratings or DEFAULT_RATINGS
        data = self._get("/manga", params=params)
        return [self._parse_manga(m) for m in data.get("data", [])], data.get("total", 0)

    def get_manga(self, manga_id):
        data = self._get(f"/manga/{manga_id}", params={"includes[]": ["cover_art"]})
        return self._parse_manga(data["data"])

    @staticmethod
    def _parse_manga(m):
        attrs = m.get("attributes", {})
        title_map = attrs.get("title", {}) or {}
        title = title_map.get("en") or next(iter(title_map.values()), "Untitled")
        alt_titles = attrs.get("altTitles", [])
        desc_map = attrs.get("description", {}) or {}
        description = desc_map.get("en") or next(iter(desc_map.values()), "")

        cover_file = None
        for rel in m.get("relationships", []):
            if rel.get("type") == "cover_art":
                cover_file = rel.get("attributes", {}).get("fileName")
                break

        manga_id = m["id"]
        cover_url = f"{COVER_BASE}/{manga_id}/{cover_file}" if cover_file else None
        cover_thumb_url = f"{COVER_BASE}/{manga_id}/{cover_file}.256.jpg" if cover_file else None

        return {
            "id": manga_id,
            "title": title,
            "alt_titles": alt_titles,
            "description": description,
            "status": attrs.get("status", "unknown"),
            "year": attrs.get("year"),
            "tags": [t["attributes"]["name"].get("en", "") for t in attrs.get("tags", [])],
            "available_languages": attrs.get("availableTranslatedLanguages", []),
            "content_rating": attrs.get("contentRating", "safe"),
            "cover_url": cover_url,
            "cover_thumb_url": cover_thumb_url,
        }

    # ---------- chapters ----------

    def get_chapters(self, manga_id, languages=None, content_ratings=None, progress_cb=None):
        """Returns full chapter list (handles pagination). languages=None -> all."""
        chapters = []
        offset = 0
        limit = 500
        total = None
        while total is None or offset < total:
            params = {
                "limit": limit,
                "offset": offset,
                "order[volume]": "asc",
                "order[chapter]": "asc",
                "includes[]": ["scanlation_group"],
                "contentRating[]": content_ratings or ALL_RATINGS,
            }
            if languages:
                params["translatedLanguage[]"] = languages
            data = self._get(f"/manga/{manga_id}/feed", params=params)
            total = data.get("total", 0)
            for c in data.get("data", []):
                chapters.append(self._parse_chapter(c))
            offset += limit
            if progress_cb:
                progress_cb(min(offset, total), total)
            if limit == 0:
                break
        return chapters

    @staticmethod
    def _parse_chapter(c):
        attrs = c.get("attributes", {})
        group_name = None
        for rel in c.get("relationships", []):
            if rel.get("type") == "scanlation_group":
                group_name = rel.get("attributes", {}).get("name")
                break
        return {
            "id": c["id"],
            "chapter": attrs.get("chapter"),
            "volume": attrs.get("volume"),
            "title": attrs.get("title") or "",
            "language": attrs.get("translatedLanguage"),
            "pages": attrs.get("pages", 0),
            "publish_at": attrs.get("publishAt"),
            "group": group_name or "Unknown group",
        }

    # ---------- page images ----------

    def get_page_urls(self, chapter_id, data_saver=False):
        data = self._get(f"/at-home/server/{chapter_id}")
        base = data["baseUrl"]
        chapter = data["chapter"]
        h = chapter["hash"]
        files = chapter["dataSaver"] if data_saver else chapter["data"]
        mode = "data-saver" if data_saver else "data"
        return [f"{base}/{mode}/{h}/{f}" for f in files]

    def report_at_home(self, url, success, bytes_len, duration_ms):
        # Best-effort feedback to the MD@Home network; failures are ignored.
        try:
            self.session.post(
                "https://api.mangadex.org/at-home/report",
                json={
                    "url": url,
                    "success": success,
                    "bytes": bytes_len,
                    "duration": duration_ms,
                },
                timeout=5,
            )
        except requests.RequestException:
            pass
