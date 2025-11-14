from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import time

def ensure_multiple(value: str | float | Decimal,
                    tick: str | float | Decimal,
                    mode: str = "floor") -> Decimal:
    """
    Align value to a multiple of tick.

    Parameters
    ----------
    value : str|float|Decimal
    tick  : str|float|Decimal   (must be > 0)
    mode  : "floor" (down) | "nearest" (ROUND_HALF_UP)

    Returns
    -------
    Decimal aligned value with the same quantum as `tick`.
    """
    v = Decimal(str(value))
    t = Decimal(str(tick))
    if t <= 0:
        raise ValueError("tick must be > 0")

    q = v / t
    if mode in ("floor", "down"):
        q = q.to_integral_value(rounding=ROUND_FLOOR)
    elif mode in ("nearest", "round"):
        q = q.to_integral_value(rounding=ROUND_HALF_UP)
    else:
        raise ValueError(f"unknown mode={mode!r}")
    return (q * t).quantize(t)

def now_ns() -> str:
    return str(time.time_ns())
