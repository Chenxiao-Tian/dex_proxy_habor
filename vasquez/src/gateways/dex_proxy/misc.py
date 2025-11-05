import logging
from typing import Optional, Any

from aiohttp.test_utils import BaseTestServer, TestClient
from aiohttp.web_runner import ServerRunner
from aiohttp import ClientTimeout

from yarl import URL


log = logging.getLogger(__name__)

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

def http_client(config):
    timeout = ClientTimeout(total=30)
    test_server = ExternalTestServer(
        scheme=config['dex_proxy']['server']['scheme'],
        host=config['dex_proxy']['server']['hostname'],
        port=int(config['dex_proxy']['server']['port'])
    )

    return TestClient(test_server, timeout=timeout)
