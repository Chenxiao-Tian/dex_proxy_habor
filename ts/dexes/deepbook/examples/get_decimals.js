import { SuiClient, getFullnodeUrl } from "@mysten/sui.js/client";

const client = new SuiClient({url: getFullnodeUrl("mainnet")});

const response = await client.getCoinMetadata({
    coinType: '0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN'
});
console.log('Decimals %s', response.decimals);
