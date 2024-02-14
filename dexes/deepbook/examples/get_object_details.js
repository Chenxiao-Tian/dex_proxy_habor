import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const client = new SuiClient({url: getFullnodeUrl("testnet")});
const accountCapId = "0x27db71ddf34661fe5c49901d737b4ecc7482e1b9cd4541a5512d9f1a9401d07a";
const SUI_USDT_POOL = "0x5d2687b354f2ad4bce90c828974346d91ac1787ff170e5d09cb769e5dbcdefae"

const response = await client.getObject({
    id: SUI_USDT_POOL,
    options: {
        "showBcs": false,
        "showContent": true,
        "showDisplay": false,
        "showOwner": true,
        "showPreviousTransaction": false,
        "showStorageRebate": false,
        "showType": true
    }
});
console.log(JSON.stringify(response, null, 4));
