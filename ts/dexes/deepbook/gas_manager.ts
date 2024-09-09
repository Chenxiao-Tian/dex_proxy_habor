import { LoggerFactory } from "../../logger";

import { Logger } from "winston";
import { SuiClient } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { TransactionBlock } from "@mysten/sui.js/transactions";

export enum GasCoinStatus {
    Free,
    InUse,
    SkipForRemainderOfEpoch,
    NeedsVersionUpdate
};

export class GasCoin {
    #logger: Logger;
    objectId: string;
    status: GasCoinStatus = GasCoinStatus.Free;
    digest: string;
    version: bigint;
    balanceMist: bigint;

    constructor(lf: LoggerFactory, id: string, digest: string, version: string,
                balanceMist: string) {
        this.#logger = lf.createLogger(`gasCoin=${id}`);
        this.objectId = id;
        this.digest = digest;
        this.version = BigInt(version);
        this.balanceMist = BigInt(balanceMist);
    }

    updateInstance = async (suiClient: SuiClient): Promise<boolean> => {
        try {
            let response = await suiClient.getObject({
                id: this.objectId, options: { showContent: true }
            });

            let data = response.data;
            if (data && data.content && data.content.dataType === "moveObject") {
                let fields = data.content.fields as any;
                const updatedVersion = BigInt(data.version);
                if (this.version < updatedVersion) {
                    this.#logger.debug(`oldVer=${this.version} newVer=${data.version}`);
                    this.digest = data.digest;
                    this.version = BigInt(data.version);
                    this.balanceMist = BigInt(fields.balance);
                    return true;
                } else {
                    // Debatable whether we want to return false for this scenario
                    // as there are a few corner cases where the version of a
                    // coin should not be updated.
                    // TODO: revisit this at some point.
                    this.#logger.debug(`oldVer=${this.version} >= newVer=${data.version}`);
                    return false;
                }
            }
            return false;
        } catch (error) {
            this.#logger.error(`Failed to update gasCoin=${this.objectId}`);
            return false;
        }
    }

    repr = (): string => {
        return `objectId=${this.objectId} version=${this.version} digest=${this.digest} balanceMist=${this.balanceMist}`;
    }
};

export class GasManager {
    static #suiCoinStructType: string = "0x2::coin::Coin<0x2::sui::SUI>"

    #loggerFactory: LoggerFactory;
    #logger: Logger;
    #suiClient: SuiClient;
    #walletAddress: string;
    #keyPair: Ed25519Keypair;
    #expectedCount: number;
    #balancePerInstanceMist: bigint;
    #minBalancePerInstanceMist: bigint;
    #mainGasCoin: GasCoin | undefined = undefined;
    #gasCoins: Map<string, GasCoin>;
    #gasCoinKeys: Array<string>;
    #syncIntervalMs: number;
    #nextCoinIdx: number = 0;

    constructor(lf: LoggerFactory, suiClient: SuiClient, walletAddress: string,
                keyPair: Ed25519Keypair, expectedCount: number,
                balancePerInstanceMist: bigint, minBalancePerInstanceMist: bigint,
                syncIntervalMs: number) {
        this.#loggerFactory = lf;
        this.#logger = this.#loggerFactory.createLogger("gas_mgr");
        this.#suiClient = suiClient;
        this.#walletAddress = walletAddress;
        this.#keyPair = keyPair;
        this.#expectedCount = expectedCount;
        this.#balancePerInstanceMist = balancePerInstanceMist;
        this.#minBalancePerInstanceMist = minBalancePerInstanceMist;
        this.#gasCoins = new Map<string, GasCoin>();
        this.#gasCoinKeys = new Array<string>();
        this.#syncIntervalMs = syncIntervalMs;
    }

    start = async () => {
        await this.#setupCoinInstances();

        setTimeout(async () => {await this.#onSyncTimer();},
                   this.#syncIntervalMs);
    }

    #setMainGasCoin = () => {
        // Choose the gas coin with the highest balance
        this.#mainGasCoin = [...this.#gasCoins.values()].reduce(
            (lt: GasCoin, rt: GasCoin): GasCoin => {
                return rt.balanceMist < lt.balanceMist ? lt : rt;
            }
        );

        this.#gasCoins.delete(this.#mainGasCoin.objectId);

        this.#logger.info(`Setting mainGasCoin=${this.#mainGasCoin.repr()}`);
    }

