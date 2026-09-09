"""Automatic build numbers. You never pick 1.2.0 — we just count up."""

from __future__ import annotations

from datetime import datetime, timezone


def next_build(previous: int | None) -> int:
    return max(int(previous or 0), 0) + 1


def label_for(build: int, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    return f"Build {int(build)} · {when.strftime('%Y-%m-%d')}"


def is_newer(candidate: int, installed: int | None) -> bool:
    return int(candidate or 0) > int(installed or 0)


def same_or_older(candidate: int, installed: int | None) -> bool:
    return int(candidate or 0) <= int(installed or 0)
