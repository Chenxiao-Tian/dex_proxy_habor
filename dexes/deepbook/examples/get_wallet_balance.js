

import { getFullnodeUrl, SuiClient } from '@mysten/sui.js/client';

// use getFullnodeUrl to define testnet RPC location
const rpcUrl = getFullnodeUrl('testnet');

// create a client connected to devnet
const client = new SuiClient({ url: rpcUrl });

// https://docs.sui.io/sui-api-ref#suix_getallbalances

const coins = await client.getAllBalances({
    owner: '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c',
});

console.log(coins)

const suiBalance = coins[0]['totalBalance'] / 10 ** 9

console.log(suiBalance)
