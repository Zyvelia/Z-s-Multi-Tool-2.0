"""CTk-free EXIF helpers for JPEG/PNG/TIFF via Pillow."""

from __future__ import annotations

from PIL import Image

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")

EXIF_FIELDS = [
    (0x010E, "ImageDescription"),
    (0x013B, "Artist"),
    (0x8298, "Copyright"),
    (0x010F, "Make"),
    (0x0110, "Model"),
    (0x0131, "Software"),
    (0x0132, "DateTime"),
]


def read_exif(path: str) -> dict:
    values = {}
    with Image.open(path) as img:
        exif = img.getexif()
        for tag_id, _label in EXIF_FIELDS:
            value = exif.get(tag_id)
            if value:
                values[tag_id] = str(value)
    return values


def write_exif(path: str, fields: dict) -> None:
    img = Image.open(path)
    exif = img.getexif()
    for tag_id, value in fields.items():
        text = (value or "").strip()
        if text:
            exif[tag_id] = text
        elif tag_id in exif:
            del exif[tag_id]
    img.save(path, exif=exif.tobytes())


def strip_exif(path: str) -> None:
    img = Image.open(path)
    img.save(path, exif=b"")
