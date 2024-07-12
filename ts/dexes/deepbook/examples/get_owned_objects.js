

import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

const client = new SuiClient({url: getFullnodeUrl("testnet")});

const objs = await client.getOwnedObjects({
    owner: '0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c',
    filter: {
        MatchAll: [
            {
                StructType: "0xdee9::custodian_v2::AccountCap"
            }
        ]
    }
});

let objIds = []
for (let val of objs["data"]) {
    objIds.push(val["data"]["objectId"]);
}
console.log(objIds);

for (let objId of objIds) {
    console.log(await client.getObject({
        id: objId,
        options: {
            showType: true,
            showDisplay: true,
            showOwner: true
        }
    }));
}
