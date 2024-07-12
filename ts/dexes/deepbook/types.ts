import type {
  TransactionBlock,
  TransactionObjectArgument,
  TransactionArgument,
} from '@mysten/sui.js/transactions';
import type { SuiObjectRef } from '@mysten/sui.js/client';
import type { SharedObjectRef, ObjectArg } from '@mysten/sui.js/bcs';
import type { SerializedBcs } from '@mysten/bcs';

export type NetworkType = 'testnet' | 'mainnet' | 'devnet' | 'localnet';

export type AccountMangerParams = {
  mnemonics?: string;
  secretKey?: string;
};

export type DerivePathParams = {
  accountIndex?: number;
  isExternal?: boolean;
  addressIndex?: number;
};

type TransactionBlockType = InstanceType<typeof TransactionBlock>;

export type PureCallArg = {
  Pure: number[];
};
export type ObjectCallArg = {
  Object: ObjectArg;
};
export type TransactionType = Parameters<TransactionBlockType['add']>;

export type TransactionPureArgument = Extract<
  TransactionArgument,
  {
    kind: 'Input';
    type: 'pure';
  }
>;

export type SuiTxArg = SuiAddressArg | number | bigint | boolean;

export type SuiAddressArg =
  | TransactionArgument
  | SerializedBcs<any>
  | string
  | PureCallArg;

export type SuiObjectArg =
  | TransactionObjectArgument
  | string
  | SharedObjectRef
  | SuiObjectRef
  | ObjectCallArg;

export type SuiVecTxArg =
  | { value: SuiTxArg[]; vecType: SuiInputTypes }
  | SuiTxArg[];

/**
 * These are the basics types that can be used in the SUI
 */
export type SuiBasicTypes =
  | 'address'
  | 'bool'
  | 'u8'
  | 'u16'
  | 'u32'
  | 'u64'
  | 'u128'
  | 'u256'
  | 'signer';

export type SuiInputTypes = 'object' | SuiBasicTypes;

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
