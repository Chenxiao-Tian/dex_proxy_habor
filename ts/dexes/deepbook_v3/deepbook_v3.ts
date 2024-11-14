import { LoggerFactory } from "../../logger.js";
import { WebServer, RestResult, RestRequestHandler } from "../../web_server.js";
import { ClientPool } from "./client_pool.js";
import { GasManager, GasCoinStatus } from "./gas_manager.js";
import { Executor } from "./executor.js";
import { DexProxy } from "../../dex_proxy.js";
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
  OrderFilledEvent,
} from "../../order_cache.js";
import { Coin, Pool } from "@mysten/deepbook-v3";
import { ORDER_MAX_EXPIRE_TIMESTAMP_MS } from "./utils.js";
import type { NetworkType } from "./types.js";
import { bcs } from "@mysten/sui/bcs";
import {
  EventId,
  JsonRpcError,
  PaginatedEvents,
  QueryTransactionBlocksParams,
  QueryEventsParams,
  SuiClient,
  SuiEvent,
  SuiEventFilter,
  SuiHTTPStatusError,
  SuiTransactionBlockResponse,
  TransactionFilter,
} from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import {
  fromHex,
  normalizeSuiAddress,
  SUI_CLOCK_OBJECT_ID,
} from "@mysten/sui/utils";
import { Transaction } from "@mysten/sui/transactions";
import { readFileSync } from "fs";
import { dirname } from "path";
import { Logger } from "winston";
import { SuiTxBlock } from "./sui_tx_block.js";
import { ParsedOrderError, DexInterface, Mode } from "../../types.js";
import { assertFields } from "../../utils.js";

const FLOAT_SCALING_FACTOR: number = 1_000_000_000;

interface ParsedExchangeError {
  type: string | null;
  txNumber: number | null;
}

class MandatoryFields {
  static InsertRequest = [
    "pool",
    "client_order_id",
    "order_type",
    "side",
    "quantity",
    "price",
  ];
  static BulkInsertRequest = ["pool", "orders"];
  static CancelRequest = ["pool", "client_order_id"];
  static BulkCancelRequest = ["pool", "client_order_ids"];
  static CancelAllRequest = ["pool"];
  static TransactionBlockRequest = ["digest"];
  static EventsFromDigests = ["tx_digests_list"];
  static OrderStatusRequest = ["pool", "client_order_id"];
  static AllOpenOrdersRequest = ["pool"];
  static SuiWithdrawalRequest = ["recipient", "quantity"];
  static WithdrawalRequest = ["coin_type_id", "recipient", "quantity"];
  static ObjectInfoRequest = ["id"];
  static PoolInfoRequest = ["pool"];
  static BalanceManagerFundsRequest = ["coin"];
  static DepositIntoBalanceManagerRequest = ["coin", "quantity"];
  static WithdrawFromBalanceManagerRequest = ["coin", "quantity"];
  static TradesByTimeRequest = ["start_ts", "max_pages"];
  static TradesByDigestRequest = ["tx_digests_list"];
}

export class DeepBookV3 implements DexInterface {
  private logger: Logger;
  private config: any;
  private server: WebServer;
  private mode: Mode;
  private dexProxy: DexProxy;
  private log_responses: boolean;

  private orderCache: OrderCache;

  private keyPair: Ed25519Keypair | undefined;

  private walletAddress: string;

  private balanceManagerId: string;

  private clientPool: ClientPool;
  private gasManager: GasManager | undefined;
  private executor: Executor | undefined;

  private chainName: string;
  private withdrawalAddresses: Map<string, Set<string>>;
  private coinsMap: Record<string, Coin>;
  private poolsMap: Record<string, Pool>;

  private currentEpoch: string | undefined;

  // pools for which we might need to call: withdraw settled amounts
  private maybeWithdrawSettledAmounts: Set<string>;

  private environment: NetworkType;
  private deepbookPackageId: string;

  private static exchangeErrors = new Map<string, Map<string, string>>([
    [
      "balance_manager",
      new Map<string, string>([
        ["0", "INVALID_OWNER"],
        ["1", "INVALID_TRADER"],
        ["2", "INVALID_TRADE_PROOF"],
        ["3", "INSUFFICIENT_FUNDS"],
      ]),
    ],
    ["big_vector", new Map<string, string>([["5", "REMOVED_FROM_BOOK"]])],

    // pool in which we haven't placed any order yet
    ["dynamic_field", new Map<string, string>([["1", "UNUSED_POOL"]])],

    [
      "order_info",
      new Map<string, string>([
        ["0", "INVALID_PRICE"],
        ["1", "BELOW_MINIMUM_QUANTITY"],
        ["2", "INVALID_LOT_SIZE"],
        ["3", "INVALID_EXPIRE_TIME"],
        ["4", "INVALID_ORDER_TYPE"],
        ["5", "GPO_WOULD_TAKE"],
        ["8", "STP_REJECT_TAKER"],
      ]),
    ],
    ["pool", new Map<string, string>([["9", "INVALID_FEE_TYPE"]])],
    ["state", new Map<string, string>([["2", "MAX_OPEN_ORDERS"]])],
  ]);

  public channels: Array<string> = ["ORDER", "TRADE"];
  private static TESTNET_DEEPBOOKV3_PACKAGE_ID: string =
    "0xcbf4748a965d469ea3a36cf0ccc5743b96c2d0ae6dee0762ed3eca65fac07f7e";
  private static MAINNET_DEEPBOOKV3_PACKAGE_ID: string =
    "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809";

  constructor(
    lf: LoggerFactory,
    server: WebServer,
    config: any,
    mode: Mode,
    dexProxy: DexProxy
  ) {
    this.logger = lf.createLogger("deepbook_v3");
    this.config = config;
    this.server = server;

    if (config.dex === undefined) {
      throw new Error(
        "A section corresponding to `dex` must be present in the config"
      );
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
      this.keyPair = Ed25519Keypair.fromSecretKey(fromHex(secretKey));
      this.walletAddress = this.keyPair.getPublicKey().toSuiAddress();
    } else {
      this.keyPair = undefined;
      if (config.dex.wallet_address === undefined) {
        throw new Error(
          "The key, `dex.wallet_address` must be present in the config"
        );
      }
      this.walletAddress = config.dex.wallet_address;
    }
    this.logger.info(`wallet=${this.walletAddress}`);

    this.maybeWithdrawSettledAmounts = new Set<string>();

    if (config.dex.env === undefined) {
      throw new Error("The key, `dex.env` must be present in the config");
    }
    this.environment = config.dex.env;

    this.chainName = config.dex.chain_name;
    this.withdrawalAddresses = new Map<string, Set<string>>();
    this.coinsMap = {};
    this.poolsMap = {};

    if (this.chainName === undefined) {
      throw new Error("The key `dex.chain_name` must be present in the config");
    }
    this.loadResources();

    if (this.environment === "mainnet") {
      this.deepbookPackageId = DeepBookV3.MAINNET_DEEPBOOKV3_PACKAGE_ID;
    } else {
      this.deepbookPackageId = DeepBookV3.TESTNET_DEEPBOOKV3_PACKAGE_ID;
    }

    this.balanceManagerId = config.dex.balance_manager_id;
    if (this.balanceManagerId === undefined) {
      this.logger.warn(
        "Cannot perform any account related operations without an entry for `dex.balance_manager_id` in the config"
      );
    }

    this.clientPool = new ClientPool(
      lf,
      config.dex,
      this.balanceManagerId,
      this.walletAddress,
      this.environment,
      this.coinsMap,
      this.poolsMap
    );

    if (this.mode === "read-write") {
      const maxBalancePerInstanceMist = BigInt(
        config.dex.gas_manager.max_balance_per_instance_mist.replace(/,/g, "")
      );
      const minBalancePerInstanceMist = BigInt(
        config.dex.gas_manager.min_balance_per_instance_mist.replace(/,/g, "")
      );
      const syncIntervalMs =
        1000 * Number(config.dex.gas_manager.sync_interval_s);

      if (config.dex.gas_manager.gas_coin_expected_count === undefined) {
        throw new Error(
          "The key, `dex.gas_manager.gas_coin_expected_count` must be present in the config"
        );
      }

      this.gasManager = new GasManager(
        lf,
        this.clientPool,
        this.walletAddress,
        this.keyPair!,
        config.dex.gas_manager.gas_coin_expected_count,
        maxBalancePerInstanceMist,
        minBalancePerInstanceMist,
        syncIntervalMs,
        this.log_responses
      );

      const gasBudgetMist = BigInt(
        config.dex.gas_manager.gas_budget_mist.replace(/,/g, "")
      );

      this.executor = new Executor(
        lf,
        this.keyPair!,
        this.gasManager,
        gasBudgetMist
      );
    } else {
      this.gasManager = undefined;
      this.executor = undefined;
    }

    this.registerEndpoints();
  }

  loadResources = (): void => {
    try {
      const filePrefix = dirname(process.argv[1]);
      const filename = `${filePrefix}/resources/dbv3_withdrawal_addresses.json`;
      let contents = JSON.parse(readFileSync(filename, "utf8"));

      this.logger.info(
        `Looking up resources file for chainName=${this.chainName} from file=${filename}`
      );

      this.coinsMap = contents[this.chainName].coins_map;
      this.poolsMap = contents[this.chainName].pools_map;

      if (this.mode === "read-write") {
        this.fetchWithdrawalAddresses(contents);
      }
    } catch (error) {
      const msg: string = `Failed to parse resources file: ${error}`;
      this.logger.error(msg);
      throw new Error(msg);
    }
  };

