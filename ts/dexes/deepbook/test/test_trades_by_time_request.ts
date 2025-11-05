import { get } from "./requests.js";

const main = async () => {
    let txDigests = [ "FMjeKV7CCVARzij5qUsGF6DiqZwcFNcwLYznmfR1Qi2d" ];
    const thirtyNineMinutesInMs = 39 * 60 * 1000
    const startTs = Date.now() - thirtyNineMinutesInMs;
    const maxPages = 1;

    get("trades", { "start_ts": startTs, "max_pages": maxPages });
}

await main()
