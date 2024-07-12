

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";


// mainnet or testnet or devnet
const client = new SuiClient({url: getFullnodeUrl("testnet")});
const deepbook = new DeepBookClient(client);

const pools = await deepbook.getAllPools({});
console.log("All pools created on Deepbook:", pools);
