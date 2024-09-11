import { LoggerFactory } from "./logger.js";
import { WebServer } from "./web_server.js";
import { DeepBook } from "./dexes/deepbook/deepbook.js";
import { parseConfig } from "./config.js";
import { DexInterface, Mode} from "./types";
import { WebSocket } from "ws";
import { parseArgs } from "node:util";
import http from "http";
import winston from "winston";

export class DexProxy {
    private config: any;
    private logger: winston.Logger;
    private webServer: WebServer;
    private dexImpl: DexInterface;
    private subscriptions: Map<string, Set<WebSocket>>;

    constructor(config: any, mode: Mode) {
        this.config = config;
        let lf = new LoggerFactory(config);
        this.logger = lf.createLogger("dex_proxy");
        this.webServer = new WebServer(lf, config, this);

        if (config.dex.name == "deepbook") {
            this.dexImpl = new DeepBook(lf, this.webServer, config, mode, this);
        }
        else {
            const error = `${config.dex.name} is not supported`;
            throw new Error(error);
        }

        this.subscriptions = new Map<string, Set<WebSocket>>();
    }

    start = async () => {
        await this.dexImpl.start();
    }

    onWsMessage = async (ws: WebSocket, json: any) => {
        // TODO: Assert for the presence of keys
        const requestId: string = json.id;
        const method: string = json.method;
        let channels: Array<string> = json.params.channels;

        if (method === "subscribe") {
            this.onWsSubscription(ws, requestId, channels);
        } else if (method === "unsubscribe") {
            // TODO
        } else {
            this.logger.crit(`Unknown method ${method} in {json} from {ws}`);
            // TODO: Close ws connection on unknown message
        }
    }

    onWsSubscription = async (ws: WebSocket,
                              requestId: string,
                              channels: Array<string>) => {
        let reply: any = {
            jsonrpc: "2.0",
            id: requestId
        };

        let nonExistentChannels = new Array<string>();
        for (const channel of channels) {
            if (! this.dexImpl.channels.includes(channel)) {
                nonExistentChannels.push(channel);
            }
        }
        if (nonExistentChannels.length !== 0) {
            reply.error = `Channel(s): [${nonExistentChannels.join(",")}] do not exist`;
        } else {
            let result = new Array<string>();
            for (const channel of channels) {
                let channelSubscriptions = this.subscriptions.get(channel);
                if (channelSubscriptions === undefined) {
                    channelSubscriptions = new Set([ws]);
                    this.subscriptions.set(channel, channelSubscriptions)
                } else {
                    channelSubscriptions.add(ws);
                }
                result.push(channel);
            }
            reply.result = result;
        }

        await this.webServer.sendWsMsg(ws, reply);
    }

    onEvent = async (channel: string, event: any) => {
        this.logger.debug(`channel=${channel}, event=${JSON.stringify(event)}`);
        let channelSubs = this.subscriptions.get(channel);
        if (channelSubs !== undefined) {
            for (let ws of channelSubs) {
                await this.webServer.sendWsMsg(ws, event);
            }
        }
    }
};

const parseCmdLine = (args: Array<string>) => {
    const params = {
        config: {
            type: "string" as "string",
            short: "c"
        },
        mode: {
            type: "string" as "string",
            short: "m"
        }
    };

    let parsedArgs = parseArgs({args: args, options: params}).values

    if (parsedArgs.mode === undefined) {
        parsedArgs.mode = "read-write";
    } else if (parsedArgs.mode !== "read-only" &&
               parsedArgs.mode !== "read-write") {
        throw new Error("--mode only accepts values `read-only` and `read-write`");
    }

    return parsedArgs;
}

const main = async () => {
    let parsedArgs = parseCmdLine(process.argv.slice(2));
    let config = parseConfig(parsedArgs.config);
    let dexProxy = new DexProxy(config, parsedArgs.mode! as Mode);
    await dexProxy.start();
}

await main();
