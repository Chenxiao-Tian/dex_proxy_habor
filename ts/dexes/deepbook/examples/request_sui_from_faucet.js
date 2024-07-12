

import { getFullnodeUrl, SuiClient } from '@mysten/sui.js/client';
import { getFaucetHost, requestSuiFromFaucetV0 } from '@mysten/sui.js/faucet';
import { MIST_PER_SUI } from '@mysten/sui.js/utils';

const MY_ADDRESS = '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c';

// create a new SuiClient object pointing to the network you want to use
const suiClient = new SuiClient({ url: getFullnodeUrl('testnet') });

// Convert MIST to Sui
const balance = (balance) => {
    return Number.parseInt(balance.totalBalance) / Number(MIST_PER_SUI);
};

// store the JSON representation for the SUI the address owns before using faucet
const suiBefore = await suiClient.getBalance({
    owner: MY_ADDRESS,
});

/*
await requestSuiFromFaucetV0({
    // use getFaucetHost to make sure you're using correct faucet address
    // you can also just use the address (see Sui TypeScript SDK Quick Start for values)
    host: getFaucetHost('testnet'),
    recipient: MY_ADDRESS,
});
*/

// store the JSON representation for the SUI the address owns after using faucet
const suiAfter = await suiClient.getBalance({
    owner: MY_ADDRESS,
});

// Output result to console.
console.log(
    `Balance before faucet: ${balance(suiBefore)} SUI. Balance after: ${balance(
        suiAfter,
    )} SUI. Hello, SUI!`,
);
