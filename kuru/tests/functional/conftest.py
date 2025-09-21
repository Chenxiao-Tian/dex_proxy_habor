import asyncio
import logging
import os

import pytest
import pytest_asyncio
from aiohttp import web, ClientTimeout
from eth_account import Account
from pantheon import Pantheon, StandardArgParser

from dex_proxy import DexProxy
from dexes.kuru.handler.handler import KuruHandlerSingleton
from dexes.kuru.tests.common import configure_test_logging, read_config
# Removed direct import of margin utilities - using handler methods instead

configure_test_logging()


log = logging.getLogger(__name__)


async def create_app(pk: str):
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    config_file_path = os.path.join("dexes", "kuru", "kuru.local.config.json")

    pt = Pantheon('dex_proxy', enable_loop_measurement=False)
    parser = StandardArgParser('Dex Proxy')
    custom_args = ["-s",  "-c", os.path.join(project_root, config_file_path), "-n", "kuru"]
    pt.load_args_and_config(parser, custom_args)
    proxy = DexProxy(pt)
    app = proxy._DexProxy__server.app

    await KuruHandlerSingleton.get_instance({}).start(pk)

    return app

@pytest_asyncio.fixture(loop_scope="function")
async def client(aiohttp_client, private_key_hex_module):
    app = await create_app(private_key_hex_module)
    # Configure timeout for the client
    timeout = ClientTimeout(total=30)
    return await aiohttp_client(app, timeout=timeout)

@pytest.fixture(scope="module")
def config_data_module():
    config_data, _ = read_config()
    return config_data

@pytest.fixture(scope="module")
def private_key_hex_module():
    _, private_key_hex = read_config()
    return private_key_hex

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def margin_balance_manager(config_data_module, private_key_hex_module):
    handler = KuruHandlerSingleton.get_instance(config_data_module)
    await handler.start(private_key_hex_module)
    
    params = {
        "amount": "1000.0",  # $1000 USDC for testing
        "currency": "USDC"
    }

    log.info(f"Depositing funds: {params['amount']} {params['currency']}")
    status_code, response = await handler.deposit("", params, 0)
    assert status_code == 200, f"Failed to deposit: {response}"

    yield  # Tests run here

    await asyncio.sleep(2)
    log.info("Withdrawing funds from margin account")
    withdraw_params = {"currency": "USDC"}
    status_code, response = await handler.withdraw("", withdraw_params, 0)
    assert status_code == 200, f"Failed to withdraw: {response}"