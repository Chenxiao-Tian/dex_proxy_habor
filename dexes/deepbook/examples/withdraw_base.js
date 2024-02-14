import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { DeepBookClient } from '@mysten/deepbook';
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

const secretKey = "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6"
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
const accountCapId = "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a";

const client = new SuiClient({url: getFullnodeUrl("testnet")});
const wallet = "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c"
const deepbook = new DeepBookClient(client, accountCapId, wallet);

const SUI_USDT_POOL = "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"

const poolId = SUI_USDT_POOL
const quantity = 200001001n
const assetType = "base";
const txb = await deepbook.withdraw(
    poolId,
    quantity,
    assetType
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
