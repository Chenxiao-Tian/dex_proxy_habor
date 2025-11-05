import winston from "winston";
import { LoggerFactory } from "./logger";


export type OrderState         = "Unknown" |
                                 "PendingInsert" |
                                 "Open" |
                                 "PendingCancel" |
                                 "Cancelled" |
                                 "Finalised";

export type OrderType          = "GTC" | "IOC";
export type Side               = "BUY" | "SELL";
export type LiquidityIndicator = "Taker" | "Maker"

export type ClientOrderId   = string & {__brand: "ClientOrderId"};
export type ExchangeOrderId = string & {__brand: "ExchangeOrderId"};
export type ExchangeTradeId = string & {__brand: "ExchangeTradeId"};
export type PoolId          = string & {__brand: "PoolId"};
export type Quantity        = bigint & {__brand: "Quantity"};
export type Price           = bigint & {__brand: "Price"};
export type TxDigest        = string & {__brand: "TxDigest"};
export type TimestampMs     = number & {__brand: "TimestampMs"};

export type Order = {
    readonly clientOrderId: ClientOrderId;
    status: OrderState;

    readonly poolId: PoolId;
    qty: Quantity;
    remQty: Quantity;
    execQty: Quantity;
    price: Price;
    readonly type: OrderType | null;
    readonly side: Side;
    expirationTs: TimestampMs;

    txDigests: Array<TxDigest>;

    exchangeOrderId: ExchangeOrderId | null;
};

export interface OrderStatus {
    client_order_id: ClientOrderId;
    exchange_order_id: ExchangeOrderId | null;
    status: OrderState;
    side: Side;
    qty: string;
    rem_qty: string;
    exec_qty: string;
    price: string;
    expiration_ts: string;
};

export type EventType = "order_placed" |
                        "order_cancelled" |
                        "all_orders_cancelled" |
                        "order_filled";

export interface Event {
    readonly timestamp_ms : string | null;
    readonly event_type: EventType;
    pool_id: PoolId;
};

export interface OrderPlacedEvent extends Event {
    readonly client_order_id: ClientOrderId;
    readonly exchange_order_id: ExchangeOrderId;
    readonly side: Side;
    qty: Quantity | string;
    exec_qty: Quantity | string;
    rem_qty: Quantity | string;
    price: Price | string;
};

export interface OrderCancelledEvent extends Event {
    readonly client_order_id: ClientOrderId;
    readonly exchange_order_id: ExchangeOrderId;
    readonly side: Side;
    qty: Quantity | string;
    exec_qty: Quantity | string;
    price: Price | string;
}

export interface OrderFilledEvent extends Event {
    readonly liquidity_indicator: LiquidityIndicator;
    readonly client_order_id: ClientOrderId;
    readonly exchange_order_id: ExchangeOrderId;
    readonly trade_id: ExchangeTradeId;
    readonly side: Side;
    readonly exec_qty: Quantity | string;
    readonly price: Quantity | string;
    readonly fee: Quantity | string;
}

export interface AllOrdersCancelledEvent extends Event {
    readonly orders_cancelled: Array<OrderCancelledEvent>;
}

interface PurgeInfo {
    clientOrderId: ClientOrderId;
    additionTs: TimestampMs;
};

export class OrderCache {

    private logger: winston.Logger;
    private store: Map<ClientOrderId, Order>;
    private toPurge: Array<PurgeInfo>;

    constructor(lf: LoggerFactory, config: any) {
        if (config === undefined || config.purge_interval_s === undefined) {
            throw new Error("The key `order_cache.purge_interval_s` must be present in the config");
        }
        const purgeIntervalMs = (config.purge_interval_s * 1000) as TimestampMs;
        this.logger = lf.createLogger("order_cache");
        this.store = new Map<ClientOrderId, Order>();
        this.toPurge = new Array<PurgeInfo>();

        setInterval(this.purgeCache, purgeIntervalMs);
    }

    purgeCache = () => {
        this.logger.debug("Purging cache");
        const now = Date.now();
        let count = 0;
        for (let item of this.toPurge) {
            if (item.additionTs <= now) {
                this.store.delete(item.clientOrderId);
                ++count;
            } else {
                break
            }
        }
        const purgedItems = this.toPurge.splice(0, count);
        if (purgedItems.length) {
            this.logger.debug(`${purgedItems.length} items purged from cache`);
        }
    }

    get = (clientOrderId: ClientOrderId): Order | undefined => {
        return this.store.get(clientOrderId);
    }

    add = (clientOrderId: ClientOrderId, order: Order): void => {
        this.store.set(clientOrderId, order);
    }

    delete = (clientOrderId: ClientOrderId): void => {
        this.logger.debug(`Marking clOId=${clientOrderId} for purge`);
        this.toPurge.push({
            clientOrderId: clientOrderId,
            additionTs: Date.now() as TimestampMs
        });
    }
};
