import { get } from "./requests.js";

const main = async () => {
    const poolId = "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33";

    const nonExistentPoolId = "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a4211";

    Promise.all([
        get("object-info", { "id": poolId }),
        get("object-info", { "id": nonExistentPoolId })
    ]);
}

await main()
