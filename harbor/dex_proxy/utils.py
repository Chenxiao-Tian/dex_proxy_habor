# harbor/dex_proxy/utils.py
from __future__ import annotations

import time
from decimal import Decimal, getcontext, InvalidOperation
from typing import Optional

__all__ = ["now_ns", "ensure_multiple"]


def now_ns() -> int:
    """
    Return current time in integer nanoseconds.
    """
    try:
        return time.time_ns()  # Py3.7+
    except AttributeError:
        return int(time.time() * 1_000_000_000)


def _to_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    # 防止 float 精度误差，统一走 str
    return Decimal(str(x))


def ensure_multiple(
    value: Decimal,
    tick: Decimal,
    *,
    field_name: Optional[str] = None,
) -> Decimal:
    """
    校验 value 是否为 tick 的整倍数；是则返回规范化后的值（尽量对齐 tick 的小数位），
    否则抛出带字段名的 ValueError。兼容调用方传入 field_name=... 的写法。

    参数可为 Decimal / str / int / float（将被安全地转为 Decimal）。
    """
    # 统一成 Decimal
    try:
        value = _to_decimal(value)
        tick = _to_decimal(tick) if tick is not None else None
    except (InvalidOperation, ValueError):
        # 兜底：无法解析成 Decimal 的情况直接抛错更明确
        fname = f" for '{field_name}'" if field_name else ""
        raise ValueError(f"invalid decimal input{fname}: value={value}, tick={tick}")

    if tick is None:
        return value

    # tick==0 或异常直接返回原值（由上游处理）
    try:
        if tick == 0:
            return value
    except Exception:
        return value

    # 提高精度，减少十进制误差
    ctx = getcontext().copy()
    if ctx.prec < 50:
        ctx.prec = 50
    getcontext().prec = ctx.prec  # 应用更高精度

    # 判定是否整倍数：value % tick == 0（允许极小噪声）
    try:
        remainder = value % tick
    except (InvalidOperation, ValueError, ZeroDivisionError):
        remainder = value - (value // tick) * tick  # 兜底

    # 允许极小的相对噪声
    eps = (abs(tick) * Decimal("1e-30"))
    if remainder == 0 or abs(remainder) < eps:
        # 归一小数位：不多于 tick 的小数位
        try:
            # 通过 tick 的规范化字符串估计小数位
            tick_str = f"{tick.normalize()}"
            if "." in tick_str:
                decimals = len(tick_str.split(".", 1)[1])
                quant = Decimal(1).scaleb(-decimals)  # 10^-decimals
                return value.quantize(quant)
        except Exception:
            pass
        return value

    # 不是整倍数 → 抛错
    field = f" for '{field_name}'" if field_name else ""
    raise ValueError(f"value{field}={value} is not a multiple of tick={tick}")
