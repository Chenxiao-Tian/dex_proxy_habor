import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";
import { TransactionBlock } from "@mysten/sui.js/transactions";

const secretKey = "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6"
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));

const client = new SuiClient({url: getFullnodeUrl("testnet")});


const response = await client.getCoins({
    owner: '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c',
    //coinType: '0x7a36063de0879644fd8cb3bacd28ac7d892b61493c780ac1ff7557c9d5138daf::usdc::USDC'
    coinType: '0x002::sui::SUI'
});

// Get instance ids, keeping note of the one with highest balance
let largestInstance = undefined;
let largestValue = 0
let otherInstances = new Set();

let gasCoin = {}
for (let val of response.data) {
    console.log(val)

    let bal = Number(val.balance)

    otherInstances.add(val.coinObjectId);

    if (bal > largestValue) {
        largestValue = bal;
        largestInstance = val.coinObjectId;

        gasCoin.objectId = val.coinObjectId;
        gasCoin.digest = val.digest;
        gasCoin.version = val.version;
    }
}

otherInstances.delete(largestInstance);

console.log('Largest %s (%s)', largestInstance, largestValue);
console.log('Others %s', otherInstances);

if (otherInstances.size !== 0) {
    // Now merge all into largestInstance
    const transactionBlock = new TransactionBlock();

    await transactionBlock.mergeCoins(transactionBlock.gas, Array.from(otherInstances));

    transactionBlock.setGasPayment([gasCoin]);

    const response2 = await client.signAndExecuteTransactionBlock({
        signer: keypair,
        transactionBlock: transactionBlock,
        options: { showEffects: true }
    });

    console.log(response2);
}
