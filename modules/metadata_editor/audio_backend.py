# modules/metadata_editor/audio_backend.py
#
# Shared mutagen wrappers for reading/writing audio tags + cover art.
# Used by both audio_tab.py (single file) and multi_audio_window.py
# (batch popout) so the tag/cover logic only lives in one place.

import os

try:
    from mutagen import File as MutagenFile
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".wav")

TAG_FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("date", "Year"),
    ("genre", "Genre"),
    ("tracknumber", "Track #"),
    ("comment", "Comment"),
]

NATIVE_KEY_MAP = {
    "flac": {
        "title": "title", "artist": "artist", "album": "album",
        "albumartist": "albumartist", "date": "date", "genre": "genre",
        "tracknumber": "tracknumber", "comment": "comment",
    },
    "mp4": {
        "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
        "albumartist": "aART", "date": "\xa9day", "genre": "\xa9gen",
        "tracknumber": "trkn", "comment": "\xa9cmt",
    },
}


def get_native_key(kind, key):
    if kind in ("flac", "mp4"):
        return NATIVE_KEY_MAP[kind].get(key)
    return key


def load_audio(path):
    """Returns (audio_obj, kind). Raises on failure or unsupported type."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in AUDIO_EXTS:
        raise ValueError(f"Unsupported file type: {ext}")

    if ext == ".mp3":
        try:
            tags = EasyID3(path)
        except ID3NoHeaderError:
            audio = MP3(path)
            audio.add_tags()
            audio.save()
            tags = EasyID3(path)
        return tags, "mp3"
    elif ext == ".flac":
        return FLAC(path), "flac"
    elif ext in (".m4a", ".mp4"):
        return MP4(path), "mp4"
    else:
        return MutagenFile(path, easy=True), "generic"


def get_field_value(audio_obj, kind, key):
    native_key = get_native_key(kind, key)
    if not native_key:
        return ""
    try:
        value = audio_obj.get(native_key)
    except Exception:
        value = None
    if not value:
        return ""
    if kind == "mp4" and native_key == "trkn":
        return str(value[0][0]) if value and value[0] else ""
    return str(value[0]) if isinstance(value, list) else str(value)


def set_field_value(audio_obj, kind, key, value):
    """value == "" deletes the tag; otherwise sets it."""
    native_key = get_native_key(kind, key)
    if not native_key:
        return
    if kind == "mp4" and native_key == "trkn":
        if value:
            try:
                audio_obj[native_key] = [(int(value), 0)]
            except ValueError:
                pass
        return
    if value:
        audio_obj[native_key] = value
    elif native_key in audio_obj:
        del audio_obj[native_key]


def save_audio(audio_obj):
    audio_obj.save()


def extract_cover_bytes(path, kind, audio_obj):
    try:
        if kind == "mp3":
            id3 = ID3(path)
            for tag in id3.values():
                if isinstance(tag, APIC):
                    return tag.data
        elif kind == "flac":
            if audio_obj.pictures:
                return audio_obj.pictures[0].data
        elif kind == "mp4":
            covers = audio_obj.get("covr")
            if covers:
                return bytes(covers[0])
    except Exception:
        pass
    return None


def embed_cover(path, kind, image_path):
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    with open(image_path, "rb") as f:
        data = f.read()
    if kind == "mp3":
        id3 = ID3(path)
        id3.delall("APIC")
        id3.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        id3.save(path)
    elif kind == "flac":
        flac = FLAC(path)
        flac.clear_pictures()
        pic = Picture()
        pic.data = data
        pic.type = 3
        pic.mime = mime
        flac.add_picture(pic)
        flac.save()
    elif kind == "mp4":
        mp4 = MP4(path)
        fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        mp4["covr"] = [MP4Cover(data, imageformat=fmt)]
        mp4.save()


def strip_cover(path, kind):
    if kind == "mp3":
        id3 = ID3(path)
        id3.delall("APIC")
        id3.save(path)
    elif kind == "flac":
        flac = FLAC(path)
        flac.clear_pictures()
        flac.save()
    elif kind == "mp4":
        mp4 = MP4(path)
        if "covr" in mp4:
            del mp4["covr"]
        mp4.save()
