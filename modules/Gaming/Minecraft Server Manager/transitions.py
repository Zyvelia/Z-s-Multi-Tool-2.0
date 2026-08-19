"""Small color-step animations for CustomTkinter widgets."""

from __future__ import annotations

from typing import Callable

STEP_MS = 18
STEPS = 6


def _parse_hex(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def lerp_hex(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = _parse_hex(a)
    r2, g2, b2 = _parse_hex(b)
    return "#{:02x}{:02x}{:02x}".format(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


def animate_fg_color(
    widget,
    target: str,
    *,
    steps: int = STEPS,
    step_ms: int = STEP_MS,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Step `widget`'s fg_color toward `target`."""
    try:
        current = widget.cget("fg_color")
    except Exception:
        current = target
    if isinstance(current, (tuple, list)):
        current = current[0] if current else target
    if str(current).lower() == str(target).lower():
        if on_done:
            on_done()
        return

    def step(i: int = 0) -> None:
        if i >= steps:
            try:
                widget.configure(fg_color=target)
            except Exception:
                pass
            if on_done:
                on_done()
            return
        t = (i + 1) / steps
        try:
            widget.configure(fg_color=lerp_hex(str(current), target, t))
        except Exception:
            if on_done:
                on_done()
            return
        widget.after(step_ms, lambda: step(i + 1))

    step(0)


def pulse_dim(widget, base: str, dim: str, on_mid: Callable[[], None] | None = None) -> None:
    """Brief dim, run callback, then restore — used when switching servers."""

    def after_dim() -> None:
        if on_mid:
            on_mid()
        widget.after(12, lambda: animate_fg_color(widget, base, steps=5, step_ms=14))

    animate_fg_color(widget, dim, steps=4, step_ms=14, on_done=after_dim)