  fetchWithdrawalAddresses = (contents: any): void => {
    this.logger.info(
      `Looking up configured withdrawal addresses for chainName=${this.chainName}`
    );

    let tokenData = contents[this.chainName]?.tokens;
    if (tokenData) {
      for (let entry of tokenData) {
        let coinType = entry.coin_type;
        if (this.withdrawalAddresses.has(coinType)) {
          throw new Error(`Duplicate entry in the resources file ${coinType}`);
        }

        let withdrawalAddresses = new Set<string>(
          entry.valid_withdrawal_addresses
        );
        this.withdrawalAddresses.set(coinType, withdrawalAddresses);
      }
    }
  };

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
      return { statusCode: 200, payload: { result: "Deepbook API" } };
    });
    GET("/status", this.getStatus);

    GET("/pool", this.getPoolInfo);

    GET("/object-info", this.getObjectInfo);

    GET("/wallet-address", this.getWalletAddress);
    GET("/balance-manager-id", this.getBalanceManagerId);

    GET("/wallet-balance-info", this.getWalletBalanceInfo);
    GET("/balance-manager-balance-info", this.getBalanceManagerBalanceInfo);

    GET("/transaction", this.getTransactionBlock);
    GET("/transactions", this.getTransactionBlocks);

    GET("/events", this.getEventsFromDigests);

    POST("/order", this.insertOrder);
    POST("/orders", this.insertOrders);

    GET("/order", this.getOrderStatus);
    GET("/orders", this.getOpenOrders);

    DELETE("/order", this.cancelOrder);
    DELETE("/orders", this.cancelOrders);

    GET("/trades", this.getTrades);

    POST("/withdraw-sui", this.withdrawSui);
    POST("/withdraw", this.withdraw);
    POST("/withdraw-from-balance-manager", this.withdrawFromBalanceManager);
    POST("/deposit-into-balance-manager", this.depositIntoBalanceManager);

    POST("/create-balance-manager", this.createBalanceManager);
  };

  start = async () => {
    await this.clientPool.start();

    if (this.mode === "read-write") {
      await this.gasManager!.start();

      let client = this.clientPool.getClient();
      this.logger.debug(`Using ${client.name} client to query epoch`);
      this.currentEpoch = await this.queryEpoch(client.suiClient);
      if (this.currentEpoch === undefined) {
        throw new Error("Unable to fetch current epoch on startup. Exiting");
      } else {
        this.logger.info(`Setting currentEpoch=${this.currentEpoch}`);
      }

      // 5 minutes
      const trackEpochIntervalMs = 5 * 60 * 1000;
      setInterval(this.trackEpoch, trackEpochIntervalMs);

      if (this.config.dex.withdraw_settled_amounts_interval_s === undefined) {
        throw new Error(
          "withdraw_settled_amounts_interval_s not set for read-write dex-proxy"
        );
      } else {
        for (let poolName in this.poolsMap) {
          this.maybeWithdrawSettledAmounts.add(poolName);
        }

        const withdrawSettledAmountsIntervalMs =
          this.config.dex.withdraw_settled_amounts_interval_s * 1000;
        setInterval(
          this.withdrawSettledAmounts,
          withdrawSettledAmountsIntervalMs
        );
      }
    }

    if (this.config.dex.subscribe_to_events) {
      await this.subscribeToEvents({
        Sender: this.walletAddress,
      });

      if (this.balanceManagerId) {
        // Subscribe to maker trades
        await this.subscribeToEvents({
          MoveEventField: {
            path: "/maker_balance_manager_id",
            value: this.balanceManagerId,
          },
        });

        // Subscribe to taker trades
        await this.subscribeToEvents({
          MoveEventField: {
            path: "/taker_balance_manager_id",
            value: this.balanceManagerId,
          },
        });
      } else {
        this.logger.warn(
          "Cannot subscribe to maker and taker trades, without an entry for `dex.balance_manager_id` in the config"
        );
      }
    }

    await this.server.start();
  };

  handleEvent = async (event: SuiEvent) => {
    let parsedEvent: Event | Event[] | null = null;
    let channel: string = "ORDER";
    if (event.type.endsWith("OrderInfo")) {
      parsedEvent = this.processOrderPlacedEvent(event);
    } else if (event.type.includes("OrderCanceled")) {
      parsedEvent = this.processOrderCancelledEvent(event);
    } else if (event.type.endsWith("OrderFilled")) {
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
          channel: channel,
          type: eventType,
          data: parsedEvent,
        },
      };
      await this.dexProxy.onEvent(channel, update);
    }
  };

  subscribeToEvents = async (filter: SuiEventFilter) => {
    const retryIntervalMs: number = 5_000;
    let delay = () => {
      return new Promise((resolve) => setTimeout(resolve, retryIntervalMs));
    };

    const filterAsString = JSON.stringify(filter);

    let subscribe = async () => {
      this.logger.info(
        `Subscribing to events stream with filter: ${filterAsString}`
      );
      try {
        // TODO: ideally we should make WS subsciptions from all sui clients
        // But since we are not using it currently, this is ok for now.
        let client = this.clientPool.getClient();
        this.logger.debug(`Using ${client.name} client to subscribe events`);

        await client.suiClient.subscribeEvent({
          filter: filter,
          onMessage: async (event) => {
            await this.handleEvent(event);
          },
        });
      } catch (error: unknown) {
        this.logger.error(`Failed to subscribe to events: ${error}`);

        if (error instanceof JsonRpcError) {
          let rpcError = error as JsonRpcError;
          this.logger.error(
            `Failed to subscribe to events stream with filter=${filterAsString}. Error=${rpcError.code}, ${rpcError.type}`
          );
          this.logger.info(
            `Retrying subscription to events stream in ${retryIntervalMs} ms`
          );
          await delay();
          await subscribe();
        } else if (error instanceof Error) {
          this.logger.error(
            `Failed to subscribe to events stream with filter=${filterAsString}. Error=${error}`
          );
          await delay();
          await subscribe();
        } else {
          throw error;
        }
      }
    };

    await subscribe();
  };

  static tryParseError = (error: string): ParsedExchangeError => {
    let errorRegex =
      /MoveAbort.*Identifier\("(?<errorLocation>[\w]+)"\) .* (?<errorCode>[\d]+)\) in command (?<txNumber>[\d]+)/;
    let match = error.match(errorRegex);
    let parsedError: ParsedExchangeError = {
      type: null,
      txNumber: null,
    };

    if (
      match?.groups !== undefined &&
      match.groups.errorCode !== null &&
      match.groups.errorLocation !== null &&
      match.groups.txNumber !== null
    ) {
      const errorFile = DeepBookV3.exchangeErrors.get(
        match!.groups!.errorLocation
      );
      if (errorFile != undefined) {
        const errorStr = errorFile.get(match!.groups!.errorCode);

        parsedError.type = errorStr === undefined ? null : errorStr;
        parsedError.txNumber = Number(match!.groups!.txNumber);
      }
    }

    return parsedError;
  };

  queryEpoch = async (suiClient: SuiClient): Promise<string | undefined> => {
    const retryIntervalMs: number = 5_000;
    let delay = () => {
      return new Promise((resolve) => setTimeout(resolve, retryIntervalMs));
    };

    let queryFunc = async (
      retryCount: number = 0
    ): Promise<string | undefined> => {
      this.logger.info(`Querying current epoch`);
      let attemptFailed = false;

      try {
        let state = await suiClient.getLatestSuiSystemState();
        this.logger.debug(`epoch from chain=${state.epoch}`);
        return state.epoch;
      } catch (error: unknown) {
        this.logger.error(`Failed to query epoch: ${error}`);

        if (error instanceof SuiHTTPStatusError) {
          this.logger.error(
            `Unexpected HTTP status code returned. code=${error.status}, details=${error.statusText}`
          );
        } else if (error instanceof JsonRpcError) {
          this.logger.error(
            `JSON RPC error. code=${error.code}, msg=${error.message}`
          );
        } else {
          this.logger.error(`Unknown error. msg=${error}`);
        }

        attemptFailed = true;
      } finally {
        if (attemptFailed) {
          if (retryCount < 3) {
            this.logger.info(
              `Retrying query for current epoch in ${retryIntervalMs} ms`
            );
            await delay();
            return await queryFunc(retryCount + 1);
          } else {
            this.logger.error("Exhausted max retries to get current epoch");
            return undefined;
          }
        }
      }
    };

    return await queryFunc();
  };

  trackEpoch = async () => {
    let client = this.clientPool.getClient();
    this.logger.debug(`Using ${client.name} client to query epoch`);
    const epoch = await this.queryEpoch(client.suiClient);

    if (epoch === undefined) {
      this.logger.error(
        "Unable to check for epoch change. Will try again in next scheduled iteration"
      );
    } else {
      if (epoch != this.currentEpoch) {
        this.logger.info(
          `Detected epoch update from ${this.currentEpoch} to ${epoch}`
        );
        this.currentEpoch = epoch;
        this.logger.info(`Updated currentEpoch to ${this.currentEpoch}`);
        await this.gasManager!.onEpochChange(client.suiClient);
      } else {
        this.gasManager!.logSkippedObjects();
      }
    }
  };

  // Usage of this method: https://auros-group.slack.com/archives/C063QLURS9G/p1729331016525649
  withdrawSettledAmounts = async () => {
    let client = this.clientPool.getClient();
    this.logger.debug(
      `Using ${client.name} client for withdrawing settled amounts`
    );

    let idx = 0;
    for (let poolName in this.poolsMap) {
      if (this.maybeWithdrawSettledAmounts.has(poolName)) {
        try {
          let lockedBalances = await this.getLockedBalance(
            BigInt(idx),
            client.suiClient,
            poolName,
            this.getPool(poolName)
          );

          if (
            lockedBalances === null ||
            (lockedBalances.base === BigInt(0) &&
              lockedBalances.quote === BigInt(0) &&
              lockedBalances.deep === BigInt(0))
          ) {
            this.logger.debug(
              `[${idx}] Not calling withdraw settled amounts for ${poolName} as it has no locked balance`
            );
            idx++;
            continue;
          }

          let txBlockGenerator = () => {
            this.logger.debug(
              `[${idx}] Withdrawing settled amounts from ${poolName}`
            );

            const tx = new Transaction();
            tx.add(
              client.deepBookClient.deepBook.withdrawSettledAmounts(
                poolName,
                "MANAGER"
              )
            );

            return tx;
          };

          let txBlockResponseOptions = { showEffects: true };

          let response = await this.executor!.execute(
            BigInt(idx),
            client.suiClient,
            txBlockGenerator,
            txBlockResponseOptions
          );

          const digest: string = response.digest;
          if (response.effects!.status.status === "success") {
            this.logger.debug(
              `[${idx}] Successfully withdrawn settled amounts from ${poolName}. Digest=${digest}`
            );
          } else {
            const errorMsg = response.effects!.status.error!;
            this.logger.error(
              `[${idx}] Failed to withdraw settled amounts from ${poolName}. Error=${errorMsg.toString()}. Digest=${digest}`
            );
          }
        } catch (error) {
          this.logger.error(
            `[${idx}] Error while withdrawing settled amounts  from ${poolName}: ${error}`
          );
        }
      } else {
        this.logger.debug(
          `[${idx}] Ignoring to withdraw settled amounts from ${poolName} as the pool is actively traded so not required`
        );
      }
      idx++;
    }

    // For next iteration:
    // withdraw settled amounts from pools in which we are not actively placing orders
    for (let poolName in this.poolsMap) {
      this.maybeWithdrawSettledAmounts.add(poolName);
    }
  };

  getStatus = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    this.logger.debug(`[${requestId}] Handling ${path} request`);

    return {
      statusCode: 200,
      payload: {
        status: "ok",
      },
    };
  };

  getTransactionBlocks = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
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
      order: "descending",
    };

    this.logger.debug(
      `[${requestId}] Handling ${path} request with filter: ${JSON.stringify(
        queryParams
      )}`
    );

    let txBlocks = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      txBlocks = await client.suiClient.queryTransactionBlocks(queryParams);
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);
      throw error;
    }

    return {
      statusCode: 200,
      payload: txBlocks,
    };
  };

  getTransactionBlock = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.TransactionBlockRequest);

    const digest: string = params.get("digest");
    this.logger.debug(`[${requestId}] Querying txDigest ${digest}`);

    let txBlock = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      txBlock = await client.suiClient.getTransactionBlock({
        digest: digest,
        options: {
          showBalanceChanges: true,
          showEvents: true,
          showObjectChanges: true,
          showEffects: true,
          showInput: true,
        },
      });
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);
      throw error;
    }

    return {
      statusCode: 200,
      payload: txBlock,
    };
  };

  getEventsFromDigests = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.EventsFromDigests);

    const requestedDigests: string = params.get("tx_digests_list");
    const txDigests: Array<string> = requestedDigests.split(",");
    this.logger.debug(
      `[${requestId}] Getting events for digests: ${requestedDigests}`
    );

    let client = this.clientPool.getClient();
    this.logger.debug(`[${requestId}] using ${client.name} client`);

    let events = new Array<Event>();
    for (let digest of txDigests) {
      let response = null;
      try {
        response = await client.suiClient.getTransactionBlock({
          digest: digest,
          options: { showEvents: true },
        });

        if (response && response.events) {
          for (let event of response.events as SuiEvent[]) {
            if (event.type.endsWith("OrderInfo")) {
              let orderPlacedEvent = this.processOrderPlacedEvent(event);

              let order = this.orderCache.get(orderPlacedEvent.client_order_id);
              if (order && order.exchangeOrderId === null) {
                order.exchangeOrderId = orderPlacedEvent.exchange_order_id;
              }

              events.push(orderPlacedEvent);
            } else if (event.type.endsWith("OrderFilled")) {
              let orderFilledEvent = this.processOrderFilledEvent(event);
              events.push(orderFilledEvent);
            } else if (event.type.includes("OrderCanceled")) {
              let orderCancelledEvent = this.processOrderCancelledEvent(event);

              let order = this.orderCache.get(
                orderCancelledEvent.client_order_id
              );
              if (order) {
                order.status = "Cancelled";
                this.orderCache.delete(orderCancelledEvent.client_order_id);
              }

              events.push(orderCancelledEvent);
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
  };

  getWalletAddress = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    this.logger.debug(`[${requestId}] Fetching wallet address`);

    return {
      statusCode: 200,
      payload: {
        wallet_address: this.walletAddress,
      },
    };
  };

  getBalanceManagerId = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    this.logger.debug(`[${requestId}] Fetching balance manager id`);

    return {
      statusCode: 200,
      payload: {
        balance_manager_id: this.balanceManagerId,
      },
    };
  };

  readPrivateKey = (): string => {
    if (this.config.key_store_file_path === undefined) {
      throw new Error(
        "The key `key_store_file_path` must be defined in the config"
      );
    }
    const keyStoreFilePath: string = this.config.key_store_file_path;
    try {
      return readFileSync(keyStoreFilePath, "utf8").trimEnd();
    } catch (error) {
      this.logger.error(`Cannot read private key from ${keyStoreFilePath}`);
      this.logger.error(error);
      throw error;
    }
  };

  createBalanceManager = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    let response: SuiTransactionBlockResponse | null = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Creating balance-manager: ${JSON.stringify(params)}`
        );

        const tx = new Transaction();
        tx.add(
          client.deepBookClient.balanceManager.createAndShareBalanceManager()
        );

        return tx;
      };

      let txBlockResponseOptions = { showEffects: true };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    let statusCode: number = 200;
    const digest: string = response.digest;
    let balanceManagerId: string | null = null;
    if (response.effects!.status.status === "success") {
      let createdObjs = response.effects?.created;
      if (createdObjs) {
        for (let createdObj of createdObjs) {
          balanceManagerId = createdObj.reference.objectId;
        }
      }
      this.logger.debug(
        `[${requestId}] Created balance_manager_id=${balanceManagerId}. Digest=${digest}`
      );
    } else {
      this.logger.error(
        `[${requestId}] Failed to create balance_manager. Digest=${digest}`
      );
      statusCode = 400;
    }

    return {
      statusCode: statusCode,
      payload: {
        tx_digest: digest,
        status: response.effects!.status.status,
        balance_manager_id: balanceManagerId,
      },
    };
  };

  getOrderStatus = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.OrderStatusRequest);

    const pool: string = params.get("pool");
    const clientOrderId = params.get("client_order_id") as ClientOrderId;

    this.logger.debug(
      `[${requestId}] Fetching order status. pool=${pool} and client_order_id=${clientOrderId}`
    );

    const order = this.orderCache.get(clientOrderId);
    if (order === undefined) {
      this.logger.warn(
        `[${requestId}] client_order_id=${clientOrderId} does not exist`
      );

      return {
        statusCode: 400,
        payload: {
          type: "ORDER_NOT_FOUND",
        },
      };
    }

    const exchangeOrderId = order.exchangeOrderId;

    let exchangeOrderStatus: any = null;
    if (exchangeOrderId) {
      try {
        let client = this.clientPool.getClient();
        this.logger.debug(`[${requestId}] using ${client.name} client`);

        exchangeOrderStatus = await client.deepBookClient.getOrder(
          pool,
          exchangeOrderId
        );
      } catch (error) {
        this.logger.error(`[${requestId}] ${error}`);
        throw error;
      } finally {
        if (this.log_responses) {
          const dump = JSON.stringify(exchangeOrderStatus);
          this.logger.debug(`[${requestId}] Order query response: ${dump}`);
        }
      }
    }

    if (exchangeOrderStatus !== null) {
      if (order.status === "Unknown" || order.status === "PendingInsert") {
        order.status = "Open";
      }

      // Note: Order qty is getting changed to what qty was inserted in the order book
      // Similarly execQty and remQty are the state after the order was inserted in the book
      order.qty = BigInt(exchangeOrderStatus.quantity) as Quantity;
      order.execQty = BigInt(exchangeOrderStatus.filled_quantity) as Quantity;
      order.remQty = (order.qty - order.execQty) as Quantity;
    } else {
      if (order.status !== "PendingInsert") {
        order.status = "Unknown";
      }

      return {
        statusCode: 400,
        payload: {
          type: "ORDER_NOT_FOUND",
        },
      };
    }

    let orderStatus: OrderStatus = {
      client_order_id: order.clientOrderId,
      exchange_order_id: order.exchangeOrderId,
      status: order.status,
      side: order.side,
      qty: order.qty.toString(),
      rem_qty: order.remQty.toString(),
      exec_qty: order.execQty.toString(),
      price: order.price.toString(),
      expiration_ts: order.expirationTs.toString(),
    };

    return {
      statusCode: 200,
      payload: {
        order_status: orderStatus,
      },
    };
  };

  processOpenOrdersResponse = async (
    poolId: PoolId,
    openOrders: Array<any>
  ): Promise<Array<OrderStatus>> => {
    let result = new Array<OrderStatus>();
    for (let openOrder of openOrders) {
      let cachedOrder: Order | undefined = undefined;
      cachedOrder = this.orderCache.get(openOrder.client_order_id);

      const exchangeOrderId = openOrder.order_id as ExchangeOrderId;

      const qty = BigInt(openOrder.quantity) as Quantity;
      const execQty = BigInt(openOrder.filled_quantity) as Quantity;
      const remQty = (qty - execQty) as Quantity;

      if (cachedOrder !== undefined) {
        if (cachedOrder.exchangeOrderId === null) {
          cachedOrder.exchangeOrderId = exchangeOrderId;
        }

        // Note: Order qty is getting changed to what qty was inserted in the order book
        // Similarly execQty and remQty are the state after the order was inserted in the book
        cachedOrder.qty = qty;
        cachedOrder.execQty = execQty;
        cachedOrder.remQty = remQty;

        if (
          cachedOrder.status === "Unknown" ||
          cachedOrder.status === "PendingInsert"
        ) {
          cachedOrder.status = "Open";
        }
      } else {
        cachedOrder = {
          clientOrderId: openOrder.client_order_id as ClientOrderId,
          exchangeOrderId: exchangeOrderId,
          status: "Open",
          poolId: poolId,
          qty: qty,
          remQty: remQty,
          execQty: execQty,
          price: this.parsePrice(exchangeOrderId),
          type: null,
          side: this.parseSide(exchangeOrderId),

          expirationTs: Number(openOrder.expire_timestamp) as TimestampMs,
          txDigests: [],
        };

        this.orderCache.add(cachedOrder.clientOrderId, cachedOrder);
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
        expiration_ts: cachedOrder.expirationTs.toString(),
      });
    }

    return result;
  };

  getOpenOrdersImpl = async (
    requestId: bigint,
    pool: Pool
  ): Promise<Array<any>> => {
    const tx = new Transaction();
    tx.moveCall({
      target: `${this.deepbookPackageId}::pool::get_account_order_details`,
      arguments: [tx.object(pool.address), tx.object(this.balanceManagerId)],
      typeArguments: [
        this.getCoin(pool.baseCoin).type,
        this.getCoin(pool.quoteCoin).type,
      ],
    });

    let client = this.clientPool.getClient();
    this.logger.debug(`[${requestId}] using ${client.name} client`);

    const response = await client.suiClient.devInspectTransactionBlock({
      sender: normalizeSuiAddress(this.walletAddress),
      transactionBlock: tx,
    });

    const ID = bcs.struct("ID", {
      bytes: bcs.Address,
    });
    const OrderDeepPrice = bcs.struct("OrderDeepPrice", {
      asset_is_base: bcs.bool(),
      deep_per_asset: bcs.u64(),
    });
    const Order = bcs.struct("Order", {
      balance_manager_id: ID,
      order_id: bcs.u128(),
      client_order_id: bcs.u64(),
      quantity: bcs.u64(),
      filled_quantity: bcs.u64(),
      fee_is_deep: bcs.bool(),
      order_deep_price: OrderDeepPrice,
      epoch: bcs.u64(),
      status: bcs.u8(),
      expire_timestamp: bcs.u64(),
    });

    const ordersInformation = response!.results![0].returnValues![0][0];
    let orders = bcs.vector(Order).parse(new Uint8Array(ordersInformation));

    if (this.log_responses) {
      const dump = JSON.stringify(orders);
      this.logger.debug(`[${requestId}] Fetched all open orders: ${dump}`);
    }

    return orders;
  };

  getOpenOrders = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.AllOpenOrdersRequest);
    let openOrders = null;
    try {
      const poolName: string = params.get("pool");
      const pool: Pool = this.getPool(poolName);

      this.logger.debug(
        `[${requestId}] Fetching all open orders. pool=${poolName}`
      );

      openOrders = await this.processOpenOrdersResponse(
        pool.address as PoolId,
        await this.getOpenOrdersImpl(requestId, pool)
      );
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    return {
      statusCode: 200,
      payload: {
        open_orders: openOrders,
      },
    };
  };

  checkTransactionFailure = (
    requestId: bigint,
    response: SuiTransactionBlockResponse
  ) => {
    if (response.effects!.status.status === "failure") {
      const error = response.effects!.status.error!;

      this.logger.error(`[${requestId}] Transaction failure: ${error}`);

      let type = "FAILED";
      if (error == "InsufficientGas") {
        type = "INSUFFICIENT_GAS";
      } else {
        let parsedError = DeepBookV3.tryParseError(error.toString());
        if (parsedError.type) {
          type = parsedError.type;
        }
      }

      throw new ParsedOrderError(type, error);
    }
  };

  parseInsertRequest = (request: any, poolId: PoolId): Order => {
    const qty = BigInt(request.quantity);
    const price = BigInt(request.price);

    return {
      clientOrderId: request.client_order_id as ClientOrderId,
      status: "PendingInsert",
      poolId: poolId,
      qty: qty as Quantity,
      remQty: qty as Quantity,
      execQty: 0n as Quantity,
      price: price as Price,
      type: request.order_type,
      side: request.side,
      expirationTs: ORDER_MAX_EXPIRE_TIMESTAMP_MS as TimestampMs,

      txDigests: new Array<TxDigest>(),
      exchangeOrderId: null,
    };
  };

  processOrderPlacedEvent = (event: SuiEvent): OrderPlacedEvent => {
    let json = event.parsedJson as any;

    const qty = json.original_quantity;
    const execQty = json.executed_quantity;
    const remQty = (BigInt(qty) - BigInt(execQty)).toString();
    const price = json.price;
    const timestampMs =
      event.timestampMs === undefined ? null : event.timestampMs;

    return {
      event_type: "order_placed",
      pool_id: json.pool_id as PoolId,
      client_order_id: json.client_order_id as ClientOrderId,
      exchange_order_id: json.order_id as ExchangeOrderId,
      side: (json.is_bid ? "BUY" : "SELL") as Side,
      qty: qty,
      rem_qty: remQty,
      exec_qty: execQty,
      price: price,
      timestamp_ms: timestampMs,
    };
  };

  processOrderFilledEvent = (event: SuiEvent): OrderFilledEvent => {
    let json = event.parsedJson as any;

    const tradeId = `${event.id.txDigest}_${event.id.eventSeq}`;
    const liquidityIndicator =
      json.maker_balance_manager_id === this.balanceManagerId
        ? "Maker"
        : "Taker";
    const clientOrderId =
      liquidityIndicator === "Maker"
        ? json.maker_client_order_id
        : json.taker_client_order_id;
    const exec_qty = json.base_quantity;
    const price = json.price;
    const fee =
      liquidityIndicator === "Maker" ? json.maker_fee : json.taker_fee;
    const exchangeOrderId =
      liquidityIndicator === "Maker"
        ? json.maker_order_id
        : json.taker_order_id;
    const timestampMs = json.timestamp === undefined ? null : json.timestamp;

    let side: Side;
    if (liquidityIndicator === "Taker") {
      side = json.taker_is_bid ? "BUY" : "SELL";
    } else {
      side = json.taker_is_bid ? "SELL" : "BUY";
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
      timestamp_ms: timestampMs,
    };
  };

  processInsertResponse = async (
    response: SuiTransactionBlockResponse,
    order: Order
  ): Promise<Array<Event>> => {
    order.status =
      response.effects!.status.status === "success" ? "Open" : "Finalised";
    if (order.type === "IOC") {
      order.status = "Finalised";
      this.orderCache.delete(order.clientOrderId);
    }
    order.txDigests.push(response.digest as TxDigest);

    let events = new Array<Event>();

    if (response.events) {
      for (let event of response.events as SuiEvent[]) {
        if (event.type.endsWith("OrderInfo")) {
          let orderPlacedEvent = this.processOrderPlacedEvent(event);

          // TODO: maybe we don't need this
          order.execQty = BigInt(orderPlacedEvent.exec_qty) as Quantity;
          order.remQty = BigInt(orderPlacedEvent.rem_qty) as Quantity;
          order.exchangeOrderId = orderPlacedEvent.exchange_order_id;

          events.push(orderPlacedEvent);
        } else if (event.type.endsWith("OrderFilled")) {
          let orderFilledEvent = this.processOrderFilledEvent(event);
          events.push(orderFilledEvent);
        } else if (event.type.includes("OrderCanceled")) {
          // Can receive cancel event in order insert response due to STP
          let orderCancelledEvent = this.processOrderCancelledEvent(event);

          let order = this.orderCache.get(orderCancelledEvent.client_order_id);
          if (order) {
            order.status = "Cancelled";
            this.orderCache.delete(orderCancelledEvent.client_order_id);
          }

          events.push(orderCancelledEvent);
        }
      }
    }

    return events;
  };

  static parseOrderType = (type: string | null): number => {
    if (type == "GTC") return 0;
    else if (type === "IOC") return 1;
    else if (type == "GPO") return 3;
    else throw new ParsedOrderError("UNKNOWN", `Unknown order type: ${type}`);
  };

  insertOrder = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.InsertRequest);

    const poolName: string = params.pool;
    const pool: Pool = this.getPool(poolName);

    let order = this.parseInsertRequest(params, pool.address as PoolId);
    this.orderCache.add(order.clientOrderId, order);

    const isBid = order.side === "BUY" ? true : false;
    const orderType = DeepBookV3.parseOrderType(order.type);
    const selfMatchingPrevention: number = 2; // CANCEL_MAKER

    const baseCoinTypeId: string = this.getCoin(pool.baseCoin).type;
    const quoteCoinTypeId: string = this.getCoin(pool.quoteCoin).type;

    this.logger.debug(
      `[${requestId}] Inserting order: params=${JSON.stringify(params)}`
    );

    let response = null;
    try {
      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Inserting order. params=${JSON.stringify(params)}`
        );

        const tx = new Transaction();

        let tradeProof = tx.moveCall({
          target: `${this.deepbookPackageId}::balance_manager::generate_proof_as_owner`,
          arguments: [tx.object(this.balanceManagerId)],
        });

        tx.moveCall({
          target: `${this.deepbookPackageId}::pool::place_limit_order`,
          arguments: [
            tx.object(order.poolId),
            tx.object(this.balanceManagerId),
            tradeProof,
            tx.pure.u64(order.clientOrderId),
            tx.pure.u8(orderType),
            tx.pure.u8(selfMatchingPrevention),
            tx.pure.u64(order.price),
            tx.pure.u64(order.qty),
            tx.pure.bool(isBid),
            tx.pure.bool(true),
            tx.pure.u64(order.expirationTs),
            tx.object(SUI_CLOCK_OBJECT_ID),
          ],
          typeArguments: [baseCoinTypeId, quoteCoinTypeId],
        });

        return tx;
      };

      let txBlockResponseOptions = { showEffects: true, showEvents: true };

      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);

      if (error instanceof Error) {
        const parsedError = DeepBookV3.tryParseError(error.toString());
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
      throw new ParsedOrderError("UNKNOWN", errorStr);
    } finally {
      if (this.log_responses) {
        const dump = JSON.stringify(response);
        this.logger.debug(`[${requestId}] Insert response: ${dump}`);
      }
    }

    this.checkTransactionFailure(requestId, response);

    const status = response.effects!.status.status;
    if (status === "success") {
      this.logger.info(
        `[${requestId}] Order inserted for pool=${poolName}. Digest=${response.digest}`
      );

      // we don't need to call withdraw settled amounts for this pool in the next iteration
      this.maybeWithdrawSettledAmounts.delete(poolName);
    } else {
      this.logger.error(
        `[${requestId}] Failed to insert order for pool=${poolName}. Digest=${response.digest}`
      );
    }

    let events = await this.processInsertResponse(response, order);

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: {
        status: status,
        tx_digest: response.digest,
        events: events,
      },
    };
  };

  processBulkInsertResponse = async (
    response: SuiTransactionBlockResponse,
    clientOrderIds: Array<ClientOrderId>
  ): Promise<Array<Event>> => {
    for (let clientOrderId of clientOrderIds) {
      let order = this.orderCache.get(clientOrderId);
      if (order) {
        order.status =
          response.effects!.status.status === "success" ? "Open" : "Finalised";
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
        if (event.type.endsWith("OrderInfo")) {
          let orderPlacedEvent = this.processOrderPlacedEvent(event);

          // TODO: maybe we don't need this
          let order = this.orderCache.get(orderPlacedEvent.client_order_id);
          if (order) {
            order.execQty = BigInt(orderPlacedEvent.exec_qty) as Quantity;
            order.remQty = BigInt(orderPlacedEvent.rem_qty) as Quantity;
            order.exchangeOrderId = orderPlacedEvent.exchange_order_id;
          }

          events.push(orderPlacedEvent);
        } else if (event.type.endsWith("OrderFilled")) {
          let orderFilledEvent = this.processOrderFilledEvent(event);
          events.push(orderFilledEvent);
        } else if (event.type.includes("OrderCanceled")) {
          // Can receive cancel event in order insert response due to STP
          let orderCancelledEvent = this.processOrderCancelledEvent(event);

          let order = this.orderCache.get(orderCancelledEvent.client_order_id);
          if (order) {
            order.status = "Cancelled";
            this.orderCache.delete(orderCancelledEvent.client_order_id);
          }

          events.push(orderCancelledEvent);
        }
      }
    }

    return events;
  };

  parseBulkInsertRequest = (request: any, poolId: PoolId): Array<Order> => {
    let result = new Array<Order>();
    for (let order of request.orders) {
      const qty = BigInt(order.quantity);
      const price = BigInt(order.price);

      result.push({
        clientOrderId: order.client_order_id as ClientOrderId,
        status: "PendingInsert",
        poolId: poolId,
        qty: qty as Quantity,
        remQty: qty as Quantity,
        execQty: 0n as Quantity,
        price: price as Price,
        type: order.order_type,
        side: order.side,
        expirationTs: ORDER_MAX_EXPIRE_TIMESTAMP_MS as TimestampMs,

        txDigests: new Array<TxDigest>(),
        exchangeOrderId: null,
      });
    }

    return result;
  };

  insertOrders = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.BulkInsertRequest);

    // Will be same for all orders as all are on same pool
    const poolName: string = params.pool;
    const pool: Pool = this.getPool(poolName);

    let orders = this.parseBulkInsertRequest(params, pool.address as PoolId);
    let clientOrderIds = new Array<ClientOrderId>();
    for (let order of orders) {
      this.orderCache.add(order.clientOrderId, order);
      clientOrderIds.push(order.clientOrderId);
    }

    const baseCoinTypeId: string = this.getCoin(pool.baseCoin).type;
    const quoteCoinTypeId: string = this.getCoin(pool.quoteCoin).type;

    let response = null;
    try {
      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Inserting orders. params=${JSON.stringify(params)}`
        );

        const selfMatchingPrevention: number = 2; // CANCEL_MAKER
        let tx = new Transaction();

        for (let order of orders) {
          let orderType = DeepBookV3.parseOrderType(order.type);
          let tradeProof = tx.moveCall({
            target: `${this.deepbookPackageId}::balance_manager::generate_proof_as_owner`,
            arguments: [tx.object(this.balanceManagerId)],
          });

          tx.moveCall({
            target: `${this.deepbookPackageId}::pool::place_limit_order`,
            arguments: [
              tx.object(order.poolId),
              tx.object(this.balanceManagerId),
              tradeProof,
              tx.pure.u64(order.clientOrderId),
              tx.pure.u8(orderType),
              tx.pure.u8(selfMatchingPrevention),
              tx.pure.u64(order.price),
              tx.pure.u64(order.qty),
              tx.pure.bool(order.side === "BUY"),
              tx.pure.bool(true),
              tx.pure.u64(order.expirationTs),
              tx.object(SUI_CLOCK_OBJECT_ID),
            ],
            typeArguments: [baseCoinTypeId, quoteCoinTypeId],
          });
        }

        return tx;
      };

      let txBlockResponseOptions = { showEffects: true, showEvents: true };

      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);

      if (error instanceof Error) {
        const parsedError = DeepBookV3.tryParseError(error.toString());
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
        this.logger.debug(`[${requestId}] Bulk insert response: ${dump}`);
      }
    }

    this.checkTransactionFailure(requestId, response);

    const status = response.effects!.status.status;
    if (status === "success") {
      this.logger.info(
        `[${requestId}] Bulk orders inserted for pool=${poolName}. Digest=${response.digest}`
      );

      // we don't need to call withdraw settled amounts for this pool in the next iteration
      this.maybeWithdrawSettledAmounts.delete(poolName);
    } else {
      this.logger.error(
        `[${requestId}] Failed to bulk insert orders for pool=${poolName}. Digest=${response.digest}`
      );
    }

    let events = await this.processBulkInsertResponse(response, clientOrderIds);

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: {
        status: response.effects!.status.status,
        tx_digest: response.digest,
        events: events,
      },
    };
  };

  processOrderCancelledEvent = (event: SuiEvent | any): OrderCancelledEvent => {
    let json = event.parsedJson ? (event.parsedJson as any) : event;

    // qty, qtyCancelled, execQty are the state after the order was inserted in the order book
    const qty = json.original_quantity;
    const qtyCancelled = json.base_asset_quantity_canceled;
    const execQty = BigInt(qty) - BigInt(qtyCancelled);
    const price = json.price as Price;
    const timestampMs = json.timestamp === undefined ? null : json.timestamp;

    return {
      event_type: "order_cancelled",
      pool_id: json.pool_id,
      client_order_id: json.client_order_id as ClientOrderId,
      exchange_order_id: json.order_id as ExchangeOrderId,
      side: (json.is_bid ? "BUY" : "SELL") as Side,
      qty: qty,
      exec_qty: execQty.toString(),
      price: price,
      timestamp_ms: timestampMs,
    };
  };

  processCancelResponse = (
    response: SuiTransactionBlockResponse,
    order: Order
  ): Array<OrderCancelledEvent> => {
    if (response.effects!.status.status === "success") {
      order.status = "Cancelled";
      this.orderCache.delete(order.clientOrderId);
    }
    order.txDigests.push(response.digest as TxDigest);

    let events = new Array<OrderCancelledEvent>();

    if (response.events) {
      for (let event of response.events as SuiEvent[]) {
        if (event.type.includes("OrderCanceled")) {
          let orderCancelledEvent = this.processOrderCancelledEvent(event);
          events.push(orderCancelledEvent);
        }
      }
    }

    return events;
  };

  cancelOrder = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.CancelRequest);

    const pool: string = params.get("pool");
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

    this.logger.debug(
      `[${requestId}] Calling cancelOrder with args: pool=${pool}, clientOrderId=${clientOrderId}, orderId=${order!
        .exchangeOrderId!}`
    );

    let response = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Cancelling order with exchangeOrderId=${order!
            .exchangeOrderId!}`
        );

        const tx = new Transaction();
        tx.add(
          client.deepBookClient.deepBook.cancelOrder(
            pool,
            "MANAGER",
            order!.exchangeOrderId!
          )
        );

        return tx;
      };

      let txBlockResponseOptions = { showEffects: true, showEvents: true };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);

      if (error instanceof Error) {
        const parsedError = DeepBookV3.tryParseError(error.toString());
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
      throw new ParsedOrderError("UNKNOWN", errorStr);
    } finally {
      if (this.log_responses) {
        const dump = JSON.stringify(response);
        this.logger.debug(`[${requestId}] Cancel response: ${dump}`);
      }
    }

    this.checkTransactionFailure(requestId, response);

    let events = this.processCancelResponse(response, order!);

    return {
      statusCode: response.effects!.status.status === "success" ? 200 : 400,
      payload: {
        status: response.effects!.status.status,
        tx_digest: response.digest,
        events: events,
      },
    };
  };

  processBulkCancelResponse = async (
    response: SuiTransactionBlockResponse
  ): Promise<Array<OrderCancelledEvent>> => {
    let events = new Array<OrderCancelledEvent>();

    if (response.events) {
      for (const event of response.events) {
        if (event.type.includes("OrderCanceled")) {
          let orderCancelledEvent = this.processOrderCancelledEvent(event);
          let order = this.orderCache.get(orderCancelledEvent.client_order_id);
          if (order === undefined) {
            this.logger.warn(
              `Cancelled unknown order[clOid:${orderCancelledEvent.client_order_id}, exOid:${orderCancelledEvent.exchange_order_id}]`
            );
          } else {
            order.status = "Cancelled";
            this.orderCache.delete(orderCancelledEvent.client_order_id);
          }

          events.push(orderCancelledEvent);
        }
      }
    }

    return events;
  };

  cancelOrders = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    if (params.get("client_order_ids") === null) {
      return await this.cancelAll(requestId, params);
    } else {
      return await this.bulkCancel(requestId, params);
    }
  };

  cancelAll = async (requestId: bigint, params: any): Promise<RestResult> => {
    assertFields(params, MandatoryFields.CancelAllRequest);

    const pool: string = params.get("pool");

    let response = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let txBlockGenerator = () => {
        this.logger.debug(`[${requestId}] Cancelling all orders. pool=${pool}`);

        const tx = new Transaction();
        tx.add(client.deepBookClient.deepBook.cancelAllOrders(pool, "MANAGER"));
        return tx;
      };

      let txBlockResponseOptions = {
        showEffects: true,
        showEvents: true,
        showObjectChanges: true,
      };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);

      if (error instanceof Error) {
        const parsedError = DeepBookV3.tryParseError(error.toString());
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
      throw new ParsedOrderError("UNKNOWN", errorStr);
    } finally {
      if (this.log_responses) {
        const dump = JSON.stringify(response);
        this.logger.debug(`[${requestId}] Cancel all response: ${dump}`);
      }
    }

    this.checkTransactionFailure(requestId, response);

    const status = response.effects!.status.status;
    if (status === "success") {
      this.logger.info(
        `[${requestId}] All orders canceled for pool=${pool}. Digest=${response.digest}`
      );
    } else {
      this.logger.error(
        `[${requestId}] Failed to cancel all orders for pool=${pool}. Digest=${response.digest}`
      );
    }

    let events = await this.processBulkCancelResponse(response);

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: {
        status: status,
        tx_digest: response.digest,
        events: events,
      },
    };
  };

  bulkCancel = async (requestId: bigint, params: any): Promise<RestResult> => {
    assertFields(params, MandatoryFields.BulkCancelRequest);

    const pool: string = params.get("pool");
    const clientOrderIds: Array<string> = params
      .get("client_order_ids")
      .split(",");
    const exchangeOrderIds: Array<string> = new Array<string>();

    for (let clientOrderId of clientOrderIds) {
      let order = this.orderCache.get(clientOrderId as ClientOrderId);
      if (order === undefined) {
        this.logger.warn(
          `[${requestId}] Cannot cancel: client_order_id: ${clientOrderId} does not exist`
        );
      } else if (order.exchangeOrderId === null) {
        this.logger.warn(
          `[${requestId}] Cannot cancel: exchange_order_id does not exist for client_order_id: ${clientOrderId}`
        );
      } else {
        exchangeOrderIds.push(order.exchangeOrderId);
      }
    }

    if (exchangeOrderIds.length == 0) {
      throw new Error("No orders to cancel");
    }

    let response = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Cancelling orders. Pool=${pool} exchangeOrderIds=${exchangeOrderIds}`
        );

        const tx = new Transaction();
        for (let exchangeOrderId of exchangeOrderIds) {
          tx.add(
            client.deepBookClient.deepBook.cancelOrder(
              pool,
              "MANAGER",
              exchangeOrderId
            )
          );
        }

        return tx;
      };

      let txBlockResponseOptions = { showEffects: true, showEvents: true };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}]: ${error}`);

      if (error instanceof Error) {
        const parsedError = DeepBookV3.tryParseError(error.toString());
        if (parsedError.type && parsedError.txNumber !== null) {
          this.logger.error(`[${requestId}] ${parsedError.type}`);
          throw new ParsedOrderError(
            parsedError.type,
            `exchangeOrderIds: ${exchangeOrderIds[parsedError.txNumber]}`
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
      throw new ParsedOrderError("UNKNOWN", errorStr);
    } finally {
      if (this.log_responses) {
        const dump = JSON.stringify(response);
        this.logger.debug(`[${requestId}] Bulk cancel response: ${dump}`);
      }
    }

    this.checkTransactionFailure(requestId, response);

    const status = response.effects!.status.status;
    if (status === "success") {
      this.logger.info(
        `[${requestId}] Bulk orders canceled for pool=${pool}. Digest=${response.digest}`
      );
    } else {
      this.logger.error(
        `[${requestId}] Failed to bulk cancel orders for pool=${pool}. Digest=${response.digest}`
      );
    }

    let events = await this.processBulkCancelResponse(response);

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: {
        status: response.effects!.status.status,
        tx_digest: response.digest,
        events: events,
      },
    };
  };

  getTrades = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    let client = this.clientPool.getClient();
    this.logger.debug(`[${requestId}] using ${client.name} client`);

    if (params.get("tx_digests_list") !== null) {
      return await this.getTradesByDigest(
        requestId,
        client.suiClient,
        path,
        params,
        receivedAtMs
      );
    } else {
      return await this.getTradesByTime(
        requestId,
        client.suiClient,
        path,
        params,
        receivedAtMs
      );
    }
  };

  getTradesByTimeImpl = async (
    requestId: bigint,
    suiClient: SuiClient,
    queryParams: QueryEventsParams,
    requestedStartTs: number
  ) => {
    let response = null;
    try {
      response = (await suiClient.queryEvents(queryParams)) as PaginatedEvents;
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
      if (event.type.endsWith("OrderFilled")) {
        if (
          parsedJson.maker_balance_manager_id === this.balanceManagerId ||
          parsedJson.taker_balance_manager_id === this.balanceManagerId
        ) {
          orderFilledEvents.push(this.processOrderFilledEvent(event));
        }
      }
    }

    if (startTs !== null && startTs < requestedStartTs) {
      hasNextPage = false;
      nextCursor = null;
    } else if (response.hasNextPage && response.nextCursor) {
      hasNextPage = response.hasNextPage;
      nextCursor = {
        tx_digest: response.nextCursor.txDigest,
        event_seq: response.nextCursor.eventSeq,
      };
    }

    return {
      hasNextPage: hasNextPage,
      nextCursor: nextCursor,
      orderFilledEvents: orderFilledEvents,
      startTs: startTs,
    };
  };

  getTradesByTime = async (
    requestId: bigint,
    suiClient: SuiClient,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.TradesByTimeRequest);

    const startTs = Number(params.get("start_ts"));
    const maxPages = Number(params.get("max_pages"));
    const txDigest = params.get("tx_digest");
    const eventSeq = params.get("event_seq");

    let cursor: EventId | null = null;
    if (txDigest && eventSeq) {
      cursor = {
        txDigest: txDigest,
        eventSeq: eventSeq,
      };
    }

    this.logger.debug(
      `[${requestId}] Fetching trades by time. start_ts=${startTs} max_pages=${maxPages} cursor=${JSON.stringify(
        cursor
      )}`
    );

    const now = Date.now();
    const fortyMinutesInMs = 40 * 60 * 1000;
    if (now - startTs > fortyMinutesInMs) {
      let error =
        "Can't query for trades more than 40 minutes in the past. Please update the field, `startTs` in the request";
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
              path: "/maker_balance_manager_id",
              value: this.balanceManagerId
            }
      */

      MoveEventType: `${this.deepbookPackageId}::order_info::OrderFilled`,
    };

    let queryParams: QueryEventsParams = {
      query: query,
      cursor: cursor,
      limit: limit,
      order: "descending",
    };

    let response = await this.getTradesByTimeImpl(
      requestId,
      suiClient,
      queryParams,
      startTs
    );
    let pagesQueried = 1;
    while (
      response.orderFilledEvents.length === 0 &&
      response.hasNextPage &&
      pagesQueried < maxPages
    ) {
      queryParams.cursor = {
        txDigest: response.nextCursor!.tx_digest,
        eventSeq: response.nextCursor!.event_seq,
      };
      response = await this.getTradesByTimeImpl(
        requestId,
        suiClient,
        queryParams,
        startTs
      );
      ++pagesQueried;
    }

    this.logger.debug(
      `[${requestId}] Fetched ${
        response.orderFilledEvents.length
      } trades by time. start_ts=${startTs} max_pages=${maxPages} cursor=${JSON.stringify(
        cursor
      )}`
    );

    return {
      statusCode: 200,
      payload: {
        has_next_page: response.hasNextPage,
        next_cursor: response.nextCursor,
        data: response.orderFilledEvents,
        start_ts: response.startTs,
      },
    };
  };

  getTradesByDigestImpl = async (
    requestId: bigint,
    suiClient: SuiClient,
    queryParams: QueryEventsParams
  ) => {
    let response = null;
    try {
      response = (await suiClient.queryEvents(queryParams)) as PaginatedEvents;
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    let orderFilledEvents = new Array<OrderFilledEvent>();
    for (let event of response.data) {
      let parsedJson = event.parsedJson as any;
      if (event.type.endsWith("OrderFilled")) {
        if (
          parsedJson.maker_balance_manager_id === this.balanceManagerId ||
          parsedJson.taker_balance_manager_id === this.balanceManagerId
        ) {
          orderFilledEvents.push(this.processOrderFilledEvent(event));
        }
      }
    }

    return {
      hasNextPage: response.hasNextPage,
      nextCursor: response.nextCursor,
      orderFilledEvents: orderFilledEvents,
    };
  };

  getTradesByDigest = async (
    requestId: bigint,
    suiClient: SuiClient,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.TradesByDigestRequest);

    this.logger.debug(`[${requestId}] Fetching trades by digest`);

    const txDigestsList: Array<string> = params
      .get("tx_digests_list")
      .split(",");

    let orderFilledEvents = new Array<OrderFilledEvent>();

    for (let txDigest of txDigestsList) {
      this.logger.debug(`Querying trades for tx_digest=${txDigest}`);

      let queryParams: QueryEventsParams = {
        query: { Transaction: txDigest },
        cursor: null,
        limit: 50,
        order: "descending",
      };

      let response = await this.getTradesByDigestImpl(
        requestId,
        suiClient,
        queryParams
      );
      for (let event of response.orderFilledEvents) {
        orderFilledEvents.push(event);
      }

      // Handle pagination
      while (response.hasNextPage) {
        queryParams.cursor = {
          txDigest: response.nextCursor!.txDigest,
          eventSeq: response.nextCursor!.eventSeq,
        };
        response = await this.getTradesByDigestImpl(
          requestId,
          suiClient,
          queryParams
        );
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
      },
    };
  };

  canWithdraw = (coinTypeId: string, withdrawalAddress: string): boolean => {
    let configuredAddresses = this.withdrawalAddresses.get(coinTypeId);
    if (configuredAddresses === undefined) {
      this.logger.error(
        `No entry for coin=${coinTypeId} in the withdrawal addresses file`
      );
      return false;
    }

    return configuredAddresses.has(withdrawalAddress);
  };

  withdrawSui = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    this.logger.debug(
      `[${requestId}] Handling withdrawSui request. params=${JSON.stringify(
        params
      )}`
    );

    assertFields(params, MandatoryFields.SuiWithdrawalRequest);

    const recipient: string = params["recipient"];
    const quantity: number = Number(params["quantity"]);

    const coinTypeId =
      "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI";
    if (!this.canWithdraw(coinTypeId, recipient)) {
      const msg = `Cannot withdraw coin=${coinTypeId} to address=${recipient}. Please check the valid_addresses file`;
      this.logger.error(`Alert: ${msg}`);
      throw new Error(msg);
    }

    let client = this.clientPool.getClient();
    this.logger.debug(`[${requestId}] using ${client.name} client`);

    let response = null;
    let status: string | undefined = undefined;
    let mainGasCoin = null;
    try {
      mainGasCoin = await this.gasManager!.getMainGasCoin(client.suiClient);
      if (mainGasCoin === null) {
        throw new Error(
          "The mainGasCoin is being used in a concurrent transaction. Please retry"
        );
      }

      await this.gasManager!.mergeUntrackedGasCoinsInto(mainGasCoin, client.suiClient);
      if (mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
        throw new Error(
          "Unable to update the version of the mainGasCoin after merging untracked gasCoins into it. Please retry this request"
        );
      }

      const block = new SuiTxBlock();
      block.txBlock.setGasPayment([mainGasCoin]);
      const transaction = block.transferSui(
        recipient,
        BigInt(quantity * FLOAT_SCALING_FACTOR)
      );

      response = await client.suiClient.signAndExecuteTransaction({
        signer: this.keyPair!,
        transaction: transaction,
        options: {
          showEffects: true,
          showEvents: true,
          showBalanceChanges: true,
          showObjectChanges: true,
        },
      });

      const digest = response["digest"];

      status = response?.effects?.status.status;

      if (status === "success") {
        this.logger.info(
          `Successfully withdrawn ${quantity} SUI. Digest ${digest}`
        );
      } else {
        this.logger.error(
          `Failed to withdraw ${quantity} SUI. Digest ${digest}`
        );
      }
    } finally {
      if (mainGasCoin) {
        let gasCoinVersionUpdated = false;
        if (response) {
          // TODO maybe balance won't be updated properly
          gasCoinVersionUpdated = this.executor!.tryUpdateGasCoinVersion(
            requestId,
            response,
            mainGasCoin
          );
        }
        if (!gasCoinVersionUpdated) {
          gasCoinVersionUpdated =
            await this.gasManager!.tryUpdateGasCoinVersion(
              mainGasCoin,
              client.suiClient
            );
        }

        if (gasCoinVersionUpdated) {
          mainGasCoin.status = GasCoinStatus.Free;
        } else {
          mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
        }
      }
    }

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: response,
    };
  };

  withdraw = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    this.logger.debug(
      `[${requestId}] Handling withdraw request. params=${JSON.stringify(
        params
      )}`
    );

    assertFields(params, MandatoryFields.WithdrawalRequest);

    const coinTypeId: string = params["coin_type_id"];
    const recipient: string = params["recipient"];
    const quantity: number = Number(params["quantity"]);

    if (coinTypeId.endsWith("SUI")) {
      const msg = `Cannot withdraw SUI from this endpoint`;
      this.logger.error(msg);
      throw new Error(msg);
    }

    if (!this.canWithdraw(coinTypeId, recipient)) {
      const msg = `Cannot withdraw coin=${coinTypeId} to address=${recipient}. Please check the valid_addresses file`;
      this.logger.error(`Alert: ${msg}`);
      throw new Error(msg);
    }

    let client = this.clientPool.getClient();
    this.logger.debug(`[${requestId}] using ${client.name} client`);

    const decimals = await this.getCoinDecimals(client.suiClient, coinTypeId);

    const nativeAmount = BigInt(quantity * 10 ** decimals);

    this.logger.info(
      `[${requestId}] Withdrawing coin ${coinTypeId}. Amount: ${nativeAmount} (${quantity})`
    );

    const coinInstances: Array<string> = await this.getCoinInstances(
      requestId,
      client.suiClient,
      coinTypeId
    );

    let response = null;
    let status: string | undefined = undefined;
    try {
      let txBlockGenerator = () => {
        const block = new SuiTxBlock();
        const tx: Transaction = block.transferCoin(
          coinInstances,
          this.walletAddress,
          recipient,
          nativeAmount
        );

        return tx;
      };

      let txBlockResponseOptions = {
        showEffects: true,
        showEvents: true,
        showBalanceChanges: true,
        showObjectChanges: true,
      };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );

      const digest = response["digest"];
      status = response?.effects?.status.status;

      if (status === "success") {
        this.logger.info(
          `Successfully withdrawn ${quantity} ${coinTypeId}. Digest ${digest}`
        );
      } else {
        this.logger.error(
          `Failed to withdraw ${quantity} ${coinTypeId}. Digest ${digest}`
        );
      }
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: response,
    };
  };

  getObjectInfo = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.ObjectInfoRequest);

    const objectId = params.get("id");
    this.logger.debug(`[${requestId}] Querying object with id=${objectId}`);

    let objectInfo = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      objectInfo = await client.suiClient.getObject({
        id: objectId,
        options: { showContent: true, showOwner: true, showType: true },
      });
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    return {
      statusCode: 200,
      payload: objectInfo,
    };
  };

  getPoolInfo = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.PoolInfoRequest);

    // example pool = SUI_DBUSDC
    const pool: string = params.get("pool");
    this.logger.debug(`[${requestId}] Querying pool with pool=${pool}`);

    let response = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      const [poolInfo, whitelisted, poolParamsInfo] = await Promise.all([
        client.deepBookClient.poolTradeParams(pool),
        client.deepBookClient.whitelisted(pool),
        client.deepBookClient.poolBookParams(pool),
      ]);

      response = {
        takerFee: poolInfo.takerFee,
        makerFee: poolInfo.makerFee,
        stakeRequired: poolInfo.stakeRequired,
        whitelisted: whitelisted,
        tickSize: poolParamsInfo.tickSize,
        lotSize: poolParamsInfo.lotSize,
        minSize: poolParamsInfo.minSize,
      };
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    } finally {
      if (this.log_responses) {
        const dump = JSON.stringify(response);
        this.logger.debug(`[${requestId}] Pool info: ${dump}`);
      }
    }

    return {
      statusCode: 200,
      payload: response,
    };
  };

  getWalletBalanceInfo = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    this.logger.debug(`[${requestId}] Querying wallet balance`);
    let balanceInfo = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      balanceInfo = await client.suiClient.getAllBalances({
        owner: this.walletAddress,
      });
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    return {
      statusCode: 200,
      payload: balanceInfo,
    };
  };

  getBalanceManagerBalanceInfo = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.BalanceManagerFundsRequest);

    const coin: string = params.get("coin");

    this.logger.debug(
      `[${requestId}] Querying balance manager fund for coin=${coin} balanceManagerId=${this.balanceManagerId}`
    );

    let posInfo = null;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let response = await client.deepBookClient.checkManagerBalance(
        "MANAGER",
        coin
      );

      posInfo = {
        coinType: response.coinType,
        availableBalance: response.balance,
        lockedBalance: 0,
      };

      let tasks = [];
      for (let poolName in this.poolsMap) {
        let pool: Pool = this.poolsMap[poolName];
        if (
          coin === "DEEP" ||
          coin === pool.baseCoin ||
          coin === pool.quoteCoin
        ) {
          tasks.push(
            this.getCoinLockedAmount(
              requestId,
              client.suiClient,
              coin,
              poolName,
              pool
            )
          );
        }
      }

      (await Promise.all(tasks)).forEach((value) => {
        posInfo!.lockedBalance += value;
      });
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    } finally {
      if (this.log_responses) {
        this.logger.debug(
          `[${requestId}] getBalanceManagerBalanceInfo coin=${coin} response: ${JSON.stringify(
            posInfo
          )}`
        );
      }
    }

    return {
      statusCode: 200,
      payload: posInfo,
    };
  };

  getCoinLockedAmount = async (
    requestId: bigint,
    suiClient: SuiClient,
    coin: string,
    poolName: string,
    pool: Pool
  ): Promise<number> => {
    let lockedBalance: number = 0;

    let response = await this.getLockedBalance(
      requestId,
      suiClient,
      poolName,
      pool
    );
    if (response) {
      const baseCoin = this.getCoin(pool.baseCoin);
      const quoteCoin = this.getCoin(pool.quoteCoin);
      const deep = this.getCoin("DEEP");
      if (coin === pool.baseCoin) {
        lockedBalance += Number(
          (Number(response.base) / baseCoin.scalar).toFixed(9)
        );
      } else if (coin === pool.quoteCoin) {
        lockedBalance += Number(
          (Number(response.quote) / quoteCoin.scalar).toFixed(9)
        );
      }

      if (coin === "DEEP") {
        lockedBalance += Number(
          (Number(response.deep) / deep.scalar).toFixed(9)
        );
      }
    }

    this.logger.debug(
      `[${requestId}] Locked balance for ${coin} in ${poolName} is ${lockedBalance}.`
    );
    return lockedBalance;
  };

  getLockedBalance = async (
    requestId: bigint,
    suiClient: SuiClient,
    poolName: string,
    pool: Pool
  ): Promise<{
    base: bigint;
    quote: bigint;
    deep: bigint;
  } | null> => {
    const baseCoin = this.getCoin(pool.baseCoin);
    const quoteCoin = this.getCoin(pool.quoteCoin);

    const tx = new Transaction();
    tx.moveCall({
      target: `${this.deepbookPackageId}::pool::locked_balance`,
      arguments: [tx.object(pool.address), tx.object(this.balanceManagerId)],
      typeArguments: [baseCoin.type, quoteCoin.type],
    });

    let response = await suiClient.devInspectTransactionBlock({
      sender: normalizeSuiAddress(this.walletAddress),
      transactionBlock: tx,
    });

    if (response.effects!.status.status === "success") {
      let result = {
        base: BigInt(
          bcs.U64.parse(
            new Uint8Array(response.results![0].returnValues![0][0])
          )
        ),
        quote: BigInt(
          bcs.U64.parse(
            new Uint8Array(response.results![0].returnValues![1][0])
          )
        ),
        deep: BigInt(
          bcs.U64.parse(
            new Uint8Array(response.results![0].returnValues![2][0])
          )
        ),
      };

      this.logger.debug(
        `[${requestId}] Successfully got locked balance for ${poolName}. Result = ${JSON.stringify(
          result,
          (_, value) => (typeof value === "bigint" ? value.toString() : value)
        )}`
      );

      return result;
    } else {
      const error = response.effects!.status.error!;
      let parsedError = DeepBookV3.tryParseError(error.toString());
      if (parsedError.type && parsedError.type === "UNUSED_POOL") {
        this.logger.debug(
          `[${requestId}] ${poolName} is not traded yet by us, thus no locked balance`
        );

        return null;
      } else {
        let msg = `Failed to get locked balance for ${poolName}. Error=${error.toString()}`;
        this.logger.error(`[${requestId}] ${msg}.`);

        throw new Error(msg);
      }
    }
  };

  depositIntoBalanceManager = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.DepositIntoBalanceManagerRequest);

    const coin: string = params.coin;
    const quantity: number = Number(params.quantity);

    if (coin === "SUI") {
      return await this.depositSuiIntoBalanceManager(requestId, quantity);
    }

    let response = null;
    let status: string | undefined = undefined;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Depositing into balance_manager_id=${this.balanceManagerId}: coin=${coin}, quantity=${quantity} `
        );

        const tx = new Transaction();
        tx.add(
          client.deepBookClient.balanceManager.depositIntoManager(
            "MANAGER",
            coin,
            quantity
          )
        );

        return tx;
      };

      let txBlockResponseOptions = {
        showEffects: true,
        showEvents: true,
        showBalanceChanges: true,
        showObjectChanges: true,
      };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    const digest = response["digest"];

    status = response?.effects?.status.status;

    if (status === "success") {
      this.logger.info(
        `[${requestId}] Successfully deposited ${quantity} ${coin} into balance manager ${this.balanceManagerId}. Digest=${digest}`
      );
    } else {
      this.logger.error(
        `[${requestId}] Failed to deposit ${quantity} ${coin} into balance manager ${this.balanceManagerId}. Digest=${digest}`
      );
    }

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: response,
    };
  };

  depositSuiIntoBalanceManager = async (
    requestId: bigint,
    quantity: number
  ): Promise<RestResult> => {
    this.logger.debug(
      `[${requestId}] Depositing SUI into balance_manager_id=${this.balanceManagerId}: quantity=${quantity} `
    );
    let client = this.clientPool.getClient();
    this.logger.debug(`[${requestId}] using ${client.name} client`);

    let mainGasCoin = null;
    let response = null;
    let status: string | undefined = undefined;
    try {
      mainGasCoin = await this.gasManager!.getMainGasCoin(client.suiClient);

      if (mainGasCoin === null) {
        throw new Error(
          "The mainGasCoin is being used in a concurrent transaction. Please retry"
        );
      }

      await this.gasManager!.mergeUntrackedGasCoinsInto(mainGasCoin, client.suiClient);
      if (mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
        throw new Error(
          "Unable to update the version of the mainGasCoin after merging untracked gasCoins into it. Please retry this request"
        );
      }

      const tx = new Transaction();
      tx.add(
        client.deepBookClient.balanceManager.depositIntoManager(
          "MANAGER",
          "SUI",
          quantity
        )
      );
      tx.setGasPayment([mainGasCoin]);

      response = await client.suiClient.signAndExecuteTransaction({
        signer: this.keyPair!,
        transaction: tx,
        options: {
          showEffects: true,
          showEvents: true,
          showBalanceChanges: true,
          showObjectChanges: true,
        },
      });

      const digest = response["digest"];

      status = response?.effects?.status.status;

      if (status === "success") {
        this.logger.info(
          `[${requestId}] Successfully deposited ${quantity} SUI into balance manager ${this.balanceManagerId}. Digest=${digest}`
        );
      } else {
        this.logger.error(
          `[${requestId}] Failed to deposit ${quantity} SUI into balance manager ${this.balanceManagerId}. Digest=${digest}`
        );
      }
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    } finally {
      if (mainGasCoin) {
        let gasCoinVersionUpdated = false;
        if (response) {
          // TODO maybe balance won't be updated properly
          gasCoinVersionUpdated = this.executor!.tryUpdateGasCoinVersion(
            requestId,
            response,
            mainGasCoin
          );
        }
        if (!gasCoinVersionUpdated) {
          gasCoinVersionUpdated =
            await this.gasManager!.tryUpdateGasCoinVersion(
              mainGasCoin,
              client.suiClient
            );
        }

        if (gasCoinVersionUpdated) {
          mainGasCoin.status = GasCoinStatus.Free;
        } else {
          mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
        }
      }
    }

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: response,
    };
  };

  withdrawFromBalanceManager = async (
    requestId: bigint,
    path: string,
    params: any,
    receivedAtMs: number
  ): Promise<RestResult> => {
    assertFields(params, MandatoryFields.WithdrawFromBalanceManagerRequest);

    const coin: string = params.coin;
    const quantity: number = Number(params.quantity);

    let response = null;
    let status: string | undefined = undefined;
    try {
      let client = this.clientPool.getClient();
      this.logger.debug(`[${requestId}] using ${client.name} client`);

      let txBlockGenerator = () => {
        this.logger.debug(
          `[${requestId}] Withdrawing from balance_manager_id=${this.balanceManagerId}: coin=${coin}, quantity=${quantity}`
        );

        const tx = new Transaction();
        tx.add(
          client.deepBookClient.balanceManager.withdrawFromManager(
            "MANAGER",
            coin,
            quantity,
            this.walletAddress
          )
        );

        return tx;
      };

      let txBlockResponseOptions = {
        showEffects: true,
        showEvents: true,
        showBalanceChanges: true,
        showObjectChanges: true,
      };

      response = await this.executor!.execute(
        requestId,
        client.suiClient,
        txBlockGenerator,
        txBlockResponseOptions
      );
    } catch (error) {
      this.logger.error(`[${requestId}] ${error}`);
      throw error;
    }

    const digest = response["digest"];

    status = response?.effects?.status.status;

    if (status === "success") {
      this.logger.info(
        `Successfully withdrawn ${quantity} ${coin} from balance manager ${this.balanceManagerId}. Digest=${digest}`
      );
    } else {
      this.logger.error(
        `Failed to withdraw ${quantity} ${coin} from balance manager ${this.balanceManagerId}. Digest=${digest}`
      );
    }

    return {
      statusCode: status === "success" ? 200 : 400,
      payload: response,
    };
  };

  getCoinInstances = async (
    requestId: bigint,
    suiClient: SuiClient,
    coinTypeId: string
  ): Promise<Array<string>> => {
    this.logger.info(`[${requestId}] Getting instances of ${coinTypeId}`);

    const response = await suiClient.getCoins({
      owner: this.walletAddress,
      coinType: coinTypeId,
    });

    let instancesOfType: Array<string> = new Array<string>();

    for (let val of response.data) {
      instancesOfType.push(val.coinObjectId);
    }

    this.logger.info(
      `Found ${instancesOfType.length} instances of ${coinTypeId}`
    );

    return instancesOfType;
  };

  getCoinDecimals = async (
    suiClient: SuiClient,
    coinTypeId: string
  ): Promise<number> => {
    const response = await suiClient.getCoinMetadata({
      coinType: coinTypeId,
    });

    if (response) {
      return response.decimals;
    } else {
      throw new Error("Could not find decimals for coin " + coinTypeId);
    }
  };

  getCoinTypeAddress(coinTypeId: string): string {
    const parts = coinTypeId.split("::");
    if (parts.length != 3) {
      throw new Error('coinTypeId should be in the format "0x123::coin::COIN"');
    }

    return parts[0];
  }

  getCoin(coinName: string): Coin {
    const coin = this.coinsMap[coinName];
    if (coin === undefined) {
      throw new Error(`Coin ${coinName} not added in dex-proxy resources file`);
    }

    return coin;
  }

  getPool(poolName: string): Pool {
    const pool = this.poolsMap[poolName];
    if (pool === undefined) {
      throw new Error(`Pool ${poolName} not added in dex-proxy resources file`);
    }

    return pool;
  }

  parsePrice(exchangeOrderId: ExchangeOrderId): Price {
    // ExchangeOrderId is moduled as following in deepbook:
    // 128-bits unsigned int
    // first bit (from left) is 0 for bid, 1 for ask
    // next 63 bits are price
    // last 64 bits are some internal Id of deepbook

    let exchOrderIdAsInt = BigInt(exchangeOrderId);
    let price = exchOrderIdAsInt >> BigInt(64);
    price = price & ((BigInt(1) << BigInt(63)) - 1n);

    return price as Price;
  }

  parseSide(exchangeOrderId: ExchangeOrderId): Side {
    // ExchangeOrderId is moduled as following in deepbook:
    // 128-bits unsigned int
    // first bit (from left) is 0 for bid, 1 for ask
    // next 63 bits are price
    // last 64 bits are some internal Id of deepbook

    let exchOrderIdAsInt = BigInt(exchangeOrderId);
    let is_bid = exchOrderIdAsInt >> BigInt(127) == BigInt(0);

    return is_bid == true ? "BUY" : "SELL";
  }
}
