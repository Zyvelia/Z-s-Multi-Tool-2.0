# modules/Icon Favicon Generator/generator.py
#
# Turns one source image into a full favicon/app-icon set: a multi-size
# .ico, the standard PNG sizes browsers/OSes/PWAs look for, and a
# site.webmanifest tying the PNGs together. Pure Pillow - no extra
# dependency.

from __future__ import annotations

import os
import json

from PIL import Image

# (filename, pixel size)
PNG_TARGETS = [
    ("favicon-16x16.png", 16),
    ("favicon-32x32.png", 32),
    ("favicon-48x48.png", 48),
    ("favicon-96x96.png", 96),
    ("apple-touch-icon.png", 180),
    ("android-chrome-192x192.png", 192),
    ("android-chrome-512x512.png", 512),
]

ICO_SIZES = [16, 32, 48]

ICO_FILENAME = "favicon.ico"
MANIFEST_FILENAME = "site.webmanifest"


class IconGeneratorError(Exception):
    pass


def _prepare_square(img: Image.Image, size: int, mode: str) -> Image.Image:
    """
    Returns a size x size RGBA image.
      mode == "fit"  -> whole image visible, padded with transparency
      mode == "fill" -> image cropped to fill the square (center crop)
    """
    img = img.convert("RGBA")
    w, h = img.size

    if mode == "fill":
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        return img.resize((size, size), Image.LANCZOS)

    # fit: pad onto a transparent square canvas
    scale = size / max(w, h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(resized, ((size - new_w) // 2, (size - new_h) // 2), resized)
    return canvas


def generate(
    source_path: str,
    output_dir: str,
    fit_mode: str = "fit",
    make_png: bool = True,
    make_ico: bool = True,
    make_manifest: bool = True,
    app_name: str = "App",
    theme_color: str = "#151922",
    background_color: str = "#ffffff",
) -> list[str]:
    """
    Generates the requested files into output_dir. Returns the list of
    file paths written. Raises IconGeneratorError on any failure.
    """
    if fit_mode not in ("fit", "fill"):
        fit_mode = "fit"

    try:
        source = Image.open(source_path)
        source.load()
    except Exception as e:
        raise IconGeneratorError(f"Couldn't open source image: {e}") from e

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        raise IconGeneratorError(f"Couldn't create output folder: {e}") from e

    written: list[str] = []

    if make_png:
        for filename, size in PNG_TARGETS:
            try:
                square = _prepare_square(source, size, fit_mode)
                out_path = os.path.join(output_dir, filename)
                square.save(out_path, format="PNG")
                written.append(out_path)
            except Exception as e:
                raise IconGeneratorError(f"Failed generating {filename}: {e}") from e

    if make_ico:
        try:
            base = _prepare_square(source, max(ICO_SIZES), fit_mode)
            ico_path = os.path.join(output_dir, ICO_FILENAME)
            base.save(
                ico_path, format="ICO",
                sizes=[(s, s) for s in ICO_SIZES],
            )
            written.append(ico_path)
        except Exception as e:
            raise IconGeneratorError(f"Failed generating {ICO_FILENAME}: {e}") from e

    if make_manifest:
        try:
            manifest = {
                "name": app_name,
                "short_name": app_name,
                "icons": [
                    {"src": "android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"},
                ],
                "theme_color": theme_color,
                "background_color": background_color,
                "display": "standalone",
            }
            manifest_path = os.path.join(output_dir, MANIFEST_FILENAME)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            written.append(manifest_path)
        except Exception as e:
            raise IconGeneratorError(f"Failed generating {MANIFEST_FILENAME}: {e}") from e

    if not written:
        raise IconGeneratorError("Nothing was selected to generate.")

    return written


HTML_SNIPPET = """<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">"""
