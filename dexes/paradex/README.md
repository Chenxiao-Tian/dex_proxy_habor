### General Description
- On success, an http status code of 200 is returned.
- On failure, an http error code of 400 is returned and the response json contains an `error` field.


### Endpoints
1. `POST /private/exchange-token`
   - Description:
     - Returns the active JWT fetched from the exchange.
     - The JWT is refreshed periodically from the exchange and shared with clients on request.
   - Response Schema:
     ```
     {
         "token": <string>,   // "eyJhbGciOiJFUzM4NCIsInR5cCI6IkpXVCJ9.eyJ0eXAiOiJhdCtKV1QiLCJpc3MiOiJQYXJhZGV4IHRlc3RuZXQiLCJzdWIiOiIweDQzY2ExMzBkMTNiMTdjMDdhMGRjYWU0NWQyM2I1OWExOTcwOWUwNWJjNmJlZjg3ODQ1NDI3NjYxYmM5MTMzNyIsImV4cCI6MTY4NjY0ODY1NiwiaWF0IjoxNjg2NjQ4MzU2fQ.lhtsE4LiSHeA0KimT-_FEAR2hDLN7dpXWcb8zeJnNw0Ru18MNu8v8MhVVYGtIXDs8AL3K2ntnqgKsT07UD2ocRutCGCF6WNZ11jQhlTR6alX4eXkwelBWSU7EoSOZfLd"
         "expiration": <int>  // 1686648656
     }
     ```

2. `POST /private/order-signature`
   - Description:
     - Signs an order request with the STARKNET private key.
   - Request Schema:
     ```
     {
         "order_creation_ts_ms": <int>,  // 1684862276499
         "market": <string>,             // "BTC-USD-PERP"
         "side": <side>,                 // "BUY"
         "type": <string>,               // "LIMIT"
         "size": <string>,               // "1.213"
         "price": <string>               // "29500.12"
     }
     ```
   - Response Schema:
     ```
     {
         "signature": <string>  // "[\"1715098085494234226866494772187091940809671362228661809072604915842875804005\",\"2037208684358908384038866323316526219291278011692617172651343108028904528359\"]"
     }
     ```

3. `GET /private/get-l2-balance`
   - Description:
     - Returns the balance of the supplied token in our paradex L2 account.
   - Query parameters:
     ```
     "symbol": <string> // "USDC"
     ```
   - Response Schema:
     ```
     {
         "balance": <string> // "10.1607000000000002870592652470804750919342041015625"
     }
     ```

4. `GET /private/get-socialized-loss-factor`
   - Description:
     - Returns the socialized loss factor.
   - Response Schema:
     ```
     {
         "socialized_loss_factor": <string>  // "0"
     }
     ```

5. `POST /private/deposit-into-l2`
   - Description:
     - Calls `deposit` on the L1 bridge contract providing our L2 account address as the recipient.
     - This is an L1 transaction.
   - Request Schema:
     ```
     {
         "client_request_id": <string>, // "test2"
         "symbol": <string>,            // "USDC"
         "amount": <string>,            // "0.1"
         "gas_price_wei": <int>,        // 15081473971
         "gas_limit": <int>             // 300000
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string> // "0xac0d59283c82401209122e0435bfbfb98a148772e1d28d8d0a7c89380df5f138"
     }
     ```

6. `POST /private/transfer-to-l2-trading`
   - Description:
     - Calls `increaseAllowance` on the L2 token contract to allow sending the corresponding amount to the L2 paraclear account.
     - Calls `deposit` on the L2 paraclear contract.
     - This is an L2 transaction.
   - Request Schema:
     ```
     {
         "client_request_id": <string>, // "test4"
         "symbol": <string>,            // "USDC"
         "amount": <string>,            // "0.1"
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string> // "0x4ac1f6e9f8289fce0d6f57476809c9c9d4f12450da453dbe3ead92310a03897"
     }

7. `POST /private/withdraw-from-l2`
   - Description:
     - Calls `withdraw` on the L2 paraclear trading contract passing in the L2 token contract address of the user supplied token for the corresponding amount.
     - Calls `initiate` withdraw on the L2 bridge contract passing our L1 wallet address as the recipient.
     - This is an L2 transaction.
   - Request Schema
     ```
     {
         "client_request_id": <string>, // "test5"
         "symbol": <string>,            // "USDC"
         "amount": <string>,            // "0.1"
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string> // "0x73405a8f4d09263797d2c4dd9fce1da5145eaea998ad9b1b6e8ec2494c2a479"
     }

