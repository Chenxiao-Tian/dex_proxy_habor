1. Get dex-proxy status:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/status"
```

```
        { "status": "ok" }
```

2. Get object info:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/object-info?id=0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c"
```

    Response:

```
{
  "data": {
    "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
    "version": "343630086",
    "digest": "9vYDekcbFVMtLTQeiDtGMNKyEvaKM26mRzS67v1yVW17",
    "type": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceManager",
    "owner": { "Shared": { "initial_shared_version": 343185334 } },
    "content": {
      "dataType": "moveObject",
      "type": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceManager",
      "hasPublicTransfer": true,
      "fields": {
        "allow_listed": {
          "type": "0x2::vec_set::VecSet<0x2::object::ID>",
          "fields": { "contents": [] }
        },
        "balances": {
          "type": "0x2::bag::Bag",
          "fields": {
            "id": {
              "id": "0x5deb7b5dd92bc80f69c505033bc28b26c0eb443e8f1dfbd9e29e730f18307c6d"
            },
            "size": "1"
          }
        },
        "id": {
          "id": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c"
        },
        "owner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
      }
    }
  }
}
```

3. Get wallet address:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/wallet-address"
```

    Response:

```
        {
            "wallet_address": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
        }
```

4. Get balance manager id:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/balance-manager-id"
```

    Response:

```
        {
            "balance_manager_id": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c"
        }
```

5. Get wallet balance info:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/wallet-balance-info"
```

    Response:

```
        [
            {
                "coinType": "0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN",
                "coinObjectCount": 1,
                "totalBalance": "4736372",
                "lockedBalance": {}
            },
            {
                "coinType": "0x2::sui::SUI",
                "coinObjectCount": 3,
                "totalBalance": "14438020776",
                "lockedBalance": {}
            }
        ]
```

6. Get events from digests:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/events?tx_digests_list=HR2xpFXN8xZ8zy3aKpiNMobnw9RwZ1wphy4pN7eQkkKd"
```

    Response:

```
    [
        {
            "event_type": "order_placed",
            "pool_id": "0xe9aecf5859310f8b596fbe8488222a7fb15a55003455c9f42d1b60fab9cca9ba",
            "client_order_id": "11",
            "exchange_order_id": "1844674407389401905673709551614",
            "side": "BUY",
            "qty": "10000000",
            "rem_qty": "10000000",
            "exec_qty": "0",
            "price": "100000000000",
            "timestamp_ms": null
        }
    ]
```

7. Create a Balance Manager:
   Request:

```
        curl \
        -X POST \
        -H "Content-Type: application/json" \
        http://localhost:3000/create-balance-manager -d {}
```

    Response:

```
        {
            "tx_digest": "DReT6eNcQydLud1ks2snpGVjrKRmpSkMtuKz7Yw9DAAM",
            "status": "success",
            "balance_manager_id": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c"
        }
```

8. Delete all orders of a pool:
   Request:

```
        curl \
        -X DELETE \
        -H "Content-Type: application/json" \
        "http://localhost:3000/orders?pool=DEEP_USDC"
```

    Response:

```
        {
            "status": "success",
            "tx_digest": "CtxBarqS3AQgt2JCKqbGdtvRhDXhizxjNo19i4kbRkJj",
            "events": []
        }
```

9. Balance manager funds info:
   Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        http://localhost:3000/balance-manager-balance-info?coin=SUI
```

    Response:

```
        {
            "coinType": "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI",
            "availableBalance": 1,
            "lockedBalance": 0
        }
```

10. Insert order:
    Request:

```
        curl \
        -X POST \
        -H "Content-Type: application/json" \
        http://localhost:3000/order -d \
        '{"client_order_id": "11", "pool": "DEEP_SUI", "order_type": "GTC", "side": "BUY", "quantity": "10000000", "price": "100000000000"}'
```

    Response:

```
        {
            "status": "success",
            "tx_digest": "HR2xpFXN8xZ8zy3aKpiNMobnw9RwZ1wphy4pN7eQkkKd",
            "events": [
                {
                    "event_type": "order_placed",
                    "pool_id": "0xe9aecf5859310f8b596fbe8488222a7fb15a55003455c9f42d1b60fab9cca9ba",
                    "client_order_id": "11",
                    "exchange_order_id": "1844674407389401905673709551614",
                    "side": "BUY",
                    "qty": "10000000",
                    "rem_qty": "10000000",
                    "exec_qty": "0",
                    "price": "100000000000",
                    "timestamp_ms": null
                }
            ]
        }
