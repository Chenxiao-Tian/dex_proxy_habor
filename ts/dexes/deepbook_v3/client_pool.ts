import { LoggerFactory } from "../../logger.js";
import type { Client, NetworkType } from "./types.js";
import {
  Coin,
  DeepBookClient,
  Pool,
  BalanceManager,
} from "@mysten/deepbook-v3";
import { SuiClient, SuiHTTPTransport } from "@mysten/sui/client";
import { Logger } from "winston";
import { WebSocket } from "ws";

export class ClientPool {
  private logger: Logger;
  private clients: Array<Client>;
  private clientIdxToUse: number = 0;

  // not setting as default 0 to avoid conflicts
  private internalClientIdxToUse: number = -1;

  private trackLeadingClientPollIntervalMs: number;
  private latestSequenceNumberFound: bigint = BigInt(0);

  // a separate variable to avoid conflict with existing functionality
  private latestInternalNodeSequenceNumberFound: bigint = BigInt(0);

  constructor(
    lf: LoggerFactory,
    config: any,
    supportedBalanceManagers: Array<string>,
    walletAddress: string,
    environment: NetworkType,
    coinsMap: Record<string, Coin>,
    poolsMap: Record<string, Pool>
  ) {
    this.logger = lf.createLogger("clients_pool");

    let balanceManagersConfig: {
      [key: string]: BalanceManager;
    } = {};

    if (supportedBalanceManagers) {
      for (let balanceManager of supportedBalanceManagers) {
        balanceManagersConfig[balanceManager] = {
          address: balanceManager,
          tradeCap: "",
        };
      }
    }

    this.clients = new Array();
    let connectors = this.parseExchangeConnectorConfig(config);

    for (let restConfig of connectors.rest) {
      this.logger.info(
        `RPC node rest api: name=${restConfig.name}, url=${restConfig.url}`
      );

      let suiClient = new SuiClient({
        transport: new SuiHTTPTransport({
          url: restConfig.url,
          rpc: {
            headers: restConfig.headers,
          },
          WebSocketConstructor: WebSocket as never,
          websocket: {
            url: connectors.ws.url,
            callTimeout: connectors.ws.callTimeoutMs,
            reconnectTimeout: connectors.ws.reconnectTimeoutMs,
            maxReconnects: connectors.ws.maxReconnects,
          },
        }),
      });

      let deepBookClient = new DeepBookClient({
        client: suiClient,
        address: walletAddress,
        env: environment,
        balanceManagers: balanceManagersConfig,
        coins: coinsMap,
        pools: poolsMap,
      });

      this.clients.push({
        name: restConfig.name,
        suiClient: suiClient,
        deepBookClient: deepBookClient,
      });
    }

    if (config.track_leading_client_poll_interval_s === undefined) {
      throw new Error("track_leading_client_poll_interval_s not set");
    }

    this.trackLeadingClientPollIntervalMs =
      config.track_leading_client_poll_interval_s * 1000;
  }

  start = async () => {
    await this.trackLeadingClient();
    setInterval(this.trackLeadingClient, this.trackLeadingClientPollIntervalMs);
  };

  trackLeadingClient = async () => {
    this.logger.debug("Tracking leading clients");

    let tasks = [];
    for (let idx = 0; idx < this.clients.length; idx++) {
      tasks.push(this.checkIfLeading(this.clients.at(idx)!, idx));
    }

    await Promise.allSettled(tasks);
  };

  checkIfLeading = async (client: Client, idx: number) => {
    try {
      let sequenceNumber = BigInt(
        await client.suiClient.getLatestCheckpointSequenceNumber()
      );
      this.logger.debug(`${client.name}: sequence_number: ${sequenceNumber}`);

      if (
        sequenceNumber > this.latestSequenceNumberFound ||
        // prefer internal_sui if same sequence number
        (sequenceNumber == this.latestSequenceNumberFound &&
          this.isInternalNode(client) &&
          !this.isInternalNode(this.clients.at(this.clientIdxToUse)!))
      ) {
        if (this.clientIdxToUse !== idx) {
          this.clientIdxToUse = idx;
          this.logger.debug(`${client.name} is leading now`);
        }
        this.latestSequenceNumberFound = sequenceNumber;
      }

      if (client.name.startsWith("internal_sui")) {
        if (sequenceNumber > this.latestInternalNodeSequenceNumberFound) {
          if (this.internalClientIdxToUse !== idx) {
            this.internalClientIdxToUse = idx;
            this.logger.debug(`${client.name} is leading internal node now`);
          }
          this.latestInternalNodeSequenceNumberFound = sequenceNumber;
        }
      }
    } catch (error) {
      this.logger.error(
        `${client.name} error while querying sequence number: ${error}`
      );
    }
  };

  getClient = (): Client => {
    return this.clients.at(this.clientIdxToUse)!;
  };

  getInternalClient = (): Client => {
    if (this.internalClientIdxToUse !== -1) {
      return this.clients.at(this.internalClientIdxToUse)!;
    } else {
      //fall back to default client if the functionality fails
      this.logger.warn(
        `Internal leading client not set, current value ${this.internalClientIdxToUse}, falling back to default client`
      );
      return this.clients.at(this.clientIdxToUse)!;
    }
  };

  parseExchangeConnectorConfig = (config: any): any => {
    if (config.exchange_connectors === undefined) {
      throw new Error(
        "The section, `dex.exchange_connectors` must be present in the config"
      );
    }

    let connectors = config.exchange_connectors;
    if (connectors.rest === undefined) {
      throw new Error(
        "The sections `dex.exchange_connectors.rest` must be present in the config"
      );
    }

    let parsedConfig = {
      rest: Array<{
        name: string;
        url: string;
        headers: Map<String, String>;
      }>(),
      ws: {},
    };

    for (let entry of connectors.rest) {
      const headers: Map<String, String> = entry.headers
        ? entry.headers
        : new Map<String, String>();

      parsedConfig.rest.push({
        name: entry.name,
        url: entry.url,
        headers: headers,
      });
    }

    if (connectors.ws) {
      const wsCallTimeoutMs =
        connectors.ws.call_timeout_s !== undefined
          ? connectors.ws.call_timeout_s * 1_000
          : 30_000;
      const wsReconnectTimeoutMs =
        connectors.ws.reconnect_timeout_s !== undefined
          ? connectors.ws.reconnect_timeout_s * 1_000
          : 3_000;
      const wsMaxReconnects =
        connectors.ws.max_reconnects !== undefined
          ? connectors.ws.max_reconnects
          : 5;

      parsedConfig.ws = {
        url: connectors.ws.url,
        callTimeoutMs: wsCallTimeoutMs,
        reconnectTimeoutMs: wsReconnectTimeoutMs,
        maxReconnects: wsMaxReconnects,
      };
    }

    return parsedConfig;
  };

  isInternalNode = (client: Client) => {
    return client.name.startsWith("internal_sui");
  };
}
