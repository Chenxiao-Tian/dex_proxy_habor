import { LoggerFactory } from "../../logger";

import { Logger } from "winston";
import { SuiClient } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { TransactionBlock } from "@mysten/sui.js/transactions";
import {
    SuiTransactionBlockResponse,
    SuiObjectData,
    PaginatedObjectsResponse
} from "@mysten/sui.js/client";

const sleep = async (duration_in_ms: number) => {
    return new Promise(resolve => setTimeout(resolve, duration_in_ms));
}

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
                if (this.version <= updatedVersion) {
                    this.#logger.debug(`Queried RPC node. oldVer=${this.version} <= newVer=${data.version}, status=${GasCoinStatus[this.status]}`);
                    this.digest = data.digest;
                    this.version = BigInt(data.version);
                    this.balanceMist = BigInt(fields.balance);
                    return true;
                } else {
                    // Debatable whether we want to return false for this scenario
                    // as there are a few corner cases where the version of a
                    // coin should not be updated.
                    // TODO: revisit this at some point.
                    this.#logger.debug(`Queried RPC node. oldVer=${this.version} >= newVer=${data.version}, status=${GasCoinStatus[this.status]}`);
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
        return `{objectId=${this.objectId}, version=${this.version}, digest=${this.digest}, balanceMist=${this.balanceMist}, status=${GasCoinStatus[this.status]}}`;
    }
};

class GasCoins {
    #logger: Logger;
    #members: Array<GasCoin>;
    // objectId -> Index
    #keys: Map<string, number>;
    #nextCoinIdx = 0;

    constructor(lf: LoggerFactory) {
        this.#logger = lf.createLogger(`gasCoins`);
        this.#members = new Array<GasCoin>();
        this.#keys = new Map<string, number>();
    }

    add = (coin: GasCoin) => {
        // This check is not ideal
        if (! this.#keys.has(coin.objectId)) {
            this.#members.push(coin);
            this.#keys.set(coin.objectId, this.#members.length - 1);
        }
    }

    // Order of items in #members changes
    remove = (toRemove: string) => {
        let idxToRemove = this.#keys.get(toRemove);

        if (idxToRemove !== undefined) {
            let lastIdx = this.#members.length - 1;
            if (idxToRemove !== lastIdx) {
                // swap with last item
                this.#keys.set(this.#members[lastIdx].objectId, idxToRemove);
                this.#members[idxToRemove] = this.#members[lastIdx];
            }
            this.#keys.delete(toRemove);
            this.#members.pop();

            if (this.#nextCoinIdx === lastIdx) {
                this.#nextCoinIdx = 0;
            }
        }
    }

    getFreeCoin = (): GasCoin => {
        if (this.#members.length === 0) {
            throw new Error("No gas coins configured");
        }

        const startingIdx = this.#nextCoinIdx % this.#members.length;
        let idx = startingIdx;
        do {
            let coin = this.#members[idx];

            if (coin.status === GasCoinStatus.Free) {
                this.#nextCoinIdx = (idx + 1) % this.#members.length;
                coin.status = GasCoinStatus.InUse;
                return coin;
            }

            idx = (idx + 1) % this.#members.length;

        } while (idx != startingIdx);

        throw new Error("All gas coins in use");
    }

    getCoinWithMaxBalance = (): GasCoin | undefined => {
        if (this.#members.length === 0) return undefined;

        return this.#members.reduce(
            (lt: GasCoin, rt: GasCoin): GasCoin => {
                return rt.balanceMist < lt.balanceMist ? lt : rt;
            }
        );
    }

