# music_player/cue.py
#
# Minimal .cue sheet parser. Cue sheets are the standard companion to a
# single-file album rip (classically APE+CUE, but also FLAC+CUE etc.) —
# one big audio file plus a text sheet describing where each track starts.
#
# Only the handful of commands we actually need are understood:
#   FILE "name.ape" WAVE
#   TRACK 01 AUDIO
#   TITLE "..."
#   PERFORMER "..."
#   INDEX 01 mm:ss:ff
# Anything else is ignored. Never raises — a malformed/unsupported cue
# sheet just yields an empty track list, so the referenced audio file
# falls back to being indexed as one normal whole-file track.

import os
import re

_TIME_RE = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})$")


def _parse_time(s):
    """mm:ss:ff (frames, 75/sec) -> seconds, or None if unparseable."""
    m = _TIME_RE.match(s.strip())
    if not m:
        return None
    mm, ss, ff = (int(x) for x in m.groups())
    return mm * 60 + ss + ff / 75.0


def _strip_quotes(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def parse_cue(cue_path):
    """
    Parse a .cue sheet. Returns a list of track dicts, in order:
        {"file": <filename referenced by FILE>, "track": int,
         "title": str|None, "performer": str|None, "album": str|None,
         "start": seconds (float)}
    Tracks with no resolvable INDEX 01 (or INDEX 00 as a fallback) are
    dropped. Returns [] on any read/parse failure — never raises.
    """
    tracks = []
    current_file = None
    current_track = None
    album_title = None
    album_performer = None

    try:
        # Cue sheets are frequently mislabeled Latin-1/CP1252 even when
        # they claim UTF-8 — be lenient rather than blow up on a scan.
        with open(cue_path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()

        if upper.startswith("FILE "):
            rest = line[5:].strip()
            # FILE "name.ape" WAVE  (quotes are the common case, but be
            # tolerant of unquoted filenames too)
            if '"' in rest:
                parts = rest.split('"')
                current_file = parts[1] if len(parts) >= 2 else None
            else:
                current_file = rest.split()[0] if rest.split() else None

        elif upper.startswith("PERFORMER "):
            val = _strip_quotes(line[10:])
            if current_track is not None:
                current_track["performer"] = val
            else:
                album_performer = val

        elif upper.startswith("TITLE "):
            val = _strip_quotes(line[6:])
            if current_track is not None:
                current_track["title"] = val
            else:
                album_title = val

        elif upper.startswith("TRACK "):
            parts = line.split()
            current_track = None
            if len(parts) >= 3 and parts[2].upper() == "AUDIO":
                try:
                    num = int(parts[1])
                except ValueError:
                    continue
                current_track = {
                    "file": current_file, "track": num,
                    "title": None, "performer": album_performer,
                    "album": album_title, "start": None,
                }
                tracks.append(current_track)
            # else: non-audio track (e.g. DATA) — ignored

        elif upper.startswith("INDEX ") and current_track is not None:
            parts = line.split()
            if len(parts) >= 3:
                idx_num, t_str = parts[1], parts[2]
                t = _parse_time(t_str)
                if t is None:
                    continue
                # INDEX 01 is the real track start; only use INDEX 00
                # (pre-gap) as a fallback if 01 never shows up.
                if idx_num == "01":
                    current_track["start"] = t
                elif current_track["start"] is None:
                    current_track["start"] = t

    return [t for t in tracks if t["file"] and t["start"] is not None]


def windows_for_file_tracks(file_tracks, file_duration):
    """
    Given tracks that all reference the same audio file (list of dicts
    with a "start" key) plus that file's total duration (seconds, or
    None if unknown), returns [(track_dict, start, end), ...] where end
    is the next track's start, or file_duration (may be None) for the
    last track.
    """
    ordered = sorted(file_tracks, key=lambda t: t["start"])
    out = []
    for i, t in enumerate(ordered):
        start = t["start"]
        end = ordered[i + 1]["start"] if i + 1 < len(ordered) else file_duration
        out.append((t, start, end))
    return out
