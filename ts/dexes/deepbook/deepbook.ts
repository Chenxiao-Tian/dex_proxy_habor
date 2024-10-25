import { LoggerFactory } from "../../logger.js";
import {
    WebServer,
    RestResult,
    RestRequestHandler
} from "../../web_server.js";
import {
    GasManager,
    GasCoin,
    GasCoinStatus
} from "./gas_manager.js";
import { Executor, TransactionBlockGenerator, AccountCap } from "./executor.js";
import { DexProxy } from "../../dex_proxy.js";
import type { PoolInfo } from "./types.js";
import {
    OrderCache,
    Order,
    Side,
    OrderStatus,
    ClientOrderId,
    ExchangeOrderId,
    ExchangeTradeId,
    PoolId,
    Quantity,
    Price,
    TxDigest,
    TimestampMs,
    Event,
    OrderPlacedEvent,
    OrderCancelledEvent,
    OrderFilledEvent
} from "../../order_cache.js";
import { DeepBookClient } from '@mysten/deepbook';
import {
    SuiClient,
    TransactionFilter,
    QueryTransactionBlocksParams,
    QueryEventsParams,
    SuiTransactionBlockResponse,
    PaginatedObjectsResponse,
    SuiHTTPTransport,
    SuiEvent,
    SuiEventFilter,
    JsonRpcError,
    EventId,
    SuiHTTPStatusError,
    SuiTransactionBlockResponseOptions
} from "@mysten/sui.js/client";
import {
  parseStructTag,
  normalizeStructTag,
  normalizeSuiAddress,
  SUI_CLOCK_OBJECT_ID
} from "@mysten/sui.js/utils";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";
import { TransactionBlock } from "@mysten/sui.js/transactions";
import { readFileSync } from "fs";
import { dirname } from "path";
import { Logger } from "winston";
import { SuiTxBlock }  from "./sui_tx_block.js";
import { WebSocket } from "ws";
import {ParsedOrderError, DexInterface, Mode} from "../../types.js";
import { assertFields } from "../../utils.js";

const FLOAT_SCALING_FACTOR: number = 1_000_000_000;

interface ParsedExchangeError {
    type: string | null;
    txNumber: number | null;
}

class MandatoryFields {
    static InsertRequest           = ["client_order_id", "pool_id",
                                      "order_type", "side", "quantity",
                                      "price", "expiration_ts"];
    static BulkInsertRequest       = ["pool_id", "expiration_ts", "orders"];
    static CancelRequest           = ["client_order_id", "pool_id"];
    static CancelAllRequest        = ["pool_id"];
    static BulkCancelRequest       = ["pool_id", "client_order_ids"];
    static TransactionBlockRequest = ["digest"];
    static EventsFromDigests       = ["tx_digests"];
    static OrderStatusRequest      = ["pool_id", "client_order_id"];
    static AllOpenOrdersRequest    = ["pool_id"];
    static PoolDepositRequest      = ["pool_id", "coin_type_id", "quantity"];
    static PoolWithdrawalRequest   = ["pool_id", "coin_type_id", "quantity"];
    static SuiWithdrawalRequest    = ["recipient", "quantity"];
    static WithdrawalRequest       = ["coin_type_id", "recipient", "quantity"];
    static ObjectInfoRequest       = ["id"];
    static PoolInfoRequest         = ["id"];
    static UserPositionRequest     = ["id"];
    static TradesByTimeRequest     = ["start_ts", "max_pages"];
    static TradesByDigestRequest   = ["tx_digests"];
}

type TxBlockGenerator = () => Promise<TransactionBlock>;

export class DeepBook implements DexInterface {
    private logger: Logger;
    private config: any;
    private server: WebServer;
    private mode: Mode;
    private dexProxy: DexProxy;
    private log_responses: boolean;

    private orderCache: OrderCache;

    private keyPair: Ed25519Keypair | undefined;
    private suiClient: SuiClient;

    private walletAddress: string;

    private mainAccountCapId: string;
    private mainDeepbookClient: DeepBookClient;

    private gasManager: GasManager | undefined ;
    private executor: Executor | undefined;

    private chainName: string;
    private withdrawalAddresses: Map<string, Set<string>>;

    private currentEpoch: string | undefined;

    private static exchangeErrors = new Map<string, Map<string, string>> ([
        ["clob_v2", new Map<string, string>([
          ["2",  "INVALID_FEE_RATE_REBATE_RATE"],
          ["3",  "INVALID_ORDER_ID"],
          ["4",  "UNAUTHORIZED_CANCEL"],
          ["5",  "INVALID_PRICE"],
          ["6",  "INVALID_QUANTITY"],
          ["7",  "INSUFFICIENT_BASE_COIN"],
          ["8",  "INSUFFICIENT_QUOTE_COIN"],
          ["9",  "ORDER_CANNOT_BE_FULLY_FILLED"],
          ["10", "ORDER_CANNOT_BE_FULLY_PASSIVE"],
          ["11", "INVALID_TICK_PRICE"],
          ["12", "INVALID_USER"],
          ["13", "NOT_EQUAL"],
          ["14", "INVALID_RESTRICTION"],
          ["16", "INVALID_PAIR"],
          ["18", "INVALID_FEE"],
          ["19", "INVALID_EXPIRE_TIMESTAMP"],
          ["20", "INVALID_TICK_SIZE_LOT_SIZE"],
          ["21", "INVALID_SELF_MATCHING_PREVENTION_ARG"]
        ])],
        ["balance", new Map<string, string>([
            ["2", "INSUFFICIENT_BALANCE"]
        ])]
    ]);

    public channels: Array<string> = ["ORDER", "TRADE"];

    constructor(lf: LoggerFactory, server: WebServer, config: any, mode: Mode,
                dexProxy: DexProxy) {
        this.logger = lf.createLogger("deepbook");
        this.config = config;
        this.server = server;

        if (config.dex === undefined) {
            throw new Error("A section corresponding to `dex` must be present in the config");
        }

        this.orderCache = new OrderCache(lf, config.dex.order_cache);
        this.mode = mode;
        this.logger.info(`mode=${mode}`);

        this.log_responses = false;
        if (config.dex.log_responses != undefined) {
            this.log_responses = config.dex.log_responses;
        }

        this.dexProxy = dexProxy;

        if (this.mode == "read-write") {
            const secretKey = this.readPrivateKey();
            this.keyPair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
            this.walletAddress = this.keyPair.getPublicKey().toSuiAddress();
        } else {
            this.keyPair = undefined;
            if (config.dex.wallet_address === undefined) {
                throw new Error("The key, `dex.wallet_address` must be present in the config");
            }
            this.walletAddress = config.dex.wallet_address
        }
        this.logger.info(`wallet=${this.walletAddress}`);

        let connectors = this.parseExchangeConnectorConfig();
        this.logger.info(`RPC node rest api url=${connectors.rest.url}`);
        this.logger.info(`RPC node websocket url=${connectors.ws.url}`);

        if (config.dex.subscribe_to_events) {
            this.logger.info("Subscribing to events");
            this.suiClient = new SuiClient({
                transport: new SuiHTTPTransport({
                    url: connectors.rest.url,
                    rpc: {
                        headers: connectors.rest.headers
                    },
                    WebSocketConstructor: WebSocket as never,
                    websocket: {
                        url: connectors.ws.url,
                        callTimeout: connectors.ws.callTimeoutMs,
                        reconnectTimeout: connectors.ws.reconnectTimeoutMs,
                        maxReconnects: connectors.ws.maxReconnects
                    }
                }),
            });
        } else {
            this.logger.info("Not subscribing to events");
            this.suiClient = new SuiClient({
                transport: new SuiHTTPTransport({
                    url: connectors.rest.url,
                    rpc: {
                        headers: connectors.rest.headers
                    }
                })
            });
        }

        if (config.dex.account_cap_ids === undefined) {
            this.logger.warn("Cannot perform order or transfer related operations with an entry for `dex.account_cap_ids` in the config");
        }
        this.mainAccountCapId = config.dex.account_cap_ids.main;
        if (this.mainAccountCapId === undefined) {
            this.logger.warn("Cannot perform any account related operations without an entry for `dex.account_cap_ids.main` in the config");
        }
        this.mainDeepbookClient = new DeepBookClient(
            this.suiClient, this.mainAccountCapId, this.walletAddress
        );

        let childAccountCapIds = config.dex.account_cap_ids.children;
        if (childAccountCapIds === undefined) {
            this.logger.warn("Cannot send orders or make transfers without an entry for `dex.account_cap_ids.children` in the config");
            childAccountCapIds = new Array<string>();
        }

        if (this.mode === "read-write") {
            const balancePerInstanceMist = BigInt(config.dex.gas_manager.balance_per_instance_mist.replace(/,/g, ''));
            const minBalancePerInstanceMist = BigInt(config.dex.gas_manager.min_balance_per_instance_mist.replace(/,/g, ''));
            const syncIntervalMs = 1000 * Number(config.dex.gas_manager.sync_interval_s);
            this.gasManager = new GasManager(lf, this.suiClient,
                                             this.walletAddress, this.keyPair!,
                                             childAccountCapIds.length,
                                             balancePerInstanceMist,
                                             minBalancePerInstanceMist,
                                             syncIntervalMs, this.log_responses);

            const gasBudgetMist = BigInt(config.dex.gas_manager.gas_budget_mist.replace(/,/g, ''));

            this.executor = new Executor(lf, this.suiClient, this.keyPair!,
                                         this.gasManager, gasBudgetMist, this.walletAddress,
                                         childAccountCapIds);
        } else {
            this.gasManager = undefined;
            this.executor = undefined;
        }

        this.chainName = config.dex.chain_name;
        this.withdrawalAddresses = new Map<string, Set<string>>();
        if (mode === "read-write") {
            if (this.chainName === undefined) {
                throw new Error("The key `dex.chain_name` must be present in the config");
            }
            this.fetchWithdrawalAddresses();
        }

        this.registerEndpoints();
    }

    fetchWithdrawalAddresses = (): void => {
        const filePrefix = dirname(process.argv[1]);
        const filename = `${filePrefix}/resources/deep_withdrawal_addresses.json`;
        try {
            let contents = JSON.parse(readFileSync(filename, "utf8"));
            this.logger.info(`Looking up configured withdrawal addresses for chainName=${this.chainName} from ${filename}`);
            let tokenData = contents[this.chainName]?.tokens;
            if (tokenData) {
                for (let entry of tokenData) {
                    let coinType = entry.coin_type;
                    let withdrawalAddresses = new Set<string>(entry.valid_withdrawal_addresses);
                    this.withdrawalAddresses.set(coinType, withdrawalAddresses);
                }
            }
        } catch (error) {
            const msg = `Failed to parse withdrawal addresses from ${filename}`;
            this.logger.error(msg);
            throw new Error(msg);
        }
    }

