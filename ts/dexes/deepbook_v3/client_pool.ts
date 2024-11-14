import { LoggerFactory } from "../../logger.js";
import type { NetworkType } from "./types.js";
import { Coin, DeepBookClient, Pool } from "@mysten/deepbook-v3";
import { SuiClient, SuiHTTPTransport } from "@mysten/sui/client";
import { Logger } from "winston";
import { WebSocket } from "ws";

export class ClientPool {
  private logger: Logger;
  private clients: Array<{
    name: string;
    suiClient: SuiClient;
    deepBookClient: DeepBookClient;
  }>;
  private clientIdxToUse: number = 0;
  private trackLeadingClientPollIntervalMs: number;
  private latestSequenceNumberFound: bigint = BigInt(0);

  constructor(
    lf: LoggerFactory,
    config: any,
    balanceManagerId: string,
    walletAddress: string,
    environment: NetworkType,
    coinsMap: Record<string, Coin>,
    poolsMap: Record<string, Pool>
  ) {
    this.logger = lf.createLogger("clients_pool");

    let balanceManager = undefined;
    if (balanceManagerId) {
      balanceManager = {
        MANAGER: {
          address: balanceManagerId,
          tradeCap: "",
        },
      };
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
        balanceManagers: balanceManager,
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
    let idx = -1;
    for (let client of this.clients) {
      try {
        idx++;
        let sequenceNumber = BigInt(
          await client.suiClient.getLatestCheckpointSequenceNumber()
        );
        this.logger.debug(
          `${client.name}: sequence_number: ${sequenceNumber}`
        );

        if (sequenceNumber > this.latestSequenceNumberFound) {
          if (this.clientIdxToUse !== idx) {
            this.clientIdxToUse = idx;
            this.logger.debug(`${client.name} is leading now`);
          }
          this.latestSequenceNumberFound = sequenceNumber;
        }
      } catch (error) {
        this.logger.error(
          `${client.name} error while querying sequence number: ${error}`
        );
      }
    }
  };

  getClient = (): { name: string; suiClient: SuiClient, deepBookClient: DeepBookClient } => {
    return this.clients.at(this.clientIdxToUse)!;
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
}
