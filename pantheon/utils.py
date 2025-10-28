"""Utility helpers for websocket handling."""


async def receive_json(ws):
    """Read a JSON payload from an aiohttp WebSocket response."""
    return await ws.receive_json()
