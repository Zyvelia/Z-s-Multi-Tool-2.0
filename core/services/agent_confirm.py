"""Phone vs desktop confirm for agent writes.

Desktop Chat still uses the Tk dialog. A phone Chat/build thread
marks itself with phone_scope(); writes then wait on a pending
item the phone polls and answers.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

TIMEOUT_SECONDS = 90

_phone = threading.local()
_lock = threading.Lock()
_pending: dict[str, dict] = {}


def phone_scope():
    return _PhoneScope()


class _PhoneScope:
    def __enter__(self):
        _phone.active = True
        return self

    def __exit__(self, *_exc):
        _phone.active = False
        expire_stale()


def is_phone_context() -> bool:
    return bool(getattr(_phone, "active", False))


def ask_phone(name: str, args: dict) -> bool:
    cid = uuid.uuid4().hex[:12]
    done = threading.Event()
    item = {
        "id": cid,
        "name": name,
        "args": _preview(args),
        "created": time.time(),
        "event": done,
        "ok": False,
    }
    with _lock:
        _pending[cid] = item
    if not done.wait(timeout=TIMEOUT_SECONDS):
        with _lock:
            _pending.pop(cid, None)
        return False
    with _lock:
        _pending.pop(cid, None)
        return bool(item.get("ok"))


def snapshot() -> dict | None:
    expire_stale()
    with _lock:
        if not _pending:
            return None
        item = next(iter(_pending.values()))
        return {
            "id": item["id"],
            "name": item["name"],
            "args": item.get("args") or "",
            "created": item.get("created", 0),
            "expires": float(item.get("created", 0)) + TIMEOUT_SECONDS,
        }


def answer(confirm_id: str, ok: bool) -> bool:
    with _lock:
        item = _pending.get((confirm_id or "").strip())
        if item is None:
            return False
        item["ok"] = bool(ok)
        item["event"].set()
        return True


def expire_stale() -> None:
    now = time.time()
    with _lock:
        dead = [
            cid for cid, item in _pending.items()
            if now - float(item.get("created") or 0) > TIMEOUT_SECONDS + 2
        ]
        for cid in dead:
            item = _pending.pop(cid, None)
            if item is not None:
                item["event"].set()


def _preview(args: dict) -> str:
    try:
        text = json.dumps(args or {}, ensure_ascii=False)
    except TypeError:
        text = str(args)
    return text[:280]
