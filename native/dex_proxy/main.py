from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer

from .native import Native


class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config['dex']
        name = dex_config['name']
        web_server = WebServer(pantheon.config['server'], self, name)
        super().__init__(pantheon, web_server, Native(pantheon, dex_config, web_server, self))

if __name__ == '__main__':
    pt = Pantheon('native_dex_proxy')
    parser = StandardArgParser('Native Dex Proxy')
    pt.load_args_and_config(parser)
    proxy = Main(pt)
    pt.run_app(proxy.run())
