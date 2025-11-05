import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

const testnet = {
    network: "testnet",
    wallet: "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c",
    secretKey: "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6",
    accountCapId: "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a"
};

const createChildAccountCap = async (nw, wallet, secretKey, accountCapId) => {
    const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
    const client = new SuiClient({url: getFullnodeUrl(nw)});
    const deepbook = new DeepBookClient(client);
    const txb = deepbook.createChildAccountCap(wallet, accountCapId);
    return await client.signAndExecuteTransactionBlock({
        signer: keypair,
        transactionBlock: txb,
        options: {
            showEffects: true,
            showEvents: true,
            showBalanceChanges: true,
            showObjectChanges: true
        }
    });
}

const response = await createChildAccountCap(testnet.network,
                                             testnet.wallet,
                                             testnet.secretKey,
                                             testnet.accountCapId);

console.log(JSON.stringify(response, null, 4));
