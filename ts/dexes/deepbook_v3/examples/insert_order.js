import { DeepBookClient } from "@mysten/deepbook-v3";

import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Transaction } from "@mysten/sui/transactions";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { fromHEX } from "@mysten/sui/utils";

const balanceManagers = {
  MANAGER_1: {
    address:
      "0xd65d3223d2b61e7ecd85ffdf2c7dd2ddb196cdceee48e695b30bde2eeef67964",
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
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
const address = keypair.toSuiAddress();

const suiClient = new SuiClient({ url: getFullnodeUrl("testnet") });
const deepBookClient = new DeepBookClient({
  client: suiClient,
  address: address,
  env: "testnet",
  balanceManagers: balanceManagers,
});

const tx = new Transaction();
tx.add(
  deepBookClient.deepBook.placeLimitOrder({
    poolKey: "SUI_DBUSDC",
    balanceManagerKey: "MANAGER_1",
    clientOrderId: "1",
    price: 0.1,
    quantity: 0.2,
    isBid: false,
    orderType: 0, // GTC: 0, IOC: 1, FOK: 2, GPO: 3
    selfMatchingOption: 0, // SELF_MATCHING_ALLOWED = 0, CANCEL_TAKER = 1, CANCEL_MAKER = 2
    payWithDeep: true,
    // expiration: default is no expire
  })
);

const resp = await suiClient.signAndExecuteTransaction({
  transaction: tx,
  signer: keypair,
  options: {
    showBalanceChanges: true,
    showEffects: true,
    showEvents: true,
    showInput: true,
    showObjectChanges: true,
  },
});

console.log(JSON.stringify(resp, null, 4));
