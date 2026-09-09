"""
Pair a phone to this PC. Tailscale is still the network fence.

When required=True, every gated API needs a device HMAC. Steal the
phone → revoke it here → that copy of the app stops. A new phone
pairs with a fresh code shown only on this PC.

This is not hardware attestation and does not detect malware on the
handset. The kill switch is revoke.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from core import paths

FILE = Path(paths.data_path("device_trust", "devices.json"))
PAIR_TTL = 10 * 60
SKEW = 5 * 60
HDR_ID = "X-Device-Id"
HDR_TS = "X-Device-Ts"
HDR_SIG = "X-Device-Sig"

LOOPBACK_PORT = 8773


def _empty() -> dict:
    return {"required": False, "devices": [], "pair_hash": "", "pair_expires": 0}


def load() -> dict:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("required", False)
            data.setdefault("devices", [])
            data.setdefault("pair_hash", "")
            data.setdefault("pair_expires", 0)
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return _empty()


def save(data: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_required() -> bool:
    return bool(load().get("required"))


def set_required(on: bool) -> None:
    data = load()
    data["required"] = bool(on)
    save(data)


def list_devices() -> list[dict]:
    out = []
    for d in load().get("devices", []):
        if not isinstance(d, dict):
            continue
        out.append({
            "id": d.get("id"),
            "label": d.get("label") or "phone",
            "created": d.get("created"),
            "last_seen": d.get("last_seen"),
            "revoked": bool(d.get("revoked")),
        })
    return out


def issue_pair_code() -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    data = load()
    data["pair_hash"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
    data["pair_expires"] = time.time() + PAIR_TTL
    save(data)
    return code


def pair(code: str, device_id: str, label: str = "") -> tuple[bool, str, str]:
    """Returns (ok, secret_or_error, device_id). Secret only on success."""
    code = (code or "").strip()
    device_id = (device_id or "").strip()
    if not device_id or len(device_id) < 8:
        return False, "Need a device id from the phone app.", ""
    if not code.isdigit() or len(code) != 6:
        return False, "Pairing code is 6 digits from Remote Hub on the PC.", ""
    data = load()
    expires = float(data.get("pair_expires") or 0)
    expected = data.get("pair_hash") or ""
    if not expected or time.time() > expires:
        return False, "Pairing code expired. Issue a new one on the PC.", ""
    got = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(got, expected):
        return False, "Wrong pairing code.", ""

    secret = secrets.token_hex(32)
    now = time.time()
    devices = [d for d in data.get("devices", []) if isinstance(d, dict)]
    devices = [d for d in devices if d.get("id") != device_id]
    devices.append({
        "id": device_id,
        "label": (label or "phone").strip() or "phone",
        "secret": secret,
        "created": now,
        "last_seen": now,
        "revoked": False,
    })
    data["devices"] = devices
    data["pair_hash"] = ""
    data["pair_expires"] = 0
    save(data)
    return True, secret, device_id


def revoke(device_id: str) -> bool:
    data = load()
    found = False
    for d in data.get("devices", []):
        if isinstance(d, dict) and d.get("id") == device_id:
            d["revoked"] = True
            d["secret"] = ""
            found = True
    if found:
        save(data)
    return found


def revoke_all() -> None:
    data = load()
    for d in data.get("devices", []):
        if isinstance(d, dict):
            d["revoked"] = True
            d["secret"] = ""
    save(data)


def _hdr(headers, name: str) -> str:
    return (headers.get(name) or headers.get(name.lower()) or "").strip()


def verify_request(headers, method: str, path: str, query: dict | None = None) -> tuple[bool, str]:
    if not is_required():
        return True, ""
    query = query or {}
    hid = _hdr(headers, HDR_ID) or str(query.get("device_id") or "").strip()
    ts = _hdr(headers, HDR_TS) or str(query.get("ts") or "").strip()
    sig = _hdr(headers, HDR_SIG) or str(query.get("sig") or "").strip()
    if not hid or not ts or not sig:
        return False, "This PC only answers paired phones. Pair in Settings, or revoke is on Remote Hub."
    try:
        when = int(ts)
    except ValueError:
        return False, "Bad device timestamp."
    if abs(time.time() - when) > SKEW:
        return False, "Device clock is too far off. Check the phone time."

    data = load()
    device = None
    for d in data.get("devices", []):
        if isinstance(d, dict) and d.get("id") == hid:
            device = d
            break
    if device is None:
        return False, "Unknown phone. Pair it from Remote Hub."
    if device.get("revoked") or not device.get("secret"):
        return False, "This phone was revoked on the PC. Pair again if it's still yours."

    msg = f"{ts}.{method.upper()}.{path}".encode("utf-8")
    expect = hmac.new(device["secret"].encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig.lower()):
        return False, "Device signature failed. If this phone was copied, revoke it on the PC."

    device["last_seen"] = time.time()
    save(data)
    return True, hid


# just_audio (and similar) hit these as bare URLs — no custom headers.
# A 5-minute HMAC would expire mid-track, so they stay on the existing
# access-code / tailnet fence instead.
SKIP_PATH_PREFIXES = ("/api/stream",)


def allow_handler(handler) -> bool:
    """Call at the top of do_GET/do_POST. Sends 403 JSON and returns False if blocked."""
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(handler.path)
    path = parts.path
    if any(path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
        return True
    query = {k: (v[0] if v else "") for k, v in parse_qs(parts.query).items()}
    ok, err = verify_request(handler.headers, handler.command, path, query)
    if ok:
        return True
    payload = json.dumps({"ok": False, "error": err, "code": "device_untrusted"}).encode("utf-8")
    try:
        handler.send_response(403)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        if hasattr(handler, "_cors"):
            handler._cors()
        elif hasattr(handler, "_cors_headers"):
            handler._cors_headers()
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception:
        pass
    return False
