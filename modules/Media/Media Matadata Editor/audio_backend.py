# modules/metadata_editor/audio_backend.py
#
# Shared mutagen wrappers for reading/writing audio tags + cover art.
# Used by both audio_tab.py (single file) and multi_audio_window.py
# (batch popout) so the tag/cover logic only lives in one place.

import os

try:
    from mutagen import File as MutagenFile
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, APIC, COMM, USLT, ID3NoHeaderError
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".wav")

# Every field here shows up as an editable row in the Audio Tags tab
# (and, minus title/tracknumber, in the batch editor). Not every field
# is supported by every file type -- MP4/M4A only has real atoms for a
# subset of these, so fields with no MP4 mapping below just won't do
# anything on .m4a/.mp4 files (silently skipped, same as before).
TAG_FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("composer", "Composer"),
    ("genre", "Genre"),
    ("date", "Year / Date"),
    ("tracknumber", "Track #"),
    ("discnumber", "Disc #"),
    ("bpm", "BPM"),
    ("comment", "Comment"),
    ("lyrics", "Lyrics"),
    ("grouping", "Grouping"),
    ("copyright", "Copyright"),
    ("conductor", "Conductor"),
    ("lyricist", "Lyricist"),
    ("organization", "Publisher / Label"),
    ("isrc", "ISRC"),
    ("encodedby", "Encoded By"),
    ("compilation", "Compilation (1/0)"),
]

# MP4/M4A atom codes for fields that have a real iTunes-style tag.
# Fields not listed here (conductor, lyricist, organization, isrc)
# have no standard MP4 atom, so they're simply not editable on
# .m4a/.mp4 files -- get_native_key returns None for them and the
# read/write helpers below no-op accordingly.
NATIVE_KEY_MAP = {
    "mp4": {
        "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
        "albumartist": "aART", "composer": "\xa9wrt", "genre": "\xa9gen",
        "date": "\xa9day", "tracknumber": "trkn", "discnumber": "disk",
        "bpm": "tmpo", "comment": "\xa9cmt", "lyrics": "\xa9lyr",
        "grouping": "\xa9grp", "copyright": "cprt", "encodedby": "\xa9too",
        "compilation": "cpil",
    },
}

# MP4 atoms that hold an (number, total) pair rather than plain text.
MP4_TUPLE_KEYS = {"trkn", "disk"}
# MP4 atoms that hold a single integer.
MP4_INT_KEYS = {"tmpo"}
# MP4 atoms that hold a plain boolean.
MP4_BOOL_KEYS = {"cpil"}


def _register_easyid3_extras():
    """EasyID3 doesn't ship keys for Comment (COMM) or Lyrics (USLT)
    out of the box -- both frames carry a language + description on
    top of the text, so mutagen leaves mapping them up to the caller.
    Register simple 'default' variants (lang='eng', desc='') so they
    behave like any other single-value text field in this app."""

    def _comment_get(id3, key):
        frames = id3.getall("COMM")
        if not frames:
            return None
        for f in frames:
            if f.desc == "":
                return list(f.text)
        return list(frames[0].text)

    def _comment_set(id3, key, value):
        id3.delall("COMM")
        id3.add(COMM(encoding=3, lang="eng", desc="", text=value))

    def _comment_delete(id3, key):
        id3.delall("COMM")

    def _lyrics_get(id3, key):
        frames = id3.getall("USLT")
        if not frames:
            return None
        for f in frames:
            if f.desc == "":
                return [f.text]
        return [frames[0].text]

    def _lyrics_set(id3, key, value):
        id3.delall("USLT")
        text = value[0] if isinstance(value, list) else value
        id3.add(USLT(encoding=3, lang="eng", desc="", text=text))

    def _lyrics_delete(id3, key):
        id3.delall("USLT")

    EasyID3.RegisterKey("comment", _comment_get, _comment_set, _comment_delete)
    EasyID3.RegisterKey("lyrics", _lyrics_get, _lyrics_set, _lyrics_delete)


if MUTAGEN_AVAILABLE:
    _register_easyid3_extras()


def get_native_key(kind, key):
    if kind == "mp4":
        return NATIVE_KEY_MAP["mp4"].get(key)
    if kind == "flac":
        # FLAC/Vorbis comments accept arbitrary field names, so any key
        # not given a special mapping just passes through as-is.
        return key
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
    if value in (None, [], ""):
        return ""

    if kind == "mp4":
        if native_key in MP4_TUPLE_KEYS:
            pair = value[0] if value else None
            if not pair:
                return ""
            num, total = pair
            return f"{num}/{total}" if total else str(num)
        if native_key in MP4_INT_KEYS:
            return str(value[0]) if value else ""
        if native_key in MP4_BOOL_KEYS:
            return "1" if value else "0"

    return str(value[0]) if isinstance(value, list) else str(value)


def set_field_value(audio_obj, kind, key, value):
    """value == "" deletes the tag; otherwise sets it."""
    native_key = get_native_key(kind, key)
    if not native_key:
        return

    if kind == "mp4":
        if native_key in MP4_TUPLE_KEYS:
            if value:
                try:
                    if "/" in value:
                        num_s, tot_s = value.split("/", 1)
                        num, total = int(num_s.strip()), int(tot_s.strip() or 0)
                    else:
                        num, total = int(value.strip()), 0
                    audio_obj[native_key] = [(num, total)]
                except ValueError:
                    pass
            elif native_key in audio_obj:
                del audio_obj[native_key]
            return
        if native_key in MP4_INT_KEYS:
            if value:
                try:
                    audio_obj[native_key] = [int(value.strip())]
                except ValueError:
                    pass
            elif native_key in audio_obj:
                del audio_obj[native_key]
            return
        if native_key in MP4_BOOL_KEYS:
            if value:
                audio_obj[native_key] = value.strip() not in ("0", "false", "no")
            elif native_key in audio_obj:
                del audio_obj[native_key]
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
