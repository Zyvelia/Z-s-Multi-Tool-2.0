"""One-off: replace import-time theme color snapshots with live theme.* refs."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules"

HEX_TO_THEME = {
    "#0f1115": "theme.BG",
    "#151922": "theme.PANEL",
    "#1b2030": "theme.PANEL_2",
    "#212739": "theme.PANEL_HOVER",
    "#252d3d": "theme.BORDER",
    "#4ea1ff": "theme.ACCENT",
    "#3d8fe0": "theme.ACCENT_DIM",
    "#2f7fd6": "theme.ACCENT_DIM",
    "#a78bfa": "theme.ACCENT",
    "#7d8494": "theme.MUTED",
    "#9aa4b2": "theme.MUTED",
    "#5c6474": "theme.FAINT",
    "#e6e6e6": "theme.TEXT",
    "#ff5c5c": "theme.DANGER",
    "#2ecc71": "theme.SUCCESS",
    "#2a1b1b": "theme.DANGER_BG",
    "#d14b4b": "theme.DANGER_HOVER",
    "#e04545": "theme.DANGER_HOVER",
    "#211a35": "theme.ACCENT_GLOW",
    "#1a3a5c": "theme.ACCENT_GLOW",
    "#8f2d2d": "theme.RED_DIM",
    "#e06c75": "theme.ERROR",
}

SNAP_RE = re.compile(
    r"^([A-Z][A-Z0-9_]*)\s*=\s*(theme\.([A-Z_0-9]+)|([\"'])(#[0-9a-fA-F]{3,8})\4)(\s*#.*)?$"
)


def ensure_theme_import(text: str) -> str:
    if re.search(r"\bfrom core import theme\b", text) or re.search(r"\bimport core\.theme\b", text):
        return text
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_at = i + 1
        elif line.strip() and not line.strip().startswith("#") and insert_at > 0:
            break
    lines.insert(insert_at, "from core import theme")
    return "\n".join(lines)


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "theme." not in text and not any(h in text for h in HEX_TO_THEME):
        return False

    aliases: dict[str, str] = {}
    out_lines: list[str] = []
    changed = False

    for line in text.splitlines():
        stripped = line.strip()
        m = SNAP_RE.match(stripped)
        if m and not stripped.startswith("#"):
            name, rhs, theme_token, _q, hex_val = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            if theme_token:
                replacement = f"theme.{theme_token}"
            else:
                replacement = HEX_TO_THEME.get(hex_val.lower())
                if not replacement:
                    out_lines.append(line)
                    continue
            aliases[name] = replacement
            changed = True
            continue
        out_lines.append(line)

    if not changed:
        return False

    new_text = "\n".join(out_lines)
    if "from core import theme" not in new_text:
        new_text = ensure_theme_import(new_text)
        changed = True

    for name in sorted(aliases, key=len, reverse=True):
        new_text = re.sub(rf"\b{re.escape(name)}\b", aliases[name], new_text)

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        print(f"fixed: {path.relative_to(ROOT.parent)}")
        return True
    return False


def main():
    count = 0
    for path in sorted(ROOT.rglob("*.py")):
        if process_file(path):
            count += 1
    print(f"Done — updated {count} files.")


if __name__ == "__main__":
    main()
