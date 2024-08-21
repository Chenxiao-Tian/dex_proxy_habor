import { post } from "./requests.js";

const main = async () => {
    await post("child-account-cap", {});
}

await main()