    #trackInstances = async () => {
        try {
            let coins = await this.#suiClient.getOwnedObjects({
                owner: this.#walletAddress,
                filter: { StructType: GasManager.#suiCoinStructType },
                options: { showContent: true }
            });

            for (let coin of coins.data) {
                let data = coin.data;
                if (data && data.content &&
                    data.content.dataType === "moveObject") {
                    let fields = data.content.fields as any;
                    this.#logger.debug(`coin=${data.objectId} version=${data.version}`);
                    this.#gasCoins.set(data.objectId,
                                       new GasCoin(this.#loggerFactory,
                                                   data.objectId,
                                                   data.digest,
                                                   data.version,
                                                   fields.balance));
                }
            }

            this.#logger.info(`Found ${this.#gasCoins.size} gasCoin instance(s) in the linked wallet`);
        } catch (error) {
            const msg = `Unable to setup tracking of gasCoin instance(s). Error=${error}`;
            this.#logger.error(msg);
            throw new Error(msg);
        }
    }

    #tryUpdateMainGasCoinVersion = async (): Promise<boolean> => {
        if (this.#mainGasCoin == undefined) return false;

        let attempts = 2;

        let versionUpdated = false;
        for (let attempt = 0; attempt < attempts; ++attempt) {
            versionUpdated = await this.#mainGasCoin.updateInstance(this.#suiClient);
            if (versionUpdated) break;
        }

        return versionUpdated;
    }

    #tryConsolidateGasCoins = async (coinsToMerge: Array<string>) => {
        if (this.#mainGasCoin == undefined) return;
        if (coinsToMerge.length == 0) return;

        this.#logger.info(`Merging ${coinsToMerge.length} coins with balance <= ${this.#minBalancePerInstanceMist} and balance > ${this.#balancePerInstanceMist} into the mainGasCoin`);

        try {
            const merged = await this.#mergeCoins(this.#mainGasCoin,
                                                  coinsToMerge);
            if (merged) {
                for (let coin of coinsToMerge) {
                    this.#gasCoins.delete(coin);
                }
            }
        } finally {
            // Do not free the mainGasCoin at this stage as it's part of a larger
            // operation.
            if (! await this.#tryUpdateMainGasCoinVersion()) {
                this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate;
                throw new Error(`Unable to update the mainGasCoin=${this.#mainGasCoin.repr()} after merging other coins into it`);
            }
        }
    }

    #splitIntoRequiredInstances = async () => {
        if (this.#mainGasCoin == undefined) return;
        if (this.#gasCoins.size == this.#expectedCount) return;

        const instancesNeeded = this.#expectedCount - this.#gasCoins.size;
        const instanceToSplit = this.#mainGasCoin;

        this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`);

        try {
            await this.#createChildInstances(instancesNeeded, instanceToSplit);
        } finally {
            // Free the gas coin at the call site
            if(! await this.#tryUpdateMainGasCoinVersion()) {
                this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate;
                throw new Error(`Unable to update the mainGasCoin=${this.#mainGasCoin.repr()} after creating child instances from it`);
            }
        }
    }


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
            if (this.#mainGasCoin && this.#mainGasCoin.status != GasCoinStatus.NeedsVersionUpdate) {
                this.#mainGasCoin.status = GasCoinStatus.Free;
            }
            this.#gasCoinKeys = [...this.#gasCoins.keys()];
            this.#nextCoinIdx = 0;
        }
    }

    #untrackedCoinsToMerge = async (): Promise<Array<string>> => {
        let untrackedCoinsToMerge = new Array<string>();

        try {
            let coins = await this.#suiClient.getOwnedObjects({
                owner: this.#walletAddress,
                filter: { StructType: "0x2::coin::Coin<0x2::sui::SUI>" },
                options: { showContent: true }
            });

            for (let coin of coins.data) {
                let data = coin.data;
                if (data) {
                    if (data.objectId === this.#mainGasCoin?.objectId ||
                        this.#gasCoins.has(data.objectId)) {
                        continue;
                    } else {
                        this.#logger.debug(`Found untracked gasCoin=${data.objectId} in wallet`);
                        untrackedCoinsToMerge.push(data.objectId);
                    }
                }
            }
        } catch (error) {
            this.#logger.error(`Failed to query untracked gas coins. Error=${error}`);
        }

        return untrackedCoinsToMerge;
    }

    #trackedCoinsToMerge = (): Array<string> => {
        let trackedCoinsToMerge = new Array<string>();

        for (let coin of this.#gasCoins.values()) {
            if (coin.status === GasCoinStatus.Free
                && (coin.balanceMist <= this.#minBalancePerInstanceMist ||
                    coin.balanceMist > this.#balancePerInstanceMist)) {
                coin.status = GasCoinStatus.InUse;
                this.#logger.debug(`Coin=${coin.repr()} out of bounds=(${this.#minBalancePerInstanceMist}, ${this.#balancePerInstanceMist}]`);
                trackedCoinsToMerge.push(coin.objectId);
            }
        }

        return trackedCoinsToMerge;
    }

    #handleCoinsNeedingVersionUpdate = async () => {
        if (this.#mainGasCoin && this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
            if (await this.#mainGasCoin.updateInstance(this.#suiClient)) {
                this.#mainGasCoin.status = GasCoinStatus.Free;
            }
        }

        for (let coin of this.#gasCoins.values()) {
            if (coin.status == GasCoinStatus.NeedsVersionUpdate) {
                if (await coin.updateInstance(this.#suiClient)) {
                    coin.status = GasCoinStatus.Free;
                }
            }
        }
    }

    #canRunPeriodicTask = (): boolean => {
        if (this.#mainGasCoin === undefined) {
            this.#logger.debug(`onSyncTimer: mainGasCoin not set. Skipping`);
            return false;
        }

        this.#logger.debug(`onSyncTimer: mainGasCoin=${this.#mainGasCoin.repr()}`);

        if (this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
            this.#logger.debug(`onSyncTimer: The version of the ${this.#mainGasCoin.repr()} is stale. Will retry updating in next iteration of the periodic task`);
            return false;
        }

        if (this.#mainGasCoin.status !== GasCoinStatus.Free) {
            this.#logger.debug(`onSyncTimer: mainGasCoin is in use. Skipping`);
            return false;
        }

        return true;
    }

    #onSyncTimer = async () => {
        let trackedCoinsToMerge = Array<string>();
        let untrackedCoinsToMerge = Array<string>();
        let coinsMerged = false;
        try {
            await this.#handleCoinsNeedingVersionUpdate();

            if (! this.#canRunPeriodicTask()) return;

            this.#mainGasCoin!.status = GasCoinStatus.InUse;

            // Check for untracked SUI coins in the wallet and merge them into
            // the main gas coin.
            // Merge coins with <= minBalancePerInstanceMist and > balancePerinstanceMist into the mainGasCoin
            untrackedCoinsToMerge = await this.#untrackedCoinsToMerge();
            trackedCoinsToMerge = this.#trackedCoinsToMerge();

            if (trackedCoinsToMerge.length + untrackedCoinsToMerge.length > 0) {
                this.#logger.debug(`Scanning found ${untrackedCoinsToMerge.length} untracked, ${trackedCoinsToMerge.length} tracked gas coins to merge`);

                coinsMerged = await this.#mergeCoins(this.#mainGasCoin!,
                                                     [...untrackedCoinsToMerge,
                                                      ...trackedCoinsToMerge]);
            }
        } finally {
            setTimeout(async () => { await this.#onSyncTimer(); },
                       this.#syncIntervalMs);

            if (! this.#mainGasCoin) {
                return;
            }

            if (trackedCoinsToMerge.length > 0) {
                if (coinsMerged) {
                    for (let coin of trackedCoinsToMerge) {
                        this.#gasCoins.delete(coin);
                    }

                    if (! await this.#mainGasCoin.updateInstance(this.#suiClient)) {
                        this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                        this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin}. Will split the mainGasCoin in the next iteration of the periodic task.`);
                        return;

                    }

                    const instancesNeeded = this.#expectedCount - this.#gasCoins.size;
                    const instanceToSplit = this.#mainGasCoin;
                    if (instancesNeeded > 0) {
                        this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`);

                        await this.#createChildInstances(instancesNeeded,
                                                         instanceToSplit);
                    }
                } else {
                    for (let coinId of trackedCoinsToMerge) {
                        let coin = this.#gasCoins.get(coinId);
                        if (coin) {
                            if (await coin.updateInstance(this.#suiClient)) {
                                coin.status = GasCoinStatus.Free;
                            } else {
                                coin.status = GasCoinStatus.NeedsVersionUpdate;
                            }
                        }
                    }
                }
                if (! await this.#mainGasCoin.updateInstance(this.#suiClient)) {
                    this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                    this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin}`);
                    return;
                }
            }

            if (untrackedCoinsToMerge.length > 0 && trackedCoinsToMerge.length ===0) {
                if (! await this.#mainGasCoin.updateInstance(this.#suiClient)) {
                    this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                    this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin}`);
                    return;
                }
            }

            this.#mainGasCoin.status = GasCoinStatus.Free;
        }
    }

    #createChildInstances = async (instancesNeeded: number,
                                   instanceToSplit: GasCoin) => {
        try {
            const splitStatus = await this.#splitCoins(instanceToSplit!,
                                                       instancesNeeded,
                                                       this.#balancePerInstanceMist);

            if (splitStatus) {
                let coins = await this.#suiClient.getOwnedObjects({
                    owner: this.#walletAddress,
                    filter: { StructType: "0x2::coin::Coin<0x2::sui::SUI>" },
                    options: { showContent: true }
                });

                for (let coin of coins.data) {
                    let data = coin.data;
                    if (data) {
                        if (data.objectId === this.#mainGasCoin!.objectId ||
                            this.#gasCoins.has(data.objectId)) {
                            continue;
                        }
                        if (data.content && data.content.dataType === "moveObject") {
                            let fields = data.content.fields as any;
                            this.#gasCoins.set(data.objectId,
                                               new GasCoin(this.#loggerFactory,
                                                           data.objectId,
                                                           data.digest,
                                                           data.version,
                                                           fields.balance));
                        }
                    }
                }

                this.#logger.info(`${this.#gasCoins.size} child gasCoin instances in the linked wallet after the split`);
            }
        } finally {
            this.#gasCoinKeys = [...this.#gasCoins.keys()];
            this.#nextCoinIdx = 0;
        }
    }

    #splitCoins = async (instanceToSplit: GasCoin, count: number,
                         balancePerCoin: bigint) => {
        const txBlock = new TransactionBlock();
        let response = null;

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

            response = await this.#suiClient.signAndExecuteTransactionBlock({
                signer: this.#keyPair,
                transactionBlock: txBlock,
                options: { showEffects: true }
            });
        } catch (error) {
            this.#logger.error(`Failed to split coin=${instanceToSplit.objectId}. Error=${error}`);
        }

        const digest = response?.digest;
        const status = response?.effects?.status.status;

        this.#logger.info(`Split coin=${instanceToSplit.objectId} digest=${digest} status=${status}`);

        return status === "success";
    }

    #mergeCoins = async (parentInstance: GasCoin,
                         instancesToMerge: Array<string>) => {

        this.#logger.info(`Merging ${instancesToMerge.length} coin(s) into the gasCoin=${parentInstance.objectId}`);

        this.#logger.debug(`mainGasCoin=${parentInstance.objectId} version=${parentInstance.version}`);

        let txBlock = new TransactionBlock();
        let response = null;

        try {
            txBlock.mergeCoins(txBlock.gas, instancesToMerge);
            txBlock.setGasPayment([parentInstance]);

            response = await this.#suiClient.signAndExecuteTransactionBlock({
                signer: this.#keyPair,
                transactionBlock: txBlock,
                options: { showEffects: true }
            });

            const status = response.effects?.status.status;
            const digest = response.digest;

            this.#logger.info(`Merged ${instancesToMerge.length} coin(s) into the gasCoin=${parentInstance.objectId} digest=${digest} status=${status}`);
        } catch (error) {
            this.#logger.error(`Failed to merge coins. Error=${error}`);
        }

        return response?.effects?.status.status === "success";
    }

    // The caller is responsible for obtaining the gasCoin before calling this
    // and freeing it afterwards
    mergeUntrackedGasCoinsInto = async (gasCoin: GasCoin) => {
        let untrackedCoinsToMerge = new Array<string>();

        try {
            untrackedCoinsToMerge = await this.#untrackedCoinsToMerge();

            this.#logger.info(`mergeUntrackedGasCoinsInto: Found ${untrackedCoinsToMerge.length} untracked gas coin(s)`);
            if (untrackedCoinsToMerge.length == 0) {
                this.#logger.info(`mergeUntrackedGasCoinsInto: No untracked gasCoin to merge. Returning`);
                return
            }

            await this.#mergeCoins(gasCoin,
                                   untrackedCoinsToMerge);

        } catch (error) {
            this.#logger.error(`mergeUntrackedGasCoinsInto: Failed to merge untracked coins into gasCoin=${gasCoin.objectId}. Error=${error}`);
        } finally {
            await gasCoin.updateInstance(this.#suiClient);
        }
    }

    getFreeGasCoin = (): GasCoin => {
        if (this.#gasCoinKeys.length === 0) {
            throw new Error("No gas coins configured");
        }

        const startingIdx = this.#nextCoinIdx;
        let idx = startingIdx;
        do {
            const coinId = this.#gasCoinKeys[this.#nextCoinIdx];
            let coin = this.#gasCoins.get(coinId);
            if (coin === undefined) { throw new Error(`No gas coin found with id=${coinId}`); }
            this.#nextCoinIdx = (this.#nextCoinIdx + 1) % this.#gasCoinKeys.length;

            if (coin.status === GasCoinStatus.Free) {
                coin.status = GasCoinStatus.InUse;
                return coin;
            }
        } while (idx != startingIdx);

        throw new Error("All gas coins in use");
    }

    getMainGasCoin = async (): Promise<GasCoin | null> => {
        if (this.#mainGasCoin === undefined) {
            throw new Error("The main gas coin has not been allocated yet");
        }

        if (this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
            if (await this.#mainGasCoin.updateInstance(this.#suiClient)) {
                this.#mainGasCoin.status = GasCoinStatus.Free;
            } else {
                this.#logger.error(`Unable to update the version of the mainGasCoin={this.#mainGasCoin}`);
            }
        }
        if (this.#mainGasCoin.status !== GasCoinStatus.Free) {
            this.#logger.error("mainGasCoin is not free");
            return null;
        }

        this.#mainGasCoin.status = GasCoinStatus.InUse;

        return this.#mainGasCoin;
    }

    onEpochChange = async () => {
        for (let [_, gasCoin] of this.#gasCoins) {
            if (gasCoin.status == GasCoinStatus.SkipForRemainderOfEpoch) {
                this.#logger.info(`Freeing gasCoin=${gasCoin.objectId} skipped for last epoch`);
                if (await gasCoin.updateInstance(this.#suiClient)) {
                    gasCoin.status = GasCoinStatus.Free;
                } else {
                    gasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                }
            }
        }
    }

    logSkippedObjects = () => {
        let count: number = 0;
        for (let [_, gasCoin] of this.#gasCoins) {
            if (gasCoin.status == GasCoinStatus.SkipForRemainderOfEpoch) {
                this.#logger.debug(`gasCoin=${gasCoin.objectId} will be skipped for the remainder of the current epoch`);
                ++count;
            }
        }
        this.#logger.info(`Skipping ${count} gas coins for the remainder of the current epoch`);
    }
};
