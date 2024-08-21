import { post } from "./requests.js";

const main = async () => {
    let payload = {
        "client_order_id": "1",
        "pool_id": "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33",
        "order_type": "GTC",
        "side": "BUY",
        "quantity": "100000000",
        "price": "843900",
        "expiration_ts": "1735145773250"
    };

    await post("order", payload);
}

await main()