```

11. Get all open orders for a pool:
    Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/orders?pool=DEEP_SUI"
```

    Response:

```
        {
            "open_orders": [
                {
                    "client_order_id": "11",
                    "exchange_order_id": "1844674407389401905673709551614",
                    "status": "Open",
                    "side": "BUY",
                    "qty": "10000000",
                    "rem_qty": "10000000",
                    "exec_qty": "0",
                    "price": "100000000000",
                    "expiration_ts": "2524608000000"
                }
            ]
        }
```

12. Get open order by client order id:
    Request:

```
    curl \
    -X GET \
    -H "Content-Type: application/json" \
    "http://localhost:3000/order?pool=DEEP_SUI&client_order_id=11"
```

    Response:

```
        {
            "order_status": {
                "client_order_id": "11",
                "exchange_order_id": "184467440755542260233709551612",
                "status": "Open",
                "side": "BUY",
                "qty": "10000000",
                "rem_qty": "10000000",
                "exec_qty": "0",
                "price": "10000000000",
                "expiration_ts": "2524608000000"
            }
        }
```

13. Delete orders:
    Request:

```
        curl \
        -X DELETE \
        -H "Content-Type: application/json" \
        "http://localhost:3000/orders?pool=DEEP_SUI&client_order_ids=11"
```

    Response:

```
        {
            "status": "success",
            "tx_digest": "BoLCQqV2xuUEgLWBgTecp5Zi2CU8qMGQTVcQAki4QbC",
            "events": [
                {
                    "event_type": "order_cancelled",
                    "pool_id": "0xe9aecf5859310f8b596fbe8488222a7fb15a55003455c9f42d1b60fab9cca9ba",
                    "client_order_id": "11",
                    "exchange_order_id": "1844674407389401905673709551614",
                    "side": "BUY",
                    "qty": "10000000",
                    "exec_qty": "0",
                    "price": "100000000000",
                    "timestamp_ms": "1728817088556"
                }
            ]
        }
```

14. Get pool info:
    Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/pool?pool=DEEP_SUI"

```

    Response:

```
        {
            "takerFee": 0,
            "makerFee": 0,
            "stakeRequired": 0,
            "whitelisted": true,
            "tickSize": 0.001,
            "lotSize": 1,
            "minSize": 10
        }
```

15. Get trades:
    Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/trades?start_ts=1728844359176&max_pages=10"
```

    Response:

```
        {
            "has_next_page": false,
            "next_cursor": null,
            "data": [
                {
                    "event_type": "order_filled",
                    "pool_id": "0x520c89c6c78c566eed0ebf24f854a8c22d8fdd06a6f16ad01f108dad7f1baaea",
                    "liquidity_indicator": "Maker",
                    "client_order_id": "794202486501090928",
                    "exchange_order_id": "170141183460509999036090201824955519555",
                    "trade_id": "AGb8c9rC7r9GvHbTnxzzWgjRB97jgT6AbCiJ5uM6gczd_1",
                    "side": "SELL",
                    "exec_qty": "1000000000",
                    "price": "2210000",
                    "fee": "1105",
                    "timestamp_ms": "1728844417160"
                },
                {
                    "event_type": "order_filled",
                    "pool_id": "0x520c89c6c78c566eed0ebf24f854a8c22d8fdd06a6f16ad01f108dad7f1baaea",
                    "liquidity_indicator": "Taker",
                    "client_order_id": "794202486501090928",
                    "exchange_order_id": "170141183460509999036090201824955519555",
                    "trade_id": "5vx9yAMyTnSqoKELGv5xQKxNMPXw1dgSuG9eorCd91Bz_2",
                    "side": "SELL",
                    "exec_qty": "1000000000",
                    "price": "2210000",
                    "fee": "2210",
                    "timestamp_ms": "1728844401425"
                }
            ],
            "start_ts": 1728843883881
        }

```

16. Deposit into balance manager:
    Request:

