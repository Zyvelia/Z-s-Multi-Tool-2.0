"""
formats.py — format handlers + auto-detection.

Each handler is a BaseFormat subclass implementing:
    detect(raw: bytes) -> bool        # sniff whether raw looks like this format
    decode(raw: bytes) -> (data, meta)
    encode(data, meta) -> bytes

decode() at module level tries every registered format's detect() in a
sensible order (wrappers like gzip/zlib/base64 first, since they just peel
a layer and recurse) and returns the first match.
"""

from __future__ import annotations
import json
import gzip
import zlib
import base64
import configparser
import io
import xml.etree.ElementTree as ET
from typing import Any

try:
    import yaml  # optional dependency
    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False


class BaseFormat:
    name = "base"

    def detect(self, raw: bytes) -> bool:
        raise NotImplementedError

    def decode(self, raw: bytes) -> tuple:
        raise NotImplementedError

    def encode(self, data: Any, meta: dict) -> bytes:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Compression / encoding wrappers — these peel one layer then hand the
# inner bytes back to decode() to keep auto-detecting.
# ----------------------------------------------------------------------

class GzipFormat(BaseFormat):
    name = "gzip"

    def detect(self, raw: bytes) -> bool:
        return len(raw) >= 2 and raw[:2] == b"\x1f\x8b"

    def decode(self, raw: bytes) -> tuple:
        inner = gzip.decompress(raw)
        fmt, data, meta = decode(inner)
        meta = dict(meta)
        meta["_wrapper"] = "gzip"
        meta["_inner_fmt"] = fmt
        return self, data, meta

    def encode(self, data: Any, meta: dict) -> bytes:
        inner_fmt = meta["_inner_fmt"]
        return gzip.compress(inner_fmt.encode(data, meta))


class ZlibFormat(BaseFormat):
    name = "zlib"

    def detect(self, raw: bytes) -> bool:
        # zlib header bytes are almost always 0x78 followed by one of a few values
        return len(raw) >= 2 and raw[0] == 0x78 and raw[1] in (0x01, 0x5E, 0x9C, 0xDA)

    def decode(self, raw: bytes) -> tuple:
        inner = zlib.decompress(raw)
        fmt, data, meta = decode(inner)
        meta = dict(meta)
        meta["_wrapper"] = "zlib"
        meta["_inner_fmt"] = fmt
        return self, data, meta

    def encode(self, data: Any, meta: dict) -> bytes:
        inner_fmt = meta["_inner_fmt"]
        return zlib.compress(inner_fmt.encode(data, meta))


class Base64Format(BaseFormat):
    name = "base64"

    def detect(self, raw: bytes) -> bool:
        stripped = raw.strip()
        if not stripped or len(stripped) % 4 not in (0, 2, 3):
            pass  # base64 without padding is common too, don't hard-fail on this
        sample = stripped[:512]
        allowed = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r")
        if not sample or any(c not in allowed for c in sample):
            return False
        try:
            base64.b64decode(stripped + b"=" * (-len(stripped) % 4))
            return True
        except Exception:
            return False

    def decode(self, raw: bytes) -> tuple:
        stripped = raw.strip()
        inner = base64.b64decode(stripped + b"=" * (-len(stripped) % 4))
        fmt, data, meta = decode(inner)
        meta = dict(meta)
        meta["_wrapper"] = "base64"
        meta["_inner_fmt"] = fmt
        return self, data, meta

    def encode(self, data: Any, meta: dict) -> bytes:
        inner_fmt = meta["_inner_fmt"]
        return base64.b64encode(inner_fmt.encode(data, meta))


# ----------------------------------------------------------------------
# Structured text formats
# ----------------------------------------------------------------------

class JSONFormat(BaseFormat):
    name = "json"

    def detect(self, raw: bytes) -> bool:
        s = raw.strip()
        if not s or s[:1] not in (b"{", b"["):
            return False
        try:
            json.loads(s)
            return True
        except Exception:
            return False

    def decode(self, raw: bytes) -> tuple:
        return self, json.loads(raw.decode("utf-8")), {}

    def encode(self, data: Any, meta: dict) -> bytes:
        return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")


