"""
crypto_formats.py — pluggable decryption layer for encrypted saves.

Compression wrappers (gzip/zlib/base64) have byte signatures you can sniff.
Encryption doesn't — ciphertext looks like noise no matter what the key is.
So instead of "detecting" an algorithm, you register a SaveProfile once per
game (algorithm + key + IV handling); decode() then tries every registered
profile and keeps whichever one produces bytes that another format (JSON/
XML/etc.) can actually parse. After that one-time setup, opening that
game's saves is automatic — same as any other format here.

Figuring out the algorithm/key for a given game is a one-time reverse-
engineering step, not something this file can do for you:
  - search for the game engine + "save file format" (Unity/Unreal/RPG Maker
    titles often reuse a handful of well-known schemes, sometimes with a
    key baked right into the executable or a public modding-wiki page)
  - if you have a hex editor, look for a fixed-size header before a block
    of high-entropy bytes (a plausible IV/nonce) followed by dense-looking
    ciphertext
  - once you have a candidate key/algo, decrypt, change one known stat
    in-game, save again, and use SaveFile.diff() on the two *decrypted*
    trees to confirm the field you expect actually moved
"""

from __future__ import annotations
import json
import os
import zlib
from dataclasses import dataclass
from typing import Any

try:
    from Crypto.Cipher import AES  # optional: pycryptodome
    _AES_BACKEND = "pycryptodome"
except ImportError:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        _AES_BACKEND = "cryptography"
    except ImportError:
        _AES_BACKEND = None

_HAVE_AES = _AES_BACKEND is not None


def _aes_ecb_decrypt(key: bytes, raw: bytes) -> bytes:
    if _AES_BACKEND == "pycryptodome":
        return AES.new(key, AES.MODE_ECB).decrypt(raw)
    if _AES_BACKEND == "cryptography":
        return Cipher(algorithms.AES(key), modes.ECB()).decryptor().update(raw)
    raise RuntimeError("No AES backend installed (install pycryptodome or cryptography)")


def _aes_ecb_encrypt(key: bytes, raw: bytes) -> bytes:
    if _AES_BACKEND == "pycryptodome":
        return AES.new(key, AES.MODE_ECB).encrypt(raw)
    if _AES_BACKEND == "cryptography":
        return Cipher(algorithms.AES(key), modes.ECB()).encryptor().update(raw)
    raise RuntimeError("No AES backend installed (install pycryptodome or cryptography)")

from . import formats

# Borderlands 4: AES-256-ECB, key = BASE_KEY with its first 8 bytes XORed
# against the player's Steam/Epic ID (little-endian u64). Decrypted bytes
# are zlib-compressed YAML with an 8-byte footer (adler32 + uncompressed
# length) after the compressed stream, before PKCS7 padding.
_BL4_BASE_KEY = bytes([
    0x35, 0xEC, 0x33, 0x77, 0xF3, 0x5D, 0xB0, 0xEA, 0xBE, 0x6B, 0x83, 0x11, 0x54, 0x03, 0xEB, 0xFB,
    0x27, 0x25, 0x64, 0x2E, 0xD5, 0x49, 0x06, 0x29, 0x05, 0x78, 0xBD, 0x60, 0xBA, 0x4A, 0xA7, 0x87,
])


def _bl4_derive_key(steam_or_epic_id: str) -> bytes:
    digits = "".join(c for c in steam_or_epic_id if c.isdigit())
    if not digits:
        raise ValueError("bl4-steamid profile needs a numeric Steam/Epic ID")
    id_num = int(digits)
    id_bytes = id_num.to_bytes(8, "little", signed=False)
    key = bytearray(_BL4_BASE_KEY)
    for i in range(8):
        key[i] ^= id_bytes[i]
    return bytes(key)




# ----------------------------------------------------------------------
# Small dependency-free YAML fallback used by BL4.
# BL4's decrypted YAML is deliberately simple: indentation-based mappings,
# sequences, quoted/unquoted scalars, and arbitrary YAML tags.  If PyYAML is
# available we use it; otherwise this parser keeps the Save Editor usable
# without requiring a separate Python package just to open BL4 saves.
# ----------------------------------------------------------------------

