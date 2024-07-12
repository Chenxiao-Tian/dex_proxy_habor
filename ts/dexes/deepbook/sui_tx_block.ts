import { TransactionBlock } from '@mysten/sui.js/transactions';
import { convertArgs, convertAddressArg, convertObjArg } from './utils.js';
import type {
  SuiTxArg,
  SuiAddressArg,
  SuiObjectArg,
} from './types.js';

export class SuiTxBlock {
    public txBlock: TransactionBlock;

    constructor(transaction?: TransactionBlock) {
        this.txBlock = new TransactionBlock(transaction);
    }

    mergeCoinsIntoFirstCoin(coins: SuiObjectArg[]) {
        const coinObjects = coins.map((coin) => convertObjArg(this.txBlock, coin));
        const mergedCoin = coinObjects[0];
        if (coins.length > 1) {
          this.txBlock.mergeCoins(mergedCoin, coinObjects.slice(1));
        }

        return this.txBlock;
    }

    splitMultiCoins(coins: SuiObjectArg[], amounts: SuiTxArg[]) {
        const coinObjects = coins.map((coin) => convertObjArg(this.txBlock, coin));
        const mergedCoin = coinObjects[0];
        if (coins.length > 1) {
          this.txBlock.mergeCoins(mergedCoin, coinObjects.slice(1));
        }
        const splitedCoins = this.txBlock.splitCoins(
          mergedCoin,
          convertArgs(this.txBlock, amounts)
        );
        return { splitedCoins, mergedCoin };
    }

    transferSuiToMany(recipients: SuiAddressArg[], amounts: SuiTxArg[]) {
        // require recipients.length === amounts.length
        if (recipients.length !== amounts.length) {
          throw new Error(
            'transferSuiToMany: recipients.length !== amounts.length'
          );
        }

        const coins = this.txBlock.splitCoins(
          this.txBlock.gas,
          convertArgs(this.txBlock, amounts)
        );

        const recipientObjects = recipients.map((recipient) =>
          convertAddressArg(this.txBlock, recipient)
        );

        recipientObjects.forEach((address, index) => {
          this.txBlock.transferObjects([coins[index]], address);
        });

        return this.txBlock;
    }

    transferSui(address: SuiAddressArg, amount: SuiTxArg) {
        return this.transferSuiToMany([address], [amount]);
    }

    transferCoinToMany(
        coins: SuiObjectArg[],
        sender: SuiAddressArg,
        recipients: SuiAddressArg[],
        amounts: SuiTxArg[])
    {
        // require recipients.length === amounts.length
        if (recipients.length !== amounts.length) {
          throw new Error(
            'transferSuiToMany: recipients.length !== amounts.length'
          );
        }
        const coinObjects = coins.map((coin) => convertObjArg(this.txBlock, coin));
        const { splitedCoins, mergedCoin } = this.splitMultiCoins(
          coinObjects,
          amounts
        );
        const recipientObjects = recipients.map((recipient) =>
          convertAddressArg(this.txBlock, recipient)
        );
        recipientObjects.forEach((address, index) => {
          this.txBlock.transferObjects([splitedCoins[index]], address);
        });
        this.txBlock.transferObjects(
          [mergedCoin],
          convertAddressArg(this.txBlock, sender)
        );
        return this.txBlock;
    }

    transferCoin(
        coins: SuiObjectArg[],
        sender: SuiAddressArg,
        recipient: SuiAddressArg,
        amount: SuiTxArg)
    {
        return this.transferCoinToMany(coins, sender, [recipient], [amount]);
    }
}