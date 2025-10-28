"""Stub implementation of the Fireblocks API used for local tests."""


class FireblocksApi:
    def __init__(self, pantheon, connector):
        self._pantheon = pantheon
        self._connector = connector

    async def start(self):  # pragma: no cover - compatibility hook
        return None
