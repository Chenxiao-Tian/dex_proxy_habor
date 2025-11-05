#!/usr/bin/env python3

import logging
import asyncio
import argparse
import json

from strategies.strategy_factory import StrategyFactory


class App:
    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            config = json.load(f)
        self.config = config
        self.logger = logging.getLogger("App")
        self._running = False

        self._strategy = StrategyFactory.create(config)

    async def start(self):
        self.logger.info("Starting")
        await self._strategy.start()

    async def run(self):
        await self.start()

        self._running = True
        while self._running:
            # run periodic task if needed
            await asyncio.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config", required=True, help="Path to the config JSON file"
    )
    args = parser.parse_args()
    app = App(args.config)

    asyncio.run(app.run())
