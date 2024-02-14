import { DeepBookClient } from '@mysten/deepbook';
import { SuiClient, getFullnodeUrl, SuiHTTPTransport } from "@mysten/sui.js/client";
import { WebSocket } from "ws";

const client = new SuiClient({
    transport: new SuiHTTPTransport({
        url: getFullnodeUrl("testnet"),
        WebSocketConstructor: WebSocket
    }),
});
const deepbook = new DeepBookClient(client);
const packageId = "0x000000000000000000000000000000000000000000000000000000000000dee9";
const walletAddress = "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c";
const deepbookClobEventsFilter = {
    //MoveModule: {
    //    package: packageId,
    //    module: "clob_v2"
    //}
    Sender: walletAddress
}

client.subscribeEvent({
    filter: deepbookClobEventsFilter,
    onMessage(event) {
        console.log(JSON.stringify(event, null, 4));
    }
});
