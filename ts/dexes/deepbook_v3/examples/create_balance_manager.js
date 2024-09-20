import { BalanceManagerContract, DeepBookConfig } from "@mysten/deepbook-v3";

import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Transaction } from "@mysten/sui/transactions";
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
const deepBookConfig = new DeepBookConfig({ env: "testnet", address: address });
const balanceManagerContract = new BalanceManagerContract(deepBookConfig);

const tx = new Transaction();
tx.add(balanceManagerContract.createAndShareBalanceManager());

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

// created balance_manager address is effects.created[0].reference.objectId
console.log(JSON.stringify(resp, null, 4));