class _FallbackTaggedValue:
    __slots__ = ("tag", "value")
    def __init__(self, tag: str, value: Any):
        self.tag, self.value = tag, value
    def __getitem__(self, key): return self.value[key]
    def __setitem__(self, key, item): self.value[key] = item
    def __delitem__(self, key): del self.value[key]
    def __len__(self): return len(self.value)
    def __iter__(self): return iter(self.value)
    def items(self): return self.value.items()


# Let the UI's generic TaggedValue checks also work when PyYAML is absent.
if not hasattr(formats, "TaggedValue"):
    formats.TaggedValue = _FallbackTaggedValue


def _strip_yaml_comment(s: str) -> str:
    quoted = False
    quote = None
    for i, ch in enumerate(s):
        if ch in "'\"":
            if not quoted:
                quoted, quote = True, ch
            elif ch == quote:
                if quote == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    continue
                quoted = False
        elif ch == '#' and not quoted and (i == 0 or s[i - 1].isspace()):
            return s[:i].rstrip()
    return s.rstrip()


def _yaml_scalar(s: str):
    s = s.strip()
    if not s:
        return None
    # Tagged scalar / tagged collection marker.
    if s.startswith("!"):
        parts = s.split(None, 1)
        tag = parts[0]
        if len(parts) == 1:
            return _FallbackTaggedValue(tag, None)
        return _FallbackTaggedValue(tag, _yaml_scalar(parts[1]))
    if s in ("null", "Null", "NULL", "~"):
        return None
    if s.lower() == "true": return True
    if s.lower() == "false": return False
    if s.startswith("'") and s.endswith("'") and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        try:
            import json as _json
            return _json.loads(s)
        except Exception:
            return s[1:-1]
    if s.startswith("0x") or s.startswith("0X"):
        try: return int(s, 16)
        except ValueError: pass
    try:
        if s.lstrip("+-").isdigit(): return int(s, 10)
        if any(c in s for c in ".eE"):
            return float(s)
    except ValueError:
        pass
    return s


def _split_mapping(s: str):
    quoted = False; quote = None; depth = 0
    for i, ch in enumerate(s):
        if ch in "'\"":
            if not quoted: quoted, quote = True, ch
            elif ch == quote:
                if quote == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    continue
                quoted = False
        elif not quoted:
            if ch in "[{": depth += 1
            elif ch in "]}": depth -= 1
            elif ch == ":" and depth == 0 and (i + 1 == len(s) or s[i + 1].isspace()):
                return s[:i].strip(), s[i + 1:].strip()
    return None, None


def _fallback_yaml_load(text: str):
    raw_lines = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = _strip_yaml_comment(raw[indent:])
        if content:
            raw_lines.append((indent, content, number))
    if not raw_lines:
        return None

    def parse_block(pos, indent):
        if pos >= len(raw_lines): return None, pos
        is_list = raw_lines[pos][0] == indent and raw_lines[pos][1].startswith("-")
        obj = [] if is_list else {}
        while pos < len(raw_lines):
            ind, content, _line = raw_lines[pos]
            if ind < indent: break
            if ind > indent: raise ValueError(f"Unexpected indentation at YAML line {_line}")
            if is_list:
                if not content.startswith("-"): break
                rest = content[1:].lstrip()
                pos += 1
                if not rest:
                    if pos < len(raw_lines) and raw_lines[pos][0] > indent:
                        val, pos = parse_block(pos, raw_lines[pos][0])
                    else: val = None
                    obj.append(val); continue
                key, value = _split_mapping(rest)
                if key is not None:
                    item = {}
                    if value:
                        parsed = _yaml_scalar(value)
                        # A bare tag with no scalar means the child block belongs to the tag.
                        if isinstance(parsed, _FallbackTaggedValue) and parsed.value is None and pos < len(raw_lines) and raw_lines[pos][0] > indent:
                            child, pos = parse_block(pos, raw_lines[pos][0])
                            parsed.value = child
                        item[key] = parsed
                    elif pos < len(raw_lines) and raw_lines[pos][0] > indent:
                        child, pos = parse_block(pos, raw_lines[pos][0]); item[key] = child
                    else: item[key] = None
                    # Consume additional mapping members belonging to this list item.
                    if pos < len(raw_lines) and raw_lines[pos][0] > indent:
                        extra, pos = parse_block(pos, raw_lines[pos][0])
                        if isinstance(extra, dict): item.update(extra)
                    obj.append(item)
                else:
                    obj.append(_yaml_scalar(rest))
            else:
                key, value = _split_mapping(content)
                if key is None: raise ValueError(f"Unsupported YAML syntax at line {_line}: {content}")
                pos += 1
                if value:
                    parsed = _yaml_scalar(value)
                    if isinstance(parsed, _FallbackTaggedValue) and parsed.value is None and pos < len(raw_lines) and (raw_lines[pos][0] > indent or (raw_lines[pos][0] == indent and raw_lines[pos][1].startswith("-"))):
                        child, pos = parse_block(pos, raw_lines[pos][0]); parsed.value = child
                    obj[key.strip("'\"")] = parsed
                elif pos < len(raw_lines) and (raw_lines[pos][0] > indent or (raw_lines[pos][0] == indent and raw_lines[pos][1].startswith("-"))):
                    child, pos = parse_block(pos, raw_lines[pos][0]); obj[key.strip("'\"")] = child
                else:
                    obj[key.strip("'\"")] = None
        return obj, pos

    result, end = parse_block(0, raw_lines[0][0])
    if end != len(raw_lines): raise ValueError("Could not consume entire BL4 YAML document")
    return result


