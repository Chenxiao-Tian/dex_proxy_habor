

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

const secretKey = "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6"
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
const client = new SuiClient({url: getFullnodeUrl("testnet")});
const deepbook = new DeepBookClient(client);
const txb = deepbook.createAccount("0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c");
const resp = await client.signAndExecuteTransactionBlock({
    signer: keypair,
    transactionBlock: txb,
    options: {
        showEffects: true,
        showEvents: true,
        showBalanceChanges: true,
        showObjectChanges: true
    }
});

console.log(resp)
