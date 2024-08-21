import { post } from "./requests.js";

const main = async () => {
    let payload = {
        "pool_id": "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33",
        // USDC
        "coin_type_id": "0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN",
        "quantity": "0.01"
    };

    post("deposit-into-pool", payload);
}

await main()
