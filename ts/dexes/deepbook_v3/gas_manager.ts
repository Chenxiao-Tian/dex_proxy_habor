import { LoggerFactory } from "../../logger";

import { Logger } from "winston";
import { SuiClient } from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { Transaction } from "@mysten/sui/transactions";
import { SuiTransactionBlockResponse } from "@mysten/sui/client";

const sleep = async (duration_in_ms: number) => {
  return new Promise((resolve) => setTimeout(resolve, duration_in_ms));
};

export enum GasCoinStatus {
  Free,
  InUse,
  SkipForRemainderOfEpoch,
  NeedsVersionUpdate,
}

export class GasCoin {
  #logger: Logger;
  objectId: string;
  status: GasCoinStatus = GasCoinStatus.Free;
  digest: string;
  version: string;
  balanceMist: bigint;

  constructor(
    lf: LoggerFactory,
    id: string,
    digest: string,
    version: string,
    balanceMist: string
  ) {
    this.#logger = lf.createLogger(`gasCoin=${id}`);
    this.objectId = id;
    this.digest = digest;
    this.version = version;
    this.balanceMist = BigInt(balanceMist);
  }

  updateInstance = async (suiClient: SuiClient): Promise<boolean> => {
    try {
      let response = await suiClient.getObject({
        id: this.objectId,
        options: { showContent: true },
      });

      let data = response.data;
      if (data && data.content && data.content.dataType === "moveObject") {
        let fields = data.content.fields as any;
        const updatedVersion = data.version;
        if (this.version < updatedVersion) {
          this.#logger.debug(
            `Queried RPC node: prevVersion=${this.version} < newVersion=${
              data.version
            }. ${this.repr()}`
          );
          this.digest = data.digest;
          this.version = data.version;
          this.balanceMist = BigInt(fields.balance);
          return true;
        } else {
          // Debatable whether we want to return false for this scenario
          // as there are a few corner cases where the version of a
          // coin should not be updated.
          // TODO: revisit this at some point.
          this.#logger.debug(
            `Queried RPC node: prevVersion=${this.version} >= newVersion=${
              data.version
            }. ${this.repr()}`
          );
          return false;
        }
      }

      return false;
    } catch (error) {
      this.#logger.error(`Failed to update gasCoin=${this.repr()}`);
      return false;
    }
  };

  repr = (): string => {
    return `[objectId=${this.objectId} status=${
      GasCoinStatus[this.status]
    } version=${this.version} digest=${this.digest} balanceMist=${
      this.balanceMist
    }]`;
  };
}

class SplitCoinsResult {
  txSuceeded: boolean = false;
  digest: string = "";
  coinsCreated: Array<GasCoin> = new Array<GasCoin>();
  gasCoinVersionUpdated: boolean = false;
}

class MergeCoinsResult {
  txSuceeded: boolean = false;
  digest: string = "";
  coinsDeleted: Array<string> = new Array<string>();
  gasCoinVersionUpdated: boolean = false;
}

export class GasManager {
  static #suiCoinStructType: string = "0x2::coin::Coin<0x2::sui::SUI>";

  #loggerFactory: LoggerFactory;
  #logger: Logger;
  #suiClient: SuiClient;
  #walletAddress: string;
  #keyPair: Ed25519Keypair;
  #expectedCount: number;
  #maxBalancePerInstanceMist: bigint;
  #minBalancePerInstanceMist: bigint;
  #mainGasCoin: GasCoin | undefined = undefined;
  #gasCoins: Map<string, GasCoin>;
  #gasCoinKeys: Array<string>;
  #syncIntervalMs: number;
  #logResponses: boolean;
  #nextCoinIdx: number = 0;

  constructor(
    lf: LoggerFactory,
    suiClient: SuiClient,
    walletAddress: string,
    keyPair: Ed25519Keypair,
    expectedCount: number,
    maxBalancePerInstanceMist: bigint,
    minBalancePerInstanceMist: bigint,
    syncIntervalMs: number,
    logResponses: boolean
  ) {
    this.#loggerFactory = lf;
    this.#logger = this.#loggerFactory.createLogger("gas_mgr");
    this.#suiClient = suiClient;
    this.#walletAddress = walletAddress;
    this.#keyPair = keyPair;
    this.#expectedCount = expectedCount;
    this.#maxBalancePerInstanceMist = maxBalancePerInstanceMist;
    this.#minBalancePerInstanceMist = minBalancePerInstanceMist;
    this.#gasCoins = new Map<string, GasCoin>();
    this.#gasCoinKeys = new Array<string>();
    this.#syncIntervalMs = syncIntervalMs;
    this.#logResponses = logResponses;
  }

