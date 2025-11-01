import asyncio
import logging
import os
import signal
import subprocess
from typing import Tuple, Optional, Any

import pytest
import pytest_asyncio
from aiohttp import web, ClientTimeout
from aiohttp.test_utils import BaseTestServer
from aiohttp.web_runner import ServerRunner
from yarl import URL
from pantheon import Pantheon, StandardArgParser
from xprocess import ProcessStarter

from py_dex_common.dex_proxy import DexProxy
from common import configure_test_logging, get_option_value, register_option
from dex_proxy_api_test_helper import DexProxyApiTestHelper, print_stats
from drft.dex_proxy.main import Main
from market_data import MarketData
from order_generator import OrderGenerator
from exchange_helper import ExchangeHelper

configure_test_logging()


log = logging.getLogger(__name__)

CONFIG_OPT_NAME = 'dex-proxy-config'
INTERNAL_PROXY_OPT_NAME = 'internal-proxy'
ADD_TOXICS_OPT_NAME = 'add-toxics'
OUTSIDE_PROXY_HOST_OPT_NAME = 'outside-proxy-host'
OUTSIDE_PROXY_PORT_OPT_NAME = 'outside-proxy-port'


def pytest_addoption(parser):
    register_option(parser, CONFIG_OPT_NAME, 'Default DexProxy config for tests', '')
    register_option(parser, ADD_TOXICS_OPT_NAME, 'Add Toxiproxy toxics during tests', '')
    register_option(parser, INTERNAL_PROXY_OPT_NAME, 'Run proxy in the same process as tests', '')
    register_option(parser, OUTSIDE_PROXY_HOST_OPT_NAME, 'Host of externally started dex_proxy', '')
    register_option(parser, OUTSIDE_PROXY_PORT_OPT_NAME, 'Port of externally started dex_proxy', '')


@pytest.fixture
def dex_proxy_config(pytestconfig):
    return get_option_value(pytestconfig, CONFIG_OPT_NAME)


@pytest.fixture(scope="session")
def internal_proxy(pytestconfig) -> bool:
    return get_option_value(pytestconfig, INTERNAL_PROXY_OPT_NAME).lower() in ['true', '1', 'yes']


@pytest.fixture
def add_toxics(pytestconfig) -> bool:
    return get_option_value(pytestconfig, 'add-toxics').lower() in ['true', '1', 'yes']

@pytest.fixture(scope="session")
def outside_proxy_host(pytestconfig) -> str:
    return get_option_value(pytestconfig, 'outside-proxy-host')


@pytest.fixture(scope="session")
def outside_proxy_port(pytestconfig) -> int:
    val = get_option_value(pytestconfig, 'outside-proxy-port')
    return 0 if not val else int(val)


async def pre_initialize_dex_proxy_hook(dex_proxy_config):
    # Cancel all orders before starting tests
    await ExchangeHelper.cancel_all_orders(make_project_root(), dex_proxy_config)

async def create_app(dex_proxy_config) -> Tuple[web.Application, DexProxy, Pantheon]:
    await pre_initialize_dex_proxy_hook(dex_proxy_config)

    log.info("Creating app")
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    config_file_path = os.path.join(dex_proxy_config)
    os.chdir(project_root)
    log.info("Internal proxy project root: %s", project_root)

    pt = Pantheon('dex_proxy', enable_loop_measurement=False)
    parser = StandardArgParser('Dex Proxy')
    # TODO: hardcoded name of Dex Proxy
    custom_args = ["-s",  "-c", os.path.join(project_root, config_file_path), "-n", "drft"]
    pt.load_args_and_config(parser, custom_args)
    proxy = Main(pt)

    pt.spawn(proxy.run())

    app = proxy._DexProxy__server._WebServer__app
    return app, proxy, pt

class ExternalTestServer(BaseTestServer):
    def __init__(
            self,
            *,
            scheme: str = "",
            host: str = "127.0.0.1",
            port: Optional[int] = None,
            **kwargs: Any,
    ) -> None:
        super().__init__(scheme=scheme, host=host, port=port, **kwargs)
        self.runner = True
        self._root = URL(f"{self.scheme}://{self.host}:{self.port}")

    async def _make_runner(self, debug: bool = True, **kwargs: Any) -> ServerRunner:
        # It should not create any runner as a process was run separately
        pass
    async def close(self) -> None:
        # It should not close anything as a process was run separately
        pass


