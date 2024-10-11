import type {
  Transaction,
  TransactionObjectArgument,
} from "@mysten/sui/transactions";
import type { SuiObjectArg } from "./types.js";
import { Coin, Pool } from "@mysten/deepbook-v3";

/**
 * Convert any valid object input into a TransactionArgument.
 *
 * @param txb The Transaction
 * @param arg The object argument to convert.
 * @returns The converted TransactionArgument.
 */
export function convertObjArg(
  txb: Transaction,
  arg: SuiObjectArg
): TransactionObjectArgument {
  if (typeof arg === "string") {
    return txb.object(arg);
  }

  if ("kind" in arg) {
    return arg;
  }

  throw new Error("Invalid argument type");
}

// January 1, 2050 12:00:00 AM GMT
export const ORDER_MAX_EXPIRE_TIMESTAMP_MS = 2524608000000;

export const MAINNET_COINS_MAP: Record<string, Coin> = {
  DEEP: {
    address:
      "0xdeeb7a4662eec9f2f3def03fb937a663dddaa2e215b8078a284d026b7946c270",
    type: "0xdeeb7a4662eec9f2f3def03fb937a663dddaa2e215b8078a284d026b7946c270::deep::DEEP",
    scalar: 1000000,
  },
  SUI: {
    address:
      "0x0000000000000000000000000000000000000000000000000000000000000002",
    type: "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI",
    scalar: 1000000000,
  },
};

export const TESTNET_COINS_MAP: Record<string, Coin> = {
  DEEP: {
    address:
      "0x36dbef866a1d62bf7328989a10fb2f07d769f4ee587c0de4a0a256e57e0a58a8",
    type: "0x36dbef866a1d62bf7328989a10fb2f07d769f4ee587c0de4a0a256e57e0a58a8::deep::DEEP",
    scalar: 1000000,
  },
  SUI: {
    address:
      "0x0000000000000000000000000000000000000000000000000000000000000002",
    type: "0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI",
    scalar: 1000000000,
  },
  DBUSDC: {
    address:
      "0xf7152c05930480cd740d7311b5b8b45c6f488e3a53a11c3f74a6fac36a52e0d7",
    type: "0xf7152c05930480cd740d7311b5b8b45c6f488e3a53a11c3f74a6fac36a52e0d7::DBUSDC::DBUSDC",
    scalar: 1000000,
  },
  DBUSDT: {
    address:
      "0xf7152c05930480cd740d7311b5b8b45c6f488e3a53a11c3f74a6fac36a52e0d7",
    type: "0xf7152c05930480cd740d7311b5b8b45c6f488e3a53a11c3f74a6fac36a52e0d7::DBUSDT::DBUSDT",
    scalar: 1000000,
  },
};

export const MAINNET_POOLS_MAP: Record<string, Pool> = {
  DEEP_SUI: {
    address:
      "0xe9aecf5859310f8b596fbe8488222a7fb15a55003455c9f42d1b60fab9cca9ba",
    baseCoin: "DEEP",
    quoteCoin: "SUI",
  },
};

export const TESTNET_POOLS_MAP: Record<string, Pool> = {
  DEEP_SUI: {
    address:
      "0x0d1b1746d220bd5ebac5231c7685480a16f1c707a46306095a4c67dc7ce4dcae",
    baseCoin: "DEEP",
    quoteCoin: "SUI",
  },
  SUI_DBUSDC: {
    address:
      "0x520c89c6c78c566eed0ebf24f854a8c22d8fdd06a6f16ad01f108dad7f1baaea",
    baseCoin: "SUI",
    quoteCoin: "DBUSDC",
  },
  DEEP_DBUSDC: {
    address:
      "0xee4bb0db95dc571b960354713388449f0158317e278ee8cda59ccf3dcd4b5288",
    baseCoin: "DEEP",
    quoteCoin: "DBUSDC",
  },
  DBUSDT_DBUSDC: {
    address:
      "0x69cbb39a3821d681648469ff2a32b4872739d2294d30253ab958f85ace9e0491",
    baseCoin: "DBUSDT",
    quoteCoin: "DBUSDC",
  },
};
