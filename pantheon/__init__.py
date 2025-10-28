"""Lightweight Pantheon compatibility layer for local testing."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


class StandardArgParser:
    """Minimal argument parser used by the dex proxy entrypoints."""

    def __init__(self, description: str | None = None) -> None:
        self._parser = argparse.ArgumentParser(description=description or "")
        self._parser.add_argument("-c", "--config", required=True, help="Path to the JSON config file")
        self._parser.add_argument("-s", "--service", action="store_true", help="Run the service")
        self._parser.add_argument("-n", "--name", default=None, help="Service name override")

    def parse_args(self) -> argparse.Namespace:
        return self._parser.parse_args()

    def add_argument(self, *args, **kwargs):  # pragma: no cover - compatibility hook
        return self._parser.add_argument(*args, **kwargs)


@dataclass
class _AppHealth:
    """Very small stub mimicking the Pantheon app health helper."""

    def running(self) -> None:
        pass

    def stopping(self) -> None:
        pass

    def stopped(self) -> None:
        pass


class _InMemoryRedis:
    """Tiny in-memory Redis replacement used by the requests cache."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}

    async def exists(self, key: str) -> int:
        return int(key in self._hashes)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def hset_sync(self, key: str, field: str, value: str) -> None:
        self._hashes.setdefault(key, {})[field] = value

    def hdel_sync(self, key: str, field: str) -> None:
        if key in self._hashes:
            self._hashes[key].pop(field, None)
            if not self._hashes[key]:
                self._hashes.pop(key, None)


class Pantheon:
    """Subset of the Pantheon API required by the Harbor adapter tests."""

    def __init__(self, process_name: str) -> None:
        self.process_name = process_name
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.config: dict[str, Any] = {}
        self.args: Optional[argparse.Namespace] = None
        self._redis = _InMemoryRedis()
        self._background_tasks: list[asyncio.Task[Any]] = []

    def load_args_and_config(self, parser: StandardArgParser) -> None:
        args = parser.parse_args()
        config_path = Path(args.config).expanduser()
        with config_path.open("r", encoding="utf-8") as fp:
            self.config = json.load(fp)
        self.args = args

    def spawn(self, coro) -> asyncio.Task[Any]:
        task = self.loop.create_task(coro)
        self._background_tasks.append(task)
        return task

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def get_aioredis_connection(self) -> _InMemoryRedis:
        return self._redis

    async def get_app_health(self, app_type: str = "service") -> _AppHealth:
        return _AppHealth()

    def run_app(self, coro) -> None:
        try:
            self.loop.run_until_complete(coro)
        finally:
            if self._background_tasks:
                gatherer = asyncio.gather(*self._background_tasks, return_exceptions=True)
                self.loop.run_until_complete(gatherer)
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def get_logger(self, name: str):  # pragma: no cover - compatibility hook
        import logging

        return logging.getLogger(name)

    def get_app(self):  # pragma: no cover - compatibility hook
        return None


from .timestamp_ns import TimestampNs  # noqa: E402  pylint: disable=wrong-import-position

__all__ = ["Pantheon", "StandardArgParser", "TimestampNs"]
