import { DeepBookClient } from "@mysten/deepbook-v3";

import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { fromHEX } from "@mysten/sui/utils";

const wallet_address =
  "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c";
const privateKey =
  "suiprivkey1qzklg5g6zq328ajfgmhhgnmruvkzdpccezueggdk8l7c957cnlkvv87lmz5";
const secretKey =
  "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6";
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
const address = keypair.toSuiAddress();

const suiClient = new SuiClient({ url: getFullnodeUrl("testnet") });
const deepBookClient = new DeepBookClient({
  client: suiClient,
  address: address,
  env: "testnet",
});

const priceLow = 0.01;
const priceHigh = 100;
const isBid = true;

console.log(
  "SUI_DBUSDC ",
  "isBid=",
  isBid,
  "\n",
  await deepBookClient.getLevel2Range("SUI_DBUSDC", priceLow, priceHigh, isBid),
  "\n"
);
console.log(
  "DEEP_SUI ",
  "isBid=",
  isBid,
  "\n",
  await deepBookClient.getLevel2Range("DEEP_SUI", priceLow, priceHigh, isBid),
  "\n"
);
console.log(
  "DEEP_DBUSDC ",
  "isBid=",
  isBid,
  "\n",
  await deepBookClient.getLevel2Range(
    "DEEP_DBUSDC",
    priceLow,
    priceHigh,
    isBid
  ),
  "\n"
);
console.log(
  "DBUSDT_DBUSDC ",
  "isBid=",
  isBid,
  "\n",
  await deepBookClient.getLevel2Range(
    "DBUSDT_DBUSDC",
    priceLow,
    priceHigh,
    isBid
  ),
  "\n"
);
