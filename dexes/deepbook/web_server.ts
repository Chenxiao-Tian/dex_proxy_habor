import http from "http";
import url from "url";
import winston from "winston";
import { WebSocketServer, WebSocket } from "ws";
import { v4 as uuidV4 } from "uuid";
import util from "util";

import { LoggerFactory } from "./logger.js";
import { DexProxy } from "./dex_proxy.js";
import { ParsedOrderError } from "./deepbook.js";

export interface RestResult {
    statusCode: number;
    payload: any;
}

export interface RestRequestHandler {
    (...args: any[]): Promise<RestResult>;
}

class WebServer {
    logger: winston.Logger;
    port: Number;
    httpServer: http.Server;
    wsServer: WebSocketServer;
    // method -> path -> requestHandler
    routes: Map<string, Map<string, RestRequestHandler>>;
    wsConnections: WeakMap<WebSocket, string>;
    dexProxy: DexProxy;
    requestId: bigint;

    constructor(lf: LoggerFactory, config: any, dexProxy: DexProxy) {
        this.logger = lf.createLogger("web_server");
        if (config.server?.port === undefined) {
            throw new Error("server.port must be defined in the config");
        }
        this.port = config.server.port;
        this.httpServer = http.createServer(this.onHTTPMessage);
        this.wsServer = new WebSocketServer({noServer: true});
        this.wsServer.on("connection", this.onWSConnection);
        this.httpServer.on("upgrade", this.onHTTPUpgrade);
        this.routes = new Map<string, Map<string, RestRequestHandler>>();
        this.wsConnections = new WeakMap<WebSocket, string>();
        this.dexProxy = dexProxy;
        this.requestId = 0n;
    }

    processGetRequest = async (requestId: bigint,
                               request: http.IncomingMessage,
                               response: http.ServerResponse,
                               path: string,
                               queryParams: url.URLSearchParams,
                               receivedAtMs: number,
                               handler: RestRequestHandler) => {
        try {
            const result = await handler(requestId, path, queryParams,
                                         receivedAtMs);
            response.writeHead(result.statusCode,
                               {"Content-Type": "application/json"});
            response.end(JSON.stringify(result.payload));
        } catch (error) {
            response.writeHead(400, {"Content-Type": "application/json"});
            response.end(JSON.stringify({error: `${error}`}));
        }
    }

    processPostRequest = async (requestId: bigint,
                                request: http.IncomingMessage,
                                response: http.ServerResponse,
                                path: string,
                                receivedAtMs: number,
                                handler: RestRequestHandler) => {
        let body = "";

        request.on("data", (chunk) => {
            body += chunk.toString();
        });

        request.on("end", async () => {
            try {
                const data = JSON.parse(body);
                const result = await handler(requestId, path, data, receivedAtMs);
                response.writeHead(result.statusCode,
                                   {"Content-Type": "application/json"});
                response.end(JSON.stringify(result.payload));
            } catch (error) {
                response.writeHead(400, {"Content-Type": "application/json"});
                if (error instanceof ParsedOrderError) {
                    response.end(JSON.stringify({
                        type: error.type,
                        error: error.message
                    }));
                } else {
                    response.end(JSON.stringify({error: `${error}`}));
                }
            }
        });
    }

    processDeleteRequest = async (requestId: bigint,
                                  request: http.IncomingMessage,
                                  response: http.ServerResponse,
                                  path: string,
                                  queryParams: url.URLSearchParams,
                                  receivedAtMs: number,
                                  handler: RestRequestHandler) => {
        try {
            const result = await handler(requestId, path, queryParams,
                                         receivedAtMs);
            response.writeHead(result.statusCode,
                               {"Content-Type": "application/json"});
            response.end(JSON.stringify(result.payload));
        } catch (error) {
            if (error instanceof ParsedOrderError) {
                let responseCode = (error.responseCode) ? error.responseCode : 400
                response.writeHead(responseCode, {"Content-Type": "application/json"});
                response.end(JSON.stringify({
                    type: error.type,
                    error: error.message
                }));
            } else {
                response.writeHead(500, {"Content-Type": "application/json"});
                response.end(JSON.stringify({error: `${error}`}));
            }
        }
    }

