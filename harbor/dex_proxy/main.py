from __future__ import annotations

from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer

from .harbor import Harbor


class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        # 读取 dex 配置
        dex_config = pantheon.config["dex"]
        name = dex_config.get("name", "harbor")

        # 初始化 WebServer（把 self 作为 proxy 传入，便于路由注册）
        web_server = WebServer(pantheon.config["server"], self, name)

        # 构造 DexProxy，同时创建 Harbor 适配器并注入（event_sink 就是 self）
        super().__init__(pantheon, web_server, Harbor(pantheon, dex_config, web_server, self))


def main() -> None:
    # process_name 不能为空，否则会出现 “Pantheon.__init__() missing 1 required positional argument: 'process_name'”
    pantheon = Pantheon("harbor_dex_proxy")

    # 使用标准参数解析器：自动支持 -c/--config 来加载 JSON/YAML 配置
    parser = StandardArgParser("Harbor Dex Proxy")
    pantheon.load_args_and_config(parser)

    # 启动
    proxy = Main(pantheon)
    pantheon.run_app(proxy.run())


if __name__ == "__main__":
    main()