  start = async () => {
    await this.#setupCoinInstances();

    setTimeout(async () => {
      await this.#onSyncTimer();
    }, this.#syncIntervalMs);
  };

  #setMainGasCoin = () => {
    if (this.#gasCoins.size == 0) {
      throw new Error("No SUI token in the wallet");
    }

    // Choose the gas coin with the highest balance
    this.#mainGasCoin = [...this.#gasCoins.values()].reduce(
      (lt: GasCoin, rt: GasCoin): GasCoin => {
        return rt.balanceMist < lt.balanceMist ? lt : rt;
      }
    );

    this.#gasCoins.delete(this.#mainGasCoin.objectId);

    this.#logger.info(`Set mainGasCoin=${this.#mainGasCoin.repr()}`);
  };

  #gasCoinSummary = (prefix: string): string => {
    let summary = `${prefix}=[`;
    let index = 1;
    for (let coin of this.#gasCoins.values()) {
      summary = `${summary}#${index}=${coin.repr()}`;
      if (index < this.#gasCoins.size) summary = `${summary}, `;
      ++index;
    }

    return `${summary}]`;
  };

  #trackInstances = async () => {
    // So that we retry and not just fail at dex-proxy startup.
    let delay = (retryIntervalMs: number) => {
      return new Promise((resolve) => setTimeout(resolve, retryIntervalMs));
    };

    while (true) {
      try {
        let coins = await this.#suiClient.getOwnedObjects({
          owner: this.#walletAddress,
          filter: { StructType: GasManager.#suiCoinStructType },
          options: { showContent: true },
        });

        this.#logger.debug(`Owned Objects: ${JSON.stringify(coins)}`);
        for (let coin of coins.data) {
          let data = coin.data;
          if (data && data.content && data.content.dataType === "moveObject") {
            let fields = data.content.fields as any;
            this.#logger.debug(
              `coin=${data.objectId} version=${data.version} digest=${data.digest} balance=${fields.balance}`
            );
            this.#gasCoins.set(
              data.objectId,
              new GasCoin(
                this.#loggerFactory,
                data.objectId,
                data.digest,
                data.version,
                fields.balance
              )
            );
          }
        }

        this.#logger.info(
          `Found ${
            this.#gasCoins.size
          } gasCoin instance(s) in the linked wallet`
        );
        this.#logger.debug(this.#gasCoinSummary("gasCoins"));

        return;
      } catch (error) {
        this.#logger.error(
          `Unable to setup tracking of gasCoin instance(s). Error=${error}. Will retry in 1 sec.`
        );
        delay(1000);
      }
    }
  };

  tryUpdateGasCoinVersion = async (gasCoin: GasCoin): Promise<boolean> => {
    try {
      if (gasCoin == undefined) return false;

      let attempts = 2;

      let versionUpdated = false;
      for (let attempt = 0; attempt < attempts; ++attempt) {
        versionUpdated = await gasCoin.updateInstance(this.#suiClient);
        if (versionUpdated) break;

        this.#logger.warn(
          `Failed to update gas coin ${gasCoin.repr()}. Will retry`
        );

        if (attempt < attempts - 1) {
          await sleep(500); // 500 ms
        }
      }

      return versionUpdated;
    } catch (error) {
      this.#logger.error(
        `Failed to update gas coin ${gasCoin.repr()} error=${error}`
      );
      return false;
    }
  };

  #tryConsolidateGasCoins = async (coinsToMerge: Array<string>) => {
    if (this.#mainGasCoin == undefined) return;
    if (coinsToMerge.length == 0) return;

    this.#logger.info(
      `Merging ${coinsToMerge.length} coins with balance < ${
        this.#minBalancePerInstanceMist
      } or balance > ${this.#maxBalancePerInstanceMist} into the mainGasCoin`
    );

    let gasCoinVersionUpdated: boolean = false;
    try {
      let response = await this.#mergeCoins(this.#mainGasCoin, coinsToMerge);
      if (response.txSuceeded) {
        for (let coin of coinsToMerge) {
          this.#gasCoins.delete(coin);
        }
      }
      gasCoinVersionUpdated = response.gasCoinVersionUpdated;
    } finally {
      // Do not free the mainGasCoin at this stage as it's part of a larger
      // operation.
      if (
        !gasCoinVersionUpdated &&
        !(await this.tryUpdateGasCoinVersion(this.#mainGasCoin))
      ) {
        this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate;
        throw new Error(
          `Unable to update the mainGasCoin=${this.#mainGasCoin.repr()} after merging other coins into it`
        );
      }
    }
  };

  #splitIntoRequiredInstances = async () => {
    if (this.#mainGasCoin == undefined) return;
    if (this.#gasCoins.size >= this.#expectedCount) return;

    const instancesNeeded = this.#expectedCount - this.#gasCoins.size;
    const instanceToSplit = this.#mainGasCoin;

    this.#logger.info(
      `Available child gasCoinInstances=${
        this.#gasCoins.size
      } is less than the expectedCount=${
        this.#expectedCount
      }. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`
    );

    let gasCoinVersionUpdated = false;
    try {
      gasCoinVersionUpdated = await this.#createChildInstances(
        instancesNeeded,
        instanceToSplit
      );
    } finally {
      // Free the gas coin at the call site
      if (
        !gasCoinVersionUpdated &&
        !(await this.tryUpdateGasCoinVersion(this.#mainGasCoin))
      ) {
        this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate;
        throw new Error(
          `Unable to update the mainGasCoin=${this.#mainGasCoin.repr()} after creating child instances from it`
        );
      }
    }
  };

  #setupCoinInstances = async () => {
    try {
      await this.#trackInstances();

      this.#setMainGasCoin();

      if (this.#mainGasCoin === undefined || this.#mainGasCoin === null) {
        throw new Error("Unable to set mainGasCoin");
      }

      this.#mainGasCoin.status = GasCoinStatus.InUse;

      let trackedCoinsToMerge = this.#trackedCoinsToMerge();
      await this.#tryConsolidateGasCoins(trackedCoinsToMerge);

      await this.#splitIntoRequiredInstances();
    } finally {
      if (
        this.#mainGasCoin &&
        this.#mainGasCoin.status != GasCoinStatus.NeedsVersionUpdate
      ) {
        this.#mainGasCoin.status = GasCoinStatus.Free;
      }

      this.#gasCoinKeys = [...this.#gasCoins.keys()];
      this.#nextCoinIdx = 0;
    }
  };

  #untrackedCoinsToMerge = async (): Promise<Array<string>> => {
    let untrackedCoinsToMerge = new Array<string>();

    try {
      let coins = await this.#suiClient.getOwnedObjects({
        owner: this.#walletAddress,
        filter: { StructType: GasManager.#suiCoinStructType },
        options: { showContent: true },
      });

      this.#logger.debug(`Owned Objects: ${JSON.stringify(coins)}`);
      for (let coin of coins.data) {
        let data = coin.data;
        if (data) {
          if (
            data.objectId === this.#mainGasCoin?.objectId ||
            this.#gasCoins.has(data.objectId)
          ) {
            continue;
          } else {
            this.#logger.debug(
              `Found untracked gasCoin=${data.objectId} version=${data.version} digest=${data.digest} in wallet`
            );
            untrackedCoinsToMerge.push(data.objectId);
          }
        }
      }
    } catch (error) {
      this.#logger.error(`Failed to query untracked gas coins. Error=${error}`);
    }

    return untrackedCoinsToMerge;
  };

  #trackedCoinsToMerge = (): Array<string> => {
    let trackedCoinsToMerge = new Array<string>();

    for (let coin of this.#gasCoins.values()) {
      if (
        coin.status === GasCoinStatus.Free &&
        (coin.balanceMist < this.#minBalancePerInstanceMist ||
          coin.balanceMist > this.#maxBalancePerInstanceMist)
      ) {
        coin.status = GasCoinStatus.InUse;
        this.#logger.debug(
          `Coin=${coin.repr()} out of bounds=[${
            this.#minBalancePerInstanceMist
          }, ${this.#maxBalancePerInstanceMist}]`
        );
        trackedCoinsToMerge.push(coin.objectId);
      }
    }

    return trackedCoinsToMerge;
  };

  #handleCoinsNeedingVersionUpdate = async () => {
    if (
      this.#mainGasCoin &&
      this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate
    ) {
      if (await this.tryUpdateGasCoinVersion(this.#mainGasCoin)) {
        this.#mainGasCoin.status = GasCoinStatus.Free;
      }
    }

    for (let coin of this.#gasCoins.values()) {
      if (coin.status == GasCoinStatus.NeedsVersionUpdate) {
        if (await this.tryUpdateGasCoinVersion(coin)) {
          coin.status = GasCoinStatus.Free;
        }
      }
    }
  };

  #canRunPeriodicTask = (): boolean => {
    if (this.#mainGasCoin === undefined) {
      this.#logger.debug(`onSyncTimer: mainGasCoin not set. Skipping`);
      return false;
    }

    let status: string = `onSyncTimer: mainGasCoin=${this.#mainGasCoin.repr()}`;
    this.#logger.debug(this.#gasCoinSummary(`${status} children`));

    if (this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
      this.#logger.debug(
        `onSyncTimer: The version of the ${this.#mainGasCoin.repr()} is stale. Will retry updating in next iteration of the periodic task`
      );
      return false;
    }

    if (this.#mainGasCoin.status !== GasCoinStatus.Free) {
      this.#logger.debug(`onSyncTimer: mainGasCoin is not free. Skipping`);
      return false;
    }

    return true;
  };

  #onSyncTimer = async () => {
    let trackedCoinsToMerge = Array<string>();
    let untrackedCoinsToMerge = Array<string>();
    let coinsMerged = false;
    let gasCoinVersionUpdated = false;
    try {
      await this.#handleCoinsNeedingVersionUpdate();

      if (!this.#canRunPeriodicTask()) return;

      this.#mainGasCoin!.status = GasCoinStatus.InUse;

      // Check for untracked SUI coins in the wallet and merge them into
      // the main gas coin.
      // Merge coins with balance < minBalancePerInstanceMist or balance > maxBalancePerinstanceMist into the mainGasCoin
      untrackedCoinsToMerge = await this.#untrackedCoinsToMerge();
      trackedCoinsToMerge = this.#trackedCoinsToMerge();

      if (trackedCoinsToMerge.length + untrackedCoinsToMerge.length > 0) {
        this.#logger.debug(
          `Scanning found ${untrackedCoinsToMerge.length} untracked, ${trackedCoinsToMerge.length} tracked gas coins to merge`
        );

        let response = await this.#mergeCoins(this.#mainGasCoin!, [
          ...untrackedCoinsToMerge,
          ...trackedCoinsToMerge,
        ]);
        coinsMerged = response.txSuceeded;
        gasCoinVersionUpdated = response.gasCoinVersionUpdated;
      }
    } finally {
      setTimeout(async () => {
        await this.#onSyncTimer();
      }, this.#syncIntervalMs);

      if (!this.#mainGasCoin) {
        return;
      }

      if (trackedCoinsToMerge.length > 0) {
        if (coinsMerged) {
          for (let coin of trackedCoinsToMerge) {
            this.#gasCoins.delete(coin);
          }

          if (!gasCoinVersionUpdated) {
            gasCoinVersionUpdated = await this.tryUpdateGasCoinVersion(
              this.#mainGasCoin
            );
            if (!gasCoinVersionUpdated) {
              this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
              this.#logger.error(
                `Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}. Will split the mainGasCoin in the next iteration of the periodic task.`
              );
              return;
            }
          }

          const instancesNeeded = this.#expectedCount - this.#gasCoins.size;
          const instanceToSplit = this.#mainGasCoin;
          if (instancesNeeded > 0) {
            this.#logger.info(
              `Available child gasCoinInstances=${
                this.#gasCoins.size
              } is less than the expectedCount=${
                this.#expectedCount
              }. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`
            );
            gasCoinVersionUpdated = await this.#createChildInstances(
              instancesNeeded,
              instanceToSplit
            );
          }
        } else {
          for (let coinId of trackedCoinsToMerge) {
            let coin = this.#gasCoins.get(coinId);
            if (coin) {
              if (await this.tryUpdateGasCoinVersion(coin)) {
                coin.status = GasCoinStatus.Free;
              } else {
                coin.status = GasCoinStatus.NeedsVersionUpdate;
              }
            }
          }
        }

        if (
          !gasCoinVersionUpdated &&
          !(await this.tryUpdateGasCoinVersion(this.#mainGasCoin))
        ) {
          this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
          this.#logger.error(
            `Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}`
          );
          return;
        }
      }

      if (
        untrackedCoinsToMerge.length > 0 &&
        trackedCoinsToMerge.length === 0
      ) {
        if (
          !gasCoinVersionUpdated &&
          !(await this.tryUpdateGasCoinVersion(this.#mainGasCoin))
        ) {
          this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
          this.#logger.error(
            `Failed to update the version of the mainGasCoin=${
              this.#mainGasCoin
            }`
          );
          return;
        }
      }

      const instancesNeeded = this.#expectedCount - this.#gasCoins.size;
      const instanceToSplit = this.#mainGasCoin;
      if (instancesNeeded > 0) {
        this.#logger.info(
          `Available child gasCoinInstances=${
            this.#gasCoins.size
          } is less than the expectedCount=${
            this.#expectedCount
          }. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`
        );

        gasCoinVersionUpdated = await this.#createChildInstances(
          instancesNeeded,
          instanceToSplit
        );

        if (
          !gasCoinVersionUpdated &&
          !this.tryUpdateGasCoinVersion(this.#mainGasCoin)
        ) {
          this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
          this.#logger.error(
            `Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}`
          );
          return;
        }
      } else {
        this.#mainGasCoin.status = GasCoinStatus.Free;
      }
    }
  };

  #createChildInstances = async (
    instancesNeeded: number,
    instanceToSplit: GasCoin
  ): Promise<boolean> => {
    let gasCoinVersionUpdated = false;
    try {
      let response = await this.#splitCoins(
        instanceToSplit!,
        instancesNeeded,
        this.#maxBalancePerInstanceMist
      );

      gasCoinVersionUpdated = response.gasCoinVersionUpdated;
      if (response.txSuceeded) {
        for (let coin of response.coinsCreated) {
          if (!this.#gasCoins.has(coin.objectId)) {
            this.#gasCoins.set(coin.objectId, coin);
          }
        }

        this.#logger.info(
          `${
            this.#gasCoins.size
          } child gasCoin instances in the linked wallet after the split`
        );
      }
    } finally {
      this.#gasCoinKeys = [...this.#gasCoins.keys()];
      this.#nextCoinIdx = 0;
      return gasCoinVersionUpdated;
    }
  };

  #parseSplitCoinsResponse = (
    response: SuiTransactionBlockResponse,
    balancePerCoin: bigint,
    instanceToSplit: GasCoin
  ): SplitCoinsResult => {
    let parsedResponse = new SplitCoinsResult();

    if (response.effects?.gasObject && response.effects?.gasUsed) {
      const versionFromTx = BigInt(
        response.effects!.gasObject.reference.version
      );
      const digestFromTx = response.effects!.gasObject.reference.digest;

      const gasUsed =
        BigInt(response.effects!.gasUsed.computationCost) +
        BigInt(response.effects!.gasUsed.storageCost) -
        BigInt(response.effects!.gasUsed.storageRebate);

      if (BigInt(instanceToSplit.version) < versionFromTx) {
        const oldVersion = instanceToSplit.version;
        instanceToSplit.version = versionFromTx.toString();
        instanceToSplit.digest = digestFromTx;
        instanceToSplit.balanceMist -= gasUsed;

        this.#logger.info(
          `gasCoin=${
            instanceToSplit.objectId
          } updated. Details=${instanceToSplit.repr()}. OldVersion=${oldVersion}`
        );

        parsedResponse.gasCoinVersionUpdated = true;
      }
    }

    if (response.effects?.status.status === "success") {
      parsedResponse.txSuceeded = true;
    } else {
      return parsedResponse;
    }

    if (response?.digest) {
      parsedResponse.digest = response.digest;
    }

    if (response.effects?.created) {
      for (let instance of response.effects.created) {
        let gasCoin = new GasCoin(
          this.#loggerFactory,
          instance.reference.objectId,
          instance.reference.digest,
          instance.reference.version,
          `${balancePerCoin}`
        );

        parsedResponse.coinsCreated.push(gasCoin);
      }
    }

    return parsedResponse;
  };

  #splitCoins = async (
    instanceToSplit: GasCoin,
    count: number,
    balancePerCoin: bigint
  ): Promise<SplitCoinsResult> => {
    const txBlock = new Transaction();
    let parsedResponse = new SplitCoinsResult();

    try {
      let amounts = new Array<bigint>();
      for (let i = 0; i < count; ++i) {
        amounts.push(balancePerCoin);
      }
      let coins = txBlock.splitCoins(txBlock.gas, amounts);
      for (let i = 0; i < amounts.length; ++i) {
        txBlock.transferObjects([coins[i]], this.#walletAddress);
      }

      txBlock.setGasPayment([instanceToSplit]);

      let response = await this.#suiClient.signAndExecuteTransaction({
        signer: this.#keyPair,
        transaction: txBlock,
        options: { showEffects: true },
      });

      if (this.#logResponses) {
        const deserialized = JSON.stringify(response);
        this.#logger.debug(`Split coins response: ${deserialized}`);
      }

      parsedResponse = this.#parseSplitCoinsResponse(
        response,
        balancePerCoin,
        instanceToSplit
      );

      if (parsedResponse.txSuceeded) {
        this.#logger.info(
          `Split ${instanceToSplit.repr()} into ${
            parsedResponse.coinsCreated.length
          } coin(s), txDigest=${parsedResponse.digest}`
        );
      } else {
        this.#logger.error(
          `Failed to split ${instanceToSplit.repr()}, txDigest=${
            parsedResponse.digest
          }`
        );
      }
    } catch (error) {
      this.#logger.error(
        `Failed to split coin=${instanceToSplit.repr()}. Error=${error}`
      );
    }

    return parsedResponse;
  };

  #parseMergeCoinsResponse = (
    response: SuiTransactionBlockResponse,
    gasCoin: GasCoin
  ): MergeCoinsResult => {
    let parsedResponse = new MergeCoinsResult();

    if (response.effects?.gasObject && response.effects?.gasUsed) {
      const versionFromTx = BigInt(
        response.effects!.gasObject.reference.version
      );
      const digestFromTx = response.effects!.gasObject.reference.digest;

      const gasUsed =
        BigInt(response.effects!.gasUsed.computationCost) +
        BigInt(response.effects!.gasUsed.storageCost) -
        BigInt(response.effects!.gasUsed.storageRebate);

      if (BigInt(gasCoin.version) < versionFromTx) {
        const oldVersion = gasCoin.version;
        gasCoin.version = versionFromTx.toString();
        gasCoin.digest = digestFromTx;
        gasCoin.balanceMist -= gasUsed;

        this.#logger.info(
          `gasCoin=${
            gasCoin.objectId
          } updated. Details=${gasCoin.repr()}. OldVersion=${oldVersion}`
        );

        parsedResponse.gasCoinVersionUpdated = true;
      }
    }

    if (response.effects?.status.status === "success") {
      parsedResponse.txSuceeded = true;
    } else {
      return parsedResponse;
    }

    if (response?.digest) {
      parsedResponse.digest = response.digest;
    }

    if (response.effects?.deleted) {
      for (let instance of response.effects.deleted) {
        parsedResponse.coinsDeleted.push(instance.objectId);
      }
    }
    return parsedResponse;
  };

  #mergeCoins = async (
    parentInstance: GasCoin,
    instancesToMerge: Array<string>
  ) => {
    this.#logger.info(
      `Merging ${
        instancesToMerge.length
      } coin(s) into the gasCoin=${parentInstance.repr()}`
    );

    this.#logger.debug(`mainGasCoin=${parentInstance.repr()}`);

    let txBlock = new Transaction();
    let parsedResponse = new MergeCoinsResult();

    try {
      txBlock.mergeCoins(txBlock.gas, instancesToMerge);
      txBlock.setGasPayment([parentInstance]);

      let response = await this.#suiClient.signAndExecuteTransaction({
        signer: this.#keyPair,
        transaction: txBlock,
        options: { showEffects: true },
      });

      if (this.#logResponses) {
        const deserialized = JSON.stringify(response);
        this.#logger.debug(`Merge coins response: ${deserialized}`);
      }

      parsedResponse = this.#parseMergeCoinsResponse(response, parentInstance);
      if (parsedResponse.txSuceeded) {
        this.#logger.info(
          `Merged ${
            parsedResponse.coinsDeleted.length
          } coin(s) into the gasCoin=${parentInstance.repr()}, txDigest=${
            parsedResponse.digest
          }`
        );
      } else {
        this.#logger.error(
          `Failed to Merge coin(s) into the gasCoin=${parentInstance.repr()}, txDigest=${
            parsedResponse.digest
          }`
        );
      }
    } catch (error) {
      this.#logger.error(`Failed to merge coins. Error=${error}`);
    }

    return parsedResponse;
  };

  // The caller is responsible for obtaining the gasCoin before calling this
  // and freeing it afterwards
  mergeUntrackedGasCoinsInto = async (gasCoin: GasCoin) => {
    let untrackedCoinsToMerge = new Array<string>();
    let parsedResponse = new MergeCoinsResult();

    try {
      untrackedCoinsToMerge = await this.#untrackedCoinsToMerge();

      this.#logger.info(
        `mergeUntrackedGasCoinsInto: Found ${untrackedCoinsToMerge.length} untracked gas coin(s)`
      );
      if (untrackedCoinsToMerge.length == 0) {
        this.#logger.info(
          `mergeUntrackedGasCoinsInto: No untracked gasCoin to merge. Returning`
        );
        return;
      }

      parsedResponse = await this.#mergeCoins(gasCoin, untrackedCoinsToMerge);
    } catch (error) {
      this.#logger.error(
        `mergeUntrackedGasCoinsInto: Failed to merge untracked coins into gasCoin=${gasCoin.repr()}. Error=${error}`
      );
    } finally {
      if (!parsedResponse.gasCoinVersionUpdated) {
        if (!(await this.tryUpdateGasCoinVersion(gasCoin))) {
          gasCoin.status == GasCoinStatus.NeedsVersionUpdate;
        }
      }
    }
  };

  getFreeGasCoin = (): GasCoin => {
    if (this.#gasCoinKeys.length === 0) {
      throw new Error("No gas coins configured");
    }

    const startingIdx = this.#nextCoinIdx;
    let idx = startingIdx;
    do {
      const coinId = this.#gasCoinKeys[idx];
      let coin = this.#gasCoins.get(coinId);
      if (coin === undefined) {
        throw new Error(`No gas coin found with id=${coinId}`);
      }
      idx = (idx + 1) % this.#gasCoinKeys.length;

      if (coin.status === GasCoinStatus.Free) {
        coin.status = GasCoinStatus.InUse;
        this.#nextCoinIdx = idx;
        return coin;
      }
    } while (idx != startingIdx);

    throw new Error("All gas coins in use");
  };

  getMainGasCoin = async (): Promise<GasCoin | null> => {
    if (this.#mainGasCoin === undefined) {
      throw new Error("The main gas coin has not been allocated yet");
    }

    if (this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
      if (await this.tryUpdateGasCoinVersion(this.#mainGasCoin)) {
        this.#mainGasCoin.status = GasCoinStatus.Free;
      } else {
        this.#logger.error(
          `Unable to update the version of the mainGasCoin={this.#mainGasCoin}`
        );
      }
    }

    if (this.#mainGasCoin.status !== GasCoinStatus.Free) {
      this.#logger.error("mainGasCoin is not free");
      return null;
    }

    this.#mainGasCoin.status = GasCoinStatus.InUse;

    return this.#mainGasCoin;
  };

  onEpochChange = async () => {
    for (let [_, gasCoin] of this.#gasCoins) {
      if (gasCoin.status == GasCoinStatus.SkipForRemainderOfEpoch) {
        this.#logger.info(
          `Freeing gasCoin=${gasCoin.repr()} skipped for last epoch`
        );
        if (await this.tryUpdateGasCoinVersion(gasCoin)) {
          gasCoin.status = GasCoinStatus.Free;
        } else {
          gasCoin.status = GasCoinStatus.NeedsVersionUpdate;
        }
      }
    }
  };

  logSkippedObjects = () => {
    let count: number = 0;
    for (let [_, gasCoin] of this.#gasCoins) {
      if (gasCoin.status == GasCoinStatus.SkipForRemainderOfEpoch) {
        this.#logger.debug(
          `gasCoin=${gasCoin.repr()} will be skipped for the remainder of the current epoch`
        );
        ++count;
      }
    }

    if (count > 0) {
      this.#logger.warn(
        `Skipping ${count} gas coins for the remainder of the current epoch`
      );
    }
  };
}