def _fallback_yaml_scalar(value):
    if value is None: return "null"
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, int): return str(value)
    if isinstance(value, float): return repr(value)
    s = str(value).replace("'", "''")
    return "'" + s + "'"


def _fallback_yaml_key(key):
    s = str(key)
    if s and all(ch.isalnum() or ch in "._-" for ch in s): return s
    return _fallback_yaml_scalar(s)


def _fallback_yaml_dump(data, indent=0):
    out = []
    pad = " " * indent
    if isinstance(data, _FallbackTaggedValue):
        if isinstance(data.value, (dict, list)):
            out.append(pad + data.tag)
            out.extend(_fallback_yaml_dump(data.value, indent + 2))
        else:
            out.append(pad + data.tag + " " + _fallback_yaml_scalar(data.value))
        return out
    if isinstance(data, dict):
        for k, v in data.items():
            key = _fallback_yaml_key(k)
            if isinstance(v, _FallbackTaggedValue) and isinstance(v.value, (dict, list)):
                out.append(pad + key + ": " + v.tag)
                out.extend(_fallback_yaml_dump(v.value, indent + 2))
            elif isinstance(v, (dict, list)):
                out.append(pad + key + ":")
                out.extend(_fallback_yaml_dump(v, indent + 2))
            else:
                out.append(pad + key + ": " + (_fallback_yaml_dump(v, 0)[0] if isinstance(v, _FallbackTaggedValue) else _fallback_yaml_scalar(v)))
        return out
    if isinstance(data, list):
        for v in data:
            if isinstance(v, dict):
                if not v: out.append(pad + "- {}")
                else:
                    first = True
                    for k, child in v.items():
                        key = _fallback_yaml_key(k)
                        prefix = pad + "- " if first else pad + "  "
                        first = False
                        if isinstance(child, (dict, list)):
                            out.append(prefix + key + ":")
                            out.extend(_fallback_yaml_dump(child, indent + 4))
                        elif isinstance(child, _FallbackTaggedValue) and isinstance(child.value, (dict, list)):
                            out.append(prefix + key + ": " + child.tag)
                            out.extend(_fallback_yaml_dump(child.value, indent + 4))
                        else:
                            out.append(prefix + key + ": " + (_fallback_yaml_dump(child,0)[0] if isinstance(child,_FallbackTaggedValue) else _fallback_yaml_scalar(child)))
            elif isinstance(v, list):
                out.append(pad + "-")
                out.extend(_fallback_yaml_dump(v, indent + 2))
            else:
                out.append(pad + "- " + (_fallback_yaml_dump(v,0)[0] if isinstance(v,_FallbackTaggedValue) else _fallback_yaml_scalar(v)))
        return out
    out.append(pad + _fallback_yaml_scalar(data))
    return out


def _fallback_yaml_encode(data) -> bytes:
    return ("\n".join(_fallback_yaml_dump(data)) + "\n").encode("utf-8")

