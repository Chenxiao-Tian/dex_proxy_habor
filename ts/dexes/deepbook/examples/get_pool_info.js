

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const client = new SuiClient({url: getFullnodeUrl("mainnet")});
const deepbook = new DeepBookClient(client);

const SUI_USDT_POOL = "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33"
const poolInfo = await deepbook.getPoolInfo(SUI_USDT_POOL);
console.log("poolInfo: ", poolInfo);
