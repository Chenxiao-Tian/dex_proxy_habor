import { get } from "./requests.js";

const main = async () => {
  const tx_digests =
    "GiKsAPjcxemtC7M67BqR4AvheonirMCsW9y8FmrM1aF5,FMjeKV7CCVARzij5qUsGF6DiqZwcFNcwLYznmfR1Qi2d";

  await get("events", { tx_digests: tx_digests });
};

await main();
