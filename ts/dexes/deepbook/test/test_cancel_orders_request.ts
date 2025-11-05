import { delete_ } from "./requests.js";

const main = async () => {
    const poolId = "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33";
    let clientOrderIds = [ "1", "2" ];

    delete_("orders", { "pool_id": poolId, "client_order_ids": clientOrderIds });
}

await main()
