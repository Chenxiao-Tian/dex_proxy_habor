import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiofiles
from anchorpy import Wallet
from solders.keypair import Keypair

from dex_proxy.drift_connector import DriftConnector, DriftConfiguration, DriftConnection

from driftpy.drift_client import DriftClient

log = logging.getLogger(__name__)


class ExchangeHelper:
    @staticmethod
    async def cancel_all_orders(
        project_root: str,
        dex_proxy_config: str,
        cancel_timeout: float = 10,
        num_retries: int = 10
    ):
        """Cancel all orders and wait for them to be cleared with retries

        Args:
            project_root: Root directory of the project
            dex_proxy_config: Path to the dex proxy configuration file
            cancel_timeout: Timeout in seconds for each cancel_orders attempt (default: 30.0)
            num_retries: Number of retry attempts on timeout (default: 3)
        """
        log.info("Creating drift client for canceling orders...")

        config_data, config_path = await ExchangeHelper._load_config(dex_proxy_config, project_root)

        client = await ExchangeHelper._init_client(config_data, config_path)

        try:
            await ExchangeHelper._cancel_order_with_retry(client, cancel_timeout, num_retries)
        finally:
            log.info("DriftClient unsubscribing ...")
            await client.unsubscribe()
            log.info("DriftClient unsubscribed.")

    @staticmethod
    async def _cancel_order_with_retry(
        client: DriftClient,
        cancel_timeout: float = 30.0,
        num_retries: int = 3
    ):
        orders = client.get_user().get_open_orders()
        if len(orders) == 0:
            log.info("There are no open orders to cancel")
            return

        log.info(f"There are {len(orders)} open orders. Canceling all orders...")

        for retry_attempt in range(num_retries):
            try:
                tx_sig = await asyncio.wait_for(client.cancel_orders(), timeout=cancel_timeout)
                log.info(f"Cancel all orders tx_sig: {tx_sig}")
                break  # Success, exit retry loop
            except asyncio.TimeoutError as e:
                if retry_attempt < num_retries - 1:
                    log.warning(
                        f"Cancel orders attempt {retry_attempt + 1}/{num_retries} "
                        f"timed out after {cancel_timeout}s. Retrying..."
                    )
                else:
                    error_msg = f"Cancel orders failed after {num_retries} attempts due to timeout ({cancel_timeout}s)"
                    log.error(error_msg)
                    raise RuntimeError(error_msg) from e

        max_retries = 60
        for retry in range(max_retries):
            orders = client.get_user().get_open_orders()
            if len(orders) == 0:
                log.info(f"All orders canceled successfully after {retry + 1} check(s)")
                return

            log.info(f"Retry {retry + 1}/{max_retries}: Still {len(orders)} open orders, waiting 1s...")
            await asyncio.sleep(1)

        error_msg = (
            f"Failed to cancel all orders: After {max_retries} retries, "
            f"there are still {len(orders)} open orders"
        )
        raise RuntimeError(error_msg)

    @staticmethod
    async def _init_client(config_data, config_path: Path) -> DriftClient:
        dex_config = config_data["dex"]
        drift_config = DriftConfiguration(
            url=dex_config["url"],
            public_key=dex_config["clients_pool"]["public_key"],
            env=dex_config["env"],
            sub_account_ids=dex_config["clients_pool"]["sub_account_ids"],
        )

        # Load secret
        secret_path = config_path.parent / "secret.txt"
        async with aiofiles.open(secret_path) as f:
            secret_json = await f.read()

        wallet = Wallet(Keypair.from_json(secret_json))
        secret = list(wallet.payer.to_bytes())

        # Create drift client
        client = (await DriftConnector(drift_config).get_connection(secret=secret)).client
        return client

    @staticmethod
    async def _load_config(dex_proxy_config: str, project_root: str) -> tuple[Any, Path]:
        # Load configuration
        config_path = Path(os.path.join(project_root, dex_proxy_config))
        async with aiofiles.open(config_path) as f:
            config_data = json.loads(await f.read())
        return config_data, config_path
