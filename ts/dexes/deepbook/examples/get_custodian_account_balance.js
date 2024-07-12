

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";



const getUserPosition = async (network, accountCapId, poolId) => {
    const client = new SuiClient({url: getFullnodeUrl(network)});
    const deepbook = new DeepBookClient(client, accountCapId);

    const position = await deepbook.getUserPosition(poolId);

    const MIST_PER_SUI = 1_000_000_000;

    let result = {}
    const format = (key, value) => {
        const formattedValue = Number(value) / MIST_PER_SUI;
        result[key] = `${formattedValue.toLocaleString()}`;
    }

    for (const [key, value] of Object.entries(position)) {
        format(key, value)
    }

    console.log(`network: ${network}`);
    console.log(`accountCapId: ${accountCapId}`);
    console.log(`poolId: ${poolId}`);
    console.log(result)
}

const testnetDetails = {
    network: "testnet",
    // Main accountCap
    //accountCapId: "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a",
    // Child accountCap
    accountCapId: "0x2605db4d2e7028c8679fcc006fe2c247f51006f900c3881103303475343adff2",
    // SUI_USDT_POOL
    //poolId: "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"
    // FISH_GOLD_POOL
    poolId: "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2"
}

const mainnetDetails = {
    network: "mainnet",
    accountCapId: "0xc46cfbe82b67676918fa11350978c2255f5305e855fe890c0a1a6b90f00075a1",
    // SUI_USDC_POOL
    poolId: "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33"
}

//const details = mainnetDetails;
const details = testnetDetails;
await getUserPosition(details.network, details.accountCapId, details.poolId);