if _HAVE_YAML:

    class TaggedValue:
        """Wraps a scalar/sequence/mapping that came in under a YAML tag
        SafeLoader doesn't know (e.g. `!tags`, `!Vector`, game-specific
        tags). Keeping the tag attached lets encode() write it back out
        unchanged instead of silently dropping it or crashing on load."""

        __slots__ = ("tag", "value")

        def __init__(self, tag: str, value: Any):
            self.tag = tag
            self.value = value

        def __repr__(self) -> str:
            return f"TaggedValue({self.tag!r}, {self.value!r})"

        def __eq__(self, other) -> bool:
            return (
                isinstance(other, TaggedValue)
                and self.tag == other.tag
                and self.value == other.value
            )

        # Delegate container access to the wrapped value so a tagged
        # dict/list keeps working with SaveFile.get/set path traversal
        # (which just does node[tok]) and with tree/UI code that iterates
        # or measures it, without every caller needing to know or care
        # that a custom tag sits on top.
        def __getitem__(self, key):
            return self.value[key]

        def __setitem__(self, key, item):
            self.value[key] = item

        def __delitem__(self, key):
            del self.value[key]

        def __len__(self):
            return len(self.value)

        def __iter__(self):
            return iter(self.value)

        def items(self):
            return self.value.items()

    def _construct_any_tag(loader, node):
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        elif isinstance(node, yaml.MappingNode):
            value = loader.construct_mapping(node, deep=True)
        else:
            value = None
        return TaggedValue(node.tag, value)

    def _represent_tagged_value(dumper, data: "TaggedValue"):
        if isinstance(data.value, dict):
            return dumper.represent_mapping(data.tag, data.value)
        if isinstance(data.value, list):
            return dumper.represent_sequence(data.tag, data.value)
        return dumper.represent_scalar(data.tag, "" if data.value is None else str(data.value))

    class _TagTolerantLoader(yaml.SafeLoader):
        """SafeLoader plus a catch-all fallback constructor: any tag it
        doesn't already recognize (custom `!whatever` tags) is wrapped in
        a TaggedValue instead of raising ConstructorError."""

    # add_constructor(None, ...) registers the fallback used when no
    # tag-specific constructor matches — this is what makes it generic
    # rather than special-cased to one tag name.
    _TagTolerantLoader.add_constructor(None, _construct_any_tag)

    class _TagTolerantDumper(yaml.SafeDumper):
        pass

    _TagTolerantDumper.add_representer(TaggedValue, _represent_tagged_value)


class YAMLFormat(BaseFormat):
    name = "yaml"

    def detect(self, raw: bytes) -> bool:
        if not _HAVE_YAML:
            return False
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return False
        stripped = text.strip()
        if not stripped or stripped[:1] in ("{", "["):
            return False  # let JSON claim these first
        try:
            result = yaml.load(text, Loader=_TagTolerantLoader)
            return isinstance(result, (dict, list))
        except Exception:
            return False

    def decode(self, raw: bytes) -> tuple:
        return self, yaml.load(raw.decode("utf-8"), Loader=_TagTolerantLoader), {}

    def encode(self, data: Any, meta: dict) -> bytes:
        return yaml.dump(
            data, Dumper=_TagTolerantDumper, allow_unicode=True, sort_keys=False
        ).encode("utf-8")


