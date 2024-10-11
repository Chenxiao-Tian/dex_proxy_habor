import { DeepBookClient } from "@mysten/deepbook-v3";

import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { fromHex } from "@mysten/sui/utils";

const balanceManagers = {
  MANAGER_1: {
    address:
      "0xff40dfdaa475ffa9d86d5e74d321f1f275a079b4e70891ad51bc88fdddfde775",
    tradeCap: "",
  },
  MANAGER_2: {
    address: "",
    tradeCap: "",
  },
};

const wallet_address =
  "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c";
const privateKey =
  "suiprivkey1qzklg5g6zq328ajfgmhhgnmruvkzdpccezueggdk8l7c957cnlkvv87lmz5";
const secretKey =
  "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6";
const keypair = Ed25519Keypair.fromSecretKey(fromHex(secretKey));
const address = keypair.toSuiAddress();

const suiClient = new SuiClient({ url: getFullnodeUrl("testnet") });
const deepBookClient = new DeepBookClient({
  client: suiClient,
  address: address,
  env: "testnet",
  balanceManagers: balanceManagers,
});

console.log(
  "SUI_DBUSDC: ",
  await deepBookClient.accountOpenOrders("SUI_DBUSDC", "MANAGER_1")
);
console.log(
  "DEEP_SUI: ",
  await deepBookClient.accountOpenOrders("DEEP_SUI", "MANAGER_1")
);
console.log(
  "DEEP_DBUSDC: ",
  await deepBookClient.accountOpenOrders("DEEP_DBUSDC", "MANAGER_1")
);
console.log(
  "DBUSDT_DBUSDC: ",
  await deepBookClient.accountOpenOrders("DBUSDT_DBUSDC", "MANAGER_1")
);
