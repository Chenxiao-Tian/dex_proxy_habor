import logging
import pytest
import pytest_asyncio
import os
from xprocess import ProcessStarter

from dexes.kuru.tests.common import configure_test_logging, read_config
from dexes.kuru.util.margin import add_margin_balance, clear_margin_balance

configure_test_logging()

log = logging.getLogger(__name__)

@pytest.fixture(scope="module")
def config_data_module():
    config_data, _ = read_config()
    return config_data

@pytest.fixture(scope="module")
def private_key_hex_module():
    _, private_key_hex = read_config()
    return private_key_hex

@pytest_asyncio.fixture(scope="module", autouse=True, loop_scope="module")
async def margin_balance_manager(config_data_module, private_key_hex_module):
    rpc_url = config_data_module.get("dex", {}).get("url", "")
    price = "0.00000283"
    size = "10000"
    num_orders = 100

    log.info(f"Adding margin balance for {num_orders} orders")
    await add_margin_balance(rpc_url, price, size, num_orders, private_key_hex_module)
    
    yield  # Tests run here
    
    log.info("Clearing margin account balance")
    await clear_margin_balance(rpc_url, private_key_hex_module)

@pytest.fixture(scope="module") # Changed to module scope, common for xprocess
def dex_proxy_service(xprocess, request, margin_balance_manager):
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    config_file_path = os.path.join("dexes", "kuru", "kuru.local.config.json")

    class DexProxyStarter(ProcessStarter):
        pattern = r"\[WebServer\] Started"
        timeout = 10
        terminate_on_interrupt = True
        args = [
            "python3", 
            os.path.join(project_root, "dex_proxy.py"), # Ensure dex_proxy.py is found from project_root
            "-s", 
            "-c", os.path.join(project_root, config_file_path),
            "-n", "kuru"
        ]
        popen_kwargs = {
            'cwd': project_root,
        }


    xprocess.ensure("dex_proxy_service", DexProxyStarter)

    yield

    log.info("Terminating dex_proxy_service ...")
    xprocess.getinfo("dex_proxy_service").terminate(timeout=20)
    log.info("dex_proxy_service terminated by fixture")

@pytest.fixture
def dex_proxy_proc(dex_proxy_service):
    return dex_proxy_service 

@pytest.fixture
def config_data(config_data_module):
    return config_data_module

@pytest.fixture
def private_key_hex(private_key_hex_module):
    return private_key_hex_module