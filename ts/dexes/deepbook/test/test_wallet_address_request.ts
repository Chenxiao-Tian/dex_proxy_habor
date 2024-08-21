import { get } from "./requests.js";

const main = async () => {
    await get("wallet-address");
}

await main()
