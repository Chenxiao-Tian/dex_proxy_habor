from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

@dataclass
class ExpectedEvent:
    channel: str
    required_data: Optional[Dict[str, Any]] = None
    alias: Optional[str] = None


def event_matches(expected: ExpectedEvent, incoming: Dict[str, Any]) -> bool:
    params = incoming.get("params") or {}
    channel = params.get("channel")
    if channel != expected.channel:
        return False

    if expected.required_data is not None:
        data = params.get("data") or {}
        for k, v in expected.required_data.items():
            if data.get(k) != v:
                log.warning("Event data mismatch on key '%s': expected %r, got %r", k, v, data.get(k))
                return False

    return True


async def wait_for_ws_events(
    ws,
    expected: List[ExpectedEvent],
    timeout: float = 35.0,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Wait until all expected events are observed on the WebSocket or
    timeout. Matching is always out-of-order (any order is accepted).

    - expected: list of ExpectedEvent; all must be matched.
    - on_event: optional hook called for every ws_event_in event for
      logging/metrics.

    Returns:
      dict alias -> matched full ws_event_in event (as dict)

    Raises:
      AssertionError on timeout with diagnostics.
    """
    seen: List[Dict[str, Any]] = []
    matched_map: Dict[str, Dict[str, Any]] = {}

    remaining_expected_indices = list(range(len(expected)))

    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline and remaining_expected_indices:
            remaining = max(0.001, deadline - time.monotonic())
            ws_event_in = await ws.receive_json(timeout=remaining)

            if on_event:
                on_event(ws_event_in)

            seen.append(ws_event_in)

            matched_idx: Optional[int] = None
            for idx in remaining_expected_indices:
                if event_matches(expected[idx], ws_event_in):
                    matched_idx = idx
                    break
            if matched_idx is not None:
                alias = expected[matched_idx].alias
                matched_map[alias] = ws_event_in
                remaining_expected_indices.remove(matched_idx)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        log.exception("Timeout waiting for ws.receive_json")

        if remaining_expected_indices:
            def exp_crit(idx: int) -> Dict[str, Any]:
                e = expected[idx]
                return {
                    "alias": e.alias or str(idx),
                    "channel": e.channel,
                    "required_data": e.required_data,
                }

            missing = [exp_crit(i) for i in remaining_expected_indices]
            tail = seen[-10:]
            raise AssertionError(
                f"Timed out waiting for required WS events within {timeout:.2f}s. "
                f"Missing expectations: {missing}. "
                f"Last {len(tail)} received events: {tail}"
            )

    return matched_map


__all__ = [
    "ExpectedEvent",
    "event_matches",
    "wait_for_ws_events",
]