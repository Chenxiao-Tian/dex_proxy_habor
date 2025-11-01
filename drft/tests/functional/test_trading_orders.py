import asyncio
import logging

import pytest

from aiohttp.test_utils import TestClient

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_numeric_string, assert_is_valid_solana_address, assert_is_int, POSITIVE, NON_NEGATIVE
from ws_event_waiter import ExpectedEvent, wait_for_ws_events
from market_data import MarketData

log = logging.getLogger(__name__)


class TestTradingOrders:

    @pytest.mark.asyncio
    async def test_get_status(self, client: TestClient):
        status_response = await client.get('/public/status')
        assert status_response.status == 200

    @pytest.mark.asyncio
    async def test_price(self, market_data):
        gtc_price = await market_data.get_price_for_gtc_order('SOL-PERP')
        log.info("GTC default gtc_price: %s", gtc_price)
        assert gtc_price is not None

        gtc_price = await market_data.get_price_for_gtc_order('SOL-PERP', side="SELL")
        log.info("GTC side SELL gtc_price: %s", gtc_price)
        assert gtc_price is not None

        gtc_price = await market_data.get_price_for_gtc_order('SOL-PERP', side="BUY")
        log.info("GTC side BUY gtc_price: %s", gtc_price)
        assert gtc_price is not None

        ioc_price = await market_data.get_price_for_ioc_order('SOL-PERP')
        log.info("IOC default gtc_price: %s", ioc_price)
        assert ioc_price is not None

        ioc_price = await market_data.get_price_for_ioc_order('SOL-PERP', side="SELL")
        log.info("IOC side SELL gtc_price: %s", ioc_price)
        assert ioc_price is not None

        ioc_price = await market_data.get_price_for_ioc_order('SOL-PERP', side="BUY")
        log.info("IOC side BUY gtc_price: %s", ioc_price)
        assert ioc_price is not None

    @pytest.mark.asyncio
    async def test_trade_gtc_order_functional(self, api_helper: DexProxyApiTestHelper, market_data: MarketData):
        await api_helper.cancel_all_orders()

        data = await market_data.get_gtc_order_data()

        async with api_helper.ws_connect() as ws:
            await api_helper.ws_subscribe(ws)

            log.info("Placing an order with data: %s" % data)
            _, data = await api_helper.make_order(data)

            log.info("Order created. Waiting for WebSocket event ... ")

            expected = [
                ExpectedEvent(
                    channel="ORDER",
                    required_data={
                        "status": "OPEN",
                        "client_order_id": int(data["client_order_id"]),
                        "price": data["price"],
                        "quantity": data["quantity"],
                        "symbol": data["symbol"],
                        "order_type": data["order_type"],
                        "side": data["side"],
                    },
                    alias="order_created",
                )
            ]

            matched = await wait_for_ws_events(ws, expected, timeout=35)
            order_created_event = matched["order_created"]
            log.info("Order created event: %s", order_created_event)


            log.info("Canceling thes order ...")
            await api_helper.cancel_order(data)

            log.info("Order canceled. Waiting for WebSocket event ... ")

            expected = [
                ExpectedEvent(
                    channel="ORDER",
                    required_data={
                        "status": "CANCELLED",
                        "client_order_id": int(data["client_order_id"]),
                        "price": data["price"],
                        "quantity": data["quantity"],
                        "symbol": data["symbol"],
                        "order_type": data["order_type"],
                        "side": data["side"],
                    },
                    alias="order_cancelled",
                )
            ]

            matched = await wait_for_ws_events(ws, expected, timeout=35)
            order_cancelled_event = matched["order_cancelled"]
            log.info("Order canceled event: %s", order_cancelled_event)



    @pytest.mark.asyncio
    async def test_trade_ioc_order_functional(self, api_helper: DexProxyApiTestHelper, market_data: MarketData):
        await api_helper.cancel_all_orders()
        data = await market_data.get_ioc_order_data()

        order_data = {}
        async with api_helper.ws_connect() as ws:
            await api_helper.ws_subscribe(ws)

            log.info("Placing an order ...")
            response, data = await api_helper.make_order(data)

            log.info(f"Order created ({await response.json()}) for data ({data}). Waiting for WebSocket event ... ")
            order_confimed_event = await ws.receive_json(timeout=35)
            log.info(f"Order confirmed event: {order_confimed_event}")

            assert "params" in order_confimed_event
            assert "data" in order_confimed_event["params"]

            order_data = order_confimed_event["params"]["data"]
            assert order_data["status"] == "EXPIRED" or order_data["status"] == "OPEN", \
                f"Unexpected order status: {order_data['status']}, must be EXPIRED or OPEN"
            assert len(str(order_data["order_id"])) > 0
            assert order_data["client_order_id"] == int(data["client_order_id"])
            assert order_data["price"] == data["price"]
            assert order_data["quantity"] == data["quantity"]
            assert order_data["symbol"] == data["symbol"]
            assert order_data["order_type"] == data["order_type"]
            assert order_data["side"] == data["side"]


            log.info("Waiting for order to be traded ...")
            order_traded_event = await ws.receive_json(timeout=35)
            log.info(f"Order traded event: {order_traded_event}")

            assert "params" in order_traded_event
            assert "data" in order_traded_event["params"]

            order_data = order_traded_event["params"]["data"]
            assert order_data["status"] == "EXPIRED", \
                f"Unexpected order status: {order_data['status']}, must be EXPIRED"
            assert order_data["client_order_id"] == int(data["client_order_id"])
            assert float(order_data["total_exec_quantity"]) > 0
            assert len(order_data["trades"]) > 0

            total_exec_quantity = 0
            for trade in order_data["trades"]:
                assert int(trade["trade_id"]) > 0
                assert float(trade["exec_price"]) >= float(data["price"])
                total_exec_quantity += float(trade["exec_quantity"])

            assert total_exec_quantity == float(data["quantity"])

        trades_response = await api_helper.get_trades()
        trades_json = await trades_response.json()
        log.info(f"Trades received by /public/trades: {trades_json}")
        found = False
        for tr in trades_json['records']:
            if int(tr["takerOrderId"]) == int(order_data["order_id"]):
                found = True
                self._validate_trade_record(tr)
                break
        assert found, "Trade not found in trades list"

        await asyncio.sleep(5)

    def _validate_trade_record(self, record):
        log.info(f"Validating trade record: {record}")

        assert isinstance(record, dict), f"Each record must be a dict, got {type(record)}"

        # Required fields in each trade record
        required_fields = [
            'action', 'actionExplanation', 'baseAssetAmountFilled', 'bitFlags', 'fillRecordId', 'filler',
            'fillerReward', 'maker', 'makerExistingBaseAssetAmount', 'makerExistingQuoteEntryAmount',
            'makerFee', 'makerOrderBaseAssetAmount', 'makerOrderCumulativeBaseAssetAmountFilled',
            'makerOrderCumulativeQuoteAssetAmountFilled', 'makerOrderDirection', 'makerOrderId', 'makerRebate',
            'marketFilter', 'marketIndex', 'marketType', 'oraclePrice', 'quoteAssetAmountFilled',
            'quoteAssetAmountSurplus', 'referrerReward', 'slot', 'spotFulfillmentMethodFee', 'symbol', 'taker',
            'takerExistingBaseAssetAmount', 'takerExistingQuoteEntryAmount', 'takerFee',
            'takerOrderBaseAssetAmount', 'takerOrderCumulativeBaseAssetAmountFilled',
            'takerOrderCumulativeQuoteAssetAmountFilled', 'takerOrderDirection', 'takerOrderId', 'ts', 'txSig',
            'txSigIndex', 'user'
        ]
        for field in required_fields:
            assert field in record, f"Trade record must contain '{field}'"

        # Validate action
        action = record['action']
        assert isinstance(action, str), f"'action' must be string, got {type(action)}"
        assert action in ['fill', 'liquidate'], f"'action' must be 'fill' or 'liquidate', got {action}"

        # Validate actionExplanation
        action_explanation = record['actionExplanation']
        assert isinstance(action_explanation, str), (
            f"'actionExplanation' must be string, got {type(action_explanation)}"
        )

        # Validate amounts (string with decimals)
        amount_fields = [
            'baseAssetAmountFilled', 'makerExistingBaseAssetAmount', 'makerExistingQuoteEntryAmount',
            'makerFee', 'makerOrderBaseAssetAmount', 'makerOrderCumulativeBaseAssetAmountFilled',
            'makerOrderCumulativeQuoteAssetAmountFilled', 'quoteAssetAmountFilled',
            'takerExistingBaseAssetAmount', 'takerExistingQuoteEntryAmount', 'takerFee',
            'takerOrderBaseAssetAmount', 'takerOrderCumulativeBaseAssetAmountFilled',
            'takerOrderCumulativeQuoteAssetAmountFilled'
        ]
        for amount_field in amount_fields:
            if record[amount_field] != '':
                assert_is_numeric_string(record[amount_field], amount_field)

        # Validate bitFlags
        assert_is_int(record['bitFlags'], 'bitFlags', NON_NEGATIVE)

        # Validate fillRecordId
        fill_record_id = record['fillRecordId']
        assert isinstance(fill_record_id, str), f"'fillRecordId' must be string, got {type(fill_record_id)}"

        # Validate addresses (filler, maker, taker)
        for addr_field in ['filler', 'taker', 'user']:
            assert_is_valid_solana_address(record[addr_field], addr_field)

        if record['maker'] != '':
            assert_is_valid_solana_address(record['maker'], 'maker')

        # Validate rewards/fees
        for fee_field in [
            'fillerReward', 'makerRebate', 'quoteAssetAmountSurplus', 'referrerReward', 'spotFulfillmentMethodFee'
        ]:
            assert_is_numeric_string(record[fee_field], fee_field)

        # Validate order directions
        maker_direction = record['makerOrderDirection']
        assert isinstance(maker_direction, str), (
            f"'makerOrderDirection' must be string, got {type(maker_direction)}"
        )
        assert maker_direction in ['long', 'short'], (
            f"'makerOrderDirection' must be 'long' or 'short', got {maker_direction}"
        )

        taker_direction = record['takerOrderDirection']
        assert isinstance(taker_direction, str), (
            f"'takerOrderDirection' must be string, got {type(taker_direction)}"
        )
        assert taker_direction in ['long', 'short'], (
            f"'takerOrderDirection' must be 'long' or 'short', got {taker_direction}"
        )

        # Validate order IDs
        maker_order_id = record['makerOrderId']
        assert isinstance(maker_order_id, str), f"'makerOrderId' must be string, got {type(maker_order_id)}"

        taker_order_id = record['takerOrderId']
        assert isinstance(taker_order_id, str), f"'takerOrderId' must be string, got {type(taker_order_id)}"

        # Validate marketFilter
        market_filter = record['marketFilter']
        assert isinstance(market_filter, str), f"'marketFilter' must be string, got {type(market_filter)}"
        assert market_filter in ['perp', 'spot'], (
            f"'marketFilter' must be 'perp' or 'spot', got {market_filter}"
        )

        # Validate marketIndex
        assert_is_int(record['marketIndex'], 'marketIndex', NON_NEGATIVE)

        # Validate marketType
        market_type = record['marketType']
        assert isinstance(market_type, str), f"'marketType' must be string, got {type(market_type)}"
        assert market_type in ['perp', 'spot'], f"'marketType' must be 'perp' or 'spot', got {market_type}"

        # Validate oraclePrice
        assert_is_numeric_string(record['oraclePrice'], 'oraclePrice')

        # Validate slot
        assert_is_int(record['slot'], 'slot', POSITIVE)

        # Validate symbol
        symbol = record['symbol']
        assert isinstance(symbol, str), f"'symbol' must be string, got {type(symbol)}"
        assert len(symbol) > 0, "'symbol' must not be empty"

        # Validate ts (timestamp)
        assert_is_int(record['ts'], 'ts', POSITIVE)

        # Validate txSig
        tx_sig = record['txSig']
        assert isinstance(tx_sig, str), f"'txSig' must be string, got {type(tx_sig)}"
        assert len(tx_sig) > 32, f"'txSig' should be valid transaction signature, got {tx_sig}"

        # Validate txSigIndex
        assert_is_int(record['txSigIndex'], 'txSigIndex', NON_NEGATIVE)
