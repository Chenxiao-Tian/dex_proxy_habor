from __future__ import annotations
from typing import Callable, Dict, Any, List, Optional
from aiohttp import web

# =============== 基础工具函数 ===============
def _wrap_const_json(resp: Dict[str, Any]):
    async def _h(_path: str, _params: Dict[str, Any], _t: int):
        return 200, resp
    return _h


def _wrap_passthrough(h):
    """Harbor 适配器里的 handler 已经是 (path, params, t) -> (status, data)，直接透传。"""
    async def _h(path: str, params: Dict[str, Any], t: int):
        return await h(path, params, t)
    return _h


def _wrap_cancel_request_with_body_mapping(h):
    """
    兼容 Vasquez 的撤单 body：
      { "exchangeOrderId": "vasquez-test-001" }
    Harbor 的 cancel_request 需要:
      { "client_request_id": "vasquez-test-001" }
    """
    async def _h(path: str, params: Dict[str, Any], t: int):
        body = params.get("body") or {}
        client_request_id = (
            body.get("exchangeOrderId")
            or body.get("clientOrderId")
            or body.get("client_request_id")
        )
        if not client_request_id:
            return 400, {"error": {"message": "Missing field 'client_request_id' / 'exchangeOrderId'"}}
        mapped = {"client_request_id": client_request_id}
        mapped_params = dict(params)
        mapped_params["body"] = mapped
        return await h(path, mapped_params, t)
    return _h


# =============== 默认公共余额注册（用于启动阶段） ===============
def _register_public_balance(server, *, symbols: Optional[List[str]] = None) -> None:
    """
    Vasquez 旧网关预期的响应形状必须是：
      {"exchange":[{"symbol":"ETH","free":"0","locked":"0"}, ...]}
    """
    if not symbols:
        symbols = ["ETH", "USDT", "BTC"]

    exchange = [{"symbol": s, "free": "0", "locked": "0"} for s in symbols]
    server.register("GET", "/public/balance", _wrap_const_json({"exchange": exchange}))


# =============== Mock 余额逻辑（admin测试接口） ===============
#_mock_balances: Dict[str, Dict[str, Any]] = {}

_mock_balances = {}

def register_admin_mock_routes(server):
    print(f"[DEBUG] register_admin_mock_routes app id={id(server.app)}")

    from aiohttp import web

    app = server.app
    if "mock_balances" not in app:
        app["mock_balances"] = {}
    print("[INIT] mock_balances initialized ->", app["mock_balances"])

    async def set_balance(request):
        print(f"[DEBUG] set_balance app id={id(app)}")
        data = await request.json()
        sym = data["symbol"]
        bal = data["balance"]
        dec = data.get("decimals", 6)
        app["mock_balances"][sym] = {"symbol": sym, "balance": bal, "decimals": dec}
        print(f"[SET_BALANCE] app['mock_balances']={app['mock_balances']}")
        return web.json_response({
            "status": "ok",
            "balances": list(app["mock_balances"].values()),
        })

    async def get_balance(request):
        print("[DEBUG] get_balance called")
        print(f"[DEBUG] get_balance app id={id(app)}")

        print(f"[DEBUG] get_balance app id={id(app)}")
        print(f"[GET_BALANCE] app['mock_balances']={app['mock_balances']}")
        balances = [
            {"symbol": sym, "free": bal["balance"], "locked": "0"}
            for sym, bal in app["mock_balances"].items()
        ]
        return web.json_response({"exchange": balances})


    # === 移除旧的 /public/balance ===
    to_remove = []
    for res in list(app.router._resources):
        if getattr(res, "_path", None) == "/public/balance":
            to_remove.append(res)
    for res in to_remove:
        app.router._resources.remove(res)
    print(f"[CLEANUP] removed {len(to_remove)} old /public/balance routes")

    # 注册 mock 版
    app.router.add_post("/private/admin/set_balance", set_balance)
    app.router.add_get("/public/balance", get_balance)

    print("✅ Mock admin routes registered, linked to app['mock_balances']")
    for r in app.router.routes():
        res = getattr(r.resource, "_path", "?")
        if res == "/public/balance":
            print(f"⚡ Active balance route -> {r.method} {res}")
    
    print("=== FINAL ROUTE DUMP ===")
    for r in app.router.routes():
        path = getattr(r.resource, "_path", "?")
        print(f"{r.method} {path} -> {r.handler}")
    print("=========================")





# =============== 兼容路由注册（Harbor核心适配） ===============
def register_compat_routes(
    server,
    *,
    create_order: Optional[Callable] = None,
    insert_order: Optional[Callable] = None,
    cancel_request: Optional[Callable] = None,
    cancel_all: Optional[Callable] = None,
    list_open_orders: Optional[Callable] = None,
    get_markets: Optional[Callable] = None,
    get_depth_snapshot: Optional[Callable] = None,
) -> None:
    """
    两阶段用法：
    1) Harbor 适配器构建**之前**调用：注册 /public/balance (零余额占位)
    2) Harbor 适配器构建**之后**调用：注册各兼容路由映射
    """
    # 阶段 1：先注册默认 /public/balance
    _register_public_balance(server)

    # 阶段 2：映射真实实现
    if get_markets is not None:
        server.register("GET", "/public/markets", _wrap_passthrough(get_markets))

    if get_depth_snapshot is not None:
        server.register("GET", "/public/depth", _wrap_passthrough(get_depth_snapshot))

    if create_order is not None:
        for p in [
            "/private/orders",
            "/private/create-order",
            "/private/create_order",
            "/private/harbor/create-order",
            "/private/harbor/create_order",
        ]:
            server.register("POST", p, _wrap_passthrough(create_order))

    if insert_order is not None:
        for p in [
            "/private/insert-order",
            "/private/harbor/insert-order",
        ]:
            server.register("POST", p, _wrap_passthrough(insert_order))

    if cancel_request is not None:
        server.register("POST", "/private/orders/cancel", _wrap_cancel_request_with_body_mapping(cancel_request))

    if cancel_all is not None:
        for p in [
            "/private/cancel-all",
            "/private/cancel_all",
            "/private/harbor/cancel-all",
            "/private/harbor/cancel_all",
        ]:
            server.register("DELETE", p, _wrap_passthrough(cancel_all))

    if list_open_orders is not None:
        for p in [
            "/public/orders",
            "/private/list-open-orders",
            "/private/list_open_orders",
            "/private/harbor/list-open-orders",
            "/private/harbor/list_open_orders",
        ]:
            server.register("GET", p, _wrap_passthrough(list_open_orders))
