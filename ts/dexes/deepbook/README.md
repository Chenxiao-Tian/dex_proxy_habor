## Deepbook Dex Proxy

### Setup
See ts/README.md

### Endpoints
1. `GET /status`
    - Description:
      - Used to confirm that the dex_proxy is alive and accepting user requests.
    - Response Schema:
      ```
      {
        "status": "ok"
      }
      ```

2. `GET /pool`
    - Description:
      - Returns metadata for a particular pool.
    - Query Parameters:
      ```
      "id": "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"
      ```
    - Response Schema:
      ```
      {
        "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
        "base_asset": "0xf398b9ecb31aed96c345538fb59ca5a1a2c247c5e60087411ead6c637129f1c4::gold::GOLD",
        "quote_asset": "0xf398b9ecb31aed96c345538fb59ca5a1a2c247c5e60087411ead6c637129f1c4::fish::FISH",
        "taker_fee_rate": "2500000",
        "maker_rebate_rate": "1500000",
        "tick_size": "1000000000",
        "lot_size": "1",
        "base_asset_trading_fees": "0",
        "quote_asset_trading_fees": "132045301"
      }
      ```

3. `GET /pools`
    - Description:
      - Returns metadata for all pools.
    - Response Schema:
      ```
      [
        {
          "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
          "base_asset": "0xf398b9ecb31aed96c345538fb59ca5a1a2c247c5e60087411ead6c637129f1c4::gold::GOLD",
          "quote_asset": "0xf398b9ecb31aed96c345538fb59ca5a1a2c247c5e60087411ead6c637129f1c4::fish::FISH",
          "taker_fee_rate": "2500000",
          "maker_rebate_rate": "1500000",
          "tick_size": "1000000000",
          "lot_size": "1",
          "base_asset_trading_fees": "0",
          "quote_asset_trading_fees": "132045301"
        }
      ]
      ```

4. `GET /object-info`
    - Description:
      - Returns metadata for a particular object.
    - Query Parameters:
      ```
      "id": 0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"
      ```

5. `GET /wallet-balance-info`

