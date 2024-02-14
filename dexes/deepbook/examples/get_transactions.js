

import { getFullnodeUrl, SuiClient } from '@mysten/sui.js/client';

// use getFullnodeUrl to define testnet RPC location
const rpcUrl = getFullnodeUrl('testnet');

// create a client connected to devnet
const client = new SuiClient({ url: rpcUrl });

const transactionBlocks = await client.queryTransactionBlocks({
    filter: {
        //ToAddress: '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c',
        FromAddress: '0x077338d8dbe6c4f9c8a4e85738013ae736b1b114c9bc9feed36ce41ead7d4bc0',
        //MoveFunction: {
        //    package: "0x2",
        //    module: "coin",
        //}
    },
});

console.log(transactionBlocks)

for (let i = 0; i < transactionBlocks.data.length; ++i) {
    let item = transactionBlocks.data[i];
    let digest = item['digest'];
    console.log(digest);
    const block = await client.getTransactionBlock({
        digest: digest,
        options: {
            showBalanceChanges: true,
            showEvents: true,
            showObjectChanges: true,
            showEffects: true,
            showInput: true,
        }
    });
    console.log(JSON.stringify(block));
}
