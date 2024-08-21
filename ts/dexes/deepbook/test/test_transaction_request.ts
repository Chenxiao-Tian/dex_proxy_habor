import { get } from "./requests.js";

const main = async () => {
    const txDigest = "GiKsAPjcxemtC7M67BqR4AvheonirMCsW9y8FmrM1aF5";

    await get("transaction", { "digest": txDigest });
}

await main()
