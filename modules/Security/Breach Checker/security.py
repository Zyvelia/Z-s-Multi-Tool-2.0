"""
security.py
Memory-only holder for the user's HIBP API key.

The HIBP "breached account" endpoint requires a personal, paid API
key. That key is a credential, so - same pattern as the AI Chat
module's InMemorySecret - it is kept strictly in process memory for
the current session and is never written to disk, settings.json,
logs, or anywhere else. Closing the app forgets it; the user pastes
it back in next time they want to use the Email Lookup tab.
"""


class InMemorySecret:

    __slots__ = ("_value",)

    def __init__(self, value: str = ""):
        self._value = value or ""

    def set(self, value: str) -> None:
        self._value = value or ""

    def get(self) -> str:
        return self._value

    def clear(self) -> None:
        self._value = ""

    def is_set(self) -> bool:
        return bool(self._value.strip())

    def masked(self) -> str:
        v = self._value
        if not v:
            return "(not set)"
        if len(v) <= 8:
            return "*" * len(v)
        return f"{v[:4]}{'*' * (len(v) - 8)}{v[-4:]}"

    def __repr__(self) -> str:
        return "InMemorySecret(****)"

    def __str__(self) -> str:
        return "****"
