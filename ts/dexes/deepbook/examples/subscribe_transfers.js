import { getFullnodeUrl, SuiClient, SuiHTTPTransport } from '@mysten/sui.js/client';
import { WebSocket } from 'ws';

// use getFullnodeUrl to define testnet RPC location
const rpcUrl = getFullnodeUrl('testnet');


const client = new SuiClient({
    transport: new SuiHTTPTransport({
        url: rpcUrl,
        WebSocketConstructor: WebSocket,
    }),
});

const handleMessage = (event) => {
  console.log(JSON.stringify(event) + "\n\n");
};

//const unsubscribe = await client.subscribeEvent({onMessage: (event) => {handleMessage(event)}});
const unsubscribe = await client.subscribeTransaction({
    filter: {
        //MoveFunction: {
        //  package: "0x2",
            //module: "coin",
        //},
        // FromOrToAddress is not supported :cry: https://github.com/MystenLabs/sui/issues/14301
        ToAddress: '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c'
    },
    onMessage(event) {
        handleMessage(event)
    }});