dex_proxy_started = False
async def start_dex_proxy_process(xprocess, dex_proxy_config):
    global dex_proxy_started
    if not dex_proxy_started:
        await pre_initialize_dex_proxy_hook(dex_proxy_config)

        log.info("Starting dex_proxy process with config: %s", dex_proxy_config)
        project_root = make_project_root()

        class DexProxyTestStarter(ProcessStarter):
            pattern = r"\[WebServer\] Started"
            timeout = 30
            terminate_on_interrupt = True
            max_read_lines = 30000
            # python3 -u -m dex_proxy.main -s -c gte.config.json -n gte
            args = [
                "python3",
                "-u",
                "-m",
                "dex_proxy.main",
                "-s",
                "-c", dex_proxy_config,
                # TODO: remove hardcoded ethereal mention
                "-n", "drft"
            ]
            popen_kwargs = {
                'cwd': project_root,
            }

        max_retries = 6
        for attempt in range(max_retries):
            try:
                xprocess.ensure("dex_proxy_process", DexProxyTestStarter)
                break  # Success, exit the retry loop
            except TimeoutError:
                if attempt < max_retries - 1:  # Not the last attempt
                    log.warning(f"TimeoutError on attempt {attempt + 1}/{max_retries}, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    log.error(f"Failed to start dex_proxy_process after {max_retries} attempts")
                    raise  # Re-raise the exception on the last attempt

        # Workaround to wait while dex_proxy fully subscribed to WS events
        await asyncio.sleep(10)

        dex_proxy_started = True


def make_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


@pytest.fixture(scope="session")
def market_data() -> MarketData:
    return MarketData(OrderGenerator())

@pytest.fixture(scope="function")
def api_helper(client) -> DexProxyApiTestHelper:
    return DexProxyApiTestHelper(client)


def run_command(command: list[str]):
    log.info("Running command: %s", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout:
        log.info("stdout:\n%s", result.stdout)
    if result.stderr:
        log.error("stderr:\n%s", result.stderr)
    result.check_returncode()


def add_toxic_latency_to_proxy_by_name(proxy_name: str, toxic_name: str, latency: int):
    log.info("Adding toxic latency to proxy %s with toxic name %s and latency %s", proxy_name, toxic_name, latency)
    command = ["docker", "exec", "dexproxy_toxiproxy", "/toxiproxy-cli", "toxic", "add", "-t", "latency",
               "-a", f"latency={latency}", "--toxicName", f"{toxic_name}", f"{proxy_name}"]
    run_command(command)


def remove_toxic_from_proxy_by_name(proxy_name: str, toxic_name: str):
    log.info("Removing toxic from proxy %s with toxic name %s", proxy_name, toxic_name)
    command = ["docker", "exec", "dexproxy_toxiproxy", "/toxiproxy-cli", "toxic", "remove",
               "--toxicName", f"{toxic_name}", f"{proxy_name}"]
    run_command(command)


@pytest_asyncio.fixture(scope="function", loop_scope="function")
async def client(aiohttp_client, xprocess, dex_proxy_config, add_toxics, internal_proxy, outside_proxy_host, outside_proxy_port):
    timeout = ClientTimeout(total=30)

    if internal_proxy:
        log.info("Starting internal Aiohttp Dex Proxy process ...")
        app, proxy, _ = await create_app(dex_proxy_config)
        log.info("Internal Aiohttp Dex Proxy process started. Waiting before client creation ...")
        await asyncio.sleep(20)
        client = await aiohttp_client(app, timeout=timeout)
        log.info("Client created")
    else:
        proxy_host = "localhost"
        proxy_port = 1958
        if not outside_proxy_host:
            await start_dex_proxy_process(xprocess, dex_proxy_config)
        else:
            proxy_host = outside_proxy_host
            proxy_port = outside_proxy_port
        test_server = ExternalTestServer(scheme="http", host=proxy_host, port=proxy_port)

        client = await aiohttp_client(test_server, timeout=timeout)

    if add_toxics:
        toxic_name = "high_latency"
        proxy_name = "rpc_1"
        add_toxic_latency_to_proxy_by_name(proxy_name, toxic_name, 5000)

    yield client

    if add_toxics:
        remove_toxic_from_proxy_by_name(proxy_name, toxic_name)

    if internal_proxy:
        log.info("Stopping proxy ...")
        proxy.stop(sig=signal.SIGTERM)
        # TODO: implement some flag or async feature which we can wait while proxy fully stope in proxy.run()
        await asyncio.sleep(6)
        log.info("Proxy supposed to be stopped")

@pytest.fixture(scope="session", autouse=True)
def after_all_tests(xprocess, internal_proxy):
    yield

    print_stats()

    if not internal_proxy:
        log.info("Terminating xprocess dex_proxy_process ...")
        xprocess.getinfo("dex_proxy_process").terminate(timeout=20)
        log.info("xprocess dex_proxy_process terminated by fixture")

