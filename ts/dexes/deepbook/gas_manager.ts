import { LoggerFactory } from "../../logger";

import { Logger } from "winston";
import { SuiClient } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { TransactionBlock } from "@mysten/sui.js/transactions";

export enum GasCoinStatus {
    Free,
    InUse,
    SkipForRemainderOfEpoch
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

    updateInstance = async (suiClient: SuiClient) => {
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
                } else {
                    this.#logger.debug(`oldVer=${this.version} >= newVer=${data.version}`);
                }
            }
        } catch (error) {
            this.#logger.error(`Failed to update gasCoin=${this.objectId}`);
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
        this.#mainGasCoin = [...this.#gasCoins.values()].reduce(
            (lt: GasCoin, rt: GasCoin): GasCoin => {
                return rt.balanceMist < lt.balanceMist ? lt : rt;
            }
        );

        this.#gasCoins.delete(this.#mainGasCoin.objectId);

        this.#logger.info(`Setting mainGasCoin=${this.#mainGasCoin.objectId}, balanceMist=${this.#mainGasCoin.balanceMist}`);
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

    #setupCoinInstances = async () => {
        try {
            await this.#trackInstances();

            this.#setMainGasCoin();

            if (this.#mainGasCoin === undefined || this.#mainGasCoin === null) {
                throw new Error("Unable to set mainGasCoin");
            }

            this.#mainGasCoin.status = GasCoinStatus.InUse;
            let trackedCoinsToMerge = this.#trackedCoinsToMerge();
            if (trackedCoinsToMerge.length > 0) {
                this.#logger.info(`Merging ${trackedCoinsToMerge.length} coins with balance <= ${this.#minBalancePerInstanceMist} and balance > ${this.#balancePerInstanceMist} into the mainGasCoin`);
                try {
                    const merged = await this.#mergeCoins(this.#mainGasCoin,
                                                          trackedCoinsToMerge);
                    if (merged) {
                        for (let coin of trackedCoinsToMerge) {
                            this.#gasCoins.delete(coin);
                        }
                    }
                } finally {
                    await this.#mainGasCoin.updateInstance(this.#suiClient);
                }
            }
            if (this.#gasCoins.size < (this.#expectedCount)) {
                this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin`);
                const instancesNeeded = this.#expectedCount - this.#gasCoins.size;
                const instanceToSplit = this.#mainGasCoin;
                await this.#createChildInstances(instancesNeeded, instanceToSplit);
            }
        } finally {
            if (this.#mainGasCoin) {
                await this.#mainGasCoin.updateInstance(this.#suiClient);
                this.#mainGasCoin.status = GasCoinStatus.Free;

                this.#gasCoinKeys = [...this.#gasCoins.keys()];
                this.#nextCoinIdx = 0;
            }
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
                this.#logger.debug(`Coin=${coin.objectId} balance=${coin.balanceMist} out of bounds=(${this.#minBalancePerInstanceMist}, ${this.#balancePerInstanceMist}]`);
                trackedCoinsToMerge.push(coin.objectId);
            }
        }

        return trackedCoinsToMerge;
    }

    #onSyncTimer = async () => {
        let trackedCoinsToMerge = Array<string>();
        let untrackedCoinsToMerge = Array<string>();
        let mergeStatus = false;
        try {
            if (this.#mainGasCoin === undefined) {
                this.#logger.debug(`onSyncTimer: mainGasCoin not set. Skipping`);
                return;
            }
            if (this.#mainGasCoin.status !== GasCoinStatus.Free) {
                this.#logger.debug(`onSyncTimer: mainGasCoin is in use. Skipping`);
                return;
            }

            this.#logger.debug(`onSyncTimer: mainGasCoin=${this.#mainGasCoin.repr()}`);

            this.#mainGasCoin.status = GasCoinStatus.InUse;

            // Check for untracked SUI coins in the wallet and merge them into
            // the main gas coin.
            // Merge coins with <= minBalancePerInstanceMist and > balancePerinstanceMist into the mainGasCoin
            untrackedCoinsToMerge = await this.#untrackedCoinsToMerge();
            trackedCoinsToMerge = this.#trackedCoinsToMerge();


            if (trackedCoinsToMerge.length + untrackedCoinsToMerge.length > 0) {
                this.#logger.debug(`Scanning found ${untrackedCoinsToMerge.length} untracked, ${trackedCoinsToMerge.length} tracked gas coins to merge`);

                mergeStatus = await this.#mergeCoins(this.#mainGasCoin,
                                                     [...untrackedCoinsToMerge,
                                                      ...trackedCoinsToMerge]);
            }
        } finally {
            setTimeout(async () => { await this.#onSyncTimer(); },
                       this.#syncIntervalMs);

            if (this.#mainGasCoin) {
                if (trackedCoinsToMerge.length > 0) {
                    this.#logger.debug(`Updating details`);

                    await this.#mainGasCoin.updateInstance(this.#suiClient);

                    if (mergeStatus) {
                        for (let coin of trackedCoinsToMerge) {
                            this.#gasCoins.delete(coin);
                        }

                        const instancesNeeded =
                            this.#expectedCount - this.#gasCoins.size;
                        const instanceToSplit = this.#mainGasCoin;
                        if (instancesNeeded > 0) {
                            this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin`);

                            await this.#createChildInstances(instancesNeeded,
                                                             instanceToSplit);
                        }
                    } else {
                        for (let coinId of trackedCoinsToMerge) {
                            let coin = this.#gasCoins.get(coinId);
                            if (coin) {
                                await coin.updateInstance(this.#suiClient);
                                coin.status = GasCoinStatus.Free;
                            }
                        }
                    }
                    await this.#mainGasCoin.updateInstance(this.#suiClient);
                }
                if (untrackedCoinsToMerge.length > 0 && trackedCoinsToMerge.length ===0) {
                    await this.#mainGasCoin.updateInstance(this.#suiClient);
                }
                this.#mainGasCoin.status = GasCoinStatus.Free;
            }
        }

    };

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

    getMainGasCoin = (): GasCoin | null => {
        if (this.#mainGasCoin === undefined) {
            throw new Error("The main gas coin has not been allocated yet");
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
                gasCoin.status = GasCoinStatus.Free;
                await gasCoin.updateInstance(this.#suiClient);
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
