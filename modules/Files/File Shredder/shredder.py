"""
Folder Shredder — core logic.

Secure-delete engine: overwrites file bytes before unlinking, then removes
emptied directory trees. Runs on a background thread; reports progress and
per-item results back to the UI thread via a thread-safe queue.

Note on SSDs: overwrite passes are close to cosmetic on wear-leveled flash
storage (the physical cells written to aren't guaranteed to be the ones the
filesystem just pointed you at). They're still meaningful on spinning disks
and for defeating casual/undelete-tool recovery. The UI should say this
plainly rather than implying a guarantee.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PassPattern(Enum):
    ZERO = "single pass (zero-fill)"
    RANDOM = "single pass (random)"
    DOD_3PASS = "DoD 5220.22-M (3 pass)"


_DOD_PASSES = ("zero", "one", "random")


@dataclass
class ShredItem:
    path: Path
    is_dir: bool
    size_bytes: int = 0


@dataclass
class ShredResult:
    path: Path
    ok: bool
    error: str | None = None


@dataclass
class ProgressEvent:
    kind: str  # "item_start" | "item_done" | "overall_done" | "fatal_error"
    path: Path | None = None
    result: ShredResult | None = None
    done_count: int = 0
    total_count: int = 0
    message: str = ""


CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB


def _overwrite_file(path: Path, pattern: PassPattern, chunk_size: int = CHUNK_SIZE) -> None:
    """Overwrite a single file's contents in place before deletion."""
    size = path.stat().st_size
    if size == 0:
        return

    if pattern == PassPattern.ZERO:
        passes = ("zero",)
    elif pattern == PassPattern.RANDOM:
        passes = ("random",)
    else:
        passes = _DOD_PASSES

    with open(path, "r+b") as f:
        for p in passes:
            f.seek(0)
            remaining = size
            while remaining > 0:
                write_size = min(chunk_size, remaining)
                if p == "zero":
                    buf = b"\x00" * write_size
                elif p == "one":
                    buf = b"\xff" * write_size
                else:
                    buf = os.urandom(write_size)
                f.write(buf)
                remaining -= write_size
            f.flush()
            os.fsync(f.fileno())


def _shred_file(path: Path, pattern: PassPattern) -> ShredResult:
    try:
        _overwrite_file(path, pattern)
        path.unlink()
        return ShredResult(path=path, ok=True)
    except PermissionError as e:
        return ShredResult(path=path, ok=False, error=f"locked/in-use: {e}")
    except OSError as e:
        return ShredResult(path=path, ok=False, error=str(e))


def collect_targets(paths: list[Path]) -> list[ShredItem]:
    """Expand a mixed list of files/folders into a flat list of files to
    shred, plus the directories that will need removing afterward."""
    items: list[ShredItem] = []
    for p in paths:
        if p.is_dir():
            for root, _dirs, files in os.walk(p, topdown=False):
                root_path = Path(root)
                for name in files:
                    fp = root_path / name
                    try:
                        items.append(ShredItem(path=fp, is_dir=False, size_bytes=fp.stat().st_size))
                    except OSError:
                        items.append(ShredItem(path=fp, is_dir=False, size_bytes=0))
            items.append(ShredItem(path=p, is_dir=True))
        elif p.is_file():
            try:
                items.append(ShredItem(path=p, is_dir=False, size_bytes=p.stat().st_size))
            except OSError:
                items.append(ShredItem(path=p, is_dir=False, size_bytes=0))
    return items


class ShredderWorker(threading.Thread):
    """Background worker. Put targets in, drain ProgressEvents from
    `events` on the UI thread via `after()` polling."""

    def __init__(self, items: list[ShredItem], pattern: PassPattern):
        super().__init__(daemon=True)
        self.items = items
        self.pattern = pattern
        self.events: queue.Queue[ProgressEvent] = queue.Queue()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        files = [i for i in self.items if not i.is_dir]
        dirs = [i for i in self.items if i.is_dir]
        total = len(files) + len(dirs)
        done = 0

        try:
            for item in files:
                if self._cancel.is_set():
                    self.events.put(ProgressEvent(kind="overall_done", message="Cancelled"))
                    return
                self.events.put(ProgressEvent(kind="item_start", path=item.path))
                result = _shred_file(item.path, self.pattern)
                done += 1
                self.events.put(ProgressEvent(
                    kind="item_done", path=item.path, result=result,
                    done_count=done, total_count=total,
                ))

            # Remove now-emptied directories, deepest first (os.walk topdown=False
            # ordering in collect_targets already gives us that order per-root).
            for item in dirs:
                if self._cancel.is_set():
                    self.events.put(ProgressEvent(kind="overall_done", message="Cancelled"))
                    return
                self.events.put(ProgressEvent(kind="item_start", path=item.path))
                try:
                    _remove_empty_tree(item.path)
                    result = ShredResult(path=item.path, ok=True)
                except OSError as e:
                    result = ShredResult(path=item.path, ok=False, error=str(e))
                done += 1
                self.events.put(ProgressEvent(
                    kind="item_done", path=item.path, result=result,
                    done_count=done, total_count=total,
                ))

            self.events.put(ProgressEvent(kind="overall_done", message="Done"))
        except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
            self.events.put(ProgressEvent(kind="fatal_error", message=str(e)))


def _remove_empty_tree(root: Path) -> None:
    """Remove a directory tree that should now contain only empty
    subdirectories (all files already shredded)."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            # Anything left here was skipped earlier (e.g. locked) — leave it,
            # don't silently delete unshredded data.
            pass
        try:
            os.rmdir(dirpath)
        except OSError:
            pass  # not empty (skipped files inside) — leave it in place