@dataclass
class SaveProfile:
    name: str                 # label, e.g. "Some Game"
    algo: str                 # "aes-cbc" | "aes-ecb" | "aes-gcm" | "xor" | "bl4-steamid"
    key: bytes = b""
    iv_mode: str = "none"     # "none" | "prefix16" | "fixed"  (cbc/gcm)
    fixed_iv: bytes = b""
    nonce_size: int = 12      # gcm
    tag_size: int = 16        # gcm
    steam_id: str = ""        # bl4-steamid only: numeric Steam64 or Epic account ID

    def decrypt(self, raw: bytes) -> bytes:
        if self.algo == "xor":
            k = self.key
            return bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))

        if self.algo == "bl4-steamid":
            return self._bl4_decrypt(raw)

        if not _HAVE_AES:
            raise RuntimeError("pycryptodome not installed (pip install pycryptodome)")

        if self.algo == "aes-ecb":
            return _unpad(_aes_ecb_decrypt(self.key, raw))

        if self.algo == "aes-cbc":
            iv, body = self._split_iv(raw)
            return _unpad(AES.new(self.key, AES.MODE_CBC, iv).decrypt(body))

        if self.algo == "aes-gcm":
            nonce, body, tag = raw[:self.nonce_size], raw[self.nonce_size:-self.tag_size], raw[-self.tag_size:]
            return AES.new(self.key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(body, tag)

        raise ValueError(f"Unknown algo: {self.algo}")

    def encrypt(self, data: bytes) -> bytes:
        if self.algo == "xor":
            k = self.key
            return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))

        if self.algo == "bl4-steamid":
            return self._bl4_encrypt(data)

        if not _HAVE_AES:
            raise RuntimeError("pycryptodome not installed (pip install pycryptodome)")

        if self.algo == "aes-ecb":
            return _aes_ecb_encrypt(self.key, _pad(data))

        if self.algo == "aes-cbc":
            if self.iv_mode == "prefix16":
                iv = os.urandom(16)
                return iv + AES.new(self.key, AES.MODE_CBC, iv).encrypt(_pad(data))
            cipher = AES.new(self.key, AES.MODE_CBC, self.fixed_iv)
            return cipher.encrypt(_pad(data))

        if self.algo == "aes-gcm":
            nonce = os.urandom(self.nonce_size)
            body, tag = AES.new(self.key, AES.MODE_GCM, nonce=nonce).encrypt_and_digest(data)
            return nonce + body + tag

        raise ValueError(f"Unknown algo: {self.algo}")

    def _split_iv(self, raw: bytes) -> tuple:
        if self.iv_mode == "prefix16":
            return raw[:16], raw[16:]
        if self.iv_mode == "fixed":
            return self.fixed_iv, raw
        raise ValueError("aes-cbc profile needs iv_mode 'prefix16' or 'fixed'")

    # ------------------------------------------------------------------
    # Borderlands 4: .sav -> AES-256-ECB decrypt -> zlib decompress -> YAML
    # ------------------------------------------------------------------

    def _bl4_decrypt(self, raw: bytes) -> bytes:
        if not _HAVE_AES:
            raise RuntimeError("pycryptodome not installed (pip install pycryptodome)")
        if len(raw) % 16 != 0:
            raise ValueError(f"bl4 save size {len(raw)} isn't a multiple of 16 bytes")
        key = _bl4_derive_key(self.steam_id)
        decrypted = _aes_ecb_decrypt(key, raw)
        unpadded = _unpad(decrypted)
        # zlib.decompress stops at the end-of-stream marker on its own,
        # so the trailing adler32+length footer after the compressed
        # block doesn't need to be stripped first.
        return zlib.decompress(unpadded)

    def _bl4_encrypt(self, data: bytes) -> bytes:
        if not _HAVE_AES:
            raise RuntimeError("pycryptodome not installed (pip install pycryptodome)")
        key = _bl4_derive_key(self.steam_id)
        compressor = zlib.compressobj(9)
        compressed = compressor.compress(data) + compressor.flush()
        footer = (zlib.adler32(data) & 0xFFFFFFFF).to_bytes(4, "little")
        footer += (len(data) & 0xFFFFFFFF).to_bytes(4, "little")
        padded = _pad(compressed + footer)
        return _aes_ecb_encrypt(key, padded)


