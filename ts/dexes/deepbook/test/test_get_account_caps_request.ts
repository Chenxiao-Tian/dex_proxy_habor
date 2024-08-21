import { get } from "./requests.js";

const main = async () => {
    await get("account-caps");
}

await main()