```
        curl \
        -X POST \
        -H "Content-Type: application/json" \
        http://localhost:3000/deposit-into-balance-manager \
        -d '{"jsonrpc":"2.0","coin":"SUI","quantity":"1"}'

```

    Response:

```
        {
            "digest": "CYkrDe3Jn5dFo7ycR9gcvRG1CzYZ6FxtwrXnK2QVkFBH",
            "effects": {
                "messageVersion": "v1",
                "status": { "status": "success" },
                "executedEpoch": "549",
                "gasUsed": {
                    "computationCost": "750000",
                    "storageCost": "5836800",
                    "storageRebate": "2926836",
                    "nonRefundableStorageFee": "29564"
                },
                "modifiedAtVersions": [
                {
                    "objectId": "0x02726511dc489a24db9c095a81e79fc334772f592ae34712e797c5b3ae37b160",
                    "sequenceNumber": "343185333"
                },
                {
                    "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                    "sequenceNumber": "343630082"
                }
                ],
                "sharedObjects": [
                    {
                        "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                        "version": 343630082,
                        "digest": "ELkwcDFovVq5ixYeyJdwN3QWPeHERBaj3ndFVvaprSpD"
                    }
                ],
                "transactionDigest": "CYkrDe3Jn5dFo7ycR9gcvRG1CzYZ6FxtwrXnK2QVkFBH",
                "created": [
                    {
                        "owner": {
                            "ObjectOwner": "0x5deb7b5dd92bc80f69c505033bc28b26c0eb443e8f1dfbd9e29e730f18307c6d"
                        },
                        "reference": {
                            "objectId": "0x32a5b729c09b0171fd912f3bd761d36c37ec32c1e3bc6cd51b5f365cec41b64c",
                            "version": 343630083,
                            "digest": "BwrQ4xJNugku5HSoFufWPYpBLm8aq2uVruEfoWTiWcKj"
                        }
                    }
                ],
                "mutated": [
                    {
                        "owner": {
                            "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                        },
                        "reference": {
                            "objectId": "0x02726511dc489a24db9c095a81e79fc334772f592ae34712e797c5b3ae37b160",
                            "version": 343630083,
                            "digest": "6HSM39RTuJAWn27BaYaNFsWVPEfCsfJgp7z9vKqcxjyL"
                        }
                    },
                    {
                        "owner": { "Shared": { "initial_shared_version": 343185334 } },
                        "reference": {
                            "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                            "version": 343630083,
                            "digest": "FNwCCLp3oY1yV7VbMxycAHJJxQXu9D6u9svppvnQV3An"
                        }
                    }
                ],
                "gasObject": {
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "reference": {
                        "objectId": "0x02726511dc489a24db9c095a81e79fc334772f592ae34712e797c5b3ae37b160",
                        "version": 343630083,
                        "digest": "6HSM39RTuJAWn27BaYaNFsWVPEfCsfJgp7z9vKqcxjyL"
                    }
                },
                "eventsDigest": "HiSAdgjPyzW332YUBshhAHgm8uAYCX37RARDeSzHR3df",
                "dependencies": [
                    "25Z4Fdm52WtFYMp2hD75DNfuP4QXRVXjW625ipsp8vsB",
                    "49puDQZwHRnu7zYoARCjco1dFKMiK7LVSS8B5Si1yVdh",
                    "DCgz4D66b1L5vdG6pDuZB4YSDk3eUshGJLgqzNj5upWF",
                    "Eu8iwRsBpT5b71EQyG4KnpoZ8ZM5UtX7eYxV83yxxaGq"
                ]
            },
            "events": [
                {
                    "id": {
                        "txDigest": "CYkrDe3Jn5dFo7ycR9gcvRG1CzYZ6FxtwrXnK2QVkFBH",
                        "eventSeq": "0"
                    },
                    "packageId": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809",
                    "transactionModule": "balance_manager",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "type": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceEvent",
                    "parsedJson": {
                        "amount": "1000000000",
                        "asset": {
                            "name": "0000000000000000000000000000000000000000000000000000000000000002::sui::SUI"
                        },
                        "balance_manager_id": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                        "deposit": true
                    },
                    "bcs": "gBuEb9RnswF6QaerCAU2MhdWQCZp4rry7YBgDqp4AeB5qgEDobypQGY9ducpid91oQ7AwwNUJfSuFDfkrrjr1e2DyZ5viyFF8XuinF4574rmkNQYi6G2eGEhfnWFPhvx4S8w7mguZtPcewAsu3V888Bak8fScG"
                }
            ],
            "objectChanges": [
                {
                    "type": "mutated",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "objectType": "0x2::coin::Coin<0x2::sui::SUI>",
                    "objectId": "0x02726511dc489a24db9c095a81e79fc334772f592ae34712e797c5b3ae37b160",
                    "version": "343630083",
                    "previousVersion": "343185333",
                    "digest": "6HSM39RTuJAWn27BaYaNFsWVPEfCsfJgp7z9vKqcxjyL"
                },
                {
                    "type": "mutated",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": { "Shared": { "initial_shared_version": 343185334 } },
                    "objectType": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceManager",
                    "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                    "version": "343630083",
                    "previousVersion": "343630082",
                    "digest": "FNwCCLp3oY1yV7VbMxycAHJJxQXu9D6u9svppvnQV3An"
                },
                {
                    "type": "created",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": {
                        "ObjectOwner": "0x5deb7b5dd92bc80f69c505033bc28b26c0eb443e8f1dfbd9e29e730f18307c6d"
                    },
                    "objectType": "0x2::dynamic_field::Field<0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceKey<0x2::sui::SUI>, 0x2::balance::Balance<0x2::sui::SUI>>",
                    "objectId": "0x32a5b729c09b0171fd912f3bd761d36c37ec32c1e3bc6cd51b5f365cec41b64c",
                    "version": "343630083",
                    "digest": "BwrQ4xJNugku5HSoFufWPYpBLm8aq2uVruEfoWTiWcKj"
                }
            ],
            "balanceChanges": [
                {
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "coinType": "0x2::sui::SUI",
                    "amount": "-1003659964"
                }
            ],
            "confirmedLocalExecution": false
        }
```

