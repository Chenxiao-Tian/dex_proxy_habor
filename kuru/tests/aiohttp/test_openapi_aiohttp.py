import pytest
from aiohttp import ClientTimeout
from aiohttp.test_utils import TestClient


class TestOpenapiAiohttp:

    @pytest.mark.asyncio
    async def test_openapi_aiohttp(self, client: TestClient):
        orders_response = await client.get("openapi.json", timeout=ClientTimeout(total=60))
        assert orders_response.status == 200
