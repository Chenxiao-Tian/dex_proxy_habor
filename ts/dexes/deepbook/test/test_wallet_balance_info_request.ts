import { get } from "./requests.js";

const main = async () => {
    await get("wallet-balance-info");
}

await main()