    summary = (prefix: string): string => {
        let summary = `${prefix}=[`;
        let index = 1;
        for (let coin of this.#members) {
            summary = (`${summary}#${index}=${coin.repr()}`);
            if (index < this.#members.length) summary = `${summary}, `;
            ++index;
        }

        return `${summary}]`;
    }

    size = (): number => {
        return this.#members.length;
    }

    has = (coinId: string): boolean => {
        return this.#keys.has(coinId);
    }

    outOfBounds = (lower: bigint, upper: bigint): Array<string> => {
        let result = new Array<string>();

        for (let coin of this.#members) {
            if (coin.status === GasCoinStatus.Free
                && (coin.balanceMist <= lower || coin.balanceMist > upper)) {

                coin.status = GasCoinStatus.InUse;
                this.#logger.debug(`Coin=${coin.repr()} out of bounds=(${lower}, ${upper}]`);
                result.push(coin.objectId);
            }
        }

        return result;
    }

    needVersionUpdate = (): Array<GasCoin> => {
        let result = new Array<GasCoin>();

        for (let coin of this.#members) {
            if (coin.status === GasCoinStatus.NeedsVersionUpdate) {
                result.push(coin);
            }
        }

        return result;
    }

    toSkip = (): Array<GasCoin> => {
        let result = new Array<GasCoin>();

        for (let coin of this.#members) {
            if (coin.status === GasCoinStatus.SkipForRemainderOfEpoch) {
                result.push(coin);
            }
        }

        return result;
    }

    get = (coinId: string): GasCoin | undefined => {
        let idx = this.#keys.get(coinId);

        if (idx === undefined) return undefined;

        return this.#members[idx];
    }
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
    #gasCoins: GasCoins;
    #syncIntervalMs: number;
    #logResponses: boolean;

    constructor(lf: LoggerFactory, suiClient: SuiClient, walletAddress: string,
                keyPair: Ed25519Keypair, expectedCount: number,
                balancePerInstanceMist: bigint, minBalancePerInstanceMist: bigint,
                syncIntervalMs: number, logResponses: boolean) {
        this.#loggerFactory = lf;
        this.#logger = this.#loggerFactory.createLogger("gas_mgr");
        this.#suiClient = suiClient;
        this.#walletAddress = walletAddress;
        this.#keyPair = keyPair;
        this.#expectedCount = expectedCount;
        this.#balancePerInstanceMist = balancePerInstanceMist;
        this.#minBalancePerInstanceMist = minBalancePerInstanceMist;
        this.#gasCoins = new GasCoins(lf);
        this.#syncIntervalMs = syncIntervalMs;
        this.#logResponses = logResponses;
    }

    start = async () => {
        await this.#setupCoinInstances();

        setTimeout(async () => {await this.#onSyncTimer();},
                   this.#syncIntervalMs);
    }

    #setMainGasCoin = () => {
        // Choose the gas coin with the highest balance
        this.#mainGasCoin = this.#gasCoins.getCoinWithMaxBalance();

        if (this.#mainGasCoin) {
            this.#gasCoins.remove(this.#mainGasCoin.objectId);

            this.#logger.info(`Set mainGasCoin=${this.#mainGasCoin.repr()}`);
        }
    }


    #getSuiCoins = async (): Promise<Array<SuiObjectData>> => {
        let request = async (cursor: string | null) => {
            try {
                return await this.#suiClient.getOwnedObjects({
                    owner: this.#walletAddress,
                    filter: { StructType: GasManager.#suiCoinStructType },
                    options: { showContent: true },
                    cursor: cursor
                });
            } catch(error) {
            this.#logger.error(`Unable to query the RPC node for SUI coins owned by the wallet. Error=${error}`);
                throw error;
            }
        };

        let result = await (async () => {
            let result = new Array<SuiObjectData>();

            let cursor: string | null = null;

            const parseResponse = (
                response: PaginatedObjectsResponse
            ): string | null => {
                for (let item of response.data) {
                    if (item.data) result.push(item.data);
                }
                return (response.hasNextPage) ? response.nextCursor! : null;
            }

            // Handling paginated results
            do {
                let response: PaginatedObjectsResponse = await request(cursor);
                cursor = parseResponse(response);
            } while (cursor !== null);

            return result;
        })();

        this.#logger.debug(`Fetched information about ${result.length} SUI coins owned by our wallet`);

        return result;
    }

