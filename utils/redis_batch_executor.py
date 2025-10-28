"""Very small Redis batch executor used by the requests cache."""
from __future__ import annotations

from datetime import timedelta


class RedisBatchExecutor:
    def __init__(self, pantheon, logger, redis, write_interval: timedelta, write_callback):  # pragma: no cover - stub
        self._redis = redis

    def execute(self, command: str, key: str, *args):
        command_upper = command.upper()
        if command_upper == "HSET":
            field, value = args
            self._redis.hset_sync(key, field, value)
        elif command_upper == "HDEL":
            field = args[0]
            self._redis.hdel_sync(key, field)
