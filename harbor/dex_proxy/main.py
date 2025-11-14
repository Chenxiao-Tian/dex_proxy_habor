# harbor/dex_proxy/main.py
from __future__ import annotations

from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer

from .harbor import Harbor
from .compat_routes import register_compat_routes, register_admin_mock_routes

# 在创建 Harbor 之前注册（first-wins）
from .compat_ticker_binance import make_binance_ticker_handler  # 顶部已 try/except 导入也可
if make_binance_ticker_handler is not None:
    try:
        web_server.register("GET", "/public/ticker", make_binance_ticker_handler())
    except Exception:
        pass

# 兼容行情（存在则导入；不存在也不报错）
try:
    from .compat_depth_binance import make_binance_depth_handler  # type: ignore
except Exception:  # noqa: BLE001
    make_binance_depth_handler = None  # type: ignore[misc]

try:
    from .compat_ticker_binance import make_binance_ticker_handler  # type: ignore
except Exception:  # noqa: BLE001
    make_binance_ticker_handler = None  # type: ignore[misc]


class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config["dex"]
        name = dex_config.get("name", "harbor")

        # 1) WebServer
        web_server = WebServer(pantheon.config["server"], self, name)
        pantheon.app = web_server.app

        harbor_adapter = Harbor(pantheon, dex_config, web_server, self)
        # 2) 第一阶段：至少提供 /public/balance（旧 Vasquez 依赖）
       # register_compat_routes(web_server)

        # 2.5) **关键**：在创建 Harbor 之前，先注册兼容行情端点（first-wins）
        if make_binance_depth_handler is not None:
            try:
                # 深度：支持 ?symbol=eth.eth-eth.usdt 或 ?instrument=harbor-ETH/USDT=0
                web_server.register("GET", "/public/depth", make_binance_depth_handler())
                # 常见旧别名
                web_server.register("GET", "/public/harbor/get_depth_snapshot", make_binance_depth_handler())
            except Exception:
                pass

        if make_binance_ticker_handler is not None:
            try:
                # ticker：支持 ?symbol=... 或 ?instrument=...
                web_server.register("GET", "/public/ticker", make_binance_ticker_handler())
            except Exception:
                pass
        
        # 3) 创建 Harbor 适配器（内部会注册它自己的路由；由于 first-wins，上面的兼容口会保留）
        

        # 4) 把兼容/别名映射到 Harbor 的真实实现（若存在）
        register_compat_routes(
            web_server,
            create_order=harbor_adapter.create_order,
            insert_order=getattr(harbor_adapter, "insert_order", None),
            cancel_request=harbor_adapter.cancel_request,
            cancel_all=harbor_adapter.cancel_all,
            list_open_orders=harbor_adapter.list_open_orders,
            get_markets=getattr(harbor_adapter, "get_markets", None),
            get_depth_snapshot=getattr(harbor_adapter, "get_depth_snapshot", None),
            
        )
        
        register_admin_mock_routes(web_server)

        # 5) 交给 DexProxy
        super().__init__(pantheon, web_server, harbor_adapter)
        # 👇 加上这一段
        print("=== AFTER DexProxy INIT ROUTES ===")
        for r in web_server.app.router.routes():
            res = getattr(r.resource, "_path", "?")
            print(f"{r.method} {res}")
        print("===================================")


def main() -> None:
    pantheon = Pantheon("harbor_dex_proxy")
    parser = StandardArgParser("Harbor Dex Proxy")
    pantheon.load_args_and_config(parser)

    proxy = Main(pantheon)
    pantheon.run_app(proxy.run())


if __name__ == "__main__":
    main()