def _pad(data: bytes, block: int = 16) -> bytes:
    n = block - (len(data) % block)
    return data + bytes([n]) * n


def _unpad(data: bytes, block: int = 16) -> bytes:
    n = data[-1]
    if 0 < n <= block and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data  # wasn't PKCS7-padded — leave alone rather than guess wrong



def _bl4_parse_inner(raw: bytes):
    """Parse decrypted BL4 YAML without requiring PyYAML."""
    text = raw.decode("utf-8")
    if getattr(formats, "_HAVE_YAML", False):
        fmt = formats.YAMLFormat()
        return fmt.decode(raw)[1], fmt
    return _fallback_yaml_load(text), _BL4FallbackYAMLFormat()


class _BL4FallbackYAMLFormat(formats.BaseFormat):
    name = "yaml"
    def detect(self, raw: bytes) -> bool:
        return raw.lstrip().startswith(b"state:")
    def decode(self, raw: bytes):
        return self, _fallback_yaml_load(raw.decode("utf-8")), {}
    def encode(self, data, meta):
        return _fallback_yaml_encode(data)


class EncryptedFormat(formats.BaseFormat):
    """
    Wraps one SaveProfile as a BaseFormat so it slots into the same
    detect -> decode -> recurse chain as Gzip/Zlib/Base64. detect() only
    succeeds if decrypting AND parsing the inner format both succeed —
    that's the only real signal available, since ciphertext has no magic
    bytes of its own.
    """

    def __init__(self, profile: SaveProfile):
        self.profile = profile
        self.name = f"encrypted:{profile.name}"

    def detect(self, raw: bytes) -> bool:
        try:
            inner = self.profile.decrypt(raw)
            if self.profile.algo == "bl4-steamid":
                # BL4 has a known post-decryption signature. Do not depend on
                # PyYAML being installed just to recognize the save.
                probe = inner.lstrip()
                return probe.startswith(b"state:") and b"inventory:" in probe[:20000]
            fmt, _data, _meta = formats.decode(inner)
            return fmt.name != "raw_binary"
        except Exception:
            return False

    def decode(self, raw: bytes) -> tuple:
        inner = self.profile.decrypt(raw)
        if self.profile.algo == "bl4-steamid":
            data, fmt = _bl4_parse_inner(inner)
            meta = {"_wrapper": self.name, "_inner_fmt": fmt, "_profile": self.profile}
            return self, data, meta
        fmt, data, meta = formats.decode(inner)
        meta = dict(meta)
        meta["_wrapper"] = self.name
        meta["_inner_fmt"] = fmt
        meta["_profile"] = self.profile
        return self, data, meta

    def encode(self, data: Any, meta: dict) -> bytes:
        inner_fmt = meta["_inner_fmt"]
        return self.profile.encrypt(inner_fmt.encode(data, meta))


# ----------------------------------------------------------------------
# Profile persistence — plain JSON, keys stored in the clear. That's fine
# for editing your own local single-player saves; don't reuse this for
# anything that needs to actually keep a key secret.
# ----------------------------------------------------------------------

def load_profiles(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        SaveProfile(
            name=p["name"],
            algo=p["algo"],
            key=bytes.fromhex(p["key_hex"]) if p.get("key_hex") else b"",
            iv_mode=p.get("iv_mode", "none"),
            fixed_iv=bytes.fromhex(p["fixed_iv_hex"]) if p.get("fixed_iv_hex") else b"",
            nonce_size=p.get("nonce_size", 12),
            tag_size=p.get("tag_size", 16),
            steam_id=p.get("steam_id", ""),
        )
        for p in raw
    ]


def save_profiles(path: str, profiles: list) -> None:
    raw = [{
        "name": p.name, "algo": p.algo, "key_hex": p.key.hex(),
        "iv_mode": p.iv_mode, "fixed_iv_hex": p.fixed_iv.hex(),
        "nonce_size": p.nonce_size, "tag_size": p.tag_size,
        "steam_id": p.steam_id,
    } for p in profiles]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)


def register_all(profiles: list) -> None:
    """Insert one EncryptedFormat per profile so decode() tries it
    automatically on every future file open."""
    for p in profiles:
        formats.register_format(EncryptedFormat(p))
