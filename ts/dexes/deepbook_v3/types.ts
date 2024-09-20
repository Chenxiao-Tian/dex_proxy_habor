import type {
  Transaction,
  TransactionObjectArgument,
} from "@mysten/sui/transactions";

export type NetworkType = "mainnet" | "testnet";

export type SuiObjectArg = TransactionObjectArgument | string;

export type TransactionGenerator = () => Transaction;

export type PoolInfo = {
  pool_id: string;
  base_asset: string;
  quote_asset: string;
  taker_fee_rate: string;
  maker_rebate_rate: string;
  tick_size: string;
  lot_size: string;
  base_asset_trading_fees: string;
  quote_asset_trading_fees: string;
};
