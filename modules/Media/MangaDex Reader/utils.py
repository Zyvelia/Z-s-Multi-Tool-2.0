import os
import re
import tempfile
import zipfile

import requests

_INVALID = r'<>:"/\\|?*'
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


def sanitize(name: str, fallback="Untitled") -> str:
    if not name:
        return fallback
    cleaned = "".join(c for c in name if c not in _INVALID).strip(" .")
    return cleaned or fallback


def chapter_folder_name(chapter: dict) -> str:
    num = chapter.get("chapter") or "0"
    vol = chapter.get("volume")
    title = chapter.get("title") or ""
    prefix = f"Vol.{vol} " if vol else ""
    label = f"{prefix}Ch.{num}"
    if title:
        label += f" - {sanitize(title)}"
    return sanitize(label)


def pack_as_cbz(image_paths, dest_cbz_path):
    os.makedirs(os.path.dirname(dest_cbz_path), exist_ok=True)
    with zipfile.ZipFile(dest_cbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, p in enumerate(sorted(image_paths)):
            ext = os.path.splitext(p)[1]
            zf.write(p, arcname=f"{i + 1:03}{ext}")


def download_bytes(session: requests.Session, url: str, dest_path: str, timeout=30) -> int:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
    return len(resp.content)


def list_chapter_images(folder_path):
    """Sorted list of page image paths inside a downloaded chapter folder."""
    if not os.path.isdir(folder_path):
        return []
    names = [n for n in os.listdir(folder_path) if n.lower().endswith(_IMAGE_EXTS)]
    names.sort()
    return [os.path.join(folder_path, n) for n in names]


def extract_cbz(cbz_path):
    """Unpacks a downloaded .cbz to a temp dir and returns sorted page image paths."""
    if not os.path.isfile(cbz_path):
        return []
    out_dir = tempfile.mkdtemp(prefix="mangadex_reader_cbz_")
    with zipfile.ZipFile(cbz_path, "r") as zf:
        zf.extractall(out_dir)
    names = [n for n in os.listdir(out_dir) if n.lower().endswith(_IMAGE_EXTS)]
    names.sort()
    return [os.path.join(out_dir, n) for n in names]


class ThumbCache:
    """Disk-backed cache for cover thumbnails so re-searching a title is instant."""

    def __init__(self, cache_dir: str):
        self.dir = cache_dir
        os.makedirs(self.dir, exist_ok=True)

    def path_for(self, manga_id: str) -> str:
        return os.path.join(self.dir, f"{manga_id}.jpg")

    def get_or_fetch(self, session: requests.Session, manga_id: str, url: str):
        path = self.path_for(manga_id)
        if os.path.exists(path):
            return path
        if not url:
            return None
        try:
            download_bytes(session, url, path)
            return path
        except requests.RequestException:
            return None
