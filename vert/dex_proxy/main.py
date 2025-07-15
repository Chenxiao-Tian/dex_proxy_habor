from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer
import sys
from .vert import Vert



class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config['dex']    
        name = dex_config['name']
        web_server = WebServer(pantheon.config['server'], self, name)
        super().__init__(pantheon, web_server, Vert(pantheon, dex_config, web_server, self))

if __name__ == '__main__':
   
    print(sys.path)

    pt = Pantheon('vert_dex_proxy')
    parser = StandardArgParser('Vert Dex Proxy')
    pt.load_args_and_config(parser)
    proxy = Main(pt)
    pt.run_app(proxy.run())