6. `GET /wallet-address`
    - Description:
      - Returns the address of the wallet linked to the dex_proxy.
    - Response Schema:
      ```
      {
        "wallet_address": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
      }

7. `GET /user-position`

8. `GET /transaction`

9. `GET /transactions`

10. `GET /account-caps`
     - Description:
       - Returns a list of account-cap-ids that are owned by the wallet linked to the dex_proxy.
     - Response Schema:
       ```
       {
         "account_caps": [
           "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a"
         ]
       }
       ```

11. `POST /account-cap`
     - Description:
       - Creates an account-cap owned by the wallet linked to the dex_proxy.
     - Response Schema:
       ```
       {
         "tx_digest": "3TdPuaZNCYK39ApaXqhGK8Zh1GvErGQ4a6LT868K9CVX",
         "status": "success", // or "failure"
         "account_cap": "0x7362f827fed1ce273e6964c18ba0845cf7c6a7c6df028e4041d010d3fd711e2a"
       }
       ```

12. `GET /order`
     - Description:
       - Returns the details of a particular order.
     - Query Parameters:
       ```
       "pool_id": "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae",
       "client_order_id": "2"
       ```
     - Response Schema:
       ```
       {
         "order_status": {
           "client_order_id": "1",
           "exchange_order_id": "1297",
           "status": "Open",
           "side": "BUY",
           "qty": "1000000",
           "rem_qty": "1000000",
           "exec_qty": "0",
           "price": "51000000000",
           "expiration_ts": "1735145773250"
         }
       }
       ```

13. `GET /orders`
     - Description:
       - Returns all open orders for a pool
     - Query Parameters:
       ```
       "pool_id": "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"
       ```
     - Response Schema:
       ```
       {
         "open_orders": [
           {
             "client_order_id": "1",
             "exchange_order_id": "1297",
             "status": "Open",
             "side": "BUY",
             "qty": "1000000",
             "rem_qty": "1000000",
             "exec_qty": "0",
             "price": "51000000000",
             "expiration_ts": "1735145773250"
           }
         ]
       }
       ```

14. `POST /order`
     - Description:
        - Inserts an order into a particular pool.
     - Request Schema:
       ```
       {
           "client_order_id": "1",
           "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
           "quantity": "0.001",
           "price": "51",
           "side": "BUY",
           "order_type": "GTC",
           "expiration_ts": "1735145773250"
       }
       ```
     - Response Schema:
       ```
       {
         "status": "success",
         "tx_digest": "3MXYBSWZVowR49vM7iey2zrq9aAhoChD7Jvcgn47DML8",
         "events": [
           {
             "event_type": "order_placed",
             "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
             "client_order_id": "1",
             "exchange_order_id": "1298",
             "side": "BUY",
             "qty": "1000000",
             "rem_qty": "1000000",
             "exec_qty": "0",
             "price": "51000000000",
             "timestamp_ms": null
           }
         ]
       }
       ```

15. `POST /orders`
     - Description:
        - Insert multiple orders into a particular pool.
     - Request Schema:
       ```
       {
         "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
         "expiration_ts": "1735145773250",
         "orders": [
           {
             "client_order_id": "1",
             "quantity": "0.001",
             "price": "51",
             "side": "BUY",
             "order_type": "GTC"
           },
           {
             "client_order_id": "2",
             "quantity": "0.009",
             "price": "51",
             "side": "BUY",
             "order_type": "GTC"
           }
         ]
       }
       ```
     - Response Schema:
       ```
       {
         "status": "success",
         "tx_digest": "4dTiifEHfXKwzsqTq41V1XrxVN16fkS2SzgMx6vcHYjV",
         "events": [
           {
             "event_type": "order_placed",
             "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
             "client_order_id": "1",
             "exchange_order_id": "1305",
             "side": "BUY",
             "qty": "1000000",
             "rem_qty": "1000000",
             "exec_qty": "0",
             "price": "51000000000",
             "timestamp_ms": null
           },
           {
             "event_type": "order_placed",
             "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
             "client_order_id": "2",
             "exchange_order_id": "1306",
             "side": "BUY",
             "qty": "9000000",
             "rem_qty": "9000000",
             "exec_qty": "0",
             "price": "51000000000",
             "timestamp_ms": null
           }
         ]
       }
       ```

16. `DELETE /order`
     - Description:
       - Cancels an order for a pool.
     - Request Schema:
       ```
       {
         "client_order_id": "2",
         "pool_id": "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"
       }
       ```
     - Response Schema:
       ```
       {
         "status": "success",
         "tx_digest": "69QPJjUR9o4fk1r88AeERYYPnVXrWgA5Z7jUQMRnVn9q",
         "events": [
           {
             "event_type": "order_cancelled",
             "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
             "client_order_id": "1",
             "exchange_order_id": "1298",
             "side": "BUY",
             "qty": "1000000",
             "exec_qty": "0",
             "price": "51000000000",
             "timestamp_ms": null
           }
         ]
       }
       ```

17. `DELETE /orders`
     - Description:
       - Cancels all orders for a pool.
     - Request Schema:
       ```
       {
         "pool_id": "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"
       }
       ```
     - Response Schema:
       ```
       {
         "status": "success",
         "tx_digest": "2W1uPbJQSUnCF4uH5mcK22Ed11MSw4qZHKocqLERVgHy",
         "events": [
           {
             "event_type": "order_placed",
             "pool_id": "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2",
             "client_order_id": "1",
             "exchange_order_id": "1299",
             "side": "BUY",
             "qty": "1000000",
             "rem_qty": "1000000",
             "exec_qty": "0",
             "price": "51000000000",
             "timestamp_ms": null
           }
         ]
       }
       ```

18. `POST /withdraw-from-pool`

19. `POST /deposit-into-pool`

20. `POST /withdraw-sui`

21. `POST /withdraw`

22. `GET /trades`

### Websocket Subscriptions
1. Send a request to `/ws` to open a websocket connection.
2. This should be followed by a jsonrpc request on the opened connection asking to subscribe to one of the following channels:
   1. `ORDER`
   2. `TRADE`
   3. `TRANSFER`
3. Subscription Request Schema
   ```
   {
     "jsonrpc": "2.0",
     "method": "subscribe", // "unsubscribe"
     "id": "1",
     "params": {
       "channel": ["ORDER", "TRADE"]
     }
   }
   ```
