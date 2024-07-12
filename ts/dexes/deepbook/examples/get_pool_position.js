

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const client = new SuiClient({url: getFullnodeUrl("mainnet")});
const deepbook = new DeepBookClient(client);

const accountCap = "0xf092bffceae36c2be27fb2c96c1f5f5c250896002e894ddeeeddbd51e76a6150"
const SUI_USDT_POOL = "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33"
const poolInfo = await deepbook.getUserPosition(SUI_USDT_POOL, accountCap);
console.log("pool position: ", poolInfo);
