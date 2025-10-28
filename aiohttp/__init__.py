"""Very small aiohttp compatibility layer for offline tests."""
from __future__ import annotations

from .client import ClientSession, ClientTimeout
from . import web


class WSCloseCode:
    OK = 1000


__all__ = ["ClientSession", "ClientTimeout", "WSCloseCode", "web"]
