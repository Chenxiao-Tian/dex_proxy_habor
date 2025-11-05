import { SuiClient, getFullnodeUrl } from "@mysten/sui/client";

const client = new SuiClient({ url: getFullnodeUrl("mainnet") });

const response = await client.getObject({
  id: "0xc2f1bfdd0a718582d6dbde8ac77d9fd32cf72c9f09facfa8f787febdb02ae8e2",
  options: {
    showBcs: true,
    showContent: true,
    showDisplay: true,
    showOwner: true,
    showPreviousTransaction: true,
    showStorageRebate: true,
    showType: true,
  },
});
console.log(JSON.stringify(response, null, 4));