8. `POST /private/transfer-from-l1-bridge-to-wallet`
   - Description:
     - Calls `withdraw` on the L1 bridge contract transferring the tokens to our L1 wallet.
     - This is an L1 transaction.
   - Request Schema:
     ```
     {
         "client_request_id": <string>, // "test6"
         "symbol": <string>,            // "USDC"
         "amount": <string>,            // "0.1"
         "gas_price_wei": <int>,        // 17130024083
         "gas_limit": <int>             // 100000
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string> // "0x7b7a1bd2c30a28366a3f9ad94a398ae7acd088ed8bafa2b0e8f48f1c0aadfae8"
     }
     ```

9. `POST /private/approve-token`
   - Description:
     - Approves the L1 bridge contract to spend the specified amount of L1 tokens.
     - This is an L1 transaction.
   - Request Schema:
     ```
     {
         "client_request_id": <string>, // "test1"
         "symbol": <string>,            // "USDC"
         "amount": <string>,            // "10"
         "gas_price_wei": <int>,        // 15886630028
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string> // "0x5304e9bd0e813fa2a6969938ace95e2352080ff3d039376c31882aaeba8f7e46"
     }
     ```

10. `POST /private/withdraw`
    - Description:
      - Move the requested amount of the token from the L1 wallet to an approved address.
    - Request Schema:
      ```
      {
          "client_request_id": <string>, // "test7"
          "address_to": <string>         //  "0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB"
          "symbol": <string>,            // "USDC"
          "amount": <string>,            // "0.1"
          "gas_price_wei": <int>,        // 19268249570
          "gas_limit": <int>             // 100000
      }
      ```
    - Response Schema:
      ```
      {
          "tx_hash": <string> // "0x91d83b82bb8d4ed136d64515e60570a3dc266e647ce562bbdba609ed5b95e948"
      }
      ```

11. `POST /private/amend-request`
    - Description:
      - Amend the `gas_price_wei` field on any `PENDING` L1 chain request.
    - Request Schema:
      ```
      {
          "client_request_id": <string>, // "test9"
          "gas_price_wei": <int>,        // 15311611218
      }
      ```
    - Response Schema:
      ```
      {
          "tx_hash": <string> // "0x7e5895d1adc58fab2a052f416dfd5065e9d59e8d74bbd031375300b73d0c2335"
      }
      ```


12. `DELETE /private/cancel-request`
    - Description:
      - Cancels the `PENDING` L1 chain request specified.
    - Request Parameters:
      ```
      "client_request_id": <string>, // test10
      "gas_price_wei": <int>,        // 15311611218 (optional)
      ```
    - Response Schema:
      ```
      {
          "tx_hash": <string> // "0xe80773b8fbc3d0e9be756a76382b5f2c0fe4c9546eac3fc8b982ace132a0d9c1"
      }
      ```


13. `DELETE /private/cancel-all`
    - Description:
      - Cancels all the `PENDING` L1 chain requests of the type specified.
    - Request Parameters:
      ```
      "request_type": <string>, // APPROVE, TRANSFER
      ```
    - Response Schema:
      ```
      {
          "cancel_requested": [<string>],  // ["test13"]
          "failed_cancels": [<string>],    // []
      }


14. `GET /public/get-all-open-requests`
    - Description:
      - Returns a list of all non finalized requests corresponding to the `request_type` supplied.
    - Request Parameters:
    ```
    "request_type": <string> // APPROVE, TRANSFER
    ```
    - Response Schema:
    ```
    [Request object(s)]
    ```


15. `GET /public/get-request-status`
    - Description:
      - Returns the status of the request corresponding to the `client_request_id` supplied if it has not been finalized and exists in the cache.
    - Request Parameters:
    ```
    "client_request_id": <string> // "test12"
    ```
    - Response Schema:
    ```
    [Request object]
    ```

### Signature generation
In order to bump the version of the signature generation library you should do the following:
- update [library](https://gitlab.com/auros/starknet-signing-cpp/-/tree/build-lib-with-python-bindings?ref_type=heads) `build-lib-with-python-bindings` branch
- on successful merge a package will appear in [package registry](https://gitlab.com/auros/starknet-signing-cpp/-/packages)
- update the relevant sections in the [Dockerfile](https://gitlab.com/auros/dex-proxy/-/blame/master/Dockerfile?ref_type=heads#L30)
  - `SHA1`/starknet-signing-cpp-x86_64.`SHA1`.tar.gz
  - [sha256 hash](https://gitlab.com/auros/dex-proxy/-/blame/master/Dockerfile?ref_type=heads#L32) of the package
    - calculate with `sha256sum package.tar.gz`