class XMLFormat(BaseFormat):
    name = "xml"

    def detect(self, raw: bytes) -> bool:
        s = raw.strip()
        if not s.startswith(b"<"):
            return False
        try:
            ET.fromstring(s)
            return True
        except Exception:
            return False

    def _elem_to_dict(self, elem: ET.Element) -> dict:
        d: dict = {"@attrs": dict(elem.attrib)} if elem.attrib else {}
        text = (elem.text or "").strip()
        if text:
            d["#text"] = text
        children: dict = {}
        for child in elem:
            child_d = self._elem_to_dict(child)
            if child.tag in children:
                if not isinstance(children[child.tag], list):
                    children[child.tag] = [children[child.tag]]
                children[child.tag].append(child_d)
            else:
                children[child.tag] = child_d
        d.update(children)
        return d

    def _dict_to_elem(self, tag: str, d) -> ET.Element:
        elem = ET.Element(tag)
        if isinstance(d, dict):
            for k, v in d.items():
                if k == "@attrs":
                    elem.attrib.update(v)
                elif k == "#text":
                    elem.text = str(v)
                elif isinstance(v, list):
                    for item in v:
                        elem.append(self._dict_to_elem(k, item))
                else:
                    elem.append(self._dict_to_elem(k, v))
        else:
            elem.text = str(d)
        return elem

    def decode(self, raw: bytes) -> tuple:
        root = ET.fromstring(raw)
        data = {root.tag: self._elem_to_dict(root)}
        return self, data, {"_root_tag": root.tag}

    def encode(self, data: Any, meta: dict) -> bytes:
        root_tag = meta.get("_root_tag") or next(iter(data))
        root = self._dict_to_elem(root_tag, data[root_tag])
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class INIFormat(BaseFormat):
    name = "ini"

    def detect(self, raw: bytes) -> bool:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return False
        if "[" not in text or "=" not in text:
            return False
        cp = configparser.ConfigParser()
        try:
            cp.read_string(text)
            return len(cp.sections()) > 0
        except Exception:
            return False

    def decode(self, raw: bytes) -> tuple:
        cp = configparser.ConfigParser()
        cp.read_string(raw.decode("utf-8"))
        data = {s: dict(cp.items(s)) for s in cp.sections()}
        return self, data, {}

    def encode(self, data: Any, meta: dict) -> bytes:
        cp = configparser.ConfigParser()
        for section, kv in data.items():
            cp[section] = {k: str(v) for k, v in kv.items()}
        buf = io.StringIO()
        cp.write(buf)
        return buf.getvalue().encode("utf-8")


class RawBinaryFormat(BaseFormat):
    """
    Fallback for anything unrecognized. Wraps the raw bytes (as a mutable
    bytearray) so it can be edited three ways: raw hex patching, a
    "readable text" view of the printable strings buried in it (see
    binary_scan.py), or named offset fields via a GameLayout/
    BinaryTemplate (see layouts.py / binary_template.py) once you know
    the layout.
    """
    name = "raw_binary"

    def detect(self, raw: bytes) -> bool:
        return True  # last resort, always matches

    def decode(self, raw: bytes) -> tuple:
        return self, {"_raw": bytearray(raw)}, {}

    def encode(self, data: Any, meta: dict) -> bytes:
        return bytes(data["_raw"])


# ----------------------------------------------------------------------
# Registration + top-level decode()
# ----------------------------------------------------------------------

# Order matters: wrappers first (they recurse into decode() again),
# then structured text formats, then the catch-all raw binary format.
_REGISTRY = [
    GzipFormat(),
    ZlibFormat(),
    JSONFormat(),
    XMLFormat(),
    INIFormat(),
]
if _HAVE_YAML:
    _REGISTRY.append(YAMLFormat())
_REGISTRY.append(Base64Format())  # after text formats: avoids false positives on plain text
_FALLBACK = RawBinaryFormat()

_BY_NAME = {f.name: f for f in _REGISTRY}
_BY_NAME[_FALLBACK.name] = _FALLBACK


def decode(raw: bytes, format_hint: str | None = None) -> tuple:
    """
    Returns (format_handler, data, meta). Tries format_hint first if given,
    then walks the registry, then falls back to raw binary.
    """
    if format_hint:
        fmt = _BY_NAME.get(format_hint)
        if fmt is None:
            raise ValueError(f"Unknown format hint: {format_hint!r}")
        return fmt.decode(raw)

    for fmt in _REGISTRY:
        try:
            if fmt.detect(raw):
                return fmt.decode(raw)
        except Exception:
            continue  # detection false-positived; try the next format

    return _FALLBACK.decode(raw)


def register_format(fmt: BaseFormat, priority: bool = False) -> None:
    """Let users plug in a custom format handler (e.g. a specific game's binary layout)."""
    if priority:
        _REGISTRY.insert(0, fmt)
    else:
        _REGISTRY.insert(len(_REGISTRY), fmt)
    _BY_NAME[fmt.name] = fmt
