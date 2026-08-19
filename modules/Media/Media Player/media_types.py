# music_player/media_types.py
#
# Single source of truth for which files the library indexes and VLC can play.
# The music engine runs with --no-video, so video files play their audio track.

from __future__ import annotations

import os

AUDIO_EXTS = (
    ".mp3", ".flac", ".wav", ".wave", ".ogg", ".oga", ".m4a", ".aac",
    ".wma", ".opus", ".aiff", ".aif", ".aifc", ".ape", ".wv",
    ".mp4", ".m4b", ".m4p", ".m4r", ".mka", ".webm", ".3gp", ".3g2",
    ".mpc", ".mp2", ".mp1", ".tta", ".dsf", ".dff", ".caf", ".w64",
    ".amr", ".ac3", ".dts", ".spx", ".voc", ".au", ".snd", ".gsm",
    ".mid", ".midi", ".xm", ".mod", ".s3m", ".it",
    ".ra", ".ram", ".shn", ".tak", ".aa", ".aax",
)

VIDEO_EXTS = (
    ".mkv", ".avi", ".mov", ".wmv", ".flv", ".f4v", ".m4v",
    ".mpg", ".mpeg", ".m2v", ".vob", ".ts", ".mts", ".m2ts",
    ".divx", ".asf", ".rm", ".rmvb", ".ogv", ".dv", ".wtv",
    ".mxf", ".gxf", ".nsv", ".dat", ".swf", ".f4p", ".m2p",
    ".m2t", ".tp", ".trp", ".mpg2", ".hdmov",
)

PLAYLIST_EXTS = (".m3u", ".m3u8", ".pls", ".xspf")
CUE_EXTS = (".cue",)


def _dedupe_exts(*groups) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for ext in group:
            if ext not in seen:
                seen.add(ext)
                out.append(ext)
    return tuple(out)


MEDIA_EXTS = _dedupe_exts(AUDIO_EXTS, VIDEO_EXTS)
LIBRARY_EXTS = MEDIA_EXTS  # indexed by the library scanner


def path_ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_audio_path(path: str) -> bool:
    return path_ext(path) in AUDIO_EXTS


def is_video_path(path: str) -> bool:
    return path_ext(path) in VIDEO_EXTS


def is_media_path(path: str) -> bool:
    return path_ext(path) in MEDIA_EXTS


def is_playlist_path(path: str) -> bool:
    return path_ext(path) in PLAYLIST_EXTS


def is_cue_path(path: str) -> bool:
    return path_ext(path) in CUE_EXTS


def is_library_media_path(path: str) -> bool:
    """True for audio/video indexed in the library (not playlists)."""
    return is_media_path(path)


def glob_pattern(exts=LIBRARY_EXTS) -> str:
    """Space-separated `*.ext` pattern for Tk file dialogs."""
    return " ".join(f"*{ext}" for ext in exts)


def file_dialog_media_types():
    """File-dialog tuples: (label, pattern)."""
    media = glob_pattern(MEDIA_EXTS)
    audio = glob_pattern(AUDIO_EXTS)
    video = glob_pattern(VIDEO_EXTS)
    playlists = glob_pattern(PLAYLIST_EXTS)
    return [
        ("All Media + Playlists", f"{media} {playlists}"),
        ("All Media (audio + video)", media),
        ("Audio Files", audio),
        ("Video Files", video),
        ("Playlist Files", playlists),
        ("All Files", "*.*"),
    ]


def file_dialog_video_types():
    return [
        ("All Media Files", glob_pattern(MEDIA_EXTS)),
        ("Video Files", glob_pattern(VIDEO_EXTS)),
        ("Audio Files", glob_pattern(AUDIO_EXTS)),
        ("All Files", "*.*"),
    ]
