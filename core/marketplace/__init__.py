"""Installable modules — independent of a Z's Multi Tool release."""

from __future__ import annotations

__all__ = ["MarketplaceClient"]


def __getattr__(name):
    if name == "MarketplaceClient":
        from core.marketplace.client import MarketplaceClient

        return MarketplaceClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
