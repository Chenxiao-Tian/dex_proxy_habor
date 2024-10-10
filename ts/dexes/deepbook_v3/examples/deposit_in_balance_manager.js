import { BalanceManagerContract, DeepBookConfig } from "@mysten/deepbook-v3";

import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Transaction } from "@mysten/sui/transactions";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { fromHex } from "@mysten/sui/utils";

const balanceManagers = {
  MANAGER_1: {
    address:
      "0x9d99510ddcce3e319c90d7caa8ffe81c433d201d404430bfcd08ca0bd85e514c",
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
const deepBookConfig = new DeepBookConfig({
  env: "testnet",
  address: address,
  balanceManagers: balanceManagers,
});
const balanceManagerContract = new BalanceManagerContract(deepBookConfig);

const tx = new Transaction();
tx.add(balanceManagerContract.depositIntoManager("MANAGER_1", "SUI", 10));
tx.add(balanceManagerContract.depositIntoManager("MANAGER_1", "DBUSDC", 10));
tx.add(balanceManagerContract.depositIntoManager("MANAGER_1", "DBUSDT", 10));
tx.add(balanceManagerContract.depositIntoManager("MANAGER_1", "DEEP", 100));

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