17. Withdraw from balance manager:
    Request:

```
    curl \
    -X POST \
    -H "Content-Type: application/json" \
    http://localhost:3000/withdraw-from-balance-manager \
    -d '{"jsonrpc":"2.0","coin":"SUI","quantity":"0.001"}'
```

    Response:

```
        {
            "digest": "4KEpJyiiwaV6xwA96sExF6pJB9XVgiGr1q4x1BedYZyf",
            "effects": {
                "messageVersion": "v1",
                "status": { "status": "success" },
                "executedEpoch": "549",
                "gasUsed": {
                    "computationCost": "750000",
                    "storageCost": "6824800",
                    "storageRebate": "5778432",
                    "nonRefundableStorageFee": "58368"
                },
                "modifiedAtVersions": [
                    {
                        "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                        "sequenceNumber": "343630086"
                    },
                    {
                        "objectId": "0x32a5b729c09b0171fd912f3bd761d36c37ec32c1e3bc6cd51b5f365cec41b64c",
                        "sequenceNumber": "343630086"
                    },
                    {
                        "objectId": "0x9e83b20ebcefb0cabb9f4ac91564e0e81937982ce29a6a3f5d786c7a03931a33",
                        "sequenceNumber": "343630085"
                    }
                ],
                "sharedObjects": [
                    {
                        "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                        "version": 343630086,
                        "digest": "9vYDekcbFVMtLTQeiDtGMNKyEvaKM26mRzS67v1yVW17"
                    }
                ],
                "transactionDigest": "4KEpJyiiwaV6xwA96sExF6pJB9XVgiGr1q4x1BedYZyf",
                "created": [
                    {
                        "owner": {
                            "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                        },
                        "reference": {
                            "objectId": "0xc8de8bebb44217fc82e415e583413900abf463f9f9362bd689e64566f87e9283",
                            "version": 343630087,
                            "digest": "BRj2QA4L72pVn51GCPv4VELQS3J9qN2HuKHsLNzft7un"
                        }
                    }
                ],
                "mutated": [
                    {
                        "owner": { "Shared": { "initial_shared_version": 343185334 } },
                        "reference": {
                            "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                            "version": 343630087,
                            "digest": "EmXuCLgMQspfTuF4X1GaqHyT652WcJfixR3g2rYcgxww"
                        }
                    },
                    {
                        "owner": {
                            "ObjectOwner": "0x5deb7b5dd92bc80f69c505033bc28b26c0eb443e8f1dfbd9e29e730f18307c6d"
                        },
                        "reference": {
                            "objectId": "0x32a5b729c09b0171fd912f3bd761d36c37ec32c1e3bc6cd51b5f365cec41b64c",
                            "version": 343630087,
                            "digest": "531jmKM3GRC7FCyF73fHjj8bYfUbn2YxyxcobjA9nFyR"
                        }
                    },
                    {
                        "owner": {
                            "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                        },
                        "reference": {
                            "objectId": "0x9e83b20ebcefb0cabb9f4ac91564e0e81937982ce29a6a3f5d786c7a03931a33",
                            "version": 343630087,
                            "digest": "vARV4iCQbWmRhDSZqrXp2iwmbbFJDY14tn4Ahjhu3HB"
                        }
                    }
                ],
                "gasObject": {
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "reference": {
                        "objectId": "0x9e83b20ebcefb0cabb9f4ac91564e0e81937982ce29a6a3f5d786c7a03931a33",
                        "version": 343630087,
                        "digest": "vARV4iCQbWmRhDSZqrXp2iwmbbFJDY14tn4Ahjhu3HB"
                    }
                },
                "eventsDigest": "4Em6VLXPvVeavnBqacELudFvnbae6bsEAvt7B9yiC1Rz",
                "dependencies": [
                    "BoLCQqV2xuUEgLWBgTecp5Zi2CU8qMGQTVcQAki4QbC",
                    "49puDQZwHRnu7zYoARCjco1dFKMiK7LVSS8B5Si1yVdh",
                    "DCgz4D66b1L5vdG6pDuZB4YSDk3eUshGJLgqzNj5upWF",
                    "GKSFXtNSbz8oZ59Yazc4Nq8snmLaJB5kABbu9m1waybd"
                ]
            },
            "events": [
                {
                    "id": {
                        "txDigest": "4KEpJyiiwaV6xwA96sExF6pJB9XVgiGr1q4x1BedYZyf",
                        "eventSeq": "0"
                    },
                    "packageId": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809",
                    "transactionModule": "balance_manager",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "type": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceEvent",
                    "parsedJson": {
                        "amount": "1000000",
                        "asset": {
                            "name": "0000000000000000000000000000000000000000000000000000000000000002::sui::SUI"
                        },
                        "balance_manager_id": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                        "deposit": false
                    },
                    "bcs": "gBuEb9RnswF6QaerCAU2MhdWQCZp4rry7YBgDqp4AeB5qgEDobypQGY9ducpid91oQ7AwwNUJfSuFDfkrrjr1e2DyZ5viyFF8XuinF4574rmkNQYi6G2eGEhfnWFPhvx4S8w7mguZtPcewAsu4HyioSYSrTp79"
                }
            ],
            "objectChanges": [
                {
                    "type": "mutated",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": { "Shared": { "initial_shared_version": 343185334 } },
                    "objectType": "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceManager",
                    "objectId": "0x1fe5a96fb4510de480663b1f9a14307d4e584e309d560c1dd36dcdf9556ab84c",
                    "version": "343630087",
                    "previousVersion": "343630086",
                    "digest": "EmXuCLgMQspfTuF4X1GaqHyT652WcJfixR3g2rYcgxww"
                },
                {
                    "type": "mutated",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": {
                        "ObjectOwner": "0x5deb7b5dd92bc80f69c505033bc28b26c0eb443e8f1dfbd9e29e730f18307c6d"
                    },
                    "objectType": "0x2::dynamic_field::Field<0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809::balance_manager::BalanceKey<0x2::sui::SUI>, 0x2::balance::Balance<0x2::sui::SUI>>",
                    "objectId": "0x32a5b729c09b0171fd912f3bd761d36c37ec32c1e3bc6cd51b5f365cec41b64c",
                    "version": "343630087",
                    "previousVersion": "343630086",
                    "digest": "531jmKM3GRC7FCyF73fHjj8bYfUbn2YxyxcobjA9nFyR"
                },
                {
                    "type": "mutated",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "objectType": "0x2::coin::Coin<0x2::sui::SUI>",
                    "objectId": "0x9e83b20ebcefb0cabb9f4ac91564e0e81937982ce29a6a3f5d786c7a03931a33",
                    "version": "343630087",
                    "previousVersion": "343630085",
                    "digest": "vARV4iCQbWmRhDSZqrXp2iwmbbFJDY14tn4Ahjhu3HB"
                },
                {
                    "type": "created",
                    "sender": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "objectType": "0x2::coin::Coin<0x2::sui::SUI>",
                    "objectId": "0xc8de8bebb44217fc82e415e583413900abf463f9f9362bd689e64566f87e9283",
                    "version": "343630087",
                    "digest": "BRj2QA4L72pVn51GCPv4VELQS3J9qN2HuKHsLNzft7un"
                }
            ],
            "balanceChanges": [
                {
                    "owner": {
                        "AddressOwner": "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
                    },
                    "coinType": "0x2::sui::SUI",
                    "amount": "-796368"
                }
            ],
            "confirmedLocalExecution": false
        }
```

