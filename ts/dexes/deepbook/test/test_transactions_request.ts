import { get } from "./requests.js";

const main = async () => {
    await get("transactions", { "direction": "to" });
    await get("transactions", { "direction": "from" });
}

await main()
