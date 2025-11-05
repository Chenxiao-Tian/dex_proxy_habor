

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const accountCapId = "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a";

const client = new SuiClient({url: getFullnodeUrl("testnet")});
const deepbook = new DeepBookClient(client, accountCapId);

const SUI_USDT_POOL = "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"

const openOrders = await deepbook.listOpenOrders(SUI_USDT_POOL);
console.log(`Open orders: ${JSON.stringify(openOrders)}`);
