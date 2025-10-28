"""Minimal Timestamp helper used by certain schemas."""
from __future__ import annotations

import time
from datetime import datetime


class TimestampNs:
    def __init__(self, value: int) -> None:
        self._value = int(value)

    def get_ns_since_epoch(self) -> int:
        return self._value

    def __int__(self) -> int:  # pragma: no cover - convenience
        return self._value

    def __repr__(self) -> str:  # pragma: no cover - convenience
        return f"TimestampNs({self._value})"

    @classmethod
    def now(cls) -> "TimestampNs":
        return cls(int(time.time() * 1_000_000_000))

    @classmethod
    def from_datetime(cls, dt: datetime) -> "TimestampNs":
        return cls(int(dt.timestamp() * 1_000_000_000))

    @classmethod
    def from_ns_since_epoch(cls, value: int) -> "TimestampNs":
        return cls(value)
