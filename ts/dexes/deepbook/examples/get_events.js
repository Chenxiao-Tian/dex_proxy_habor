import { getFullnodeUrl, SuiClient } from '@mysten/sui.js/client';

// use getFullnodeUrl to define testnet RPC location
const rpcUrl = getFullnodeUrl('testnet');

// create a client connected to devnet
const client = new SuiClient({ url: rpcUrl });

const events = await client.queryEvents({
    query: {
        Sender: '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c',
        //TimeRange: {
        //    startTime: "1701690515585",
        //    endTime: "1701690515588"
        //}
    },
});

console.log(JSON.stringify(events))
