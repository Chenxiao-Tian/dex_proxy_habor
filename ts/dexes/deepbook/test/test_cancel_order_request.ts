import { delete_ } from "./requests.js";

const main = async () => {
    const poolId = "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33";
    const clientOrderId = "1";

    await delete_("order", { "pool_id": poolId, "client_order_id": clientOrderId });
}

await main()
