import type {
  Transaction,
  TransactionObjectArgument,
} from "@mysten/sui/transactions";
import type { SuiObjectArg } from "./types.js";

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
