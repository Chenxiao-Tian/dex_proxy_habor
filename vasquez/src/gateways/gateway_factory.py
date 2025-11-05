from gateways.dex_proxy.dex_proxy_gateway import DexProxyGateway

from .gateway import Gateway
from .gte.gte_gateway import GteDexGateway


class GatewayFactory:
    @staticmethod
    def create(exchange: str, config: dict) -> Gateway:
        if exchange == "gte":
            return GteDexGateway(config)
        elif exchange == "dex_proxy":
            return DexProxyGateway(config)

        raise NotImplementedError(
            f"Gateway for exchange {exchange} is not implemented."
        )
