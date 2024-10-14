import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const walletAddress =
  "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c";
const StructType = "0x2::coin::Coin<0x2::sui::SUI>";

const client = new SuiClient({ url: getFullnodeUrl("testnet") });

let cursor = null;
let objs = null;
let objIds = [];
do {
  objs = await client.getOwnedObjects({
    owner: walletAddress,
    filter: {
      MatchAll: [
        {
          StructType: StructType,
        },
      ],
    },
    cursor: cursor,
  });

  cursor = objs.nextCursor;

  for (let val of objs["data"]) {
    objIds.push(val["data"]["objectId"]);
  }
} while (objs.hasNextPage);

console.log(objIds);

for (let objId of objIds) {
  console.log(
    await client.getObject({
      id: objId,
      options: {
        showType: true,
        showDisplay: true,
        showOwner: true,
      },
    })
  );
}