18. Withdraw SUI from wallet:
    Request:

```
        curl \
        -X POST \
        -H "Content-Type: application/json" \
        http://localhost:3000/withdraw-sui \
        -d '{"jsonrpc":"2.0","quantity":"1","recipient":"0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"}'
```

    Response:

```
        {
            "digest": "B6HDGTs9EYTdRVTby2ni3TTEFEJBzsJSuVwJ8r8gpgBG",
            "effects": {
                "messageVersion": "v1",
                "status": { "status": "success" },
                "executedEpoch": "530",
                "gasUsed": {
                "computationCost": "1000000",
                "storageCost": "1976000",
                "storageRebate": "978120",
                "nonRefundableStorageFee": "9880"
                },
                "modifiedAtVersions": [
                    {
                        "objectId": "0x0a31ca40fd49a147958541e2a66c0b1842fe119ce90e1f0b8150d726913e3ff3",
                        "sequenceNumber": "189502366"
                    }
                ],
                "transactionDigest": "B6HDGTs9EYTdRVTby2ni3TTEFEJBzsJSuVwJ8r8gpgBG",
                "created": [
                    {
                        "owner": {
                            "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                        },
                        "reference": {
                            "objectId": "0xbe7d29d1fc8101a4c8cce97419cad88f0fa624b8c6febd8cc624714d6f02ce4b",
                            "version": 189502367,
                            "digest": "8qyJiE3Z9WEN1GALr2Wm82etP9gdKdtdpCcafbmLbPJU"
                        }
                    }
                ],
                "mutated": [
                    {
                        "owner": {
                            "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                        },
                        "reference": {
                            "objectId": "0x0a31ca40fd49a147958541e2a66c0b1842fe119ce90e1f0b8150d726913e3ff3",
                            "version": 189502367,
                            "digest": "DZpwg9AdwzrgcoqQs6t2aXUZ3awrJ6bFLFYD7RV6xf6y"
                        }
                    }
                ],
                "gasObject": {
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "reference": {
                        "objectId": "0x0a31ca40fd49a147958541e2a66c0b1842fe119ce90e1f0b8150d726913e3ff3",
                        "version": 189502367,
                        "digest": "DZpwg9AdwzrgcoqQs6t2aXUZ3awrJ6bFLFYD7RV6xf6y"
                    }
                },
                "dependencies": ["AVtWdaWewEQ6FoFFUubmkfWz5gqPYvD3NR5N5MPo2jqe"]
            },
            "events": [],
            "objectChanges": [
                {
                    "type": "mutated",
                    "sender": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b",
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "objectType": "0x2::coin::Coin<0x2::sui::SUI>",
                    "objectId": "0x0a31ca40fd49a147958541e2a66c0b1842fe119ce90e1f0b8150d726913e3ff3",
                    "version": "189502367",
                    "previousVersion": "189502366",
                    "digest": "DZpwg9AdwzrgcoqQs6t2aXUZ3awrJ6bFLFYD7RV6xf6y"
                },
                {
                    "type": "created",
                    "sender": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b",
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "objectType": "0x2::coin::Coin<0x2::sui::SUI>",
                    "objectId": "0xbe7d29d1fc8101a4c8cce97419cad88f0fa624b8c6febd8cc624714d6f02ce4b",
                    "version": "189502367",
                    "digest": "8qyJiE3Z9WEN1GALr2Wm82etP9gdKdtdpCcafbmLbPJU"
                }
            ],
            "balanceChanges": [
                {
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "coinType": "0x2::sui::SUI",
                    "amount": "-1997880"
                }
            ],
            "confirmedLocalExecution": false
        }
```

