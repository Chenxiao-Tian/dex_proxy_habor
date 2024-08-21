import { post } from "./requests.js";

const main = async () => {
    let payload = {
        "pool_id": "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33",
        "expiration_ts": "1735145773250",
        "orders": [
            {
                "client_order_id": "2",
                "quantity": "100000000",
                "price": "843900",
                "side": "BUY",
                "order_type": "GTC"
            },
            {
                "client_order_id": "3",
                "quantity": "100000000",
                "price": "845900",
                "side": "BUY",
                "order_type": "GTC"
            }
        ]
    };

    await post("orders", payload);
}

await main()
