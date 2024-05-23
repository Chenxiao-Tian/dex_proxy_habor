### General Description
- On success, a http status code of 200 is returned.
- On failure, a http error code of 400 is returned and the response json contains an `error` field.


### Endpoints
1`POST /private/order-signature`
   - Description:
     - Signs an order request with the wallet private key.
   - Request Schema:
     ```
     {
         "coin": <string>,
         "is_buy": <bool>,
         "sz": <string>,
         "limit_px": <string>,
         "order_type": <string>,
         "reduce_only": <string>,
         "cloid": <string>
     }
     ```
   - Response Schema:
     ```
     {
         "signature": <string>  // "[\"1715098085494234226866494772187091940809671362228661809072604915842875804005\",\"2037208684358908384038866323316526219291278011692617172651343108028904528359\"]"
     }
     ```
   
2`POST /private/cancel-signature`
   - Description:
     - Signs an order cancel request with the wallet private key.
   - Request Schema:
     ```
     {
         "coin": <string>,
         "oid": <string>
     }
     ```
   - Response Schema:
     ```
     {
         "signature": <string>  // "[\"1715098085494234226866494772187091940809671362228661809072604915842875804005\",\"2037208684358908384038866323316526219291278011692617172651343108028904528359\"]"
     }
     ```
3`POST /private/withdraw-from-exchange`
   - Description:
     - Withdraws token from exchange account to our L1 wallet
   - Request Schema:
     ```
     {
         "client_request_id": <string>,
         "symbol": <string>,
         "amount": <string>
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string>
     }
     ```
     
4`POST /private/deposit-into-exchange`
   - Description:
     - Deposits token into exchange account from our L1 wallet
   - Request Schema:
     ```
     {
         "client_request_id": <string>,
         "symbol": <string>,
         "amount": <string>,
         "gas_limit": <int>,
         "gas_price": <int>
     }
     ```
   - Response Schema:
     ```
     {
         "tx_hash": <string>
     }
     ```