19. Withdraw non-SUI from wallet:
    Request:

```
        curl \
        -X POST \
        -H "Content-Type: application/json" \
        http://localhost:3000/withdraw \
        -d '{"jsonrpc":"2.0","coin_type_id":"0x36dbef866a1d62bf7328989a10fb2f07d769f4ee587c0de4a0a256e57e0a58a8::deep::DEEP","quantity":"1","recipient":"0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"}'
```

    Response:

```
        {
            "digest": "E4dj1XHfq1hPiXPPwy6DKWjXKbU4qq9wiQLdwNPs7yFc",
            "effects": {
                "messageVersion": "v1",
                "status": { "status": "success" },
                "executedEpoch": "530",
                "gasUsed": {
                    "computationCost": "1000000",
                    "storageCost": "3632800",
                    "storageRebate": "3596472",
                    "nonRefundableStorageFee": "36328"
                },
                "modifiedAtVersions": [
                    {
                        "objectId": "0x017edad944dd1cd1ec0b6ed218734db01f6a3fc9eee3c5d7e978a9a81fb6cd3b",
                        "sequenceNumber": "191187344"
                    },
                    {
                        "objectId": "0x088a22da3956f2cbe8e126aec3dbc34a68e45f1726edcc701415be7c1fb0e4a0",
                        "sequenceNumber": "189604512"
                    },
                    {
                        "objectId": "0xabd7f1ea7d306b78162275f459e049aba9ae4acd4585dc459f9951927af3f134",
                        "sequenceNumber": "189604512"
                    }
                ],
                "transactionDigest": "E4dj1XHfq1hPiXPPwy6DKWjXKbU4qq9wiQLdwNPs7yFc",
                "created": [
                    {
                        "owner": {
                            "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                        },
                        "reference": {
                            "objectId": "0x533acb3c862ab8b3f38fc9c67b6cbabeda25aa99e593ba2bd653d37574e0d8c2",
                            "version": 191187345,
                            "digest": "124aitsBhUodqcRP3bixRUC38z9nctstdoYEfzoWZ4kP"
                        }
                    }
                ],
                "mutated": [
                {
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "reference": {
                        "objectId": "0x017edad944dd1cd1ec0b6ed218734db01f6a3fc9eee3c5d7e978a9a81fb6cd3b",
                        "version": 191187345,
                        "digest": "CAqiTsUMPFygbZ3RMZt5RzfHPjsXpmnKJjRHEjmSgSJe"
                    }
                },
                {
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "reference": {
                        "objectId": "0x088a22da3956f2cbe8e126aec3dbc34a68e45f1726edcc701415be7c1fb0e4a0",
                        "version": 191187345,
                        "digest": "CGH4jz17wB5K5ipbjupDuXX8ddudebt1SZQyMLsjsqv6"
                    }
                }
                ],
                "deleted": [
                    {
                        "objectId": "0xabd7f1ea7d306b78162275f459e049aba9ae4acd4585dc459f9951927af3f134",
                        "version": 191187345,
                        "digest": "7gyGAp71YXQRoxmFBaHxofQXAipvgHyBKPyxmdSJxyvz"
                    }
                ],
                "gasObject": {
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "reference": {
                        "objectId": "0x017edad944dd1cd1ec0b6ed218734db01f6a3fc9eee3c5d7e978a9a81fb6cd3b",
                        "version": 191187345,
                        "digest": "CAqiTsUMPFygbZ3RMZt5RzfHPjsXpmnKJjRHEjmSgSJe"
                    }
                },
                "dependencies": [
                    "34VMgYqF1fbN3HQKkP69VAP4yAcBbpXDXBieXdJyfzyn",
                    "6RoTdByb1vrj87fWdGWDtj9ir7WUNCjHVyPCc43wWkAL"
                ]
            },
            "events": [],
            "objectChanges": [
                {
                    "type": "mutated",
                    "sender": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b",
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "objectType": "0x2::coin::Coin<0x2::sui::SUI>",
                    "objectId": "0x017edad944dd1cd1ec0b6ed218734db01f6a3fc9eee3c5d7e978a9a81fb6cd3b",
                    "version": "191187345",
                    "previousVersion": "191187344",
                    "digest": "CAqiTsUMPFygbZ3RMZt5RzfHPjsXpmnKJjRHEjmSgSJe"
                },
                {
                    "type": "mutated",
                    "sender": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b",
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "objectType": "0x2::coin::Coin<0x36dbef866a1d62bf7328989a10fb2f07d769f4ee587c0de4a0a256e57e0a58a8::deep::DEEP>",
                    "objectId": "0x088a22da3956f2cbe8e126aec3dbc34a68e45f1726edcc701415be7c1fb0e4a0",
                    "version": "191187345",
                    "previousVersion": "189604512",
                    "digest": "CGH4jz17wB5K5ipbjupDuXX8ddudebt1SZQyMLsjsqv6"
                },
                {
                    "type": "created",
                    "sender": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b",
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "objectType": "0x2::coin::Coin<0x36dbef866a1d62bf7328989a10fb2f07d769f4ee587c0de4a0a256e57e0a58a8::deep::DEEP>",
                    "objectId": "0x533acb3c862ab8b3f38fc9c67b6cbabeda25aa99e593ba2bd653d37574e0d8c2",
                    "version": "191187345",
                    "digest": "124aitsBhUodqcRP3bixRUC38z9nctstdoYEfzoWZ4kP"
                },
                {
                    "type": "deleted",
                    "sender": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b",
                    "objectType": "0x2::coin::Coin<0x36dbef866a1d62bf7328989a10fb2f07d769f4ee587c0de4a0a256e57e0a58a8::deep::DEEP>",
                    "objectId": "0xabd7f1ea7d306b78162275f459e049aba9ae4acd4585dc459f9951927af3f134",
                    "version": "191187345"
                }
            ],
            "balanceChanges": [
                {
                    "owner": {
                        "AddressOwner": "0x56f98ae294a565671cecc3604974863c0b3c6970eb631e12e3b1d4114885757b"
                    },
                    "coinType": "0x2::sui::SUI",
                    "amount": "-1036328"
                }
            ],
            "confirmedLocalExecution": false
        }
```

