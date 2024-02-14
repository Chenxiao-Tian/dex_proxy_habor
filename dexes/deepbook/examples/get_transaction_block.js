import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const client = new SuiClient({url: getFullnodeUrl("testnet")});
const txDigest = "AUPDTdSDVeKXzFMeUFohS7kkuVAFGfB96imqSL8vTu1L"

const response = await client.getTransactionBlock({
    digest: txDigest,
    options: {
        showBalanceChanges: true,
        showEffects: false,
        showEvents: true,
        ShowInput: false,
        ShowObjectChanges: true,
        ShowRawInput: false
    }
});
console.log(JSON.stringify(response, null, 4));
