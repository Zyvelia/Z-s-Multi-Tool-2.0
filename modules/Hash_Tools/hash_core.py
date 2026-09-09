"""CTk-free hash helpers used by both classic and Qt Hash Tools."""

from __future__ import annotations

import hashlib

ALGOS = {
    "MD5": hashlib.md5,
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}


def hash_bytes(data: bytes) -> dict[str, str]:
    return {name: ctor(data).hexdigest() for name, ctor in ALGOS.items()}


def hash_file(path: str) -> dict[str, str]:
    with open(path, "rb") as f:
        return hash_bytes(f.read())


def verify_file(path: str, algo: str, expected: str) -> tuple[bool, str]:
    ctor = ALGOS[algo]
    with open(path, "rb") as f:
        actual = ctor(f.read()).hexdigest()
    return actual.lower() == (expected or "").strip().lower(), actual
