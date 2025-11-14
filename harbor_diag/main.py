# harbor/dex_proxy/main.py
from __future__ import annotations

from aiohttp import web
from pantheon import Pantheon, StandardArgParser
from py_dex_common.dex_proxy import DexProxy
from py_dex_common.web_server import WebServer

from .harbor import Harbor
from .compat_routes import register_compat_routes


def _register_debug_routes(app: web.Application) -> None:
    async def debug_routes(request: web.Request):
        items = []
        for r in request.app.router.routes():
            try:
                items.append({
                    "method": getattr(r, "method", ""),
                    "path": r.resource.canonical if r.resource else "",
                    "name": r.name or "",
                })
            except Exception:
                pass
        return web.json_response({"routes": items, "count": len(items)})

    app.router.add_get("/debug/routes", debug_routes)


class Main(DexProxy):
    def __init__(self, pantheon: Pantheon):
        dex_config = pantheon.config["dex"]
        name = dex_config.get("name", "harbor")

        # 初始化 WebServer（注意：WebServer 需要 server 配置 + proxy 实例 + 名称）
        web_server = WebServer(pantheon.config["server"], self, name)

        # 构造 Harbor 适配器（内部会注册标准路由）
        harbor_adapter = Harbor(pantheon, dex_config, web_server, self)

        # 额外注册“兼容/别名”路由，覆盖下划线/连字符 & 带不带 /harbor 的差异
        register_compat_routes(
            web_server,
            create_order=harbor_adapter.create_order,
            insert_order=harbor_adapter.insert_order,
            cancel_request=harbor_adapter.cancel_request,
            cancel_all=harbor_adapter.cancel_all,
            list_open_orders=harbor_adapter.list_open_orders,
        )

        # 调试路由（列出所有已注册路由）
        _register_debug_routes(web_server.app)

        # 交给 DexProxy 框架
        super().__init__(pantheon, web_server, harbor_adapter)


def main() -> None:
    pantheon = Pantheon("harbor_dex_proxy")
    parser = StandardArgParser("Harbor Dex Proxy")
    pantheon.load_args_and_config(parser)

    proxy = Main(pantheon)
    pantheon.run_app(proxy.run())


if __name__ == "__main__":
    main()

