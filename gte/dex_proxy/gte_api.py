
import logging

from pantheon.timestamp_ns import TimestampNs
from dataclasses import asdict
from typing import Any, Dict, Tuple
from gte_py.clients import Client
from gte_py.models import Trade, Market, Order
from web3 import AsyncWeb3

_logger = logging.getLogger('gte_api')

class GteApi:
    def __init__(
        self,
        pantheon: Any,
        client: Client,
        event_sink: Any,
        wallet_address: str
    ):
        self.__pantheon = pantheon
        self.__client = client
        self.__event_sink = event_sink
        self.__wallet_address = wallet_address
        
    async def start(self):
        markets = await self.__client.info.get_markets(market_type='clob-spot')
        
        # TODO we need to adjust subscriptions for new/deleted markets
        # TODO: Maybe use the 'clob.stream_fill_order_processed_events()'
        # for market in markets:
        #     await self.__client.market.trades.subscribe_trades(market, callback=lambda trade: self.on_trade(trade, market))
            
    # async def on_trade(self, market: Market, trade: Trade):
    #     try:
    #         self.__logger.info(f"Received trade : {trade}")
    #         auros_trade = self.__trade_to_auros(market=market, trade=trade, include_raw=False)   
    #         event = {
    #             "jsonrpc": "2.0",
    #             "method": "subscription",
    #             "params": {"channel": "TRADE", "data": auros_trade},
    #         }
            
    #         await self.__event_sink.on_event("TRADE", event)
    #     except BaseException as ex:
    #         self.__logger.exception("Error sending trade updates %r", ex)
           
    async def get_balance(self) -> Dict[str, Any]:
        markets = await self.__client.info.get_markets(market_type='clob-spot')
        
        # This is broken
        # token_balances = await self.__client.user.get_token_balances()
        
        # Convert into auros terms
        wallet_balances = []
        spot_balances = []
        
        tokens = {}
        
        for market in markets:
            tokens[market.base.address] = market.base
            tokens[market.quote.address] = market.quote
            
        for token in tokens.values():
            exchange_balance, wallet_balance = await self.__get_balance_for_token(token.address)
            bal = {
                'symbol': token.symbol,
                'balance': str(wallet_balance)
            }
            
            wallet_balances.append(bal)
            
            bal = {
                'symbol': token.symbol,
                'balance': str(exchange_balance)
            }
            
            spot_balances.append(bal)
 
        balances = {
            'balances': {
                'wallet': wallet_balances,
                'spot': spot_balances
            }
        }
 
        return balances
    
    async def __get_balance_for_token(self, token_address) -> Tuple[float, float]:
        token = self.__client.token.get_erc20(token_address)
        exchange_balance = await self.__client.user.get_token_balance(token_address)
        exchange_balance = await token.convert_amount_to_quantity(exchange_balance)
        wallet_balance = await token.balance_of(self.__wallet_address)
        wallet_balance = await token.convert_amount_to_quantity(wallet_balance)
        return exchange_balance, wallet_balance
    
    async def get_instrument_data(self) -> Dict[str, Any]:
        raise NotImplementedError("not implemented yet")
    
    async def get_instrument_definitions(self, include_raw: bool) -> Tuple[int, Dict[str, Any]]:
        markets = await self.__client.info.get_markets(market_type='clob-spot')

        # Convert into auros terms
        instruments = []
        
        for market in markets:
            inst = {
                "native_code": market.address,
                "base_currency": market.base.symbol,
                "quote_currency": market.quote.symbol,
                "settlement_currency": "",
                "kind": "spot",
                "tick_size": "0",
                "min_order_size": "0",
                "max_order_size": "0",
                "min_order_incremental_size": "0",
                "min_order_value_in_quote_ccy": "0",
                "is_active_on_exchange": True,
                "making_fee_in_bps": "0",
                "taking_fee_in_bps": "0",
                "swap_funding_period": "0",
                "swap_funding_base_rate_bps": "0",
                "raw_response": market if include_raw else {},
                "custom_fields": {}
            }
            
            instruments.append(inst)
 
        response = {
            'instruments': instruments
        }
 
        return response

    async def get_margin(self) -> Dict[str, Any]:
        raise NotImplementedError("No margin data is available yet")

    async def get_transfers(self) -> Dict[str, Any]:
        raise NotImplementedError("not implemented yet")

    async def get_other_movements(self) -> Dict[str, Any]:
        raise NotImplementedError("No other movement data is available yet")

    async def get_trades(self, start_timestamp: TimestampNs, end_timestamp: TimestampNs, client_order_id: str, include_raw: bool) -> Dict[str, Any]:
        markets = await self.__client.info.get_markets(market_type='clob-spot')
        
        trades = []
        for market in markets:
            offset = 0
            limit = 1000
            
            while True:
                # This isn't giving us the data we need atm
                #raw_trades = await self.__client.user.get_trades(market, limit, offset)
                raw_trades = await self.__client.user.get_filled_orders(market, limit, offset)

                if raw_trades:
                    for order in raw_trades:
                        trades.append(self.__trade_to_auros(market=market, order=order, include_raw=include_raw))

                    offset += len(raw_trades)
                    last_record_ts = TimestampNs.from_ns_since_epoch(raw_trades[-1].filled_at * 1_000_000)
                    
                    if start_timestamp > last_record_ts or end_timestamp < last_record_ts or len(raw_trades) < limit:
                        break
                else:
                    break
            
        response = {
            'records': trades
        }
        
        return response
    
    def __trade_to_auros(self, market: Market, order: Order, include_raw: bool):
        amount = market.quote.convert_amount_to_quantity(order.filled_amount)
        price = market.quote.convert_amount_to_quantity(order.price)
        
        return {
            "exchange_order_id": str(order.order_id),
            "exchange_trade_id": order.txn_hash.to_0x_hex(),
            "symbol": market.address,
            "side": order.side.name,
            "amount": str(amount),
            "price": str(price),
            "exchange_timestamp": TimestampNs.from_ns_since_epoch(order.filled_at * 1_000_000).get_ns_since_epoch(),
            "fee": "0", # TODO: Need fees
            "fee_ccy": market.quote.symbol,
            "liquidity": "UNSPECIFIED",# TODO, waiting for them to update API "MAKER" if order.is_maker else "TAKER",
            "raw_response": {}
        }
    
    # BROKEN: They need to fix their endpoints 
    # def __trade_to_auros(self, market: Market, trade: Trade, include_raw: bool):
    #     we_are_taker = trade.taker == self.__wallet_address
    #     return {
    #         "exchange_order_id": trade.tx_hash.to_0x_hex(),
    #         "exchange_trade_id": trade.tx_hash.to_0x_hex(),
    #         "symbol": market.address,
    #         "side": trade.side.name,
    #         "amount": str(trade.size),
    #         "price": str(trade.price),
    #         "exchange_timestamp": TimestampNs.from_ns_since_epoch(trade.timestamp * 1_000_000).get_ns_since_epoch(),
    #         "fee": "0",
    #         "fee_ccy": market.quote.symbol,
    #         "liquidity": "TAKER" if we_are_taker else "MAKER",
    #         "raw_response": {
    #             "taker": str(trade.taker)
    #         }
    #     }
