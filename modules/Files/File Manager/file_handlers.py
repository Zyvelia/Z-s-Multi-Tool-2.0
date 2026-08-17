"""
file_handlers.py — Backend logic for image, audio, archive, and hex operations.
All heavy lifting lives here; editor widgets import from this module.
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import zipfile
import tarfile
from pathlib import Path
from typing import Optional, Generator


# ── Image ──────────────────────────────────────────────────

def pil_available() -> bool:
    try:
        import PIL
        return True
    except ImportError:
        return False


def open_image(path: str | Path):
    """Open image with Pillow. Returns PIL.Image or raises ImportError/OSError."""
    from PIL import Image
    return Image.open(str(path))


def image_to_photoimage(pil_img, tk_root=None):
    """Convert PIL Image to ImageTk.PhotoImage."""
    from PIL import ImageTk
    return ImageTk.PhotoImage(pil_img)


def rotate_image(pil_img, degrees: int):
    from PIL import Image
    return pil_img.rotate(-degrees, expand=True)


def flip_image(pil_img, horizontal: bool):
    from PIL import Image
    if horizontal:
        return pil_img.transpose(Image.FLIP_LEFT_RIGHT)
    return pil_img.transpose(Image.FLIP_TOP_BOTTOM)


def resize_image(pil_img, width: int, height: int):
    from PIL import Image
    return pil_img.resize((width, height), Image.LANCZOS)


def convert_image(pil_img, fmt: str, dest_path: str | Path):
    """Save image in a different format."""
    pil_img.save(str(dest_path), fmt.upper())


def image_metadata(pil_img) -> dict:
    """Extract basic metadata from a PIL image."""
    info = {
        "Mode":   pil_img.mode,
        "Size":   f"{pil_img.width} × {pil_img.height} px",
        "Format": pil_img.format or "unknown",
    }
    exif_data = getattr(pil_img, "_getexif", None)
    if exif_data:
        try:
            from PIL.ExifTags import TAGS
            raw = exif_data()
            if raw:
                for tag_id, val in list(raw.items())[:8]:
                    tag = TAGS.get(tag_id, str(tag_id))
                    info[tag] = str(val)[:80]
        except Exception:
            pass
    return info


# ── Audio ──────────────────────────────────────────────────

def mutagen_available() -> bool:
    try:
        import mutagen
        return True
    except ImportError:
        return False


def pygame_available() -> bool:
    try:
        import pygame
        return True
    except ImportError:
        return False


def audio_metadata(path: str | Path) -> dict:
    """Extract audio metadata using mutagen."""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(str(path), easy=True)
        if f is None:
            return {}
        meta: dict = {}
        for key in ("title", "artist", "album", "date", "tracknumber", "genre"):
            val = f.get(key)
            if val:
                meta[key.capitalize()] = str(val[0]) if isinstance(val, list) else str(val)
        info = getattr(f, "info", None)
        if info:
            dur = getattr(info, "length", None)
            if dur:
                m, s = divmod(int(dur), 60)
                meta["Duration"] = f"{m}:{s:02d}"
            br = getattr(info, "bitrate", None)
            if br:
                meta["Bitrate"] = f"{br // 1000} kbps"
        return meta
    except Exception:
        return {}


# Tag keys accepted by save_audio_metadata, in the order the editor UI
# should present them.
EDITABLE_TAG_FIELDS = ["title", "artist", "album", "date", "tracknumber", "genre"]


def save_audio_metadata(path: str | Path, tags: dict) -> None:
    """
    Write tag values back to the audio file using mutagen's "easy" tag
    interface, which normalizes the same key names (title/artist/album/
    date/tracknumber/genre) across MP3 (ID3), FLAC, OGG Vorbis, and
    M4A/MP4 — so the caller doesn't need format-specific logic.

    `tags` keys are matched case-insensitively against EDITABLE_TAG_FIELDS.
    A blank/whitespace-only value removes that tag instead of writing an
    empty string. Raises on failure (unsupported format, read-only file,
    etc.) — callers should catch and show the user what went wrong, since
    tag writing can fail for reasons outside their control (locked file,
    missing write permission, corrupt existing tag block).
    """
    from mutagen import File as MutagenFile

    f = MutagenFile(str(path), easy=True)
    if f is None:
        raise ValueError("Unrecognized or unsupported audio format")

    if f.tags is None:
        f.add_tags()

    for key, value in tags.items():
        key = key.strip().lower()
        if key not in EDITABLE_TAG_FIELDS:
            continue
        value = (value or "").strip()
        if not value:
            if key in f.tags:
                del f.tags[key]
            continue
        f.tags[key] = value

    f.save()


def audio_artwork(path: str | Path) -> Optional[bytes]:
    """Try to extract embedded album artwork bytes."""
    try:
        from mutagen.id3 import ID3
        tags = ID3(str(path))
        for key in tags.keys():
            if key.startswith("APIC"):
                return tags[key].data
    except Exception:
        pass
    try:
        from mutagen.mp4 import MP4
        tags = MP4(str(path))
        covers = tags.get("covr")
        if covers:
            return bytes(covers[0])
    except Exception:
        pass
    try:
        from mutagen.flac import FLAC
        tags = FLAC(str(path))
        if tags.pictures:
            return tags.pictures[0].data
    except Exception:
        pass
    return None


ARTWORK_SUPPORTED_SUFFIXES = (".mp3", ".m4a", ".mp4", ".m4b", ".flac")


def save_audio_artwork(path: str | Path, image_bytes: bytes, mime: str = "image/jpeg") -> None:
    """
    Embeds cover art into the audio file, replacing any existing artwork.
    Supports the same formats audio_artwork() can read back:
        - MP3   -> ID3 APIC frame
        - M4A/MP4/M4B -> MP4 'covr' atom
        - FLAC  -> Picture block

    Raises ValueError for any other format, so the caller can tell the
    user artwork editing isn't supported here rather than silently no-op.
    """
    suffix = Path(path).suffix.lower()

    if suffix == ".mp3":
        from mutagen.id3 import ID3, APIC, ID3NoHeaderError
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")  # drop existing art so we don't accumulate duplicates
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=image_bytes))
        tags.save(str(path))
        return

    if suffix in (".m4a", ".mp4", ".m4b"):
        from mutagen.mp4 import MP4, MP4Cover
        tags = MP4(str(path))
        fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        tags["covr"] = [MP4Cover(image_bytes, imageformat=fmt)]
        tags.save()
        return

    if suffix == ".flac":
        from mutagen.flac import FLAC, Picture
        tags = FLAC(str(path))
        pic = Picture()
        pic.data = image_bytes
        pic.type = 3  # "front cover" per ID3/FLAC picture-type convention
        pic.mime = mime
        tags.clear_pictures()
        tags.add_picture(pic)
        tags.save()
        return

    raise ValueError(f"Artwork editing isn't supported for {suffix} files")


# ── Archive ────────────────────────────────────────────────

class ArchiveEntry:
    """Unified entry for ZIP / TAR archive members."""
    __slots__ = ("name", "size", "compressed_size", "is_dir", "modified")

    def __init__(self, name: str, size: int, compressed_size: int,
                 is_dir: bool, modified: str):
        self.name            = name
        self.size            = size
        self.compressed_size = compressed_size
        self.is_dir          = is_dir
        self.modified        = modified


def list_archive(path: str | Path) -> list[ArchiveEntry]:
    """List all entries in a ZIP or TAR archive."""
    path = Path(path)
    entries: list[ArchiveEntry] = []

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                entries.append(ArchiveEntry(
                    name=info.filename,
                    size=info.file_size,
                    compressed_size=info.compress_size,
                    is_dir=info.filename.endswith("/"),
                    modified=str(info.date_time),
                ))
        return entries

    if tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                entries.append(ArchiveEntry(
                    name=member.name,
                    size=member.size,
                    compressed_size=member.size,
                    is_dir=member.isdir(),
                    modified=str(member.mtime),
                ))
        return entries

    return []


def extract_archive(archive_path: str | Path, dest_dir: str | Path,
                    members: Optional[list[str]] = None):
    """Extract all or selected members from an archive."""
    archive_path = Path(archive_path)
    dest_dir     = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path, "r") as zf:
            if members:
                for m in members:
                    zf.extract(m, dest_dir)
            else:
                zf.extractall(dest_dir)
        return

    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path, "r:*") as tf:
            if members:
                for m in members:
                    tf.extract(m, dest_dir)
            else:
                tf.extractall(dest_dir)


def add_to_zip(archive_path: str | Path, files: list[str | Path]):
    """Add files to an existing or new ZIP archive."""
    with zipfile.ZipFile(archive_path, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, Path(f).name)


def create_zip(archive_path: str | Path, files: list[str | Path]):
    """Create a new ZIP archive from a list of files."""
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, Path(f).name)


# ── Hex ────────────────────────────────────────────────────

CHUNK_SIZE = 16   # bytes per hex row


def read_hex_chunk(path: str | Path, offset: int, length: int) -> bytes:
    """Read a chunk of bytes from a file at a given offset."""
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read(length)


def format_hex_row(offset: int, data: bytes) -> tuple[str, str, str]:
    """
    Format one row of a hex dump.
    Returns (offset_str, hex_str, ascii_str)
    """
    offset_str = f"{offset:08X}"
    hex_parts  = [f"{b:02X}" for b in data]
    # pad to 16 bytes
    while len(hex_parts) < CHUNK_SIZE:
        hex_parts.append("  ")
    hex_str   = " ".join(hex_parts[:8]) + "  " + " ".join(hex_parts[8:])
    ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return offset_str, hex_str, ascii_str


def hex_rows(path: str | Path, start: int = 0,
             n_rows: int = 512) -> Generator[tuple[str, str, str], None, None]:
    """Yield (offset, hex, ascii) rows from a file."""
    with open(path, "rb") as f:
        f.seek(start)
        offset = start
        for _ in range(n_rows):
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            yield format_hex_row(offset, chunk)
            offset += len(chunk)


def patch_bytes(path: str | Path, offset: int, new_bytes: bytes):
    """Write bytes at a given offset without touching the rest of the file."""
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(new_bytes)
