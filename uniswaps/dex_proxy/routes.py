from collections import defaultdict
from typing import Callable


class ServerRoutes:
    def __init__(self):
        self.routes: dict[tuple[str, str], Callable] = {}
        self.route_counts: dict[tuple, int] = defaultdict(lambda: 0)

    def register(self, method, path, handler, **kwargs):
        self.route_counts[(method, path)] += 1

        self.routes[(method, path)] = handler

    async def handle_request(self, method, path, params):
        if self.route_counts[(method, path)] > 1:
            raise Exception(f'Handler for {method} {path} registered multiple times')

        return await self.routes[(method, path)](path, params)
