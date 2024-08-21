import { get } from "./requests.js";

const main = async () => {
    let txDigests = "FMjeKV7CCVARzij5qUsGF6DiqZwcFNcwLYznmfR1Qi2d";

    get("trades", { "tx_digests": txDigests });
}

await main()