    #trackInstances = async () => {
        try {
            let coins = await this.#getSuiCoins();

            for (let coin of coins) {
                if (coin && coin.content &&
                    coin.content.dataType === "moveObject") {
                    let fields = coin.content.fields as any;
                    this.#gasCoins.add(new GasCoin(this.#loggerFactory,
                                                   coin.objectId,
                                                   coin.digest,
                                                   coin.version,
                                                   fields.balance));
                }
            }


            this.#logger.info(`Found ${this.#gasCoins.size()} gasCoin instance(s) in the linked wallet`);
            this.#logger.debug(this.#gasCoins.summary("gasCoins"));

        } catch (error) {
            const msg = `Unable to setup tracking of gasCoin instance(s). Error=${error}`;
            this.#logger.error(msg);
            throw new Error(msg);
        }
    }

    tryUpdateMainGasCoinVersion = async (): Promise<boolean> => {
        if (this.#mainGasCoin == undefined) return false;

        let attempts = 2;

        let versionUpdated = false;
        for (let attempt = 0; attempt < attempts; ++attempt) {
            versionUpdated = await this.#mainGasCoin.updateInstance(this.#suiClient);
            if (versionUpdated) break;
            await sleep(500); // 500 ms
        }

        return versionUpdated;
    }

    #tryConsolidateGasCoins = async (coinsToMerge: Array<string>) => {
        if (this.#mainGasCoin == undefined) return;
        if (coinsToMerge.length == 0) return;

        this.#logger.info(`Merging ${coinsToMerge.length} coins with balance <= ${this.#minBalancePerInstanceMist} and balance > ${this.#balancePerInstanceMist} into the mainGasCoin`);

        let gasCoinVersionUpdated: boolean = false;
        try {
            let response = await this.#mergeCoins(this.#mainGasCoin,
                                                  coinsToMerge);
            if (response.txSuceeded) {
                for (let coinId of response.coinsDeleted) {
                    this.#gasCoins.remove(coinId);
                }
            }

            gasCoinVersionUpdated = response.gasCoinVersionUpdated;
        } finally {
            // Do not free the mainGasCoin at this stage as it's part of a larger
            // operation.
            if (! gasCoinVersionUpdated && ! await this.tryUpdateMainGasCoinVersion()) {
                this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                throw new Error(`Unable to update the mainGasCoin=${this.#mainGasCoin.repr()} after merging other coins into it`);
            }
        }
    }

    #splitIntoRequiredInstances = async () => {
        if (this.#mainGasCoin == undefined) return;
        if (this.#expectedCount <= this.#gasCoins.size()) return;

        const instancesNeeded = this.#expectedCount - this.#gasCoins.size();
        const instanceToSplit = this.#mainGasCoin;

        this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size()} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`);

        let gasCoinVersionUpdated = false;
        try {
            gasCoinVersionUpdated = await this.#createChildInstances(instancesNeeded, instanceToSplit);
        } finally {
            // Free the gas coin at the call site
            if(! gasCoinVersionUpdated && ! await this.tryUpdateMainGasCoinVersion()) {
                this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
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
        }
    }

    #untrackedCoinsToMerge = async (): Promise<Array<string>> => {
        let untrackedCoinsToMerge = new Array<string>();

        try {
            let coins = await this.#getSuiCoins();

            for (let coin of coins) {
                if (coin) {
                    if (coin.objectId === this.#mainGasCoin?.objectId ||
                        this.#gasCoins.has(coin.objectId)) {
                        continue;
                    } else {
                        this.#logger.debug(`Found untracked gasCoin=${coin.objectId} in wallet`);
                        untrackedCoinsToMerge.push(coin.objectId);
                    }
                }
            }
        } catch (error) {
            this.#logger.error(`Failed to query untracked gas coins. Error=${error}`);
        }

        return untrackedCoinsToMerge;
    }

    #trackedCoinsToMerge = (): Array<string> => {
        return this.#gasCoins.outOfBounds(this.#minBalancePerInstanceMist, this.#balancePerInstanceMist);
    }

    #handleCoinsNeedingVersionUpdate = async () => {
        if (this.#mainGasCoin && this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
            if (await this.tryUpdateMainGasCoinVersion()) {
                this.#mainGasCoin.status = GasCoinStatus.Free;
            }
        }

        for (let coin of this.#gasCoins.needVersionUpdate()) {
            if (await coin.updateInstance(this.#suiClient)) {
                coin.status = GasCoinStatus.Free;
            }
        }
    }

    #canRunPeriodicTask = (): boolean => {
        if (this.#mainGasCoin === undefined) {
            this.#logger.debug(`onSyncTimer: mainGasCoin not set. Skipping`);
            return false;
        }

        let status: string = `onSyncTimer: mainGasCoin=${this.#mainGasCoin.repr()}`
        this.#logger.debug(this.#gasCoins.summary(`${status} children`));

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
        let gasCoinVersionUpdated = false;
        let mergeResponse = new MergeCoinsResult();
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

                mergeResponse = await this.#mergeCoins(this.#mainGasCoin!,
                                                       [...untrackedCoinsToMerge,
                                                       ...trackedCoinsToMerge]);
                gasCoinVersionUpdated = mergeResponse.gasCoinVersionUpdated;
            }
        } finally {
            setTimeout(async () => { await this.#onSyncTimer(); },
                       this.#syncIntervalMs);

            if (! this.#mainGasCoin) {
                return;
            }

            if (trackedCoinsToMerge.length > 0) {
                if (mergeResponse.txSuceeded) {
                    for (let coinId of mergeResponse.coinsDeleted) {
                        this.#gasCoins.remove(coinId);
                    }

                    if (! gasCoinVersionUpdated) {
                        gasCoinVersionUpdated = await this.tryUpdateMainGasCoinVersion();
                        if (! gasCoinVersionUpdated) {
                            this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                            this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}. Will split the mainGasCoin in the next iteration of the periodic task.`);
                            return;
                        }
                    }

                    const instancesNeeded = this.#expectedCount - this.#gasCoins.size();
                    const instanceToSplit = this.#mainGasCoin;
                    if (instancesNeeded > 0) {
                        this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size()} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`);

                        gasCoinVersionUpdated = await this.#createChildInstances(instancesNeeded, instanceToSplit);
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
                if (! gasCoinVersionUpdated && ! await this.tryUpdateMainGasCoinVersion()) {
                    this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                    this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}`);
                    return;
                }
            }

            if (untrackedCoinsToMerge.length > 0 && trackedCoinsToMerge.length ===0) {
                if (! gasCoinVersionUpdated && ! await this.tryUpdateMainGasCoinVersion()) {
                    this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                    this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}`);
                    return;
                }
            }

            const instancesNeeded = this.#expectedCount - this.#gasCoins.size();
            const instanceToSplit = this.#mainGasCoin;
            if (instancesNeeded > 0) {
                this.#logger.info(`Available child gasCoinInstances=${this.#gasCoins.size()} is less than the expectedCount=${this.#expectedCount}. Splitting the mainGasCoin into ${instancesNeeded + 1} coins`);

                gasCoinVersionUpdated = await this.#createChildInstances(instancesNeeded, instanceToSplit);

                if (! gasCoinVersionUpdated && ! this.tryUpdateMainGasCoinVersion()) {
                    this.#mainGasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                    this.#logger.error(`Failed to update the version of the mainGasCoin=${this.#mainGasCoin.repr()}`);
                    return;
                }
            } else {
                this.#mainGasCoin.status = GasCoinStatus.Free;
            }
        }
    }

    #createChildInstances = async (instancesNeeded: number,
                                   instanceToSplit: GasCoin): Promise<boolean> => {
        let gasCoinVersionUpdated = false;
        try {
            let response = await this.#splitCoins(instanceToSplit!,
                                                  instancesNeeded,
                                                  this.#balancePerInstanceMist);

            gasCoinVersionUpdated = response.gasCoinVersionUpdated;
            if (response.txSuceeded) {
                for (let coin of response.coinsCreated) {
                    this.#gasCoins.add(coin);
                }

                this.#logger.info(`${this.#gasCoins.size()} child gasCoin instances in the linked wallet after the split`);
            }
        } finally {
            return gasCoinVersionUpdated;
        }
    }

    #parseSplitCoinsResponse = (response: SuiTransactionBlockResponse,
                                balancePerCoin: bigint,
                                instanceToSplit: GasCoin): SplitCoinsResult => {
        let parsedResponse = new SplitCoinsResult();

        if (response.effects?.gasObject && response.effects?.gasUsed) {
            const versionFromTx = BigInt(response.effects!.gasObject.reference.version);
            const digestFromTx =response.effects!.gasObject.reference.digest;

            const gasUsed = BigInt(response.effects!.gasUsed.computationCost) + BigInt(response.effects!.gasUsed.storageCost) - BigInt(response.effects!.gasUsed.storageRebate);

            if (instanceToSplit.version < versionFromTx) {
                const oldVersion = instanceToSplit.version;
                instanceToSplit.version = versionFromTx;
                instanceToSplit.digest = digestFromTx;
                instanceToSplit.balanceMist -= gasUsed;

                this.#logger.info(`gasCoin=${instanceToSplit.objectId} updated. Details=${instanceToSplit.repr()}`);

                parsedResponse.gasCoinVersionUpdated = true;
            }
        }

        if (response.effects?.status.status === "success") {
            parsedResponse.txSuceeded = true;
        } else {
            return parsedResponse;
        }
        parsedResponse.txSuceeded = true;

        if (response?.digest) {
            parsedResponse.digest = response.digest;
        }

        if (response.effects?.created) {
            for (let instance of response.effects.created) {
                let gasCoin = new GasCoin(this.#loggerFactory,
                                          instance.reference.objectId,
                                          instance.reference.digest,
                                          instance.reference.version,
                                          `${balancePerCoin}`);

                parsedResponse.coinsCreated.push(gasCoin);
            }
        }

        return parsedResponse;
    }

    #splitCoins = async (instanceToSplit: GasCoin, count: number,
                         balancePerCoin: bigint): Promise<SplitCoinsResult> => {
        const txBlock = new TransactionBlock();
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

            let response = await this.#suiClient.signAndExecuteTransactionBlock({
                signer: this.#keyPair,
                transactionBlock: txBlock,
                options: { showEffects: true }
            });

            if (this.#logResponses) {
                const deserialized = JSON.stringify(response);
                this.#logger.debug(`Split coins response: ${deserialized}`);
            }

            parsedResponse = this.#parseSplitCoinsResponse(response,
                                                           balancePerCoin,
                                                           instanceToSplit);

            if (parsedResponse.txSuceeded) {
                this.#logger.info(`Split ${instanceToSplit.repr()} into ${parsedResponse.coinsCreated.length} coin(s), txDigest=${parsedResponse.digest}`);
            }

        } catch (error) {
            this.#logger.error(`Failed to split coin=${instanceToSplit.objectId}. Error=${error}`);
        }

        return parsedResponse;
    }

    #parseMergeCoinsResponse = (response: SuiTransactionBlockResponse,
                                gasCoin: GasCoin): MergeCoinsResult => {
        let parsedResponse = new MergeCoinsResult();

        if (response.effects?.gasObject && response.effects?.gasUsed) {
            const versionFromTx = BigInt(response.effects!.gasObject.reference.version);
            const digestFromTx =response.effects!.gasObject.reference.digest;

            const gasUsed = BigInt(response.effects!.gasUsed.computationCost) + BigInt(response.effects!.gasUsed.storageCost) - BigInt(response.effects!.gasUsed.storageRebate);

            if (gasCoin.version < versionFromTx) {
                const oldVersion = gasCoin.version;
                gasCoin.version = versionFromTx;
                gasCoin.digest = digestFromTx;
                gasCoin.balanceMist -= gasUsed;

                this.#logger.info(`gasCoin=${gasCoin.objectId} updated. Details=${gasCoin.repr()}`);

                parsedResponse.gasCoinVersionUpdated = true;
            }
        }

        if (response.effects?.status.status === "success") {
            parsedResponse.txSuceeded = true;
        } else {
            return parsedResponse;
        }
        parsedResponse.txSuceeded = true;

        if (response?.digest) {
            parsedResponse.digest = response.digest;
        }

        if (response.effects?.deleted) {
            for (let instance of response.effects.deleted) {
                parsedResponse.coinsDeleted.push(instance.objectId);
            }
        }

        return parsedResponse;
    }

    #mergeCoins = async (parentInstance: GasCoin,
                         instancesToMerge: Array<string>) => {

        this.#logger.info(`Merging ${instancesToMerge.length} coin(s) into the gasCoin=${parentInstance.objectId}`);

        this.#logger.debug(`mainGasCoin=${parentInstance.objectId} version=${parentInstance.version}`);

        let txBlock = new TransactionBlock();
        let parsedResponse = new MergeCoinsResult();

        try {
            txBlock.mergeCoins(txBlock.gas, instancesToMerge);
            txBlock.setGasPayment([parentInstance]);

            let response = await this.#suiClient.signAndExecuteTransactionBlock({
                signer: this.#keyPair,
                transactionBlock: txBlock,
                options: { showEffects: true }
            });

            if (this.#logResponses) {
                const deserialized = JSON.stringify(response);
                this.#logger.debug(`Merge coins response: ${deserialized}`);
            }

            parsedResponse = this.#parseMergeCoinsResponse(response, parentInstance);
            if (parsedResponse.txSuceeded) {
                this.#logger.info(`Merged ${parsedResponse.coinsDeleted.length} coin(s) into the gasCoin=${parentInstance.repr()}, txDigest=${parsedResponse.digest}`);
            }
        } catch (error) {
            this.#logger.error(`Failed to merge coins. Error=${error}`);
        }

        return parsedResponse;
    }

    // The caller is responsible for obtaining the gasCoin before calling this
    // and freeing it afterwards
    mergeUntrackedGasCoinsInto = async (gasCoin: GasCoin) => {
        let untrackedCoinsToMerge = new Array<string>();
        let foundGasCoinsToMerge = false;
        let parsedResponse = new MergeCoinsResult();

        try {
            untrackedCoinsToMerge = await this.#untrackedCoinsToMerge();

            this.#logger.info(`mergeUntrackedGasCoinsInto: Found ${untrackedCoinsToMerge.length} untracked gas coin(s)`);
            if (untrackedCoinsToMerge.length == 0) {
                this.#logger.info(`mergeUntrackedGasCoinsInto: No untracked gasCoin to merge. Returning`);
                return
            }

            foundGasCoinsToMerge = true;
            parsedResponse = await this.#mergeCoins(gasCoin,
                                                    untrackedCoinsToMerge);

        } catch (error) {
            this.#logger.error(`mergeUntrackedGasCoinsInto: Failed to merge untracked coins into gasCoin=${gasCoin.objectId}. Error=${error}`);
        } finally {
            if (foundGasCoinsToMerge && ! parsedResponse.gasCoinVersionUpdated) {
                if(! await gasCoin.updateInstance(this.#suiClient)) {
                    gasCoin.status = GasCoinStatus.NeedsVersionUpdate;
                }
            }
        }
    }

    getFreeGasCoin = (): GasCoin => {
        return this.#gasCoins.getFreeCoin();
    }

    getMainGasCoin = async (): Promise<GasCoin | null> => {
        if (this.#mainGasCoin === undefined) {
            throw new Error("The main gas coin has not been allocated yet");
        }

        if (this.#mainGasCoin.status == GasCoinStatus.NeedsVersionUpdate) {
            if (await this.tryUpdateMainGasCoinVersion()) {
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
        for (let gasCoin of this.#gasCoins.toSkip()) {
            this.#logger.info(`Freeing gasCoin=${gasCoin.objectId} skipped for last epoch`);
            if (await gasCoin.updateInstance(this.#suiClient)) {
                gasCoin.status = GasCoinStatus.Free;
            } else {
                gasCoin.status = GasCoinStatus.NeedsVersionUpdate;
            }
        }
    }

    logSkippedObjects = () => {
        let count: number = 0;
        for (let gasCoin of this.#gasCoins.toSkip()) {
            this.#logger.debug(`gasCoin=${gasCoin.objectId} will be skipped for the remainder of the current epoch`);
            ++count;
        }
        this.#logger.info(`Skipping ${count} gas coins for the remainder of the current epoch`);
    }
};
