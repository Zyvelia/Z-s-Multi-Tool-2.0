# modules/Image Palette Extractor/palette_math.py
#
# Dominant-color extraction from an arbitrary image. Downscales first
# (extracting from a 200px-wide thumbnail is visually identical to the
# full image for this purpose and orders of magnitude faster), then
# uses Pillow's built-in median-cut quantizer with a k-means refinement
# pass to bucket every pixel into N representative colors. No extra
# dependency beyond Pillow, already used elsewhere in this app.

from __future__ import annotations

from PIL import Image

THUMBNAIL_MAX = 200


class PaletteError(Exception):
    pass


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def readable_text_color(r: int, g: int, b: int) -> str:
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


def extract_palette(image_path: str, n_colors: int = 6) -> list[dict]:
    """
    Returns a list of {"hex": "#rrggbb", "rgb": (r,g,b), "percent": float}
    dicts, sorted by how much of the image each color covers (largest
    first). Raises PaletteError if the file can't be read as an image.
    """
    n_colors = max(2, min(16, n_colors))

    try:
        img = Image.open(image_path)
        img = img.convert("RGB")
    except Exception as e:
        raise PaletteError(f"Couldn't open that as an image: {e}") from e

    small = img.copy()
    small.thumbnail((THUMBNAIL_MAX, THUMBNAIL_MAX))

    try:
        quantized = small.quantize(colors=n_colors, method=Image.MEDIANCUT, kmeans=n_colors)
    except Exception as e:
        raise PaletteError(f"Couldn't extract colors from this image: {e}") from e

    palette_raw = quantized.getpalette() or []
    counts = quantized.getcolors() or []  # [(count, palette_index), ...]
    total_pixels = sum(c for c, _ in counts) or 1

    counts.sort(key=lambda c: c[0], reverse=True)

    results = []
    for count, idx in counts:
        offset = idx * 3
        if offset + 2 >= len(palette_raw):
            continue
        r, g, b = palette_raw[offset], palette_raw[offset + 1], palette_raw[offset + 2]
        results.append({
            "hex": rgb_to_hex(r, g, b),
            "rgb": (r, g, b),
            "percent": round(100 * count / total_pixels, 1),
        })

    return results
