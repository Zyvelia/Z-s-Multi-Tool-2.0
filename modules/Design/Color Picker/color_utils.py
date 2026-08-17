# modules/color_picker/color_utils.py
#
# Color conversions and harmony/palette math. Pure stdlib (colorsys) — no
# new dependency needed for this module beyond Pillow, which is already
# used elsewhere in the app (for the eyedropper's screen capture).

from __future__ import annotations

import colorsys
import re

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


class InvalidColorError(ValueError):
    pass


def normalize_hex(value: str) -> str:
    """Validates and normalizes to '#rrggbb' (lowercase). Raises
    InvalidColorError with a UI-friendly message if it doesn't parse."""
    match = HEX_RE.match(value.strip())
    if not match:
        raise InvalidColorError("Hex color must look like #a1b2c3.")
    return "#" + match.group(1).lower()


def hex_to_rgb(hex_value: str) -> tuple[int, int, int]:
    h = normalize_hex(hex_value)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Returns (hue 0-360, saturation 0-100, value 0-100)."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return h * 360, s * 100, v * 100


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """h in 0-360, s/v in 0-100."""
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, max(0, min(100, s)) / 100, max(0, min(100, v)) / 100)
    return round(r * 255), round(g * 255), round(b * 255)


def readable_text_color(r: int, g: int, b: int) -> str:
    """Black or white text, whichever is more readable on this background
    (standard relative-luminance heuristic)."""
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


def _shift_hue(h: float, degrees: float) -> float:
    return (h + degrees) % 360


def harmony_palette(hex_value: str, scheme: str) -> list[str]:
    """Returns a list of hex colors (including the base color first,
    except for 'Shades'/'Tints' which build a ramp through it)."""
    r, g, b = hex_to_rgb(hex_value)
    h, s, v = rgb_to_hsv(r, g, b)

    if scheme == "Complementary":
        hues = [h, _shift_hue(h, 180)]
    elif scheme == "Analogous":
        hues = [_shift_hue(h, -30), h, _shift_hue(h, 30)]
    elif scheme == "Triadic":
        hues = [h, _shift_hue(h, 120), _shift_hue(h, 240)]
    elif scheme == "Split Complementary":
        hues = [h, _shift_hue(h, 150), _shift_hue(h, 210)]
    elif scheme == "Tetradic":
        hues = [h, _shift_hue(h, 90), _shift_hue(h, 180), _shift_hue(h, 270)]
    elif scheme == "Shades":
        # Same hue/sat, descending value — darker toward the end.
        steps = [1.0, 0.8, 0.6, 0.4, 0.2]
        return [rgb_to_hex(*hsv_to_rgb(h, s, v * step)) for step in steps]
    elif scheme == "Tints":
        # Same hue, descending saturation toward white — lighter toward
        # the end.
        steps = [1.0, 0.75, 0.5, 0.25, 0.08]
        return [rgb_to_hex(*hsv_to_rgb(h, s * step, v + (100 - v) * (1 - step) * 0.6 + (0 if step == 1.0 else 0)))
                for step in steps]
    else:
        hues = [h]

    return [rgb_to_hex(*hsv_to_rgb(hue, s, v)) for hue in hues]


HARMONY_SCHEMES = [
    "Complementary", "Analogous", "Triadic", "Split Complementary",
    "Tetradic", "Shades", "Tints",
]