    onHTTPMessage = async (request: http.IncomingMessage,
                           response: http.ServerResponse): Promise<void> => {
        const parsedUrl = new URL(request.url!, `http://${request.headers.host}`);
        const path = parsedUrl.pathname;
        const handler = this.routes.get(request.method!)?.get(path);
        if (handler === undefined) {
            response.writeHead(404, {"Content-Type": "application/json"});
            response.end(JSON.stringify({error: `Route (${request.method}, ${parsedUrl.pathname}) not defined`}));
            return;
        }
        const receivedAtMs = Date.now();

        if (request.method === "GET") {
            const queryParams = parsedUrl.searchParams;
            this.processGetRequest(++this.requestId, request, response, path,
                                   queryParams, receivedAtMs, handler);
        } else if (request.method === "POST") {
            this.processPostRequest(++this.requestId, request, response, path,
                                    receivedAtMs, handler);
        } else if (request.method === "DELETE") {
            const deletionParams = parsedUrl.searchParams;
            this.processDeleteRequest(++this.requestId, request, response, path,
                                      deletionParams, receivedAtMs, handler);
        }
    }

    onWSMessage = async (ws: WebSocket,
                         data: Buffer,
                         isBinary: boolean): Promise<void> => {
        const message: Buffer | string = isBinary ? data : data.toString();

        this.logger.debug(`Received ws message, ${message}`);

        try {
            if (typeof message === "string") {
                try {
                    let json = JSON.parse(message);
                    this.dexProxy.onWsMessage(ws, json);
                } catch (error) {
                    this.logger.error(error)
                    throw new Error("Unable to parse WS message as JSON");
                }
            } else {
                throw new Error("The WS server does not support binary messages");
            }
        } catch (error) {
            let errorStr = (error as any).toString();
            let message = {
                jsonrpc: "2.0",
                error: {
                    "message": errorStr
                }
            }
            this.sendWsMsg(ws, message);
            // TODO: Close ws connection
            // TODO: Add id to message
        }
    }

    onWsDisconnection = async (ws: WebSocket, code: Number, reason: Buffer) => {
        this.logger.info(`Client disconnect(id=${this.wsConnections.get(ws)}), code:${code}, reason:${reason}`);
        this.wsConnections.delete(ws);
    }

    onWSConnection = async (ws: WebSocket, request: http.IncomingMessage) => {
        const id = uuidV4();
        this.logger.debug(`New client connection(id=${id}) from ${request.socket.remoteAddress}`);
        this.wsConnections.set(ws, id);

        ws.on("error", this.logger.error);
        ws.on("message", async (data: Buffer, isBinary: boolean) => {
            this.onWSMessage(ws, data, isBinary);
        });
        let self = this;
        ws.on("close", (code, reason) => {
            self.logger.info(`Client disconnect(id=${self.wsConnections.get(ws)}), code:${code}, reason:${reason}`);
            self.wsConnections.delete(ws);
        });
    }

    onHTTPUpgrade = async (request: http.IncomingMessage,
                           socket: any,
                           head: Buffer) => {
        const parsedUrl = new URL(request.url!, `http://${request.headers.host}`);
        if (parsedUrl.pathname != "/ws") {
            // TODO: Handle gracefully
            socket.destroy();
            this.logger.error("Cannot accept WS connection request");
        } else {
            this.wsServer.handleUpgrade(
                request, socket, head,
                (ws: WebSocket, request: http.IncomingMessage) => {
                    this.wsServer.emit("connection", ws, request);
                }
            );
        }
    }

    sendWsMsg = async (ws: WebSocket, message: any) => {
        if (this.wsConnections.get(ws) === undefined) return;

        try {
            await ws.send(JSON.stringify(message), {binary: false});
        } catch (error) {
            this.logger.error(`Could not send ${JSON.stringify(message)}`);
            this.logger.error(error);
            // TODO: Close ws connection
        }
    }

    start = async () => {
        this.logger.info("Starting")
        this.httpServer.listen(this.port, () => {
            this.logger.info(`Server is listening on http://localhost:${this.port}`);
        })
    }

    register = (method: string, path: string, handler: RestRequestHandler) => {
        this.logger.debug(`Registering a handler for (${method}, ${path})`)
        if (this.routes.has(method)) {
            const methodMap = this.routes.get(method);
            if (methodMap!.has(path)) {
                throw new Error(`A handler already exists for (${method}, ${path})`)
            } else {
                methodMap!.set(path, handler);
            }
        } else {
            this.routes.set(method, new Map<string, RestRequestHandler>([
                [path, handler]
            ]));
        }
    }
}

export {WebServer};