    parseExchangeConnectorConfig = (): any => {
        if (this.config.dex.exchange_connectors === undefined) {
            throw new Error("The section, `dex.exchange_connectors` must be present in the config");
        }

        let connectors = this.config.dex.exchange_connectors;
        if (connectors.rest === undefined ||
            connectors.ws === undefined) {
            throw new Error("The sections `dex.exchange_connectors.rest` and `dex.exchange_connectors.ws` must be present in the config");
        }

        const wsCallTimeoutMs = (connectors.ws.call_timeout_s !== undefined)
                                ? connectors.ws.call_timeout_s * 1_000
                                : 30_000;
        const wsReconnectTimeoutMs = (connectors.ws.reconnect_timeout_s !== undefined)
                                     ? connectors.ws.reconnect_timeout_s * 1_000
                                     : 3_000;
        const wsMaxReconnects = (connectors.ws.max_reconnects !== undefined)
                              ? connectors.ws.max_reconnects
                              : 5;

        const headers: Map<String, String> = (connectors.rest.headers) ? connectors.rest.headers : new Map<String, String>();

        let parsedConfig = {
            rest: {
                url: connectors.rest.url,
                headers: headers
            },
            ws: {
                url: connectors.ws.url,
                callTimeoutMs: wsCallTimeoutMs,
                reconnectTimeoutMs: wsReconnectTimeoutMs,
                maxReconnects: wsMaxReconnects
            }
        };

        return parsedConfig;
    }

    registerEndpoints = () => {
        const GET = (path: string, handler: RestRequestHandler) => {
            this.server.register("GET", path, handler);
        };
        const POST = (path: string, handler: RestRequestHandler) => {
            if (this.mode === "read-write") {
                this.server.register("POST", path, handler);
            }
        };
        const DELETE = (path: string, handler: RestRequestHandler) => {
            if (this.mode === "read-write") {
                this.server.register("DELETE", path, handler);
            }
        };

        GET("/", async (path, params, receivedAtMs) => {
            return {statusCode: 200, payload: {"result": "Deepbook API"}};
        });
        GET("/status", this.getStatus);

        GET("/pool", this.getPoolInfo);
        GET("/pools", this.getAllPoolInfo);

        GET("/object-info", this.getObjectInfo);
        GET("/wallet-balance-info", this.getWalletBalanceInfo);
        GET("/wallet-address", this.getWalletAddress);
        GET("/user-position", this.getUserPosition);

        GET("/transaction", this.getTransactionBlock);
        GET("/transactions", this.getTransactionBlocks);

        GET("/events", this.getEventsFromDigests);

        GET("/account-caps", this.getAccountCaps);
        POST("/account-cap", this.createAccountCap);
        POST("/child-account-cap", this.createChildAccountCap);

        GET("/order", this.getOrderStatus);
        GET("/orders", this.getOpenOrders);

        POST("/order", this.insertOrder);
        POST("/orders", this.insertOrders);

        DELETE("/order", this.cancelOrder);
        DELETE("/orders", this.cancelOrders);

        GET("/trades", this.getTrades);

        POST("/withdraw-from-pool", this.withdrawFromPool);
        POST("/deposit-into-pool", this.depositIntoPool);
        POST("/withdraw-sui", this.withdrawSui);
        POST("/withdraw", this.withdraw);
    }

    start = async () => {
        if (this.mode === "read-write") {
            await this.gasManager!.start();

            this.currentEpoch = await this.queryEpoch();
            if (this.currentEpoch === undefined) {
              throw new Error(
                "Unable to fetch current epoch on startup. Exiting"
              );
            } else {
              this.logger.info(`Setting currentEpoch=${this.currentEpoch}`);
            }

            // 5 minutes
            const trackEpochIntervalMs = 5 * 60 * 1000;
            setInterval(this.trackEpoch, trackEpochIntervalMs);
        }

        if (this.config.dex.subscribe_to_events) {
            await this.subscribeToEvents({
                Sender: this.walletAddress
            });

            if (this.mainAccountCapId) {
                // Subscribe to maker trades
                await this.subscribeToEvents({
                    MoveEventField: {
                        path: "/maker_address",
                        value: this.mainAccountCapId
                    }
                });
            } else {
                this.logger.warn("Cannot subscribe to maker trades, without an entry for `dex.account_cap_ids.main` in the config");
            }
        }

        await this.server.start();
    }

    handleEvent = async (event: SuiEvent) => {
        let parsedEvent: Event | Event[] | null = null;
        let channel: string = "ORDER";
        if (event.type.includes("OrderPlaced")) {
            parsedEvent = this.processOrderPlacedEvent(event);
        } else if (event.type.includes("OrderCanceled")) {
            parsedEvent = this.processOrderCancelledEvent(event);
        } else if (event.type.includes("AllOrdersCanceled")) {
            parsedEvent =
                this.processAllOrdersCancelledEvent(event);
        } else if (event.type.includes("OrderFilled")) {
            channel = "TRADE";
            parsedEvent = this.processOrderFilledEvent(event);
        } else {
            this.logger.warn(`Unhandled event type: ${event.type}`);
        }

        if (parsedEvent) {
            let eventType: string | null = null;
            if (Array.isArray(parsedEvent)) {
                eventType = parsedEvent[0].event_type;
            } else {
                eventType = parsedEvent.event_type;
            }

            let update: any = {
                jsonrpc: "2.0",
                method: "subscription",
                params: {
                    "channel": channel,
                    "type": eventType,
                    "data": parsedEvent
                }
            };
            await this.dexProxy.onEvent(channel, update);
        }
    }

    subscribeToEvents = async (filter: SuiEventFilter) => {
        const retryIntervalMs: number = 5_000;
        let delay = () => {
            return new Promise(resolve => setTimeout(resolve, retryIntervalMs));
        };

        const filterAsString = JSON.stringify(filter);

        let subscribe = async () => {
            this.logger.info(`Subscribing to events stream with filter: ${filterAsString}`);
            try {
                await this.suiClient.subscribeEvent({
                    filter: filter,
                    onMessage: async (event) => {
                        await this.handleEvent(event);
                    }
                });
            } catch(error: unknown) {
                if (error instanceof JsonRpcError) {
                    let rpcError = error as JsonRpcError;
                    this.logger.error(`Failed to subscribe to events stream with filter=${filterAsString}. Error=${rpcError.code}, ${rpcError.type}`);
                    this.logger.info(`Retrying subscription to events stream in ${retryIntervalMs} ms`);
                    await delay();
                    await subscribe();
                } else if (error instanceof Error) {
                    let error_ = error as Error;
                    this.logger.error(`Failed to subscribe to events stream with filter=${filterAsString}. Error=${error}`);
                    await delay();
                    await subscribe();
                } else {
                    throw error;
                }
            }
        };

        await subscribe();
    }

     static tryParseError = (error: string): ParsedExchangeError => {
        let errorRegex = /MoveAbort.*Identifier\("(?<errorLocation>[\w]+)"\) .* (?<errorCode>[\d]+)\) in command (?<txNumber>[\d]+)/
        let match = error.match(errorRegex);
        let parsedError: ParsedExchangeError = {
            type: null,
            txNumber: null
        }

        if (match?.groups !== undefined &&
            match.groups.errorCode !== null &&
            match.groups.errorLocation !== null &&
            match.groups.txNumber !== null) {

            const errorFile = DeepBook.exchangeErrors.get(
                match!.groups!.errorLocation);
            if (errorFile !=  undefined) {
                const errorStr = errorFile.get(
                    match!.groups!.errorCode);

                parsedError.type = (errorStr === undefined) ? null : errorStr;
                parsedError.txNumber = Number(match!.groups!.txNumber);
            }
        }

