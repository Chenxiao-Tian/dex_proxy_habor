from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer

from dex_proxy.uniswap_v34 import UniswapV34

class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config['dex']
        
        # Enable capital efficient mode by default
        if "capital_efficient" not in dex_config:
            dex_config["capital_efficient"] = True
            
        name = dex_config['name']
        web_server = WebServer(pantheon.config['server'], self, name)
        
        # Create the UniswapV34 instance that supports both V3 and V4
        self.uniswap_v34 = UniswapV34(pantheon, dex_config, web_server, self)
        
        super().__init__(pantheon, web_server, self.uniswap_v34)

if __name__ == '__main__':
    pt = Pantheon('uniswap_v34_dex_proxy')
    parser = StandardArgParser('Uniswap V3/V4 Dex Proxy')
    pt.load_args_and_config(parser)
    proxy = Main(pt)
    pt.run_app(proxy.run())
