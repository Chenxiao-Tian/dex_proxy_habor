import { Transaction } from "@mysten/sui/transactions";
import { convertObjArg } from "./utils.js";
import type { SuiObjectArg } from "./types.js";

export class SuiTxBlock {
  public txBlock: Transaction;

  constructor() {
    this.txBlock = new Transaction();
  }

  mergeCoinsIntoFirstCoin(coins: SuiObjectArg[]) {
    const coinObjects = coins.map((coin) => convertObjArg(this.txBlock, coin));
    const mergedCoin = coinObjects[0];
    if (coins.length > 1) {
      this.txBlock.mergeCoins(mergedCoin, coinObjects.slice(1));
    }

    return this.txBlock;
  }

  splitMultiCoins(coins: SuiObjectArg[], amounts: bigint[]) {
    const coinObjects = coins.map((coin) => convertObjArg(this.txBlock, coin));
    const mergedCoin = coinObjects[0];
    if (coins.length > 1) {
      this.txBlock.mergeCoins(mergedCoin, coinObjects.slice(1));
    }
    const splitedCoins = this.txBlock.splitCoins(mergedCoin, amounts);
    return { splitedCoins, mergedCoin };
  }

  transferSuiToMany(recipients: string[], amounts: bigint[]) {
    // require recipients.length === amounts.length
    if (recipients.length !== amounts.length) {
      throw new Error(
        "transferSuiToMany: recipients.length !== amounts.length"
      );
    }

    const coins = this.txBlock.splitCoins(
      this.txBlock.gas,
      amounts.map((amount) => {
        return Number(amount);
      })
    );

    recipients.forEach((address, index) => {
      this.txBlock.transferObjects([coins[index]], address);
    });

    return this.txBlock;
  }

  transferSui(address: string, amount: bigint) {
    return this.transferSuiToMany([address], [amount]);
  }

  transferCoinToMany(
    coins: SuiObjectArg[],
    sender: string,
    recipients: string[],
    amounts: bigint[]
  ) {
    // require recipients.length === amounts.length
    if (recipients.length !== amounts.length) {
      throw new Error(
        "transferCoinToMany: recipients.length !== amounts.length"
      );
    }

    const { splitedCoins, mergedCoin } = this.splitMultiCoins(coins, amounts);

    recipients.forEach((address, index) => {
      this.txBlock.transferObjects([splitedCoins[index]], address);
    });
    this.txBlock.transferObjects([mergedCoin], sender);
    return this.txBlock;
  }

  transferCoin(
    coins: SuiObjectArg[],
    sender: string,
    recipient: string,
    amount: bigint
  ) {
    return this.transferCoinToMany(coins, sender, [recipient], [amount]);
  }
}
