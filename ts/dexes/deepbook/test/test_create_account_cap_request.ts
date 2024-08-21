import { post } from "./requests.js";

const main = async () => {
    await post("account-cap", {});
}

await main()
