import asyncio
import logging
import pprint


import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from order_generator import rand_id
from market_data import MarketData

from ws_event_waiter import ExpectedEvent, wait_for_ws_events
log = logging.getLogger(__name__)


class TestOrdersManagement:

    @pytest.mark.parametrize(
        "client_order_id,side,order_type,symbol,expected_response_status,calculate_price_and_quantity,price,quantity", [
        pytest.param(None, "SELL", "GTC", "SOL-PERP", 200, True, None, None, id="valid_sell_gtc_order"),
        pytest.param(None, "BUY", "GTC", "SOL-PERP", 200, True, None, None, id="valid_buy_gtc_order"),
        pytest.param(None, "SELL", "GTC_POST_ONLY", "SOL-PERP", 200, True, None, None, id="valid_sell_gtc_post_only_order"),
        pytest.param(None, "BUY", "GTC_POST_ONLY", "SOL-PERP", 200, True, None, None, id="valid_buy_gtc_post_only_success"),
        pytest.param(None, "SELL", "IOC", "SOL-PERP", 200, True, None, None, id="valid_sell_ioc_order"),
        pytest.param(None, "BUY", "IOC", "SOL-PERP", 200, True, None, None, id="valid_buy_ioc_order"),

        pytest.param(f"-{rand_id()}", None, None, None, 400, False, None, None, id="negative_client_order_id"),
        pytest.param("0", None, None, None, 400, False, None, None, id="zero_client_order_id"),
        pytest.param("abc", None, None, None, 400, False, None, None, id="only_letters_client_order_id"),
        pytest.param(None, "SOLD", None, None, 500, False, None, None, id="invalid_side"),
        pytest.param(None, None, "GTZ", None, 500, False, None, None, id="invalid_order_type"),
        pytest.param(None, None, None, "ZZZZZZZ", 500, False, None, None, id="invalid_symbol"),
        pytest.param(None, None, None, None, 400, False, "", None, id="empty_price"),
        pytest.param(None, None, None, None, 400, False, None, "0", id="zero_price"),
        pytest.param(None, None, None, None, 400, False, "zzz.zzz", None, id="invalid_price_with_letters_and_dot"),
        pytest.param(None, None, None, None, 400, False, "zzz", None, id="invalid_price_with_letters"),
        pytest.param(None, None, None, None, 400, False, "500000,111", None, id="invalid_price_with_digits_and_comma"),
        pytest.param(None, None, None, None, 400, False, None, "", id="empty_quantity"),
        pytest.param(None, None, None, None, 400, False, None, "0", id="zero_quantity"),
        pytest.param(None, None, None, None, 400, False, None,"zzz.zzz", id="invalid_quantity_with_letters_and_dot"),
        pytest.param(None, None, None, None, 400, False, None, "zzz", id="invalid_quantity_with_letters"),
        pytest.param(None, None, None, None, 400, False, None, "500000,111", id="invalid_quantity_with_digits_and_comma"),
    ])
    @pytest.mark.asyncio
    async def test_create_order(
            self, api_helper: DexProxyApiTestHelper, market_data: MarketData,
            client_order_id, side, order_type, symbol, expected_response_status, calculate_price_and_quantity, price, quantity):
        await api_helper.cancel_all_orders()

        data = await self._prepare_order_input_data(
            market_data, calculate_price_and_quantity, client_order_id, order_type, price, quantity, side, symbol)

        log.info("Creating order via POST /private/create-order: %s", data)

        retry_on_statuses=None
        if expected_response_status != 200:
            retry_on_statuses = []

        create_response, data = await api_helper.make_order(
            data, expected_status=expected_response_status, retry_on_statuses=retry_on_statuses
        )
        create_json = await create_response.json()
        log.info("Created order response: %s", create_json)

        assert create_response.status == expected_response_status

        if expected_response_status == 200:


            assert create_json["client_order_id"] == int(data["client_order_id"])
            assert create_json["price"] == data["price"]
            assert create_json["quantity"] == data["quantity"]
            assert create_json["symbol"] == data["symbol"]

            expected_order_status = "EXPIRED" if order_type == "IOC" else "OPEN"
            assert create_json["status"] == "OPEN", \
                f"Expected status {expected_order_status}, got {create_json['status']}"

            assert create_json["order_id"] is not None

            if order_type == "GTC" or order_type == "GTC_POST_ONLY":
                await api_helper.cancel_order(data)
        # else:
        #    await api_helper.get_order(data['client_order_id'], 404)

    async def _prepare_order_input_data(self, market_data: MarketData, calculate_price_and_quantity, client_order_id,
                                        order_type, price, quantity, side, symbol):
        side = side or "SELL"
        order_type = order_type or "GTC"
        symbol = symbol or "SOL-PERP"
        if calculate_price_and_quantity:
            if order_type == "GTC" or order_type == "GTC_POST_ONLY":
                data = await market_data.get_gtc_order_data(client_order_id, symbol, side)
            elif order_type == "IOC":
                data = await market_data.get_ioc_order_data(client_order_id, symbol, side)
            else:
                raise ValueError(f"Invalid order_type: {order_type}")
        else:
            data = {
                "price": "50000" if price is None else price,
                "quantity": "0.00001" if quantity is None else quantity,
                "client_order_id": client_order_id or rand_id(),
                "side": side,
                "order_type": order_type,
                "symbol": symbol,
            }
        return data

    @pytest.mark.asyncio
    async def test_get_orders(self, api_helper: DexProxyApiTestHelper, market_data: MarketData):
        await api_helper.cancel_all_orders()

        data = await market_data.get_gtc_order_data(symbol="SOL-PERP")
        create_order_response, data = await api_helper.make_order(data)
        create_order_json = await create_order_response.json()
        log.info("Created order response: %s", create_order_json)

        # Now get all active orders
        orders_response = await api_helper.get_orders()

        response_json = await orders_response.json()
        log.info("Orders response: %s", response_json)

        assert "orders" in response_json
        assert isinstance(response_json["orders"], list)

        # Verify that all returned orders have OPEN status
        for order in response_json["orders"]:
            assert order["status"] == "OPEN"

        # Find our order - it should be there immediately since it starts as OPEN
        our_order = None
        for order in response_json["orders"]:
            if order["client_order_id"] == int(data["client_order_id"]):
                our_order = order
                break

        assert our_order is not None
        assert our_order["price"] == data["price"]
        assert our_order["quantity"] == data["quantity"]
        assert our_order["symbol"] == data["symbol"]
        assert our_order["status"] == "OPEN"

        # Wait for order to be assigned an order_id (transaction completion)
        order_id_exist = await api_helper.check_order_id_was_assigned(data["client_order_id"])
        assert order_id_exist

        await api_helper.cancel_order(data)


    @pytest.mark.parametrize(
        "client_order_id,should_create,expected_status,expect_found,expected_error_code", [
        pytest.param(None, True, 200, True, None, id="order_found"),
        pytest.param(f"{rand_id()}", False, 404, False, "ORDER_NOT_FOUND", id="order_not_found"),
        pytest.param(f"-{rand_id()}", False, 404, False, "ORDER_NOT_FOUND", id="negative_id_not_found"),
        pytest.param("0", False, 404, False, "ORDER_NOT_FOUND", id="zero_id_not_found"),
        pytest.param("abc", False, 400, False, None, id="invalid_id_format"),
        pytest.param("", False, 400, False, None, id="empty_id"),
    ])
    @pytest.mark.asyncio
    async def test_get_single_order(
        self, api_helper: DexProxyApiTestHelper, market_data: MarketData,
        client_order_id, should_create, expected_status, expect_found, expected_error_code,
    ):
        """Param test for GET /public/order: found, not found, invalid id."""
        await api_helper.cancel_all_orders()

        # Create order if needed; wait until order_id is assigned
        if should_create:
            data = await market_data.get_gtc_order_data(client_order_id, symbol="SOL-PERP")
            create_response, data = await api_helper.make_order(data)
            create_json = await create_response.json()
            client_order_id = data["client_order_id"]
            log.info("Created order for retrieval test: %s", create_json)
            # Wait for order_id assignment to avoid flakiness
            assigned = await api_helper.check_order_id_was_assigned(client_order_id)
            assert assigned, "order_id was not assigned in time"
        else:
            # If not creating, generate random unused id when None
            if client_order_id is None:
                client_order_id = rand_id()

        # Perform GET
        order_response = await api_helper.get_order(
            client_order_id, expected_status
        )
        response_json = await order_response.json()
        pprint.pprint(response_json)

        if expect_found and expected_status == 200:
            assert response_json["client_order_id"] == int(client_order_id)
            assert response_json["order_id"] is not None
            assert response_json["price"] is not None
            assert response_json["quantity"] is not None
            assert response_json["symbol"] == "SOL-PERP"
            assert response_json["status"] == "OPEN"
        else:
            # For error pathways, validate error structure when available
            if expected_error_code is not None:
                assert response_json.get("error_code") == expected_error_code

    @pytest.mark.parametrize(
        "client_order_id,should_create_order,expected_response_status,expected_order_status,expected_error_code", [
        pytest.param(rand_id(), True, 200, "OPEN", None, id="cancel_success"),
        pytest.param(rand_id(), False, 404, None, "ORDER_NOT_FOUND", id="cancel_not_found"),
        pytest.param(f"-{rand_id()}", False, 404, None, "ORDER_NOT_FOUND", id="cancel_negative_client_order_id_first_try"),
        pytest.param(0, False, 404, None, "ORDER_NOT_FOUND", id="cancel_zero_int_client_order_id"),
        pytest.param("0", False, 404, None, "ORDER_NOT_FOUND", id="cancel_zero_str_client_order_id"),
        pytest.param("abc", False, 400, None, None , id="cancel_invalid_client_order_id"),
        pytest.param("", False, 400, None, None , id="cancel_empty_client_order_id"),
    ])
    @pytest.mark.asyncio
    async def test_cancel_order(self, api_helper: DexProxyApiTestHelper, market_data: MarketData, client_order_id,
                                          should_create_order, expected_response_status, expected_order_status, expected_error_code):
        #await api_helper.cancel_all_orders()

        if should_create_order:
            data = await market_data.get_gtc_order_data(client_order_id, symbol="SOL-PERP")
            _, data = await api_helper.make_order(data, expected_response_status)
            client_order_id = data["client_order_id"]
            log.info("Created order for cancellation test: %s", data)

        cancel_data = {
            "client_order_id": client_order_id
        }

        log.info("Cancelling order via DELETE %s", cancel_data['client_order_id'])
        cancel_response = await api_helper.cancel_order(cancel_data, expected_response_status)
        log.info("Cancel response status code: %s", cancel_response.status)

        cancel_json = await cancel_response.json()
        assert cancel_response.status == expected_response_status, \
            (f"Expected status code {expected_response_status}, got {cancel_response.status}. "
             f"Response: {await cancel_response.text()}")

        if expected_response_status == 200:
            assert cancel_json["client_order_id"] == int(client_order_id)
            assert cancel_json["status"] == expected_order_status

            await self.check_order_cancelled(api_helper, client_order_id, expected_response_status)

        if expected_error_code is not None:
            assert cancel_json["error_code"] == expected_error_code

        log.info("Cancel order test completed successfully for %s", client_order_id)

    async def check_order_cancelled(self, api_helper, client_order_id, expected_status):
        num_tries = 60
        was_cancelled = False
        for i in range(num_tries):
            check_order_response = await api_helper.get_order(client_order_id, expected_status)
            check_order_json = await check_order_response.json()
            log.info("Cancelled order details: %s", check_order_json)

            if check_order_json["status"] != "CANCELLED":
                log.info("Waiting for order should be cleared (%s) ... %s/%s", client_order_id, i + 1, num_tries)
                await asyncio.sleep(1)
            else:
                was_cancelled = True
                break
        assert was_cancelled, f"Order {client_order_id} was not cancelled after {num_tries} tries"


    @pytest.mark.asyncio
    async def test_cancel_all_orders(self, api_helper: DexProxyApiTestHelper, market_data: MarketData):
        # await api_helper.cancel_all_orders()

        client_order_ids = []
        num_orders = 3
        for i in range(num_orders):
            client_order_id = str(rand_id())
            log.info("Creating order %s", i + 1)
            create_data = await market_data.get_gtc_order_data(client_order_id, symbol="SOL-PERP")
            _, create_data = await api_helper.make_order(create_data)
            client_order_ids.append(create_data["client_order_id"])

        async with api_helper.ws_connect() as ws:
            await api_helper.ws_subscribe(ws)

            log.info("Cancelling all orders ...")
            cancel_response = await api_helper.cancel_all_orders(False)

            assert cancel_response.status == 200

            cancel_json = await cancel_response.json()
            assert "cancelled" in cancel_json

            created_order_ids_set = {int(client_order_id) for client_order_id in client_order_ids}
            cancelled_order_ids_set = set(cancel_json["cancelled"])
            assert created_order_ids_set.issubset(cancelled_order_ids_set)

            expected_events = []
            for client_order_id in client_order_ids:
                expected_events.append(ExpectedEvent(
                    channel="ORDER",
                    required_data={
                        "status": "CANCELLED",
                        "client_order_id": int(client_order_id),
                    },
                    alias=f"cancel_{client_order_id}"
                ))

            timeout = 35
            matched = await wait_for_ws_events(ws, expected_events, timeout=timeout, on_event=lambda e: log.info("WS cancel possible event: %s", e))
            log.info("Matched WS events: %s", matched)

            for client_order_id in client_order_ids:
                await self.check_order_cancelled(api_helper, client_order_id, 200)

