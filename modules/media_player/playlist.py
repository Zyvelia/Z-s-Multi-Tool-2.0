# music_player/playlist.py
#
# Parsers for the common "playlist file" formats — M3U/M3U8, PLS, and
# XSPF. Unlike a .cue sheet (which describes track boundaries *inside*
# one audio file), these just list paths/URLs to other, already-whole
# audio files, in order.
#
# Each parser is lenient and never raises: a malformed or partially
# unreadable playlist just yields whatever entries it could make sense
# of (possibly an empty list), mirroring the style of cue.py. Paths are
# resolved relative to the playlist file's own directory, since that's
# how virtually every playlist in the wild is written (e.g. exported
# from iTunes/foobar2000/VLC alongside a music folder). Entries that
# turn out to be remote URLs (http/https) are kept as-is; local entries
# that don't resolve to an existing file on disk are dropped, since
# nothing downstream can play a path that isn't there.

import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote


def _is_url(s):
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s))


def _read_text_lenient(path):
    """
    Read a playlist file's text, tolerating whatever encoding it was
    actually saved in. Exported playlists are all over the map in
    practice: UTF-8 with/without a BOM (most m3u8), UTF-16 with a BOM
    (common for .m3u saved by Windows Media Player/foobar2000), or
    plain Latin-1/CP1252 for older ASCII-range .m3u files. Detect the
    BOM if there is one; otherwise try UTF-8 and fall back to CP1252,
    which never fails to decode. Never raises.
    """
    with open(path, "rb") as f:
        raw = f.read()

    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _resolve_local(raw, base_dir):
    """
    Turn one playlist entry into an absolute, existing local path, or
    None if it can't be resolved to a file that's actually there.
    """
    raw = raw.strip()
    if not raw:
        return None
    if _is_url(raw):
        # file:// URLs are local; anything else (http, https, etc.) is
        # a streaming entry we pass through unchanged.
        parsed = urlparse(raw)
        if parsed.scheme != "file":
            return raw
        raw = unquote(parsed.path)

    # Playlists frequently use Windows-style backslashes even on
    # non-Windows exports (foobar2000, etc.) — normalize before joining.
    normalized = raw.replace("\\", os.sep).replace("/", os.sep)
    candidate = normalized if os.path.isabs(normalized) else os.path.join(base_dir, normalized)
    candidate = os.path.normpath(candidate)
    if os.path.isfile(candidate):
        return candidate

    # Playlists are often written on one machine (or with a different
    # drive letter/mount point) and then moved alongside the actual
    # audio files on another. If the literal path doesn't exist, fall
    # back to just the filename sitting next to the playlist itself —
    # this is by far the most common reason a playlist "doesn't work"
    # after being copied/dropped somewhere else.
    fallback = os.path.normpath(os.path.join(base_dir, os.path.basename(normalized)))
    return fallback if os.path.isfile(fallback) else None


def parse_m3u(path):
    """
    Parse an .m3u/.m3u8 playlist. Returns (resolved, total) where
    `resolved` is an ordered list of local paths (plus any pass-through
    remote URLs) and `total` is how many non-comment entries the file
    actually listed (so a caller can tell "empty playlist" apart from
    "every entry failed to resolve"). Returns ([], 0) on read failure.
    """
    base_dir = os.path.dirname(os.path.abspath(path))
    try:
        text = _read_text_lenient(path)
    except OSError:
        return [], 0

    out = []
    total = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        total += 1
        resolved = _resolve_local(line, base_dir)
        if resolved:
            out.append(resolved)
    return out, total


def parse_pls(path):
    """
    Parse a .pls playlist (simple INI format: FileN=..., TitleN=...,
    NumberOfEntries=...). Returns (resolved, total), same rules as
    parse_m3u. Returns ([], 0) on read failure.
    """
    base_dir = os.path.dirname(os.path.abspath(path))
    try:
        text = _read_text_lenient(path)
    except OSError:
        return [], 0

    entries = {}
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"(?i)^File(\d+)\s*=\s*(.+)$", line)
        if m:
            entries[int(m.group(1))] = m.group(2).strip()

    out = []
    for idx in sorted(entries):
        resolved = _resolve_local(entries[idx], base_dir)
        if resolved:
            out.append(resolved)
    return out, len(entries)


def parse_xspf(path):
    """
    Parse an .xspf playlist (XML "XML Shareable Playlist Format").
    Reads each <track><location>...</location></track> entry, in
    document order. Returns (resolved, total). Returns ([], 0) on any
    read/parse failure.
    """
    base_dir = os.path.dirname(os.path.abspath(path))
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return [], 0

    root = tree.getroot()
    out = []
    total = 0
    # Namespace-agnostic: match any tag named "location" regardless of
    # the XSPF namespace URI some exporters do/don't include.
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1].lower() != "location":
            continue
        if elem.text and elem.text.strip():
            total += 1
            resolved = _resolve_local(elem.text, base_dir)
            if resolved:
                out.append(resolved)
    return out, total


_PARSERS = {
    ".m3u": parse_m3u,
    ".m3u8": parse_m3u,
    ".pls": parse_pls,
    ".xspf": parse_xspf,
}


def parse_playlist_report(path):
    """
    Dispatches to the right parser based on file extension. Returns
    (resolved, total) — see the individual parsers. (0, 0)-equivalent
    ([], 0) for an unrecognized extension.
    """
    ext = os.path.splitext(path)[1].lower()
    parser = _PARSERS.get(ext)
    return parser(path) if parser else ([], 0)


def parse_playlist(path):
    """
    Dispatches to the right parser based on file extension. Returns an
    ordered list of resolved track paths/URLs, or [] for an unrecognized
    extension, unreadable file, or empty/malformed playlist.
    """
    return parse_playlist_report(path)[0]
