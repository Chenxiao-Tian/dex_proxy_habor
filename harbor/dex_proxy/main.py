from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer

from .harbor import Harbor


class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config["dex"]
        name = dex_config["name"]
        web_server = WebServer(pantheon.config["server"], self, name)
        super().__init__(pantheon, web_server, Harbor(pantheon, dex_config, web_server, self))


def main() -> None:
    pantheon = Pantheon("harbor_dex_proxy")
    parser = StandardArgParser("Harbor Dex Proxy")
    pantheon.load_args_and_config(parser)
    proxy = Main(pantheon)
    pantheon.run_app(proxy.run())


if __name__ == "__main__":
    main()
