import { SuiClient, getFullnodeUrl } from "@mysten/sui/client";

const client = new SuiClient({ url: getFullnodeUrl("mainnet") });

const block = await client.getTransactionBlock({
  digest: "c2f1bfdd0a718582d6dbde8ac77d9fd32cf72c9f09facfa8f787febdb02ae8e2",
  options: {
    showBalanceChanges: true,
    showEvents: true,
    showObjectChanges: true,
    showEffects: true,
    showInput: true,
  },
});

console.log(JSON.stringify(block));
