from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer
from pyutils.exchange_connectors import ConnectorType
from uniswap_shared.uniswap_v3 import UniswapV3


class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config['dex']    
        name = dex_config['name']
        web_server = WebServer(pantheon.config['server'], self, name)
        
        connector_type: ConnectorType = ConnectorType.UniswapV3
        if name == 'chainArb-uni3':
            connector_type = ConnectorType.UniswapV3Arb
        elif name == 'chainFlame-uni3':
            connector_type = ConnectorType.UniswapV3Astria
        elif name == 'chainBera-kod3':
            connector_type = ConnectorType.KodiakV3
        
        super().__init__(pantheon, web_server, UniswapV3(pantheon, dex_config, web_server, self, connector_type))


if __name__ == '__main__':
    pt = Pantheon('uniswap_v3_dex_proxy')
    parser = StandardArgParser('UniswapV3 Dex Proxy')
    pt.load_args_and_config(parser)
    proxy = Main(pt)
    pt.run_app(proxy.run())
