"""
Duplicate File Finder — core logic.

Three-pass approach so large trees don't get hashed unnecessarily:
  1. Group every file by size. A unique size can't have a duplicate —
     drop it before touching the disk again.
  2. Within a size bucket, hash only the first chunk of each file.
     Cheap, and rules out most false candidates (a 4KB read instead
     of the whole file).
  3. Within a matching partial-hash bucket, hash the full file
     (chunked, same streaming style as the File Shredder module) to
     confirm a true duplicate.

Runs on a background thread; reports progress back to the UI thread
via a thread-safe queue, matching the shared worker convention used
elsewhere in the app (see modules/Files/File Shredder/shredder.py).
"""

from __future__ import annotations

import hashlib
import os
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB
PARTIAL_HASH_BYTES = 4096


@dataclass
class ScanOptions:
    roots: list[Path]
    include_subfolders: bool = True
    min_size_bytes: int = 1024  # skip tiny files (icons, empty markers) by default


@dataclass
class DuplicateGroup:
    size: int
    file_hash: str
    paths: list[Path]


@dataclass
class ProgressEvent:
    kind: str  # "scanning" | "hashing" | "overall_done" | "fatal_error"
    message: str = ""
    done_count: int = 0
    total_count: int = 0
    groups: list[DuplicateGroup] = field(default_factory=list)


def _iter_files(options: ScanOptions):
    seen: set[Path] = set()
    for root in options.roots:
        if not root.exists():
            continue
        if options.include_subfolders:
            walker = os.walk(root)
        else:
            walker = [(str(root), [], [p.name for p in root.iterdir() if p.is_file()])]
        for dirpath, _dirs, filenames in walker:
            for name in filenames:
                fp = Path(dirpath) / name
                resolved = fp.resolve()
                if resolved in seen:
                    continue  # same file reachable via two selected roots
                seen.add(resolved)
                yield fp


def _partial_hash(path: Path) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read(PARTIAL_HASH_BYTES)).hexdigest()
    except OSError:
        return None


def _full_hash(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class DuplicateScanWorker(threading.Thread):
    """Background worker. Drains ProgressEvents from `events` on the UI
    thread via `after()` polling."""

    def __init__(self, options: ScanOptions):
        super().__init__(daemon=True)
        self.options = options
        self.events: "queue.Queue[ProgressEvent]" = queue.Queue()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
            self.events.put(ProgressEvent(kind="fatal_error", message=str(e)))

    def _run(self) -> None:
        # ---- pass 1: bucket by size ----
        self.events.put(ProgressEvent(kind="scanning", message="Scanning folders…"))
        by_size: dict[int, list[Path]] = {}
        scanned = 0
        for fp in _iter_files(self.options):
            if self._cancel.is_set():
                self.events.put(ProgressEvent(kind="overall_done", message="Cancelled"))
                return
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size < self.options.min_size_bytes:
                continue
            by_size.setdefault(size, []).append(fp)
            scanned += 1
            if scanned % 250 == 0:
                self.events.put(ProgressEvent(
                    kind="scanning", message=f"Scanning… {scanned} file(s) so far",
                ))

        candidates = [paths for paths in by_size.values() if len(paths) > 1]
        total_candidates = sum(len(paths) for paths in candidates)
        if not candidates:
            self.events.put(ProgressEvent(kind="overall_done", message="No duplicates found.", groups=[]))
            return

        # ---- pass 2: partial hash within each size bucket ----
        done = 0
        by_partial: dict[tuple[int, str], list[Path]] = {}
        for paths in candidates:
            size = paths[0].stat().st_size
            for fp in paths:
                if self._cancel.is_set():
                    self.events.put(ProgressEvent(kind="overall_done", message="Cancelled"))
                    return
                ph = _partial_hash(fp)
                done += 1
                if ph is not None:
                    by_partial.setdefault((size, ph), []).append(fp)
                if done % 100 == 0:
                    self.events.put(ProgressEvent(
                        kind="hashing", message="Comparing likely matches…",
                        done_count=done, total_count=total_candidates,
                    ))

        # ---- pass 3: full hash within each partial-hash bucket ----
        groups_by_full: dict[str, DuplicateGroup] = {}
        partial_candidates = [paths for paths in by_partial.values() if len(paths) > 1]
        for paths in partial_candidates:
            size = paths[0].stat().st_size
            for fp in paths:
                if self._cancel.is_set():
                    self.events.put(ProgressEvent(kind="overall_done", message="Cancelled"))
                    return
                fh = _full_hash(fp)
                done += 1
                if fh is not None:
                    key = f"{size}:{fh}"
                    group = groups_by_full.setdefault(key, DuplicateGroup(size=size, file_hash=fh, paths=[]))
                    group.paths.append(fp)
                if done % 50 == 0:
                    self.events.put(ProgressEvent(
                        kind="hashing", message="Confirming duplicates…",
                        done_count=done, total_count=total_candidates,
                    ))

        result_groups = [g for g in groups_by_full.values() if len(g.paths) > 1]
        result_groups.sort(key=lambda g: g.size * (len(g.paths) - 1), reverse=True)

        total_wasted = sum(g.size * (len(g.paths) - 1) for g in result_groups)
        message = (
            f"Found {len(result_groups)} duplicate group(s) "
            f"({_human_size(total_wasted)} reclaimable)."
            if result_groups else "No duplicates found."
        )
        self.events.put(ProgressEvent(kind="overall_done", message=message, groups=result_groups))


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def delete_files(paths: list[Path]) -> list[tuple[Path, bool, str]]:
    """Permanently deletes the given files. Returns (path, ok, error) per
    file so the UI can report partial failures (locked/in-use files)."""
    results = []
    for p in paths:
        try:
            p.unlink()
            results.append((p, True, ""))
        except OSError as e:
            results.append((p, False, str(e)))
    return results
