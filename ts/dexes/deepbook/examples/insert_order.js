import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

const secretKey = "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6"
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
const accountCapId = "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a";

const client = new SuiClient({url: getFullnodeUrl("testnet")});
const deepbook = new DeepBookClient(client, accountCapId);

const SUI_USDT_POOL = "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"

const poolId = SUI_USDT_POOL;
// Check against the `tick_size` of the pool
const price = 100;
// Check against the `lot_size` of the pool
const quantity = 100_000_000n;
const orderType = "ask";
const orderExpirationTsMs = Date.now() + (120 * 1000); // 2 minutes
//const restriction = 1; //LimitOrderType.IMMEDIATE_OR_CANCEL;
const restriction = 0; //LimitOrderType.NO_RESTRICTION
const clientOrderId = "2";
const selfMatchingPrevention = "CANCEL_OLDEST";

const txb = await deepbook.placeLimitOrder(
    poolId,
    price,
    quantity,
    orderType,
    orderExpirationTsMs,
    restriction,
    clientOrderId,
    selfMatchingPrevention
);

const resp = await client.signAndExecuteTransactionBlock({
    signer: keypair,
    transactionBlock: txb,
    options: {
        showBalanceChanges: true,
        showEffects: false,
        showEvents: true,
        showInput: false,
        showObjectChanges: false
    }
});

console.log(JSON.stringify(resp, null, 4))
