

import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { DeepBookClient } from '@mysten/deepbook';
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

const secretKey = "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6"
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
//const accountCapId = "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a";
const accountCapId = "0xd88a8427aec2b9bf2c5be0ef99ca9fafac9348005a92d617f031059214ed93d5"

const client = new SuiClient({url: getFullnodeUrl("testnet")});
const deepbook = new DeepBookClient(client, accountCapId);

const SUI_USDT_POOL = "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"

const txb = await deepbook.deposit(
    SUI_USDT_POOL,
    undefined,
    100000000n
);

const response = await client.signAndExecuteTransactionBlock({
    signer: keypair,
    transactionBlock: txb,
    options: {
        showEffects: true,
        showEvents: true,
        showBalanceChanges: true,
        showObjectChanges: false
    }
});

console.log(JSON.stringify(response, null, 4));