20. Get transaction block:
    Request:

```
        curl \
        -X GET \
        -H "Content-Type: application/json" \
        "http://localhost:3000/transactions?cutOffTime=1732687202000&limit=50"
```

```
        {
            "data": [
                { "digest": "8tSEv4K8q4qPRbQH4RqagNAJTQXR656vvsFbFX7mdCcJ" },
                { "digest": "45auJ2SquFNYvXFL3SS2CURTEoYvbTpwY2sHF77eem1y" },
                { "digest": "Fv4zQfYwRynStuGWbbzfQNeYknDX4ukoYh8TS792T9Gi" },
                { "digest": "GACqFQWKM6GRDUjT2qY8kmEKGKNHsq76nVkJYbSih5vh" },
                { "digest": "EH9V1SFvLu5LaQaUSR5MAk91w7R7S4UeBSWaNn7DLMM6" },
                { "digest": "H7FbAhAZmTtePtBcujdMVGjJEVLVzC5xb8Pa5wQUo1VC" },
                { "digest": "9Vhc1pnN6mG2k2Sos3YsnrJWe7duJYpgSUmnECXt7KoY" },
                { "digest": "CiVv3XMNruQBbjhvbeUxgtw42d4NVM3ErCEEtdECTBTf" },
                { "digest": "Gqn8mfHET8dy27Dyzfm6a1y8Y5CwnkKjgv2tQoXQHzq9" },
                { "digest": "GSUkqv2fct13GQ8hHNUFtk1HB3dmGxaMJr3QFjW8zjYG" }
            ],
            "nextCursor": "iCMCTCsPDRwSvnGR5AVkTAEe3QrrBHirqEt7b6vu2jt",
            "hasNextPage": false
        }
```
