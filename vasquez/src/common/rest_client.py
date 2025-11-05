import aiohttp
import logging

from yarl import URL
from types import TracebackType
from typing import Optional, Type
from typing_extensions import Self

from chainflip_jit_mm.chainflip.types import JSONType


class HttpError(Exception):
    def __init__(self, error_message: str, http_code: int):
        super().__init__(error_message)
        self.http_code = http_code


class RpcError(Exception):
    def __init__(self, error_message):
        super().__init__(error_message)


class RestClient:
    def __init__(self, name, url: str, headers: dict = None) -> None:
        self.logger = logging.getLogger(f"{name}.REST")
        self.url = url
        auth = aiohttp.BasicAuth.from_url(URL(self.url, encoded=True))
        self._client = aiohttp.ClientSession(headers=headers, auth=auth)
        self.id = 1

    async def close(self) -> None:
        return await self._client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        await self.close()
        return None

    async def rpc(self, method: str, params: list | dict) -> JSONType:
        data = {
            "id": self.id,
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        self.id += 1

        j = await self.post("", data)

        error = j.get("error")
        if error is not None:
            raise RpcError(error["message"])

        return j["result"]

    async def post(self, path: str, data: dict) -> dict:
        url_no_password = URL(self.url).with_password(None)
        self.logger.debug(f"Posting %s to %s", data, url_no_password)
        url = self.url + path
        async with self._client.post(url, json=data) as resp:
            http_code = resp.status
            j = await resp.json()
            self.logger.debug(f"Posted {j} {resp.status}")
            self.__check_http_errors(url_no_password, http_code)
            return j

    async def get(self, path: str) -> dict:
        url = self.url + path
        self.logger.debug(f"Fetching %s", url)
        async with self._client.get(url) as resp:
            http_code = resp.status
            j = await resp.json()
            self.logger.debug(f"Fetched {j} {resp.status}")
            self.__check_http_errors(url, http_code)
            return j

    async def delete(self, path: str) -> dict:
        url = self.url + path
        async with self._client.delete(url) as resp:
            http_code = resp.status
            j = await resp.json()
            self.__check_http_errors(url, http_code)
            return j

    @staticmethod
    def __check_http_errors(url, http_code):
        if http_code == 429:
            raise HttpError("Rate limit breached", http_code)
        elif http_code != 200:
            raise HttpError(f"Unable to access {url}", http_code)
