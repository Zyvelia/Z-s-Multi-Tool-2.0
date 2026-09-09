"""
core.py — the generic SaveFile object.

Every format handler (JSON, XML, INI, YAML, binary template, ...) loads its
data into a plain Python structure of nested dict / list / scalars. SaveFile
wraps that structure and gives you one consistent way to read and write
values, regardless of what the file originally was.

Path syntax:
    "player.stats.gold"        -> dict traversal
    "inventory.items[3].name"  -> list indexing mixed with dict traversal
    "party[0].hp"              -> list at top level
"""

from __future__ import annotations
import re
import copy
from typing import Any

from . import formats
from . import binary_template

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _tokenize(path: str) -> list:
    """Turn 'a.b[2].c' into ['a', 'b', 2, 'c']."""
    tokens = []
    for m in _PATH_TOKEN.finditer(path):
        key, idx = m.groups()
        if key is not None:
            tokens.append(key)
        elif idx is not None:
            tokens.append(int(idx))
    if not tokens:
        raise ValueError(f"Could not parse path: {path!r}")
    return tokens


class PathError(KeyError):
    pass


class SaveFile:
    """
    Wraps a decoded save (dict/list tree) plus the format handler that
    produced it, so it can be written back out in the same shape.
    """

    def __init__(self, data: Any, fmt: "formats.BaseFormat", meta: dict | None = None):
        self.data = data
        self.fmt = fmt
        # meta carries anything a format needs to round-trip correctly,
        # e.g. original XML root tag name, or a checksum recipe.
        self.meta = meta or {}

    # ------------------------------------------------------------------
    # loading / saving
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str, format_hint: str | None = None) -> "SaveFile":
        with open(path, "rb") as f:
            raw = f.read()
        fmt, data, meta = formats.decode(raw, format_hint=format_hint)
        return cls(data, fmt, meta)

    def save(self, path: str) -> None:
        raw = self.fmt.encode(self.data, self.meta)
        with open(path, "wb") as f:
            f.write(raw)

    def to_bytes(self) -> bytes:
        return self.fmt.encode(self.data, self.meta)

    # ------------------------------------------------------------------
    # path-based access
    # ------------------------------------------------------------------

    def get(self, path: str, default: Any = "__raise__") -> Any:
        node = self.data
        for tok in _tokenize(path):
            try:
                if isinstance(tok, int):
                    node = node[tok]
                else:
                    node = node[tok]
            except (KeyError, IndexError, TypeError):
                if default != "__raise__":
                    return default
                raise PathError(f"No such path: {path!r} (failed at {tok!r})")
        return node

    def set(self, path: str, value: Any) -> None:
        tokens = _tokenize(path)
        node = self.data
        for tok in tokens[:-1]:
            try:
                node = node[tok]
            except (KeyError, IndexError, TypeError):
                raise PathError(f"No such path: {path!r} (failed at {tok!r})")
        last = tokens[-1]
        # Preserve game-specific YAML tags when editing a tagged scalar.
        # A save editor should change the value without silently deleting
        # metadata such as !tags, !Vector, or other custom YAML tags.
        current = node[last]
        tagged_type = getattr(formats, "TaggedValue", None)
        if tagged_type is not None and isinstance(current, tagged_type) and not isinstance(value, tagged_type):
            current.value = value
        else:
            node[last] = value

    def delete(self, path: str) -> None:
        tokens = _tokenize(path)
        node = self.data
        for tok in tokens[:-1]:
            node = node[tok]
        del node[tokens[-1]]

    # ------------------------------------------------------------------
    # raw-binary field access — same idea as get()/set() above, but for
    # saves that decoded to raw bytes instead of a dict/list tree (an
    # unrecognized/proprietary binary format). A FieldSpec with an
    # `offset` set (see layouts.py) reads/writes through here instead
    # of path traversal, so the same named-field editor works for both
    # kinds of save.
    # ------------------------------------------------------------------

    def raw_bytes(self) -> bytearray:
        if not isinstance(self.data, dict) or "_raw" not in self.data:
            raise PathError("This save did not decode to raw bytes (not a binary/unrecognized format).")
        return self.data["_raw"]

    def get_binary_field(self, offset: int, type_: str, size: int | None = None, endian: str = "<"):
        return binary_template.read_value(self.raw_bytes(), type_, offset, size, endian)

    def set_binary_field(self, offset: int, type_: str, value, size: int | None = None, endian: str = "<") -> None:
        binary_template.write_value(self.raw_bytes(), type_, offset, value, size, endian)

    def find(self, key: str) -> list:
        """
        Recursively search the whole tree for any dict key matching `key`.
        Returns a list of (path_string, value) tuples. Handy when you don't
        know the exact path a stat lives at.
        """
        results = []

        def _walk(node, path):
            if isinstance(node, dict):
                for k, v in node.items():
                    new_path = f"{path}.{k}" if path else k
                    if k == key:
                        results.append((new_path, v))
                    _walk(v, new_path)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    new_path = f"{path}[{i}]"
                    _walk(v, new_path)

        _walk(self.data, "")
        return results

    def diff(self, other: "SaveFile") -> list:
        """Flat list of (path, old_value, new_value) differences vs another SaveFile."""
        out = []

        def _walk(a, b, path):
            if isinstance(a, dict) and isinstance(b, dict):
                for k in set(a) | set(b):
                    _walk(a.get(k, "<missing>"), b.get(k, "<missing>"),
                          f"{path}.{k}" if path else k)
            elif isinstance(a, list) and isinstance(b, list):
                for i in range(max(len(a), len(b))):
                    av = a[i] if i < len(a) else "<missing>"
                    bv = b[i] if i < len(b) else "<missing>"
                    _walk(av, bv, f"{path}[{i}]")
            else:
                if a != b:
                    out.append((path, a, b))

        _walk(self.data, other.data, "")
        return out

    def clone(self) -> "SaveFile":
        return SaveFile(copy.deepcopy(self.data), self.fmt, copy.deepcopy(self.meta))

    def __repr__(self):
        return f"<SaveFile format={self.fmt.name!r}>"
