from __future__ import annotations
import time
from decimal import Decimal, ROUND_DOWN, InvalidOperation, getcontext

# 保持与 Harbor 精度一致
getcontext().prec = 28


def now_ns() -> int:
    """Return current Unix timestamp in nanoseconds (int)."""
    return int(time.time() * 1e9)


def ensure_multiple(
    value: Decimal,
    tick: Decimal,
    *,
    field_name: str = "value",
    tol: Decimal | None = None
) -> Decimal:
    """
    Ensure that the given value is a multiple of the tick size.

    Args:
        value: Decimal — value to check (e.g., price, quantity)
        tick: Decimal — tick size (e.g., priceTick or qtyTick)
        field_name: used in error messages
        tol: optional tolerance (default 1e-12)

    Returns:
        Decimal: rounded-down valid multiple if within tolerance

    Raises:
        ValueError: if not a multiple of tick
    """
    if tick <= 0:
        return value

    try:
        remainder = (value % tick).normalize()
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid {field_name} {value} for tick {tick}: {exc}") from exc

    tolerance = tol if tol is not None else Decimal("1e-12")

    if remainder > tolerance and abs(tick - remainder) > tolerance:
        raise ValueError(f"{field_name}={value} is not a multiple of tick={tick}")

    # Round down to nearest multiple
    quantized = (value // tick) * tick
    return quantized.quantize(tick, rounding=ROUND_DOWN)