        return parsedError;
    }

    queryEpoch = async (): Promise<string | undefined> => {
        const retryIntervalMs: number = 5_000;
        let delay = () => {
            return new Promise(resolve => setTimeout(resolve, retryIntervalMs));
        };

        let queryFunc = async (retryCount: number = 0): Promise<string | undefined> => {
            this.logger.info(`Querying current epoch`);
            let attemptFailed = false;

            try {
                let state = await this.suiClient.getLatestSuiSystemState();
                this.logger.debug(`epoch from chain=${state.epoch}`);
                return state.epoch;

            } catch(error: unknown) {
                if (error instanceof SuiHTTPStatusError) {
                    this.logger.error(`Unexpected HTTP status code returned. code=${error.status}, details=${error.statusText}`);
                } else if ( error instanceof JsonRpcError) {
                    this.logger.error(`JSON RPC error. code=${error.code}, msg=${error.message}`);
                } else {
                    this.logger.error(`Unknown error. msg=${error}`);
                }

                attemptFailed = true;

            } finally {
                if (attemptFailed) {
                    if (retryCount < 3) {
                        this.logger.info(`Retrying query for current epoch in ${retryIntervalMs} ms`);
                        await delay();
                        return await queryFunc(retryCount + 1);
                    } else {
                        this.logger.error("Exhausted max retries to get current epoch");
                        return undefined;
                    }
                }
            }
        }

        return await queryFunc();
    }

    trackEpoch = async () => {
        const epoch = await this.queryEpoch();

        if (epoch === undefined) {
            this.logger.error("Unable to check for epoch change. Will try again in next scheduled iteration");
        } else {
            if (epoch != this.currentEpoch) {
                this.logger.info(`Detected epoch update from ${this.currentEpoch} to ${epoch}`);
                this.currentEpoch = epoch;
                this.logger.info(`Updated currentEpoch to ${this.currentEpoch}`);
                this.executor!.onEpochChange();
                await this.gasManager!.onEpochChange();
            } else {
                this.executor!.logSkippedObjects();
                this.gasManager!.logSkippedObjects();
            }
        }
    }

    getStatus = async (requestId: bigint,
                       path: string,
                       params: any,
                       receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Handling ${path} request`);

        return {
            statusCode: 200,
            payload: {
                status: "ok"
            }
        }
    }

    getTransactionBlocks = async (requestId: bigint,
                                  path: string,
                                  params: any,
                                  receivedAtMs: number): Promise<RestResult> => {
        let filter: TransactionFilter;

        if (params.get("direction") === "to") {
            filter = { ToAddress: this.walletAddress };
        } else {
            filter = { FromAddress: this.walletAddress };
        }

        const cursor: string | null = params.get("cursor");

        let limit: number | null = Number(params.get("limit"));
        if (limit === null) limit = 20;

        let queryParams: QueryTransactionBlocksParams = {
            filter: filter,
            cursor: cursor,
            limit: limit,
            order: "descending"
        };

        this.logger.debug(`[${requestId}] Handling ${path} request with filter: ${JSON.stringify(queryParams)}`);

        let txBlocks = null;
        try {
            txBlocks = await this.suiClient.queryTransactionBlocks(queryParams);
        } catch (error) {
            this.logger.error(`[${requestId}]: ${error}`);
            throw error;
        }

        return {
            statusCode: 200,
            payload: txBlocks
        }
    }

    getTransactionBlock = async (requestId: bigint,
                                 path: string,
                                 params: any,
                                 receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.TransactionBlockRequest);

        const digest: string = params.get("digest");
        this.logger.debug(`[${requestId}] Querying txDigest ${digest}`);

        let txBlock = null;
        try {
            txBlock = await this.suiClient.getTransactionBlock({
                digest: digest,
                options: {
                    showBalanceChanges: true,
                    showEvents: true,
                    showObjectChanges: true,
                    showEffects: true,
                    showInput: true
                }
            });
        } catch (error) {
            this.logger.error(`[${requestId}]: ${error}`);
            throw error;
        }

        return {
            statusCode: 200,
            payload: txBlock
        }
    }

    getEventsFromDigests = async (
        requestId: bigint,
        path: string,
        params: any,
        receivedAtMs: number
    ): Promise<RestResult> => {
        assertFields(params, MandatoryFields.EventsFromDigests);

        const requestedDigests: string = params.get("tx_digests");
        const txDigests: Array<string> = requestedDigests.split(",");
        this.logger.debug(
          `[${requestId}] Getting events for digests: ${requestedDigests}`
        );

        let events = new Array<Event>();
        
        for (let digest of txDigests) {
            let response = null;
            try {
                response = await this.suiClient.getTransactionBlock({
                    digest: digest,
                    options: { showEvents: true },
                });

                if (response && response.events) {
                    for (let event of response.events as SuiEvent[]) {
                        if (event.type.includes("OrderPlaced")) {
                            let orderPlacedEvent = this.processOrderPlacedEvent(event);
                            events.push(orderPlacedEvent);
                        } else if (event.type.includes("OrderFilled")) {
                            let orderFilledEvent = this.processOrderFilledEvent(event);
                            events.push(orderFilledEvent);
                        } else if (event.type.includes("AllOrdersCanceled")) {
                            let cancelledOrdersEvents =
                                this.processAllOrdersCancelledEvent(event);
                            for (let cancelledOrder of cancelledOrdersEvents) {
                                events.push(cancelledOrder);
                                this.orderCache.delete(cancelledOrder.client_order_id);
                            }
                        } else if (event.type.includes("OrderCanceled")) {
                            let cancelledOrderEvent =
                                this.processOrderCancelledEvent(event);
                            events.push(cancelledOrderEvent);
                            this.orderCache.delete(cancelledOrderEvent.client_order_id);
                        }
                    }
                }
            } catch (error) {
                this.logger.error(`[${requestId}]: ${error}`);
                throw error;
            } finally {
                if (this.log_responses) {
                    const dump = JSON.stringify(response);
                    this.logger.debug(
                        `[${requestId}] getEventsFromTransactionBlock digest=${digest} response: ${dump}`
                    );
                }
            }
        }

        return {
            statusCode: 200,
            payload: events,
        };
    }

    getWalletAddress = async (requestId: bigint,
                              path: string,
                              params: any,
                              receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Fetching wallet address`);

        return {
            statusCode: 200,
            payload: {
                "wallet_address": this.walletAddress
            }
        }
    }

    readPrivateKey = (): string => {
        if (this.config.key_store_file_path === undefined) {
            throw new Error("The key `key_store_file_path` must be defined in the config")
        }
        const keyStoreFilePath: string = this.config.key_store_file_path;
        try {
            return readFileSync(keyStoreFilePath, "utf8").trimEnd();
        } catch(error) {
            this.logger.error(`Cannot read private key from ${keyStoreFilePath}`);
            this.logger.error(error);
            throw(error);
        }
    }

    getAccountCaps = async (requestId: bigint,
                            path: string,
                            params: any,
                            receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Fetching accountCaps owned by wallet`);

        let request = async (cursor: string | null) => {
            try {
                return await this.suiClient.getOwnedObjects({
                    owner: this.walletAddress,
                    filter: { StructType: "0xdee9::custodian_v2::AccountCap" },
                    cursor: cursor
                });
            } catch(error) {
                this.logger.error(`[${requestId}]: ${error}`);
                throw error;
            }
        };

        let accountCapIds = await (async () => {
            let result: Array<string> = [];

            let cursor: string | null = null;

            const parseResponse = (
                response: PaginatedObjectsResponse
            ): string | null => {
                for (let item of response.data) {
                    if (item.data) result.push(item.data.objectId);
                }
                return (response.hasNextPage) ? response.nextCursor! : null;
            }

            // Handling paginated results
            do {
                let response: PaginatedObjectsResponse = await request(cursor);
                cursor = parseResponse(response);
            } while (cursor !== null);

            return result;
        })();

        this.logger.debug(`[${requestId}] Fetched ${accountCapIds.length} accountCaps`);

        return {
            statusCode: 200,
            payload: {
                "account_caps": accountCapIds
            }
        };
    }

    executeWithObjectTimeoutCheck =
        async (requestId: bigint,
               txBlockGenerator: TxBlockGenerator,
               txBlockResponseOptions: SuiTransactionBlockResponseOptions,
               gasCoin: GasCoin): Promise<SuiTransactionBlockResponse> => {

        let response: SuiTransactionBlockResponse | null = null;
        let transactionTimedOutBeforeReachingFinality: boolean = false;

        try {
            let txBlock = await txBlockGenerator();

            this.logger.debug(`[${requestId}] gasCoin=(${gasCoin.repr()})`);

            txBlock.setGasPayment([gasCoin]);

            response = await this.suiClient.signAndExecuteTransactionBlock({
                signer: this.keyPair!,
                transactionBlock: txBlock,
                options: txBlockResponseOptions
            });

            return response;

        } catch (error) {
            let error_ = error as any;
            let errorStr = error_.toString();

            if (errorStr.includes("Transaction timed out before reaching finality")) {
                transactionTimedOutBeforeReachingFinality = true;
            }

            throw error;

        } finally {
            if (gasCoin) {
                let gasCoinVersionUpdated = false;
                if (transactionTimedOutBeforeReachingFinality) {
                    this.logger.warn(`[${requestId}] Transaction timed out. Will skip using gasCoin=${gasCoin.objectId} for remainder of current epoch`);
                    gasCoin.status = GasCoinStatus.SkipForRemainderOfEpoch;
                } else {
                    if (response) {
                        gasCoinVersionUpdated = this.executor!.tryUpdateGasCoinVersion(requestId, response, gasCoin);
                        if (! gasCoinVersionUpdated) {
                            gasCoinVersionUpdated = await gasCoin.updateInstance(this.suiClient);
                        }
                    } else {
                        gasCoinVersionUpdated = await gasCoin.updateInstance(this.suiClient);
                    }
                    if (gasCoinVersionUpdated) {
                        gasCoin.status = GasCoinStatus.Free;
                    } else {
                        gasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                    }
                }
            }
        }
    }

    createAccountCap = async (requestId: bigint,
                              path: string,
                              params: any,
                              receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Creating account-cap: ${JSON.stringify(params)}`);

        let response: SuiTransactionBlockResponse | null = null;

        try {
            let gasCoin = this.gasManager!.getFreeGasCoin();

            let txBlockGenerator = async () => {
                return this.mainDeepbookClient.createAccount(
                   this.walletAddress
                );
            };

            response = await this.executeWithObjectTimeoutCheck(
                requestId,
                txBlockGenerator,
                { showEffects: true },
                gasCoin
            );

        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw(error);
        }

        let statusCode: number = 200;
        const digest: string = response.digest;
        let accountCapId: string | null = null;
        if (response.effects!.status.status === "success") {
            let createdObjs = response.effects?.created;
            if (createdObjs) {
                for (let createdObj of createdObjs) {
                    accountCapId = createdObj.reference.objectId;
                }
            }
            this.logger.debug(`[${requestId}] Created accountCap=${accountCapId}. Digest=${digest}`);
        } else {
            statusCode: 400
        }

        return {
            statusCode: statusCode,
            payload: {
                "tx_digest": digest,
                "status": response.effects!.status.status,
                "account_cap": accountCapId
            }
        }
    }

    createChildAccountCap = async (requestId: bigint,
                                   path: string,
                                   params: any,
                                   receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Creating child account-cap: ${JSON.stringify(params)}`);

        let response: SuiTransactionBlockResponse | null = null;

        try {
            let gasCoin = this.gasManager!.getFreeGasCoin();

            let txBlockGenerator = async() => {
                return await this.mainDeepbookClient.createChildAccountCap(
                    this.walletAddress
                );
            }

            response = await this.executeWithObjectTimeoutCheck(
                requestId,
                txBlockGenerator,
                { showEffects: true },
                gasCoin
            );

        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw(error);
        }

        let statusCode: number = 200;
        const digest: string = response.digest;
        let accountCapId: string | null = null;
        if (response.effects!.status.status === "success") {
            let createdObjs = response.effects?.created;
            if (createdObjs) {
                for (let createdObj of createdObjs) {
                    accountCapId = createdObj.reference.objectId;
                }
            }
            this.logger.debug(`[${requestId}] Created child accountCap=${accountCapId}. Digest=${digest}`);
        } else {
            statusCode: 400
        }

        return {
            statusCode: statusCode,
            payload: {
                "tx_digest": digest,
                "status": response.effects!.status.status,
                "account_cap": accountCapId
            }
        }
    }

    getOrderStatus = async (requestId: bigint,
                            path: string,
                            params: any,
                            receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.OrderStatusRequest);

        const poolId = params.get("pool_id") as PoolId;
        const clientOrderId = params.get("client_order_id") as ClientOrderId;

        let client = this.mainDeepbookClient;

        this.logger.debug(`[${requestId}] Fetching order status. params=${JSON.stringify(params)}`);

        const order = this.orderCache.get(clientOrderId);
        if (order === undefined) {
            const error = `client_order_id=${clientOrderId} does not exist`;
            this.logger.error(`[${requestId}] ${error}`);
            throw new ParsedOrderError("UNKNOWN", error);
        }
        const exchangeOrderId = order.exchangeOrderId;

        let exchangeStatus: any | undefined = undefined;
        if (exchangeOrderId) {
            try {
                exchangeStatus = await client.getOrderStatus(
                    poolId, exchangeOrderId
                );
            } catch (error) {
                this.logger.error(`[${requestId}] ${error}`);
                throw error;
            }
        }

        if (exchangeStatus) {
            if (this.log_responses) {
                const dump = JSON.stringify(exchangeStatus);
                this.logger.debug(`[${requestId}] Query response: ${dump}`);
            }

            if (
              order.status === "Unknown" ||
              order.status === "PendingInsert"
            ) {
              order.status = "Open";
            }
            order.remQty = BigInt(exchangeStatus.quantity) as Quantity;
            order.execQty = (order.qty - order.remQty) as Quantity;
        } else {
            this.logger.debug(`getOrderStatus did not have an update for ${clientOrderId}`);
            order.remQty = 0n as Quantity;
            order.execQty = 0n as Quantity;
            if (order.status !== "PendingInsert") {
                order.status = "Unknown";
            }
        }

        // TODO: Check if orderStatus.status can be set to "expired" by
        // inspecting the "expirationTs".
        let orderStatus: OrderStatus = {
            client_order_id: order.clientOrderId,
            exchange_order_id: order.exchangeOrderId,
            status: order.status,
            side: order.side,
            qty: order.qty.toString(),
            rem_qty: order.remQty.toString(),
            exec_qty: order.execQty.toString(),
            price: order.price.toString(),
            expiration_ts: order.expirationTs.toString()
        }

        return {
            statusCode: 200,
            payload: {
                order_status: orderStatus
            }
        }
    }

    processOpenOrdersResponse = (poolId: PoolId,
                                 openOrders: Array<any>): Array<OrderStatus> => {
        let result = new Array<OrderStatus>();
        for (let openOrder of openOrders) {
            let cachedOrder = this.orderCache.get(openOrder.clientOrderId);

            const qty = BigInt(openOrder.originalQuantity) as Quantity;
            const remQty = BigInt(openOrder.quantity) as Quantity;
            const execQty = (qty - remQty) as Quantity;
            const exchangeOrderId = openOrder.orderId as ExchangeOrderId;

            if (cachedOrder !== undefined) {
                if (cachedOrder.exchangeOrderId === null) {
                  cachedOrder.exchangeOrderId = exchangeOrderId;
                }

                cachedOrder.remQty = remQty;
                cachedOrder.execQty = execQty;

                if (
                  cachedOrder.status === "Unknown" ||
                  cachedOrder.status === "PendingInsert"
                ) {
                  cachedOrder.status = "Open";
                }
            } else {
                cachedOrder = {
                    clientOrderId: openOrder.clientOrderId as ClientOrderId,
                    exchangeOrderId: exchangeOrderId,
                    status: "Open",
                    poolId: poolId,
                    qty: qty,
                    remQty: remQty,
                    execQty: execQty,
                    price:  BigInt(openOrder.price) as Price,
                    type: null,
                    side: (openOrder.isBid) ? "BUY" : "SELL",
                    expirationTs: Number(openOrder.expireTimestamp) as TimestampMs,
                    txDigests: []
                };

                this.orderCache.add(openOrder.clientOrderId as ClientOrderId,
                                    cachedOrder);

            }

            result.push({
                client_order_id: cachedOrder.clientOrderId,
                exchange_order_id: cachedOrder.exchangeOrderId,
                status: cachedOrder.status,
                side: cachedOrder.side,
                qty: cachedOrder.qty.toString(),
                rem_qty: cachedOrder.remQty.toString(),
                exec_qty: cachedOrder.execQty.toString(),
                price: cachedOrder.price.toString(),
                expiration_ts: cachedOrder.expirationTs.toString()
            });
        }

        return result
    }

    getOpenOrders = async (requestId: bigint,
                           path: string,
                           params: any,
                           receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.AllOpenOrdersRequest);

        const poolId: PoolId = params.get("pool_id");

        let client = this.mainDeepbookClient;

        this.logger.debug(`[${requestId}] Fetching all open orders. params=${JSON.stringify(params)}`);

        let openOrders = null;
        try {
            openOrders = this.processOpenOrdersResponse(
                poolId as PoolId,
                await client.listOpenOrders(poolId)
            );
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        return {
            statusCode: 200,
            payload: {
                open_orders: openOrders
            }
        }
    }

    checkTransactionFailure = (requestId: bigint, response: SuiTransactionBlockResponse) => {
        if (response.effects!.status.status === "failure") {
            const error = response.effects!.status.error!;

            this.logger.error(`[${requestId}] Transaction failure: ${error}`);

            let type = "UNKNOWN";
            if (error == "InsufficientGas") {
                type = "INSUFFICIENT_GAS";
            } else {
                let parsedError = DeepBook.tryParseError(error.toString());
                if (parsedError.type) {
                     type = parsedError.type;
                }
            }

            throw new ParsedOrderError(type, error);
        }
    }

    parseInsertRequest = (request: any): Order => {
        const qty = BigInt(Number(request.quantity));
        const price = BigInt(Number(request.price));

        return {
            clientOrderId: request.client_order_id as ClientOrderId,
            status: "PendingInsert",
            poolId: request.pool_id as PoolId,
            qty: qty as Quantity,
            remQty: 0n as Quantity,
            execQty: 0n as Quantity,
            price:  price as Price,
            type: request.order_type,
            side: request.side,
            expirationTs: request.expiration_ts as TimestampMs,

            txDigests: new Array<TxDigest>(),
            exchangeOrderId: null
        }
    }

    processOrderPlacedEvent = (event: SuiEvent): OrderPlacedEvent => {
        let json = event.parsedJson as any;

        const qty = json.original_quantity;
        const remQty = json.base_asset_quantity_placed;
        const execQty = (BigInt(qty) - BigInt(remQty)).toString();
        const price = json.price;
        const timestampMs = (event.timestampMs === undefined)
            ? null : event.timestampMs;

        return {
            event_type: "order_placed",
            pool_id: json.pool_id as PoolId,
            client_order_id: json.client_order_id as ClientOrderId,
            exchange_order_id: json.order_id as ExchangeOrderId,
            side: ((json.is_bid) ? "BUY" : "SELL") as Side,
            qty: qty,
            rem_qty: remQty,
            exec_qty: execQty,
            price: price,
            timestamp_ms: timestampMs
        };
    }

    processOrderFilledEvent = (event: SuiEvent): OrderFilledEvent => {
        let json = event.parsedJson as any;

        const tradeId = `${event.id.txDigest}_${event.id.eventSeq}`;
        const liquidityIndicator = (json.maker_address === this.mainAccountCapId)
                                    ? "Maker" : "Taker";
        const clientOrderId = (liquidityIndicator === "Maker")
                                ? json.maker_client_order_id
                                : json.taker_client_order_id;
        const exec_qty = json.base_asset_quantity_filled;
        const price = json.price;
        const fee = (liquidityIndicator === "Maker")
            ? (BigInt(json.maker_rebates) * -1n).toString()
            : json.taker_commission;
        const exchangeOrderId = (liquidityIndicator === "Maker") ?
            json.order_id : null
        const timestampMs = (event.timestampMs === undefined)
            ? null : event.timestampMs;

        // It appears that `order_filled` events are raised with the side
        // reflecting what's on the book.
        // For a `Taker` trade we'd have to take the inverse of `is_bid` in
        // the event from the exchange.

        let side: Side = (json.is_bid) ? "BUY" : "SELL";
        if (liquidityIndicator === "Taker") {
            side = (side === "BUY") ? "SELL" : "BUY";
        }

        return {
            event_type: "order_filled",
            pool_id: json.pool_id as PoolId,
            liquidity_indicator: liquidityIndicator,
            client_order_id: clientOrderId as ClientOrderId,
            exchange_order_id: exchangeOrderId as ExchangeOrderId,
            trade_id: tradeId as ExchangeTradeId,
            side: side,
            exec_qty: exec_qty,
            price: price,
            fee: fee,
            timestamp_ms: timestampMs
        };
    }

    processInsertResponse = async (response: SuiTransactionBlockResponse,
                                   order: Order): Promise<Array<Event>> => {

        order.status = (response.effects!.status.status === "success")
                       ? "Open" : "Finalised";
        if (order.type === "IOC") {
            order.status = "Finalised";
            this.orderCache.delete(order.clientOrderId);
        }
        order.txDigests.push(response.digest as TxDigest);

        let events = new Array<Event>();

        if (response.events) {
            for (let event of response.events as SuiEvent[]) {
                if (event.type.includes("OrderPlaced")) {
                  let orderPlacedEvent = this.processOrderPlacedEvent(event);

                  order.execQty = BigInt(orderPlacedEvent.exec_qty) as Quantity;
                  order.remQty = BigInt(orderPlacedEvent.rem_qty) as Quantity;
                  order.exchangeOrderId = orderPlacedEvent.exchange_order_id;

                  events.push(orderPlacedEvent);
                } else if (event.type.includes("OrderFilled")) {
                  let orderFilledEvent = this.processOrderFilledEvent(event);
                  events.push(orderFilledEvent);
                } else if (event.type.includes("AllOrdersCanceled")) {
                  // Can receive cancel event in order insert response due to STP
                  let cancelledOrdersEvents =
                    this.processAllOrdersCancelledEvent(event);
                  for (let cancelledOrder of cancelledOrdersEvents) {
                    events.push(cancelledOrder);
                    this.orderCache.delete(cancelledOrder.client_order_id);
                  }
                } else if (event.type.includes("OrderCanceled")) {
                  // Can receive cancel event in order insert response due to STP
                  let cancelledOrderEvent = this.processOrderCancelledEvent(event);
                  events.push(cancelledOrderEvent);
                  this.orderCache.delete(cancelledOrderEvent.client_order_id);
                } 
            }
        }

        return events;
    }

    static parseOrderType = (type: string | null): number => {
        if (type === "IOC") return 1;
        else if (type == "GTC")  return 0 ;
        else if (type == "POST_ONLY") return 3;
        else throw new ParsedOrderError("UNKNOWN", `Unknown order type: ${type}`);
    }

    insertOrder = async (requestId: bigint,
                         path: string,
                         params: any,
                         receivedAtMs: number): Promise<RestResult> => {

        assertFields(params, MandatoryFields.InsertRequest);

        const poolId = params["pool_id"];

        let order = this.parseInsertRequest(params);
        this.orderCache.add(order.clientOrderId, order);

        const orderType = (order.side === "BUY") ? "bid": "ask";
        const restriction = DeepBook.parseOrderType(order.type)
        const selfMatchingPrevention: number = 0; // CANCEL_OLDEST

        this.logger.debug(`[${requestId}] Calling placeLimitOrder with args: poolId=${order.poolId}, price=${order.price}, quantity=${order.qty}, orderType=${orderType}, expirationTimestamp=${order.expirationTs}, restriction=${restriction}, clientOrderId=${order.clientOrderId}, selfMatchingPrevention=${selfMatchingPrevention}`);

        let response = null;
        try {
            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.debug(`[${requestId}] Inserting order. accCapId=${accountCap.id} gasCoin=(${gasCoin.repr()})`);

                return await accountCap.client.placeLimitOrder(
                    order.poolId,
                    order.price,
                    order.qty,
                    orderType,
                    order.expirationTs,
                    restriction,
                    order.clientOrderId,
                    selfMatchingPrevention
                );
            };

            let txBlockResponseOptions = { showEffects: true, showEvents: true };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            if (error instanceof Error) {
                const parsedError = DeepBook.tryParseError(error.toString());
                if (parsedError.type && parsedError.txNumber !== null) {
                    this.logger.error(`[${requestId}] ${parsedError.type}`);
                    throw new ParsedOrderError(
                        parsedError.type,
                        `client_order_id: ${order.clientOrderId}`
                    );
                } else {
                    const errorStr = error.toString();
                    this.logger.error(`[${requestId}] ${errorStr}`);
                    throw new ParsedOrderError("UNKNOWN", errorStr);
                }
            }
            let error_ = error as any;
            let errorStr = error_.toString();
            this.logger.error(`[${requestId}] ${errorStr}`);
            throw new ParsedOrderError("UNKNOWN", errorStr);;
        } finally {
            if (this.log_responses) {
                const dump = JSON.stringify(response);
                this.logger.debug(`[${requestId}] Insert response: ${dump}`);
            }
        }

        this.checkTransactionFailure(requestId, response);

        this.logger.info(`[${requestId}] Order inserted`);
        let events = await this.processInsertResponse(response, order);

        return {
            statusCode: (response.effects!.status.status === "success")
                         ? 200 : 400,
            payload: {
                status: response.effects!.status.status,
                tx_digest: response.digest,
                events: events
            }
        };
    }

    processBulkInsertResponse = async (response: SuiTransactionBlockResponse,
                                       clientOrderIds: Array<ClientOrderId>):
        Promise<Array<Event>> => {

        for (let clientOrderId of clientOrderIds) {
            let order = this.orderCache.get(clientOrderId);
            if (order) {
                order.status = (response.effects!.status.status === "success")
                               ? "Open" : "Finalised";
                if (order.type === "IOC") {
                    order.status = "Finalised";
                    this.orderCache.delete(order.clientOrderId);
                }
                order.txDigests.push(response.digest as TxDigest);
            }
        }

        let events = new Array<Event>();

        if (response.events) {
            for (let event of response.events as SuiEvent[]) {
                if (event.type.includes("OrderPlaced")) {
                  let orderPlacedEvent = this.processOrderPlacedEvent(event);

                  let order = this.orderCache.get(
                    orderPlacedEvent.client_order_id
                  );
                  if (order) {
                    order.execQty = BigInt(
                      orderPlacedEvent.exec_qty
                    ) as Quantity;
                    order.remQty = BigInt(orderPlacedEvent.rem_qty) as Quantity;
                    order.exchangeOrderId = orderPlacedEvent.exchange_order_id;
                  }

                  events.push(orderPlacedEvent);
                } else if (event.type.includes("OrderFilled")) {
                  let orderFilledEvent = this.processOrderFilledEvent(event);
                  events.push(orderFilledEvent);
                } else if (event.type.includes("AllOrdersCanceled")) {
                  // Can receive cancel event in order insert response due to STP
                  let cancelledOrdersEvents =
                  this.processAllOrdersCancelledEvent(event);
                  for (let cancelledOrder of cancelledOrdersEvents) {
                    events.push(cancelledOrder);
                    this.orderCache.delete(cancelledOrder.client_order_id);
                  }
                } else if (event.type.includes("OrderCanceled")) {
                  // Can receive cancel event in order insert response due to STP
                  let cancelledOrderEvent = this.processOrderCancelledEvent(event);
                  events.push(cancelledOrderEvent);
                  this.orderCache.delete(cancelledOrderEvent.client_order_id);
                }
            }
        }

        return events;
    }

    parseBulkInsertRequest = (request: any): Array<Order> => {
        let result = new Array<Order>();
        for (let order of request.orders) {
            const qty = BigInt(Number(order.quantity));
            const price = BigInt(Number(order.price));

            result.push({
                clientOrderId: order.client_order_id as ClientOrderId,
                status: "PendingInsert",
                poolId: request.pool_id as PoolId,
                qty: qty as Quantity,
                remQty: 0n as Quantity,
                execQty: 0n as Quantity,
                price:  price as Price,
                type: order.order_type,
                side: order.side,
                expirationTs: request.expiration_ts as TimestampMs,

                txDigests: new Array<TxDigest>(),
                exchangeOrderId: null
            });
        }

        return result;
    }

    insertOrders = async (requestId: bigint,
                          path: string,
                          params: any,
                          receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.BulkInsertRequest);

        const poolId = params["pool_id"];

        let orders = this.parseBulkInsertRequest(params);
        let clientOrderIds = new Array<ClientOrderId>();
        for (let order of orders) {
            this.orderCache.add(order.clientOrderId, order);
            clientOrderIds.push(order.clientOrderId);
        }

        let response = null;

        try {
            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.debug(`[${requestId}] Inserting orders. params=${JSON.stringify(params)} accCapId=${accountCap.id} gasCoin=(${gasCoin.repr()})`);

                const selfMatchingPrevention: number = 0; // CANCEL_OLDEST
                let txBlock = new TransactionBlock();
                for (let order of orders) {
                    const normalizedAccountCapId = normalizeSuiAddress(accountCap.id);
                    const restriction = DeepBook.parseOrderType(order.type)
                    let txArgs = [
                        txBlock.object(order.poolId),
                        txBlock.pure.u64(order.clientOrderId),
                        txBlock.pure.u64(order.price),
                        txBlock.pure.u64(order.qty),
                        txBlock.pure.u8(selfMatchingPrevention),
                        txBlock.pure.bool(order.side === "BUY"),
                        txBlock.pure.u64(order.expirationTs),
                        txBlock.pure.u8(restriction),
                        txBlock.object(SUI_CLOCK_OBJECT_ID),
                        txBlock.object(normalizedAccountCapId),
                    ];

                    txBlock.moveCall({
                        typeArguments:
                            await accountCap.client.getPoolTypeArgs(order.poolId),
                        target: `0xdee9::clob_v2::place_limit_order`,
                        arguments: txArgs
                    });
                }

                return txBlock;
            };

            let txBlockResponseOptions = { showEffects: true, showEvents: true };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            this.logger.error(`[${requestId}] Failed to insert order. params=${JSON.stringify(params)}`);

            if (error instanceof Error) {
                const parsedError = DeepBook.tryParseError(error.toString());
                this.logger.error(`[${requestId}] ${parsedError.type}`);
                if (parsedError.type && parsedError.txNumber !== null) {
                    throw new ParsedOrderError(
                        parsedError.type,
                        `clientOrderId: ${clientOrderIds[parsedError.txNumber]}`
                    );
                }
            }
            let error_ = error as any;
            let errorStr = error_.toString();
            this.logger.error(`[${requestId}] ${errorStr}`);
            throw error;
        } finally {
            if (this.log_responses) {
                const dump = JSON.stringify(response);
                this.logger.debug(`[${requestId}] Insert response: ${dump}`);
            }
        }

        this.checkTransactionFailure(requestId, response);

        let events = await this.processBulkInsertResponse(response,
                                                          clientOrderIds);

        return {
            statusCode: (response.effects!.status.status === "success")
                         ? 200 : 400,
            payload: {
                status: response.effects!.status.status,
                tx_digest: response.digest,
                events: events
            }
        };
    }

    processOrderCancelledEvent = (event: SuiEvent | any): OrderCancelledEvent => {
        let json = (event.parsedJson) ? event.parsedJson as any : event;

        const qty = json.original_quantity;
        const qtyCancelled = json.base_asset_quantity_canceled;
        const execQty = (BigInt(qty) - BigInt(qtyCancelled)).toString();
        const price = json.price;
        const timestampMs = (event.timestampMs === undefined)
            ? null : event.timestampMs;

        return {
            event_type: "order_cancelled",
            pool_id: json.pool_id,
            client_order_id: json.client_order_id as ClientOrderId,
            exchange_order_id: json.order_id as ExchangeOrderId,
            side: ((json.is_bid) ? "BUY" : "SELL") as Side,
            qty: qty,
            exec_qty: execQty,
            price: price,
            timestamp_ms: timestampMs
        }
    }

    processCancelResponse = (response: SuiTransactionBlockResponse,
                             order: Order): Array<Event> => {
        if (response.effects!.status.status === "success") {
            order.status = "Cancelled";
            this.orderCache.delete(order.clientOrderId);
        }
        order.txDigests.push(response.digest as TxDigest);

        let events = new Array<Event>();

        if (response.events) {
            for (let event of response.events as SuiEvent[]) {
                if (event.type.includes("OrderCanceled")) {
                    let orderCancelledEvent =
                        this.processOrderCancelledEvent(event);
                    events.push(orderCancelledEvent);
                }
            }
        }

        return events;
    }

    cancelOrder = async (requestId: bigint,
                         path: string,
                         params: any,
                         receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.CancelRequest);

        const poolId = params.get("pool_id") as PoolId;
        const clientOrderId = params.get("client_order_id") as ClientOrderId;

        let order = this.orderCache.get(clientOrderId);
        if (order === undefined) {
            const error = `client_order_id: ${clientOrderId} does not exist`;
            this.logger.error(`[${requestId}] ${error}`);
            throw new ParsedOrderError("UNKNOWN", error);
        } else if (order.exchangeOrderId === null) {
            const error = `Cannot cancel order[clOId=${clientOrderId}, exOId=${order.exchangeOrderId}]`;
            this.logger.error(error);
            throw new ParsedOrderError("UNKNOWN", error);
        }

        this.logger.debug(`[${requestId}] Calling cancelOrder with args: poolId=${poolId}, orderId=${order!.exchangeOrderId!}`);

        let response = null;
        try {
            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.debug(`[${requestId}] Cancelling order. accCapId=${accountCap.id} gasCoin=(${gasCoin.repr()})`);

                return await accountCap.client.cancelOrder(
                    poolId,
                    order!.exchangeOrderId!
                );
            };

            let txBlockResponseOptions = {
                showEffects: true,
                showEvents: true
            };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            if (error instanceof Error) {
                const parsedError = DeepBook.tryParseError(error.toString());
                if (parsedError.type && parsedError.txNumber !== null) {
                    this.logger.error(`[${requestId}] ${parsedError.type}`);
                    throw new ParsedOrderError(
                        parsedError.type,
                        `client_order_id: ${clientOrderId}`
                    );
                } else {
                    const errorStr = error.toString();
                    this.logger.error(`[${requestId}] ${errorStr}`);
                    if (error instanceof SuiHTTPStatusError) {
                        throw new ParsedOrderError("UNKNOWN", errorStr, error.status);
                    }
                    throw new ParsedOrderError("UNKNOWN", errorStr, 500);
                }
            }
            let error_ = error as any;
            let errorStr = error_.toString();
            this.logger.error(`[${requestId}] ${errorStr}`);
            throw new ParsedOrderError("UNKNOWN", errorStr);;
        } finally {
            if (this.log_responses) {
                const dump = JSON.stringify(response);
                this.logger.debug(`[${requestId}] Cancel response: ${dump}`);
            }
        }

        this.checkTransactionFailure(requestId, response);

        let events = this.processCancelResponse(response, order!);

        return {
            statusCode: (response.effects!.status.status === "success")
                         ? 200 : 400,
            payload: {
                status: response.effects!.status.status,
                tx_digest: response.digest,
                events: events
            }
        }
    }

    processAllOrdersCancelledEvent = (event: SuiEvent):
        Array<OrderCancelledEvent> => {

        let parsedEvents = new Array<OrderCancelledEvent>();

        let json = event.parsedJson as any;
        for (let cancelledOrder of json.orders_canceled) {
            let clientOrderId = cancelledOrder.client_order_id;
            let exchangeOrderId = cancelledOrder.order_id;

            let parsedEvent = this.processOrderCancelledEvent(cancelledOrder);
            parsedEvent.pool_id = json.pool_id;

            parsedEvents.push(parsedEvent);

            let order = this.orderCache.get(clientOrderId);
            if (order === undefined) {
                this.logger.warn(`Cancelled unknown order[clOid:${clientOrderId}, exOid:${exchangeOrderId}]`);
            } else {
                order.status = "Cancelled";
            }
        }

        return parsedEvents
    }

    processCancelAllResponse = async (response: SuiTransactionBlockResponse):
        Promise<Array<OrderCancelledEvent>> => {

        let events = new Array<OrderCancelledEvent>();

        if (response.events) {
            for (const event of response.events) {
                if (event.type.includes("AllOrdersCanceled")) {
                    let cancelledOrders =
                        this.processAllOrdersCancelledEvent(event);
                    for (let cancelledOrder of cancelledOrders) {
                        events.push(cancelledOrder);
                        this.orderCache.delete(cancelledOrder.client_order_id);
                    }
                }
            }
        }

        return events;
    }

    cancelAll = async (requestId: bigint, params: any): Promise<RestResult> => {
        assertFields(params, MandatoryFields.CancelAllRequest);
        const poolId = params.get("pool_id") as PoolId;

        let response = null;
        try {
            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.debug(`[${requestId}] Cancelling all orders. poolId=${poolId} accCapId=${accountCap.id} gasCoin=(${gasCoin.repr()})`);

                return await accountCap.client.cancelAllOrders(poolId);
            };

            let txBlockResponseOptions = {
                showEffects: true,
                showEvents: true,
                showObjectChanges: true
            };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            this.logger.error(`[${requestId}] Failed to cancel all orders. poolId=${poolId}`);
            if (error instanceof Error) {
                const parsedError = DeepBook.tryParseError(error.toString());
                if (parsedError.type && parsedError.txNumber !== null) {
                    this.logger.error(`[${requestId}] ${parsedError.type}`);
                    throw new ParsedOrderError(parsedError.type, "");
                } else {
                    const errorStr = error.toString();
                    this.logger.error(`[${requestId}] ${errorStr}`);
                    throw new ParsedOrderError("UNKNOWN", errorStr);
                }
            }
            let error_ = error as any;
            let errorStr = error_.toString();
            this.logger.error(`[${requestId}] ${errorStr}`);
            throw new ParsedOrderError("UNKNOWN", errorStr);;
        } finally {
            if (this.log_responses) {
                const dump = JSON.stringify(response);
                this.logger.debug(`[${requestId}] Cancel all response: ${dump}`);
            }
        }

        this.checkTransactionFailure(requestId, response);

        let events = await this.processCancelAllResponse(response);

        const status = response.effects!.status.status;
        if (status === "success") {
            this.logger.info(`[${requestId}] All orders canceled for poolId=${poolId}. Digest=${response.digest}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: {
                status: status,
                tx_digest: response.digest,
                events: events
            }
        };
    }

    bulkCancel = async (requestId: bigint, params: any): Promise<RestResult> => {
        assertFields(params, MandatoryFields.BulkCancelRequest);

        const poolId = params.get("pool_id") as PoolId;
        const clientOrderIds: Array<string> = params.get("client_order_ids").split(',');
        const exchangeOrderIds: Array<string> = new Array<string>();

        for (let clientOrderId of clientOrderIds) {
            let order = this.orderCache.get(clientOrderId as ClientOrderId);
            if (order === undefined) {
                const error = `client_order_id: ${clientOrderId} does not exist`;
                this.logger.error(`[${requestId}] ${error}`);
                throw new ParsedOrderError("UNKNOWN", error);
            } else if (order.exchangeOrderId === null) {
                const error = `Cannot cancel order[clOId=${clientOrderId}, exOId=${order.exchangeOrderId}]`;
                this.logger.error(`[${requestId}] ${error}`);
                throw new ParsedOrderError("UNKNOWN", error);
            }
            exchangeOrderIds.push(order.exchangeOrderId);
        }

        let response = null;
        try {
            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.debug(`[${requestId}] Cancelling orders. poolId=${poolId} clientOrderIds=${clientOrderIds} accCapId=${accountCap.id} gasCoin=(${gasCoin.repr()})`);

                return await accountCap.client.batchCancelOrder(
                    poolId, exchangeOrderIds
                );
            };

            let txBlockResponseOptions = { showEffects: true, showEvents: true };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            this.logger.error(`[${requestId}] Failed to cancel orders. poolId=${poolId} clientOrderIds=${clientOrderIds}`);

            if (error instanceof Error) {
                const parsedError = DeepBook.tryParseError(error.toString());
                if (parsedError.type && parsedError.txNumber !== null) {
                    this.logger.error(`[${requestId}] ${parsedError.type}`);
                    throw new ParsedOrderError(parsedError.type, "");
                } else {
                    const errorStr = error.toString();
                    this.logger.error(`[${requestId}] ${errorStr}`);
                    if (error instanceof SuiHTTPStatusError) {
                        throw new ParsedOrderError("UNKNOWN", errorStr, error.status);
                    }
                    throw new ParsedOrderError("UNKNOWN", errorStr, 500);
                }
            }
            let error_ = error as any;
            let errorStr = error_.toString();
            this.logger.error(`[${requestId}] ${errorStr}`);
            throw new ParsedOrderError("UNKNOWN", errorStr, 500);;
        } finally {
            if (this.log_responses) {
                const dump = JSON.stringify(response);
                this.logger.debug(`[${requestId}] Cancel bulk response: ${dump}`);
            }
        }


        this.checkTransactionFailure(requestId, response);

        let events = await this.processCancelAllResponse(response);

        const status = response.effects!.status.status;
        if (status === "success") {
            this.logger.info(`[${requestId}] Orders canceled for poolId=${poolId}. Digest=${response.digest}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: {
                status: response.effects!.status.status,
                tx_digest: response.digest,
                events: events
            }
        };
    }

    cancelOrders = async (requestId: bigint,
                          path: string,
                          params: any,
                          receivedAtMs: number): Promise<RestResult> => {
        if (params.get("client_order_ids") === null) {
            return await this.cancelAll(requestId, params);
        } else {
            return await this.bulkCancel(requestId, params);
        }
    }

    getTrades = async (requestId: bigint,
                       path: string,
                       params: any,
                       receivedAtMs: number): Promise<RestResult> => {
        if (params.get("tx_digests") !== null) {
            return await this.getTradesByDigest(requestId, path, params,
                                                receivedAtMs);
        } else {
            return await this.getTradesByTime(requestId, path, params,
                                              receivedAtMs);
        }
    }

    getTradesByTimeImpl = async (requestId: bigint,
                                 queryParams: QueryEventsParams,
                                 requestedStartTs: number) => {
        let response = null;
        try {
            response = await this.suiClient.queryEvents(queryParams) as any;
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        let orderFilledEvents = new Array<OrderFilledEvent>();
        let startTs: number | null = null;
        let hasNextPage = false;
        let nextCursor = null;


        for (let event of response.data) {
            startTs = Number(event.timestampMs);
            if (startTs < requestedStartTs) break;

            let parsedJson = event.parsedJson as any;
            if (event.type.includes("OrderFilled")) {
                if (parsedJson.maker_address === this.mainAccountCapId ||
                    parsedJson.taker_address === this.mainAccountCapId) {
                    orderFilledEvents.push(
                        this.processOrderFilledEvent(event)
                    );
                }
            }
        }

        if (startTs !== null && startTs < requestedStartTs) {
            hasNextPage = false;
            nextCursor = null;
        } else if (response.hasNextPage) {
            hasNextPage = response.hasNextPage;
            nextCursor = {
                tx_digest: response.nextCursor.txDigest,
                event_seq: response.nextCursor.eventSeq
            }
        }

        return {
            hasNextPage: hasNextPage,
            nextCursor: nextCursor,
            orderFilledEvents: orderFilledEvents,
            startTs: startTs
        }
    }

    getTradesByTime = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.TradesByTimeRequest);

        const startTs  = Number(params.get("start_ts"));
        const maxPages = Number(params.get("max_pages"));
        const txDigest = params.get("tx_digest");
        const eventSeq = params.get("event_seq");

        let cursor: EventId | null = null;
        if (txDigest && eventSeq) {
            cursor = {
                txDigest: txDigest,
                eventSeq: eventSeq
            }
        }

        this.logger.debug(`[${requestId}] Fetching trades by time. start_ts=${startTs} max_pages=${maxPages} cursor=${JSON.stringify(cursor)}`);


        const now = Date.now();
        const fortyMinutesInMs = 40 * 60 * 1000;
        if (now - startTs > fortyMinutesInMs) {
            let error = "Can't query for trades more than 40 minutes in the past. Please update the field, `startTs` in the request";
            this.logger.error(`[${requestId}] ${error}`);
            throw new Error(error);
        }

        let limit: number | null = Number(params.get("limit"));
        if (limit === null) limit = 50;

        let query: SuiEventFilter = {
            // Does not get us maker trades
            // Sender: this.walletAddress

            // This query filter is not supported by the full node
            /*
            MoveEventField: {
                path: "/maker_address",
                value: this.mainAccountCapId
            }
            */

            MoveEventModule: {
                package: "0xdee9",
                module: "clob_v2"
            }
        };

        let queryParams: QueryEventsParams = {
            query: query,
            cursor: cursor,
            limit: limit,
            order: "descending"
        };

        let response = await this.getTradesByTimeImpl(requestId, queryParams,
                                                      startTs);
        let pagesQueried = 1;
        while (response.orderFilledEvents.length === 0
               && response.hasNextPage && pagesQueried < maxPages) {
            queryParams.cursor = {
                txDigest: response.nextCursor!.tx_digest,
                eventSeq: response.nextCursor!.event_seq
            }
            response = await this.getTradesByTimeImpl(requestId, queryParams,
                                                      startTs);
            ++pagesQueried;
        }

        this.logger.debug(`[${requestId}] Fetched ${response.orderFilledEvents.length} trades by time. start_ts=${startTs} max_pages=${maxPages} cursor=${JSON.stringify(cursor)}`);

        return {
            statusCode: 200,
            payload: {
                has_next_page: response.hasNextPage,
                next_cursor: response.nextCursor,
                data: response.orderFilledEvents,
                start_ts: response.startTs
            }
        };
    }

    getTradesByDigestImpl = async (requestId: bigint,
                                   queryParams: QueryEventsParams) => {
        let response = null;
        try {
            response = await this.suiClient.queryEvents(queryParams) as any;
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        let orderFilledEvents = new Array<OrderFilledEvent>();
        for (let event of response.data) {
            let parsedJson = event.parsedJson as any;
            if (event.type.includes("OrderFilled")) {
                if (parsedJson.maker_address === this.mainAccountCapId ||
                    parsedJson.taker_address === this.mainAccountCapId) {
                    orderFilledEvents.push(
                        this.processOrderFilledEvent(event)
                    );
                }
            }
        }

        return {
            hasNextPage: response.hasNextPage,
            nextCursor: response.nextCursor,
            orderFilledEvents: orderFilledEvents,
        }
    };

    getTradesByDigest = async(requestId: bigint,
                              path: string,
                              params: any,
                              receivedAtMs: number): Promise<RestResult> => {

        assertFields(params, MandatoryFields.TradesByDigestRequest);

        this.logger.debug(`[${requestId}] Fetching trades by digest`);

        const txDigests: Array<string> = params.get("tx_digests").split(',');

        let orderFilledEvents = new Array<OrderFilledEvent>();

        for (let txDigest of txDigests) {
            this.logger.debug(`Querying trades for tx_digest=${txDigest}`);

            let queryParams: QueryEventsParams = {
                query: { Transaction: txDigest },
                cursor: null,
                limit: 50,
                order: "descending"
            };


            let response = await this.getTradesByDigestImpl(requestId,
                                                            queryParams);
            for (let event of response.orderFilledEvents) {
                orderFilledEvents.push(event);
            }

            // Handle pagination
            while (response.hasNextPage) {
                queryParams.cursor = {
                    txDigest: response.nextCursor!.tx_digest,
                    eventSeq: response.nextCursor!.event_seq
                }
                response = await this.getTradesByDigestImpl(requestId,
                                                            queryParams);
                for (let event of response.orderFilledEvents) {
                    orderFilledEvents.push(event);
                }
            }
        }

        this.logger.debug(`[${requestId}] Fetched trades by digest`);

        return {
            statusCode: 200,
            payload: {
                data: orderFilledEvents,
            }
        };
    }

    depositIntoPool = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.PoolDepositRequest);

        const poolId = params["pool_id"] as PoolId;
        const coinTypeId: string = params["coin_type_id"];
        const coinTypeAddress: string = this.getCoinTypeAddress(coinTypeId);
        const quantity: number = Number(params["quantity"]);

        this.logger.debug(`[${requestId}] Handling depositIntoPool request. params=${JSON.stringify(params)}`);

        let response = null;
        let mainGasCoin = null;
        let status: string | undefined = undefined;
        let gasCoinVersionUpdated: boolean = false;

        try {
            let firstCoin: string | undefined = undefined;
            if (!coinTypeId.includes('SUI')) {
                const coinInstances: Array<string> = await this.getCoinInstances(coinTypeId);

                firstCoin = coinInstances[0];

                if (coinInstances.length > 1) {
                    this.logger.info(`Merging coin instances ${coinInstances} into ${firstCoin}...`);

                    try {
                        let gasCoin = this.gasManager!.getFreeGasCoin();
                        let txBlockGenerator = async () => {
                            const block = new SuiTxBlock();
                            return block.mergeCoinsIntoFirstCoin(coinInstances);
                        };

                        let response = await this.executeWithObjectTimeoutCheck(
                            requestId,
                            txBlockGenerator,
                            { showEffects: true },
                            gasCoin
                        );

                        this.logger.info(`Merged coin instances ${coinInstances} into ${firstCoin}. Digest=${response["digest"]}`);
                    } catch (error) {
                        this.logger.error(`[${requestId}]: ${error}`);
                        throw error;

                    }
                }
            } else {
                mainGasCoin = await this.gasManager!.getMainGasCoin();
                if (mainGasCoin === null) {
                    throw new Error("The mainGasCoin is being used in a concurrent transaction. Please retry");
                }

                await this.gasManager!.mergeUntrackedGasCoinsInto(mainGasCoin)

                if (mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
                    throw new Error("Unable to update the version of the mainGasCoin after merging untracked gasCoins into it. Please retry this transaction");
                }

                firstCoin = mainGasCoin.objectId;
            }

            const decimals = await this.getCoinDecimals(coinTypeId)

            const nativeAmount = BigInt(quantity * 10 ** decimals);

            this.logger.info(`Depositing coin ${firstCoin} into pool ${poolId}. Amount: ${nativeAmount} (${quantity})`);

            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.info(`[${requestId}] accCapId=${accountCap.id} gasCoin=${gasCoin.objectId}`);

                return await accountCap.client.deposit(
                    poolId,
                    firstCoin,
                    nativeAmount
                );
            };

            let txBlockResponseOptions = {
                showEffects: true,
                showEvents: true,
                showBalanceChanges: true,
                showObjectChanges: true
            };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        } finally {
            if (mainGasCoin) {
                if (response) {
                    gasCoinVersionUpdated = this.executor!.tryUpdateGasCoinVersion(requestId, response, mainGasCoin);
                    if (! gasCoinVersionUpdated) {
                        gasCoinVersionUpdated = await this.gasManager!.tryUpdateMainGasCoinVersion();
                    }
                } else {
                    gasCoinVersionUpdated = await this.gasManager!.tryUpdateMainGasCoinVersion();
                }
                if (gasCoinVersionUpdated) {
                    mainGasCoin.status = GasCoinStatus.Free;
                } else {
                    mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                }
            }
        }

        const digest = response["digest"];

        status = response?.effects?.status.status;

        if (status === "success") {
            this.logger.info(`[${requestId}] Successfully deposited ${quantity} into ${poolId}. Digest=${digest}`);
        } else {
            this.logger.error(`[${requestId}] Failed to deposit ${quantity} into ${poolId}. Digest=${digest}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    withdrawFromPool = async (requestId: bigint,
                              path: string,
                              params: any,
                              receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.PoolWithdrawalRequest);

        const poolId = params["pool_id"] as PoolId;
        const quantity: number = Number(params["quantity"]);
        const coinTypeId: string = params["coin_type_id"];
        const coinTypeAddress: string = this.getCoinTypeAddress(coinTypeId);
        const decimals = await this.getCoinDecimals(coinTypeId);

        this.logger.debug(`[${requestId}] Handling withdrawFromPool request. params=${JSON.stringify(params)}`);

        let response = null;
        let status: string | undefined = undefined;
        try {
            const pool = await this.getPoolInfoImpl(requestId, poolId);

            let assetType: string = '';

            if (coinTypeId == pool.base_asset) {
                assetType = 'base'
            }
            else if (coinTypeId == pool.quote_asset) {
                assetType = 'quote'
            }
            else {
                throw new Error('Coin type is not part of pool ' + coinTypeId);
            }

            const nativeAmount = BigInt(quantity * 10 ** decimals);

            this.logger.info(`Withdrawing coin ${coinTypeId} from pool ${poolId}. Amount: ${nativeAmount} (${quantity})`);

            let txBlockGenerator = async (accountCap: AccountCap, gasCoin: GasCoin) => {
                this.logger.info(`[${requestId}] accCapId=${accountCap.id} gasCoin=(${gasCoin.repr()})`);
                return await accountCap.client.withdraw(
                    poolId,
                    nativeAmount,
                    <"base"|"quote">assetType
                );
            }

            let txBlockResponseOptions = {
                showEffects: true,
                showEvents: true,
                showBalanceChanges: true
            };

            response = await this.executor!.execute(requestId,
                                                    txBlockGenerator,
                                                    txBlockResponseOptions);
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        const digest = response["digest"];

        status = response?.effects?.status.status;

        if (status === "success") {
            this.logger.info(`Successfully withdrawn ${quantity} from ${poolId}. Digest=${digest}`);
        } else {
            this.logger.error(`Failed to withdraw ${quantity} from ${poolId}. Digest=${digest}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    canWithdraw = (coinTypeId: string, withdrawalAddress: string): boolean => {
        let configuredAddresses = this.withdrawalAddresses.get(coinTypeId);
        if (configuredAddresses === undefined) {
            this.logger.error(`No entry for coin=${coinTypeId} in the withdrawal addresses file`);
            return false;
        }

        return configuredAddresses.has(withdrawalAddress)
    }

    withdrawSui = async (requestId: bigint,
                         path: string,
                         params: any,
                         receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Handling withdrawSui request. params=${JSON.stringify(params)}`);

        assertFields(params, MandatoryFields.SuiWithdrawalRequest);

        const recipient: string = params["recipient"];
        const quantity: number = Number(params["quantity"]);

        const coinTypeId = "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI";
        if (! this.canWithdraw(coinTypeId, recipient)) {
            const msg = `Cannot withdraw coin=${coinTypeId} to address=${recipient}. Please check the valid_addresses file`
            this.logger.error(`Alert: ${msg}`);
            throw new Error(msg);
        }

        let response = null;
        let status: string | undefined = undefined;
        let mainGasCoin = null;
        let gasCoinVersionUpdated: boolean = false;
        try {
            const block = new SuiTxBlock();
            mainGasCoin = await this.gasManager!.getMainGasCoin();
            if (mainGasCoin === null) {
                throw new Error("The mainGasCoin is being used in a concurrent transaction. Please retry");
            }

            await this.gasManager!.mergeUntrackedGasCoinsInto(mainGasCoin)

            if (mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
                throw new Error("Unable to update the version of the mainGasCoin after merging untracked gasCoins into it. Please retry this transaction");
            }

            block.txBlock.setGasPayment([mainGasCoin]);
            const transaction = block.transferSui(recipient, BigInt(quantity * FLOAT_SCALING_FACTOR));

            response = await this.suiClient.signAndExecuteTransactionBlock({
                signer: this.keyPair!,
                transactionBlock: transaction,
                options: {
                    showEffects: true,
                    showEvents: true,
                    showBalanceChanges: true,
                    showObjectChanges: true
                }
            });

            const digest = response["digest"];

            status = response?.effects?.status.status;

            if (status === "success") {
                this.logger.info(`Successfully withdrawn ${quantity}. Digest ${digest}`);
            } else {
                this.logger.error(`Failed to withdraw ${quantity}. Digest ${digest}`);
            }
        } finally {
            if (mainGasCoin) {
                if (response) {
                    gasCoinVersionUpdated = this.executor!.tryUpdateGasCoinVersion(requestId, response, mainGasCoin);
                    if (! gasCoinVersionUpdated) {
                        gasCoinVersionUpdated = await this.gasManager!.tryUpdateMainGasCoinVersion();
                    }
                } else {
                    gasCoinVersionUpdated = await this.gasManager!.tryUpdateMainGasCoinVersion();
                }
                if (gasCoinVersionUpdated) {
                    mainGasCoin.status = GasCoinStatus.Free;
                } else {
                    mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                }
            }
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    withdraw = async (requestId: bigint,
                      path: string,
                      params: any,
                      receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Handling withdraw request. params=${JSON.stringify(params)}`);

        assertFields(params, MandatoryFields.WithdrawalRequest);

        const coinTypeId: string = params["coin_type_id"];
        const coinTypeAddress: string = this.getCoinTypeAddress(coinTypeId);
        const recipient: string = params["recipient"];
        const quantity: number = Number(params["quantity"]);

        if (! this.canWithdraw(coinTypeId, recipient)) {
            const msg = `Cannot withdraw coin=${coinTypeId} to address=${recipient}. Please check the valid_addresses file`
            this.logger.error(`Alert: ${msg}`);
            throw new Error(msg);
        }

        const decimals = await this.getCoinDecimals(coinTypeId)

        const nativeAmount = BigInt(quantity * 10 ** decimals);

        this.logger.info(`[${requestId}] Withdrawing coin ${coinTypeId}. Amount: ${nativeAmount} (${quantity})`);

        const coinInstances: Array<string> = await this.getCoinInstances(coinTypeId);

        const block = new SuiTxBlock();

        let response = null;
        let status: string | undefined = undefined;

        try {
            let gasCoin = this.gasManager!.getFreeGasCoin();

            let txBlockGenerator = async () => {
                return await block.transferCoin(coinInstances, this.walletAddress, recipient, nativeAmount);
            }

            response = await this.executeWithObjectTimeoutCheck(
                requestId,
                txBlockGenerator,
                {
                    showEffects: true,
                    showEvents: true,
                    showBalanceChanges: true,
                    showObjectChanges: true
                },
                gasCoin
            );

            const digest = response["digest"];

            status = response?.effects?.status.status;

            if (status === "success") {
                this.logger.info(`Successfully withdrawn ${quantity}. Digest ${digest}`);
            } else {
                this.logger.info(`Failed to withdraw ${quantity}. Digest ${digest}`);
            }
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    getObjectInfo = async (requestId: bigint,
                           path: string,
                           params: any,
                           receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.ObjectInfoRequest);

        const objectId = params.get("id");
        this.logger.debug(`[${requestId}] Querying object with id=${objectId}`);

        let objectInfo = null;
        try {
            objectInfo = await this.suiClient.getObject({
                id: objectId,
                options: { showContent: true, showOwner: true, showType: true }
            });
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        return {
            statusCode: 200,
            payload: objectInfo
        };
    }

    getPoolInfoImpl = async (requestId: bigint,
                             poolId: string): Promise<PoolInfo> => {

        let response = null;
        try {
            response = await this.suiClient.getObject({
                id: poolId,
                options: { showContent: true }
            });
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        if (response?.data?.content?.dataType !== "moveObject") {
            const error = `pool ${poolId} does not exist`;
            this.logger.error(`[${requestId}] ${error}`);
            throw new Error(error);
        }

        const [baseAsset, quoteAsset] =
            parseStructTag(response.data.content.type).typeParams.map(
                (t) => normalizeStructTag(t)
            );

        let fields = response.data.content.fields as any;
        return {
            pool_id: response.data.objectId,
            base_asset: baseAsset,
            quote_asset: quoteAsset,
            taker_fee_rate: fields.taker_fee_rate,
            maker_rebate_rate: fields.maker_rebate_rate,
            tick_size: fields.tick_size,
            lot_size: fields.lot_size,
            base_asset_trading_fees: fields.base_asset_trading_fees,
            quote_asset_trading_fees: fields.quote_asset_trading_fees,
        };
    }

    getPoolInfo = async (requestId: bigint,
                         path: string,
                         params: any,
                         receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.PoolInfoRequest);

        const poolId = params.get("id");
        this.logger.debug(`[${requestId}] Querying pool with id=${poolId}`);

        let poolInfo = await this.getPoolInfoImpl(requestId, poolId);

        return {
            statusCode: 200,
            payload: poolInfo
        };
    }

    getAllPoolInfo = async (requestId: bigint,
                            path: string,
                            params: any,
                            receivedAtMs: number): Promise<RestResult> => {
        let pools = new Array<PoolInfo>();
        this.logger.debug(`[${requestId}] Querying all pools`);
        let request = async (cursor: EventId | null) => {
            try {
                return await this.mainDeepbookClient.getAllPools({
                    cursor: cursor
                });
            } catch (error) {
                this.logger.error(`[${requestId}] ${error}`);
                throw error;
            }
        };
        let poolIds = await (async () => {
            let result = new Array<string>();

            let cursor: EventId | null = null;

            const parseResponse = (response: any): EventId | null => {
                for (let item of response.data) {
                    result.push(item.poolId);
                }
                return (response.hasNextPage) ? response.nextCursor! : null;
            }

            // Handling paginated results
            do {
                let response: any =
                    await request(cursor);
                cursor = parseResponse(response);
            } while (cursor !== null);

            return result;
        })();

        for (let poolId of poolIds) {
            pools.push(await this.getPoolInfoImpl(requestId, poolId));
        }

        return {
            statusCode: 200,
            payload: pools
        };
    }

    getWalletBalanceInfo = async (requestId: bigint,
                                  path: string,
                                  params: any,
                                  receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Querying wallet balance`);
        let balanceInfo = null;
        try {
            balanceInfo = await this.suiClient.getAllBalances({
              owner: this.walletAddress
             });
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        return {
            statusCode: 200,
            payload: balanceInfo
        };
    }

    getUserPosition = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        assertFields(params, MandatoryFields.UserPositionRequest);

        const poolId = params.get("id");
        let client = this.mainDeepbookClient;

        this.logger.debug(`[${requestId}] Querying user position in pool=${poolId} accCapId=${client.accountCap}`);

        let posInfo = null;
        try {
            posInfo = await client.getUserPosition(poolId);
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        let jsonString = JSON.stringify(posInfo, (_, value) => typeof value ==="bigint" ? value.toString(): value)

        return {
            statusCode: 200,
            payload: JSON.parse(jsonString)
        };
    }

    getCoinInstances = async(coinTypeId: string): Promise<Array<string>> => {
        this.logger.info(`Getting instances of ${coinTypeId}`);

        const response = await this.suiClient.getCoins({
            owner: this.walletAddress,
            coinType: coinTypeId
        });

        let instancesOfType: Array<string> = new Array<string>();

        for (let val of response.data) {
            instancesOfType.push(val.coinObjectId);
        }

        this.logger.info(`Found ${instancesOfType.length} instances of ${coinTypeId}`);

        return instancesOfType;
    }

    getCoinDecimals = async(coinTypeId: string): Promise<number> => {
        const response = await this.suiClient.getCoinMetadata({
            coinType: coinTypeId
        });

        if (response) {
            return response.decimals;
        }
        else {
            throw new Error('Could not find decimals for coin ' + coinTypeId);
        }
    }

    getCoinTypeAddress(
        coinTypeId: string): string {
        const parts = coinTypeId.split('::');
        if (parts.length != 3) {
            throw new Error('coinTypeId should be in the format "0x123::coin::COIN"')
        }

        return parts[0];
    }
}
