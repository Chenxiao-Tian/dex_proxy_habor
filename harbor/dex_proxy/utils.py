from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation, getcontext

getcontext().prec = 28


def now_ns() -> int:
    """Return current epoch timestamp in nanoseconds."""

    return int(time.time() * 1_000_000_000)


def ensure_multiple(value: Decimal, tick: Decimal, *, field_name: str) -> Decimal:
    """Validate that *value* is a multiple of *tick* and return the normalized decimal."""

    if tick <= 0:
        return value

    try:
        quotient = value / tick
    except (InvalidOperation, ZeroDivisionError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid {field_name} {value} for tick {tick}: {exc}") from exc

    if quotient != quotient.to_integral_value():
        raise ValueError(
            f"{field_name}={value} does not respect tick size {tick}"
        )

    # Normalize to the tick precision to avoid sending scientific notation to Harbor
    return (quotient.to_integral_value() * tick).normalize()
